#!/usr/bin/env python3
"""Prepare a source-closed portable raw-to-label bundle after native v4.

This forward bundle is deliberately gated by the completed native v4 receipt,
the all-frame typed comparison, and the v15/v16 label outputs.  It records
original paths only as provenance and creates a deterministic role overlay for
a later parent copy/replay.  Building the manifest reads JSON reports and
metadata only; it never opens the source HDF5 or BI4 arrays and performs no
copy.  The resulting package is raw-to-typed-to-label evidence, distinct from
the v26 typed-only relocation request.  QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


BUNDLE_SCHEMA = "ds02.stage2.f2-native-raw-to-label-bundle.v3"
REQUEST_SCHEMA = "ds02.stage2.f2-native-raw-to-label-portable-request.v3"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")


class RawToLabelBundleV3Error(ValueError):
    """Raised when native evidence is absent or source bindings are unsafe."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _load(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().resolve().read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RawToLabelBundleV3Error(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise RawToLabelBundleV3Error(f"JSON object required: {path}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise RawToLabelBundleV3Error(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _record(path: Path | str, role: str, declared_sha: str | None, relative: str,
            *, status: str = "PARENT_GUARD_CONTENT_SHA_BOUND",
            replay_actionable: bool = True) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise RawToLabelBundleV3Error(f"bound source is missing: {role}: {target}")
    stat = target.stat()
    if not isinstance(declared_sha, str) or len(declared_sha) != 64 or any(ch not in HEX64 for ch in declared_sha):
        raise RawToLabelBundleV3Error(f"{role} needs a declared SHA-256: {target}")
    return {
        "role": role,
        "original_path": str(target),
        "bundle_relative_path": relative,
        "bytes": int(stat.st_size),
        "original_mtime_ns": int(stat.st_mtime_ns),
        "content_sha256": declared_sha,
        "content_hash_status": status,
        "replay_actionable": replay_actionable,
    }


def _derive_paths(compare_report: Path, report: Mapping[str, Any]) -> dict[str, Path]:
    labels = report.get("labels")
    if not isinstance(labels, Mapping):
        raise RawToLabelBundleV3Error("native v4 labels binding is missing")
    v15 = Path(str(labels.get("result"))).expanduser().resolve()
    v16_item = labels.get("v16_forward")
    if not isinstance(v16_item, Mapping):
        raise RawToLabelBundleV3Error("native v4 v16 forward binding is missing")
    v16 = Path(str(v16_item.get("result"))).expanduser().resolve()
    raw_label = v15.with_name("raw-to-typed-to-label-report-v2.json")
    raw_converter = v15.with_name("raw-converter-report-v2.json")
    attempt = compare_report.parent.parent
    receipt = attempt / "execution-receipt.json"
    request_path = Path(str(report.get("request", {}).get("path"))).expanduser().resolve()
    base_request = Path(str(_load(request_path).get("base_v2_request", {}).get("path"))).expanduser().resolve()
    return {
        "compare_report": compare_report,
        "v4_request": request_path,
        "base_v2_request": base_request,
        "execution_receipt": receipt,
        "v15_result": v15,
        "v16_result": v16,
        "raw_label_report": raw_label,
        "raw_converter_report": raw_converter,
    }


def _native_gate(paths: Mapping[str, Path], report: Mapping[str, Any], receipt: Mapping[str, Any],
                 raw_label: Mapping[str, Any]) -> dict[str, Any]:
    if report.get("schema") != "ds02.stage2.f2-native-raw-to-typed-reference-compare-report.v4":
        raise RawToLabelBundleV3Error("unexpected native v4 report schema")
    if report.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise RawToLabelBundleV3Error("native v4 terminal status is not complete")
    if report.get("qualification") != UNKNOWN:
        raise RawToLabelBundleV3Error("native v4 qualification is not UNKNOWN")
    boundary = report.get("execution_boundary")
    # v4 records the converter as ``v2_invoked`` and records label execution
    # through the v15/v16 result statuses.  Do not invent newer boundary keys
    # when consuming the immutable parent report.
    if not isinstance(boundary, Mapping) or not all(boundary.get(key) is True for key in ("raw_opened", "hdf5_opened", "v2_invoked", "reference_comparison_invoked")):
        raise RawToLabelBundleV3Error("native v4 did not record raw/HDF5/converter/reference execution")
    comparison = report.get("typed_reference_comparison")
    if not isinstance(comparison, Mapping) or comparison.get("all_nonpressure_arrays_equal") is not True or comparison.get("all_nonpressure_arrays_within_tolerance") is not True or comparison.get("exact_structural_datasets") is not True:
        raise RawToLabelBundleV3Error("native v4 all-frame typed comparison is not exact")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise RawToLabelBundleV3Error("native v4 execution receipt is not a successful terminal receipt")
    if report.get("labels", {}).get("status") != "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN":
        raise RawToLabelBundleV3Error("v15 labels are not complete development output")
    if report.get("labels", {}).get("v16_forward", {}).get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise RawToLabelBundleV3Error("v16 forward labels are not complete development output")
    raw_binding = raw_label.get("raw_to_typed", {}).get("raw_evidence")
    if not isinstance(raw_binding, Mapping):
        raise RawToLabelBundleV3Error("raw-to-label report has no raw evidence")
    before = raw_binding.get("before_tree_sha256")
    after = raw_binding.get("after_tree_sha256")
    expected = raw_binding.get("expected_raw_tree_sha256")
    if not isinstance(before, str) or before != after or before != expected:
        raise RawToLabelBundleV3Error("raw tree before/after/expected SHA is not identical")
    frames = raw_binding.get("frames")
    if not isinstance(frames, list) or len(frames) != int(raw_binding.get("frame_count", -1)) or len(frames) != 401:
        raise RawToLabelBundleV3Error("raw evidence does not contain all 401 frames")
    for index, frame in enumerate(frames):
        if not isinstance(frame, Mapping) or frame.get("frame") != index or not isinstance(frame.get("raw_frame_file_sha256"), str):
            raise RawToLabelBundleV3Error(f"raw evidence frame {index} lacks content SHA")
    typed_output = raw_label.get("typed_output")
    if not isinstance(typed_output, Mapping) or not isinstance(typed_output.get("sha256"), str):
        raise RawToLabelBundleV3Error("raw-to-label typed output is not content-bound")
    return {
        "raw_tree_sha256": before,
        "raw_file_count": int(raw_binding.get("file_count")),
        "raw_frame_count": len(frames),
        "raw_source_bytes": sum(int(frame.get("raw_frame_file_bytes", 0)) for frame in frames),
        "typed_output": dict(typed_output),
        "reference_hdf5": dict(report["reference_typed_hdf5"]),
        "native_elapsed_seconds": receipt.get("elapsed_seconds"),
        "native_cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "native_receipt_bytes": receipt.get("bytes"),
    }


def build_bundle(v4_report_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    compare_report = Path(v4_report_path).expanduser().resolve()
    report = _load(compare_report)
    paths = _derive_paths(compare_report, report)
    receipt = _load(paths["execution_receipt"])
    raw_label = _load(paths["raw_label_report"])
    gate = _native_gate(paths, report, receipt, raw_label)
    request = _load(paths["v4_request"])
    base_request = _load(paths["base_v2_request"])
    if request.get("status") != "READY_FOR_PARENT_GUARD" or request.get("qualification") != UNKNOWN:
        raise RawToLabelBundleV3Error("v4 request is not development/guard-bound")
    if request.get("root_canonical_wrapper", {}).get("case_scope") != "SINGLE_EXACT_F2_S1_CURRENT_ROW_ONLY":
        raise RawToLabelBundleV3Error("portable bundle must remain a single exact F2 CURRENT row")
    if base_request.get("qualification") != UNKNOWN or base_request.get("schema") != "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2":
        raise RawToLabelBundleV3Error("immutable base request is not the expected v2 raw-to-label route")
    raw_evidence = raw_label["raw_to_typed"]["raw_evidence"]
    source_records: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(record: Mapping[str, Any], role_prefix: str, *, actionable: bool = True) -> None:
        path = Path(str(record.get("path"))).expanduser().resolve()
        if str(path) in seen:
            return
        seen.add(str(path))
        role = str(record.get("role", role_prefix))
        source_records.append(_record(path, role, record.get("sha256"), f"sources/{len(source_records):04d}-{path.name}", replay_actionable=actionable))

    # Bind the immutable request and every v4 wrapper source role, including
    # the original HDF5 producer binding.  These are provenance and future
    # overlay inputs; this builder never hashes their content itself.
    add({"path": str(paths["v4_request"]), "sha256": sha256_file(paths["v4_request"]), "role": "v4_request"}, "v4_request")
    add({"path": str(paths["base_v2_request"]), "sha256": sha256_file(paths["base_v2_request"]), "role": "immutable_base_v2_request"}, "base_v2_request")
    wrapper = request.get("root_canonical_wrapper", {})
    for item in wrapper.get("immutable_file_bindings", []) if isinstance(wrapper, Mapping) else []:
        if isinstance(item, Mapping):
            add(item, "v4_wrapper_source")
    for item in wrapper.get("installed_runtime_bindings", []) if isinstance(wrapper, Mapping) else []:
        if isinstance(item, Mapping):
            add(item, "v4_runtime_source")
    for item in request.get("installed_runtime_anchors", []):
        if isinstance(item, Mapping):
            add(item, "v4_runtime_anchor")
    modules = request.get("modules", {})
    if isinstance(modules, Mapping):
        for role, item in modules.items():
            if isinstance(item, Mapping):
                add({**item, "role": str(item.get("role", role))}, str(role))
    for item in (request.get("decoder"), request.get("base_v2_request")):
        if isinstance(item, Mapping):
            add(item, str(item.get("role", "request_source")))
    closure = request.get("source_closure", {}).get("import_closure")
    if isinstance(closure, Mapping):
        add(closure, "import_closure", actionable=False)
    # Parent worker supplied a SHA for every raw frame in the terminal report.
    for frame in raw_evidence["frames"]:
        add({"path": frame["path"], "sha256": frame["raw_frame_file_sha256"], "bytes": frame.get("raw_frame_file_bytes"), "role": "raw_frame_input"}, "raw_frame_input")
    # Evidence/results are bound separately so a relocation loader can require
    # them without treating a previous output as a new input trajectory.
    evidence: list[dict[str, Any]] = []
    evidence_specs = [
        (paths["execution_receipt"], "native_v4_execution_receipt", None),
        (paths["compare_report"], "native_v4_compare_report", None),
        (paths["raw_label_report"], "raw_to_typed_to_label_report_v2", None),
        (paths["raw_converter_report"], "raw_converter_report_v2", None),
        (paths["v15_result"], "v15_label_result", report["labels"]["result_sha256"]),
        (paths["v16_result"], "v16_label_result", report["labels"]["v16_forward"]["result_sha256"]),
    ]
    for path, role, declared in evidence_specs:
        if not path.is_file():
            raise RawToLabelBundleV3Error(f"native evidence artifact is missing: {path}")
        digest = declared or sha256_file(path)
        evidence.append(_record(path, role, digest, f"evidence/{path.name}", replay_actionable=False))
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "status": "READY_FOR_PARENT_PORTABLE_GUARD; NATIVE_V4_TERMINAL_VERIFIED; DEVELOPMENT_UNKNOWN",
        "role": "DEVELOPMENT",
        "case_scope": {
            "family_id": "F2",
            "current_case_index": 78,
            "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
            "manifest_case_id": "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010",
            "frames": 401,
            "particles": 418104,
            "identity_key": "(Zone,Idp)",
            "fluid_cohort_count": 21114,
            "fluid_initial_mass_denominator_kg": 21.114001002861187,
            "selected_identity_sha256": "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70",
        },
        "native_gate": gate,
        "source_bindings": source_records,
        "evidence_artifacts": evidence,
        "raw_producer_binding": {
            "original_data_root": str(raw_evidence["data_root"]),
            "expected_file_count": gate["raw_file_count"],
            "frame_count": gate["raw_frame_count"],
            "frame_pattern": "Part_%04d.bi4",
            "expected_raw_tree_sha256": gate["raw_tree_sha256"],
            "per_frame_sha256_status": "VERIFIED_IN_NATIVE_V4_REPORT; PARENT_COPY_MUST_REHASH",
            "partout_runparts": "provenance only; never frame input",
        },
        "typed_reference_binding": {
            "original_path": gate["reference_hdf5"]["path"],
            "producer_content_sha256": gate["reference_hdf5"]["sha256"],
            "bytes": gate["reference_hdf5"]["bytes"],
            "content_hash_status": "VERIFIED_BY_NATIVE_V4_PARENT_RECEIPT; REHASH_AFTER_COPY",
            "typed_only_v26_relation": "v26 is a separate typed-only relocated replay; this bundle requires raw BI4 reconstruction and v15/v16 labels",
        },
        "raw_to_typed_to_label": {
            "native_v4_report": str(paths["compare_report"]),
            "raw_converter_report": str(paths["raw_converter_report"]),
            "typed_output_sha256": gate["typed_output"]["sha256"],
            "typed_output_bytes": gate["typed_output"]["bytes"],
            "v15_result_sha256": report["labels"]["result_sha256"],
            "v16_result_sha256": report["labels"]["v16_forward"]["result_sha256"],
            "labels_status": "COMPLETE_DEVELOPMENT_UNKNOWN",
            "receiver_qualification": "UNKNOWN",
        },
        "portable_overlay": {
            "original_paths_are_provenance_only": True,
            "copy_required_before_replay": True,
            "target_paths_must_be_new": True,
            "source_hash_required_after_copy": True,
            "path_map_roles": "source_bindings.bundle_relative_path",
            "original_path_fallback": "FORBIDDEN",
            "native_c_open_audit": "parent must run OS-level strace/openat audit; Python audit hooks do not cover HDF5 C opens",
        },
        "replay_contract": {
            "entrypoint": "native v4 raw converter + v15 replay + v16 forward operator",
            "raw_bi4_to_typed": True,
            "typed_reference_compare": True,
            "labels_v15_v16": True,
            "hdf5_copy_or_read": "parent slot only",
            "no_solver_model_cfd": True,
            "all_qi_qn_qe": "UNKNOWN",
        },
        "resource_request": {
            "cpu_threads": 1,
            "max_wall_seconds": 5400,
            "max_rss_observational_bytes": 5 * 1024**3,
            "raw_source_bytes": 7377823492,
            "reference_hdf5_bytes": 1191110523,
            # This is the complete source overlay, including the 401 raw
            # frames and every small provenance/runtime input.  Keep it
            # derived from the bound records instead of the raw+HDF5 pair;
            # the latter undercounts the initial CSV and other source roles.
            "source_copy_bytes_upper_bound": sum(int(item["bytes"]) for item in source_records),
            "evidence_copy_bytes": sum(int(item["bytes"]) for item in evidence),
            "bundle_input_bytes": sum(int(item["bytes"]) for item in source_records) + sum(int(item["bytes"]) for item in evidence),
            "typed_output_bytes": gate["typed_output"]["bytes"],
            "new_storage_reservation_bytes": 16 * 1024**3,
            "rss_enforcement": "parent guard records ru_maxrss; no RLIMIT_AS claim",
        },
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": UNKNOWN,
        "limitations": [
            "Portable copy/replay has not been run by this builder; parent must copy and rehash every role",
            "Native v4 labels are development evidence with hidden-between-save recrossing/physical qualification limits",
            "v26 typed-only relocation remains separate and cannot supply raw-to-label credit",
        ],
    }
    manifest["sha256"] = canonical_sha(manifest)
    _write_new(output_path, manifest)
    return {"path": str(Path(output_path).expanduser().resolve()), "sha256": manifest["sha256"], "source_count": len(source_records), "evidence_count": len(evidence)}


def build_request(manifest_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    manifest_file = Path(manifest_path).expanduser().resolve()
    manifest = _load(manifest_file)
    if manifest.get("schema") != BUNDLE_SCHEMA or not str(manifest.get("status", "")).startswith("READY_FOR_PARENT_PORTABLE_GUARD"):
        raise RawToLabelBundleV3Error("bundle is not native-v4-gated/guard-ready")
    if manifest.get("qualification") != UNKNOWN or manifest.get("portable_overlay", {}).get("original_path_fallback") != "FORBIDDEN":
        raise RawToLabelBundleV3Error("portable bundle qualification/fallback policy is unsafe")
    request = {
        "schema": REQUEST_SCHEMA,
        "request_id": "f2-s1-native-raw-to-label-portable-v3-001",
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "bundle": {"path": str(manifest_file), "sha256": sha256_file(manifest_file), "canonical_sha256": manifest["sha256"]},
        "input_files": [str(manifest_file)] + [item["original_path"] for item in manifest.get("source_bindings", [])] + [item["original_path"] for item in manifest.get("evidence_artifacts", [])],
        "input_hashes": {str(manifest_file): sha256_file(manifest_file), **{item["original_path"]: item["content_sha256"] for item in manifest.get("source_bindings", [])}, **{item["original_path"]: item["content_sha256"] for item in manifest.get("evidence_artifacts", [])}},
        "execution": {
            "command": ["/usr/bin/strace", "-f", "-yy", "-e", "trace=open,openat,openat2,creat", "-o", "<attempt_root>/os-trace.log", "<portable_runner>", "--bundle", "<relocated-bundle-manifest>", "--io-slot-approved"],
            "copy_before_run": True,
            "rehash_after_copy": True,
            "os_open_audit_required": True,
            "original_path_fallback": False,
            "hdf5_or_bi4_read": "parent slot only",
        },
        "resource_request": manifest["resource_request"],
        "raw_to_label": manifest["raw_to_typed_to_label"],
        "case_scope": manifest["case_scope"],
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": UNKNOWN,
        "limitations": manifest["limitations"],
    }
    request["sha256"] = canonical_sha(request)
    _write_new(output_path, request)
    return {"path": str(Path(output_path).expanduser().resolve()), "sha256": request["sha256"], "input_count": len(request["input_files"])}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-bundle")
    build.add_argument("--native-report", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    request = sub.add_parser("build-request")
    request.add_argument("--bundle", type=Path, required=True)
    request.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_bundle(args.native_report, args.output) if args.command == "build-bundle" else build_request(args.bundle, args.output)
    except (OSError, json.JSONDecodeError, RawToLabelBundleV3Error, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
