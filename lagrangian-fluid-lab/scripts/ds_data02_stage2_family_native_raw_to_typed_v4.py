#!/usr/bin/env python3
"""Forward generic raw-to-typed worker with a guarded HDF5 hash fast path.

The v2 worker and v3 shared-guard envelope are immutable.  This additive
worker keeps their raw tree pre/post hash and complete BI4 conversion.  When a
parent guard supplies an exact CURRENT reference-HDF5 pre/post content
attestation and the new typed file has the same SHA, the report records a
whole-file equality proof and does not reopen the reference for a duplicate
dataset comparison.  If the SHA differs, or no attestation is supplied, the
worker calls the trusted converter's complete field comparator.  A self
reported SHA, a stat-only record, or a producer path without a parent
attestation can never select the fast path.

``build-request`` and ``prepare`` are metadata-only.  ``run
--io-slot-approved`` is the only path that reads BI4/HDF5 payloads.  Existing
v2/v3 requests are never rewritten and all labels/qualification remain
development/UNKNOWN.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V3_PATH = SCRIPT.with_name("ds_data02_stage2_family_native_raw_to_typed_v3.py")
V2_PATH = SCRIPT.with_name("ds_data02_stage2_family_native_raw_to_typed_v2.py")
SCHEMA = "ds02.stage2.family-native-raw-to-typed-compare-request.v4"
REPORT_SCHEMA = "ds02.stage2.family-native-raw-to-typed-compare-report.v4"
ATTESTATION_SCHEMA = "ds02.stage2.parent-reference-hdf5-content-attestation.v1"
V3_SCHEMA = "ds02.stage2.family-native-raw-to-typed-compare-request.v3"
V2_SCHEMA = "ds02.stage2.family-native-raw-to-typed-compare-request.v2"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")


class FamilyNativeV4Error(RuntimeError):
    """Raised when a v4 graph or content attestation is unsafe."""


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FamilyNativeV4Error(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sha_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def _load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FamilyNativeV4Error(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise FamilyNativeV4Error(f"JSON object required: {target}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FamilyNativeV4Error(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise FamilyNativeV4Error(f"{role} must be a lowercase SHA-256")
    return value


def _import_v3() -> Any:
    return _load_module(V3_PATH, "_ds02_family_native_v3_for_v4")


def _import_v2() -> Any:
    return _load_module(V2_PATH, "_ds02_family_native_v2_for_v4")


def _load_graph(request_path: Path, *, verify_static: bool = False) -> tuple[dict[str, Any], dict[str, Any], Any, Any]:
    """Load v4 -> v3 -> v2 without opening payload contents."""
    request = _load_json(request_path)
    if request.get("schema") != SCHEMA or request.get("sha256") != _canonical(request):
        raise FamilyNativeV4Error("v4 request is noncanonical")
    source = request.get("source_v3")
    if not isinstance(source, Mapping):
        raise FamilyNativeV4Error("source_v3 binding is required")
    v3_path = Path(str(source.get("path", ""))).expanduser().resolve()
    if not v3_path.is_file() or _sha_file(v3_path) != source.get("sha256"):
        raise FamilyNativeV4Error("bound v3 request differs")
    v3 = _load_json(v3_path)
    if v3.get("schema") != V3_SCHEMA:
        raise FamilyNativeV4Error("bound v3 schema differs")
    v3_module = _import_v3()
    v3_module.validate_request(v3_path, verify_static=verify_static)
    source_v2 = v3.get("source_request")
    if not isinstance(source_v2, Mapping):
        raise FamilyNativeV4Error("v3 source_request binding is required")
    v2_path = Path(str(source_v2.get("path", ""))).expanduser().resolve()
    if not v2_path.is_file() or _sha_file(v2_path) != source_v2.get("sha256"):
        raise FamilyNativeV4Error("bound v2 request differs")
    v2 = _load_json(v2_path)
    if v2.get("schema") != V2_SCHEMA:
        raise FamilyNativeV4Error("bound v2 schema differs")
    v2_module = _import_v2()
    if v2.get("sha256") != v2_module.canonical_sha({key: item for key, item in v2.items() if key != "sha256"}):
        raise FamilyNativeV4Error("bound v2 canonical SHA differs")
    return request, v3, v3_module, (v2, v2_module, v2_path)


def _validate_attestation(attestation: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    if attestation.get("schema") != ATTESTATION_SCHEMA:
        raise FamilyNativeV4Error("unsupported parent reference attestation schema")
    if attestation.get("sha256") != _canonical(attestation):
        raise FamilyNativeV4Error("parent reference attestation canonical SHA differs")
    if attestation.get("status") != "PASS_PARENT_CONTENT_ATTESTATION":
        raise FamilyNativeV4Error("parent reference attestation is not a completed pass")
    if attestation.get("scope") != "exact CURRENT trajectory_h5":
        raise FamilyNativeV4Error("attestation scope is not the exact CURRENT trajectory")
    if attestation.get("content_verified") is not True:
        raise FamilyNativeV4Error("parent content verification is not true")
    path = Path(str(attestation.get("source_path", ""))).expanduser().resolve()
    ref_path = Path(str(reference.get("path", ""))).expanduser().resolve()
    if path != ref_path:
        raise FamilyNativeV4Error("attested reference path differs from v2 CURRENT binding")
    expected = _require_sha(reference.get("sha256"), "CURRENT trajectory producer SHA")
    pre = _require_sha(attestation.get("pre_content_sha256"), "attestation.pre_content_sha256")
    post = _require_sha(attestation.get("post_content_sha256"), "attestation.post_content_sha256")
    if pre != post or pre != expected:
        raise FamilyNativeV4Error("parent pre/post content SHA does not equal CURRENT producer SHA")
    pre_stat = attestation.get("pre_stat")
    post_stat = attestation.get("post_stat")
    if not isinstance(pre_stat, Mapping) or not isinstance(post_stat, Mapping) or dict(pre_stat) != dict(post_stat):
        raise FamilyNativeV4Error("parent reference stat changed between pre/post")
    if not isinstance(attestation.get("parent_attempt_id"), str) or not attestation["parent_attempt_id"]:
        raise FamilyNativeV4Error("parent attempt identity is required")
    return {
        "source_path": str(path),
        "expected_sha256": expected,
        "parent_attempt_id": attestation["parent_attempt_id"],
        "pre_stat": dict(pre_stat),
        "post_stat": dict(post_stat),
        "attestation_sha256": attestation["sha256"],
    }


def _comparison_mode(*, output_sha256: str, attestation: Mapping[str, Any] | None) -> str:
    """Select only the two safe branches; caller performs fallback compare."""
    if attestation is not None and output_sha256 == attestation["expected_sha256"]:
        return "WHOLE_FILE_SHA_EQUAL_PARENT_ATTESTED"
    return "FULL_FIELD_FALLBACK_REQUIRED"


def build_request(source_request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    source_path = Path(source_request_path).expanduser().resolve()
    if not source_path.is_file():
        raise FamilyNativeV4Error(f"v3 source request is missing: {source_path}")
    v3 = _load_json(source_path)
    if v3.get("schema") != V3_SCHEMA or v3.get("sha256") != _canonical(v3):
        raise FamilyNativeV4Error("source v3 request is noncanonical")
    v3_module = _import_v3()
    v3_module.validate_request(source_path, verify_static=False)
    source_v2 = v3.get("source_request")
    if not isinstance(source_v2, Mapping):
        raise FamilyNativeV4Error("source v3 request lacks v2 binding")
    v2_path = Path(str(source_v2["path"])).expanduser().resolve()
    v2 = _load_json(v2_path)
    if v2.get("schema") != V2_SCHEMA or _sha_file(v2_path) != source_v2.get("sha256"):
        raise FamilyNativeV4Error("source v2 request is not the exact v3 dependency")
    v2_module = _import_v2()
    if v2.get("sha256") != v2_module.canonical_sha({key: item for key, item in v2.items() if key != "sha256"}):
        raise FamilyNativeV4Error("source v2 request is noncanonical")
    reference = v2.get("typed_reference_hdf5")
    if not isinstance(reference, Mapping):
        reference = v2.get("current_binding", {}).get("trajectory_h5")
    if not isinstance(reference, Mapping):
        raise FamilyNativeV4Error("exact CURRENT reference HDF5 binding is required")
    _require_sha(reference.get("sha256"), "typed reference producer SHA")
    case_index = int(v2.get("current_binding", {}).get("case_index", -1))
    family = str(v2.get("family_id"))
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "request_id": f"{family.lower()}-native-raw-to-typed-v4-{case_index:03d}-001",
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "family_id": family,
        "case_id": v3.get("case_id"),
        "attempt_id": f"{family.lower()}-native-raw-to-typed-v4-{case_index:03d}-001",
        "source_v3": {"path": str(source_path), "sha256": _sha_file(source_path), "schema": V3_SCHEMA},
        "source_v2": {"path": str(v2_path), "sha256": _sha_file(v2_path), "schema": V2_SCHEMA},
        "reference_hdf5": copy.deepcopy(dict(reference)),
        "reference_parent_attestation": None,
        "comparison_policy": {
            "mode": "WHOLE_FILE_SHA_THEN_FULL_FIELD_FALLBACK",
            "fast_path_requires": ["parent pre/post content SHA", "exact CURRENT producer SHA", "unchanged parent stat", "completed parent attempt"],
            "fallback": "trusted converter complete reference_hdf5_comparison when SHA differs or attestation is absent",
            "raw_tree_pre_post_required": True,
            "self_reported_or_stat_only_sha_is_insufficient": True,
        },
        "command": [sys.executable, str(SCRIPT), "run", "--request", "<request>",
                    "--output-dir", "<new-output-root>", "--io-slot-approved"],
        "forward_of": {"v3_request_is_immutable": True, "v2_request_is_immutable": True},
        "resource_request": {
            "cpu": int(v3.get("cpu_threads", 1)),
            "max_wall_seconds": int(v3.get("max_wall_seconds", 5400)),
            "max_rss_bytes": int(v3.get("scientific_request", {}).get("resource_request", {}).get("max_rss_bytes", 5 * 1024**3)),
            "new_storage_budget_bytes": int(v3.get("estimated_storage_bytes", 16 * 1024**3)),
        },
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "actual_or_planned": "PLANNED_PARENT_GUARD_REQUEST; NO_NATIVE_EXECUTION_CREDIT",
        "payload_policy": {
            "builder_reads_hdf5": False,
            "builder_reads_bi4": False,
            "raw_tree_before_after_required": True,
            "reference_hdf5_duplicate_read_skippable_only_after_parent_attestation": True,
        },
        "limitations": [
            "The v4 builder and prepare path read only request metadata and stats.",
            "A parent attestation is required before whole-file SHA equality can replace field comparison.",
            "A differing SHA must run the trusted complete field comparator; no error tolerance is relaxed.",
            "Family labels, recovery equivalence, prospective split safety, and QI/QN/QE remain UNKNOWN.",
        ],
    }
    request["sha256"] = _canonical(request)
    _write_new(output_path, request)
    return request


def attach_parent_attestation(request_path: Path | str, attestation_path: Path | str,
                              output_path: Path | str) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load_json(request_file)
    if request.get("schema") != SCHEMA or request.get("sha256") != _canonical(request):
        raise FamilyNativeV4Error("v4 request is noncanonical")
    if request.get("reference_parent_attestation") is not None:
        raise FamilyNativeV4Error("refusing to replace an existing parent attestation")
    att_file = Path(attestation_path).expanduser().resolve()
    attestation = _load_json(att_file)
    checked = _validate_attestation(attestation, request["reference_hdf5"])
    forward = copy.deepcopy(request)
    forward["reference_parent_attestation"] = {
        "path": str(att_file),
        "sha256": _sha_file(att_file),
        "content": attestation,
        "validated": checked,
    }
    forward["status"] = "READY_FOR_PARENT_GUARD_WITH_REFERENCE_ATTESTATION"
    forward["sha256"] = _canonical(forward)
    _write_new(output_path, forward)
    return forward


def validate_request(request_path: Path | str, *, verify_static: bool = False) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request, v3, v3_module, (v2, v2_module, v2_path) = _load_graph(request_file, verify_static=verify_static)
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise FamilyNativeV4Error("v4 request must remain development/UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise FamilyNativeV4Error("model/CFD flags are unsafe")
    policy = request.get("comparison_policy")
    if not isinstance(policy, Mapping) or policy.get("mode") != "WHOLE_FILE_SHA_THEN_FULL_FIELD_FALLBACK":
        raise FamilyNativeV4Error("comparison policy is incomplete")
    reference = request.get("reference_hdf5")
    if not isinstance(reference, Mapping):
        raise FamilyNativeV4Error("reference_hdf5 binding is required")
    _require_sha(reference.get("sha256"), "reference_hdf5.sha256")
    attestation_binding = request.get("reference_parent_attestation")
    attested: dict[str, Any] | None = None
    if attestation_binding is not None:
        if not isinstance(attestation_binding, Mapping):
            raise FamilyNativeV4Error("reference attestation binding is malformed")
        att_path = Path(str(attestation_binding.get("path", ""))).expanduser().resolve()
        if not att_path.is_file() or _sha_file(att_path) != attestation_binding.get("sha256"):
            raise FamilyNativeV4Error("reference attestation file differs")
        attestation = attestation_binding.get("content")
        if not isinstance(attestation, Mapping):
            raise FamilyNativeV4Error("reference attestation content is missing")
        if attestation.get("sha256") != _canonical(attestation):
            raise FamilyNativeV4Error("reference attestation content is not canonical")
        attested = _validate_attestation(attestation, reference)
    return {
        "family_id": request.get("family_id"),
        "case_id": request.get("case_id"),
        "attempt_id": request.get("attempt_id"),
        "source_v3_sha256": request["source_v3"]["sha256"],
        "source_v2_sha256": request["source_v2"]["sha256"],
        "reference_hdf5_sha256": reference["sha256"],
        "parent_attestation": attested,
        "qualification": dict(UNKNOWN),
    }


def prepare_report(request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    bound = validate_request(request_file, verify_static=False)
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "READY_FOR_PARENT_IO_SLOT",
        "request": {"path": str(request_file), "sha256": _sha_file(request_file)},
        "comparison_policy": {
            "parent_attestation_present": bound["parent_attestation"] is not None,
            "planned_mode": "WHOLE_FILE_SHA_THEN_FULL_FIELD_FALLBACK",
        },
        "execution_boundary": {"raw_opened": False, "hdf5_opened": False,
                                "converter_invoked": False, "model_invoked": False,
                                "cfd_invoked": False, "parent_stage2guard_required": True},
        "binding": bound,
        "qualification": dict(UNKNOWN),
    }
    report["report_sha256"] = _canonical(report)
    _write_new(output_path, report)
    return report


def run(request_path: Path | str, output_dir: Path | str, *, io_slot_approved: bool = False) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    bound_request = validate_request(request_file, verify_static=False)
    request, v3, v3_module, (v2, v2_module, v2_path) = _load_graph(request_file, verify_static=False)
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise FamilyNativeV4Error(f"refusing existing output directory: {target}")
    target.mkdir(parents=True, exist_ok=False)
    if not io_slot_approved:
        report = {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                  "request": {"path": str(request_file), "sha256": _sha_file(request_file)},
                  "comparison_policy": {"parent_attestation_present": bound_request["parent_attestation"] is not None,
                                         "planned_mode": "WHOLE_FILE_SHA_THEN_FULL_FIELD_FALLBACK"},
                  "execution_boundary": {"raw_opened": False, "hdf5_opened": False,
                                         "converter_invoked": False, "model_invoked": False,
                                         "cfd_invoked": False}, "qualification": dict(UNKNOWN)}
        _write_new(target / "metadata-preflight.json", report)
        return report

    # Verify fixed code/metadata and all raw source content under the approved
    # slot.  v2 deliberately does not hash the reference HDF5 here; that is
    # exactly what the parent attestation covers for the fast path.
    v3_module.validate_request(Path(str(request["source_v3"]["path"])), verify_static=True)
    bound = v2_module._validate_request(v2, verify_sources=True)
    converter = v2_module._v1._load_module(bound["raw_converter"], "_ds02_family_bound_converter_v4")
    target_report = target / "raw-converter-report.json"
    typed_path = target / "typed-reconstructed.h5"
    started = time.monotonic()
    converter_report = converter.convert_direct(
        data_root=bound["raw_root"], generated_xml=bound["generated_xml"], output=typed_path,
        report_path=target_report, decoder=bound["decoder"], partvtk=None, validation_dir=None,
        solver_log=bound["solver_run_out"], solver_receipt=bound["solver_receipt"],
        gencase_receipt=bound["gencase_receipt"], owner_metadata=bound["owner_metadata"],
        reference_hdf5=None, run_partvtk=False, particle_chunk=65536,
    )
    raw_tree = converter_report.get("source_provenance", {}).get("raw_tree", {})
    before = raw_tree.get("before_tree_sha256")
    after = raw_tree.get("after_tree_sha256")
    if before != after or raw_tree.get("unchanged") is not True:
        raise FamilyNativeV4Error("raw source tree changed during conversion")
    expected_tree = bound.get("expected_raw_tree")
    if expected_tree is not None and before != expected_tree:
        raise FamilyNativeV4Error("raw source tree differs from declared producer digest")
    output_sha = _sha_file(typed_path)
    attestation = bound_request["parent_attestation"]
    mode = _comparison_mode(output_sha256=output_sha, attestation=attestation)
    comparison: Any = None
    if mode == "FULL_FIELD_FALLBACK_REQUIRED":
        comparison = converter.compare_reference_hdf5(typed_path, bound["reference_hdf5"], particle_chunk=65536)
        if not comparison.get("passed"):
            raise FamilyNativeV4Error(f"full reference HDF5 comparison failed: {comparison}")
        mode = "FULL_FIELD_FALLBACK_WITHOUT_PARENT_EQUALITY" if attestation is None else "FULL_FIELD_FALLBACK_SHA_DIFFERED"
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETE_DEVELOPMENT_UNKNOWN",
        "request": {"path": str(request_file), "sha256": _sha_file(request_file)},
        "source_closure": {"family_id": bound["family"], "frames": bound["frames"],
                            "particles": bound["particles"],
                            "raw_tree": {"expected": expected_tree, "actual_before": before,
                                         "actual_after": after, "unchanged": True},
                            "reference_hdf5": str(bound["reference_hdf5"])},
        "raw_to_typed": {"status": "COMPLETE", "converter_report": str(target_report),
                         "converter_report_sha256": _sha_file(target_report)},
        "typed_output": {"path": str(typed_path), "bytes": typed_path.stat().st_size,
                          "sha256": output_sha},
        "reference_comparison": {"mode": mode, "reference_expected_sha256": bound_request["reference_hdf5_sha256"],
                                  "parent_attestation": attestation, "field_comparison": comparison},
        "labels": {"status": "PENDING_FAMILY_SPECIFIC_OPERATOR", "receiver_geometry_inference": "FORBIDDEN"},
        "execution_boundary": {
            "raw_opened": True,
            "hdf5_opened": True,
            "typed_output_hdf5_written": True,
            "reference_hdf5_opened": mode != "WHOLE_FILE_SHA_EQUAL_PARENT_ATTESTED",
            "converter_invoked": True,
            "model_invoked": False,
            "cfd_invoked": False,
            "parent_stage2guard_required": True,
        },
        "resource": {"wall_seconds": time.monotonic() - started},
        "qualification": dict(UNKNOWN),
    }
    report["report_sha256"] = _canonical(report)
    _write_new(target / "raw-to-typed-compare-report.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--source-v3-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    attach = sub.add_parser("attach-parent-attestation")
    attach.add_argument("--request", type=Path, required=True)
    attach.add_argument("--attestation", type=Path, required=True)
    attach.add_argument("--output", type=Path, required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--request", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--request", type=Path, required=True)
    execute.add_argument("--output-dir", type=Path, required=True)
    execute.add_argument("--io-slot-approved", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "build-request":
            value = build_request(args.source_v3_request, args.output)
            result = {"status": value["status"], "sha256": value["sha256"], "family_id": value["family_id"]}
        elif args.action == "attach-parent-attestation":
            value = attach_parent_attestation(args.request, args.attestation, args.output)
            result = {"status": value["status"], "sha256": value["sha256"], "family_id": value["family_id"]}
        elif args.action == "prepare":
            value = prepare_report(args.request, args.output)
            result = {"status": value["status"], "report_sha256": value["report_sha256"]}
        else:
            value = run(args.request, args.output_dir, io_slot_approved=args.io_slot_approved)
            result = {"status": value["status"], "report_sha256": value.get("report_sha256"),
                      "reference_mode": value.get("reference_comparison", {}).get("mode")}
    except (FamilyNativeV4Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
