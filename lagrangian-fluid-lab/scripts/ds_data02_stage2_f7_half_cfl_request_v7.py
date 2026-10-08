#!/usr/bin/env python3
"""Build the deferred F7 half-CFL native solver request.

This builder is deliberately unusable before the parent-approved v12 initial
QA completes.  It consumes the actual v12 outer report and its v8 worker
report, binds the observed half-BI4 SHA without re-reading that payload, and
binds the staged motion file produced inside the fresh QA namespace.  The v6
runner then rehashes actionable sources only after its parent reservation and
materializes XML/BI4/motion into a fresh solver input namespace.  No HDF5 is
part of this request and the builder never launches a solver or GPU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
LAB_ROOT = SCRIPT_DIR.parent
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-02"
V6_RUNNER = SCRIPT_DIR / "ds_data02_stage2_external_solver_v6.py"
V5_RUNNER = SCRIPT_DIR / "ds_data02_stage2_external_solver_v5.py"
V4_RUNNER = SCRIPT_DIR / "ds_data02_stage2_external_solver_v4.py"
V1_RUNNER = SCRIPT_DIR / "ds_data02_stage2_external_solver_v1.py"
RUNTIME = SCRIPT_DIR / "ds_data02_runtime_v2.py"
V12_REQUEST = (CAMPAIGN_ROOT / "stage2/native-reconstruction/f7-half-cfl-v1/"
               "request-012-f7-v12-initial-qa/"
               "f7-s2-half-cfl-initial-typed-qa-outer-request-v12-001.json")
V12_OUTER = SCRIPT_DIR / "ds_data02_stage2_f7_half_cfl_initial_qa_outer_v12.py"
CURRENT = CAMPAIGN_ROOT / "stage2/CURRENT336.json"
V8_REQUEST = (CAMPAIGN_ROOT / "stage2/native-reconstruction/f7-half-cfl-v1/"
               "request-007-f7-v8-initial-qa/"
               "f7-s2-half-cfl-initial-typed-qa-request-v8-001.json")
LEDGER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
EXTERNAL_ROOT = Path("/var/tmp/ds02-stage2")
OFFICIAL_LIBRARY_ROOT = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/"
    "vendor/official/DualSPHysics_v5.4/bin/linux"
)
SOLVER = OFFICIAL_LIBRARY_ROOT / "DualSPHysics5.4_linux64"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
SCHEMA = "ds02.stage2.external-solver-request.v6"
REPORT_SCHEMA = "ds02.stage2.external-solver-report.v6"
MOTION_NAME = "motion_obstacle_quintic.dat"
MOTION_SHA = "6aedfbd0d7daff931917bcb126368856c63c1bb53ba17aebf9033ebea0067814"
BASELINE_BI4_SHA = "f905a45f615304877f2a753471639bf812021d1741df7fcd4b5dc536b258864a"


class HalfCFLRequestError(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HalfCFLRequestError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise HalfCFLRequestError(f"JSON object required: {target}")
    return value


def _require_file(path: Path, role: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise HalfCFLRequestError(f"{role} is missing: {path}")
    return path


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns), "inode": int(value.st_ino),
            "device": int(value.st_dev), "mode": int(value.st_mode)}


def _binding(path: Path, role: str, *, expected_sha: str | None = None,
             hash_content: bool = True, scope: str = "post_reservation_hash") -> dict[str, Any]:
    path = _require_file(path, role)
    sha = expected_sha
    if hash_content:
        sha = sha256_file(path)
    if not isinstance(sha, str) or len(sha) != 64:
        raise HalfCFLRequestError(f"{role} has no usable producer SHA")
    return {"role": role, "path": str(path), **_stat(path), "sha256": sha,
            "content_scope": scope, "content_read_by_builder": bool(hash_content)}


def _verify_canonical(path: Path, expected_schema: str) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != expected_schema or value.get("sha256") != canonical_sha(value):
        raise HalfCFLRequestError(f"noncanonical {expected_schema}: {path}")
    return value


def _parent_binding() -> dict[str, Any]:
    ledger = load_json(LEDGER)
    limits = ledger.get("limits", {})
    required = ("cpu_core_seconds", "gpu_seconds", "new_storage_bytes", "qualification_attempts",
                "production_attempts", "home_min_free_bytes", "home_path", "storage_policy")
    if any(key not in limits for key in required):
        raise HalfCFLRequestError("parent ledger lacks required live limits")
    return {"ledger_path": str(LEDGER), "data_root": str(LEDGER.parent.parent),
            "campaign_id": ledger.get("campaign_id"), "deadline_utc": ledger.get("deadline_utc"),
            "ledger_reset": False, "no_new_data_root": True,
            "limits": {key: limits[key] for key in required}}


def _qa_bindings(qa_report_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    qa_report_path = _require_file(qa_report_path, "v12 QA report")
    qa = _verify_canonical(qa_report_path, "ds02.stage2.f7-half-cfl-initial-typed-qa-outer-report.v12")
    v12_request = _verify_canonical(V12_REQUEST, "ds02.stage2.f7-half-cfl-initial-typed-qa-outer-request.v12")
    if qa.get("request_sha256") != v12_request.get("sha256"):
        raise HalfCFLRequestError("QA report is not bound to v12-001 request")
    if qa.get("status") != "PASS_INITIAL_TYPED_QA_DEVELOPMENT_UNKNOWN":
        raise HalfCFLRequestError("initial QA did not pass its development gate")
    if not isinstance(qa.get("decoder_identity_gate"), Mapping):
        raise HalfCFLRequestError("QA report lacks post-decode identity gate")
    array_gate = qa.get("decoder_initial_array_gate")
    if not isinstance(array_gate, Mapping):
        raise HalfCFLRequestError("QA report lacks post-decode Vel/Rhop gate")
    comparisons = array_gate.get("comparisons")
    if (not isinstance(comparisons, list)
            or {str(item.get("name")) for item in comparisons if isinstance(item, Mapping)}
            != {"velocity", "density"}
            or not all(isinstance(item, Mapping) and item.get("exact") is True
                       and item.get("finite") is True for item in comparisons)):
        raise HalfCFLRequestError("QA Vel/Rhop gate is not exact and finite")
    output_dir = Path(str(qa.get("output_dir", ""))).expanduser().resolve()
    if not output_dir.is_dir() or output_dir.name != "qa" or str(output_dir).startswith(("/tmp/", "/var/tmp/")):
        raise HalfCFLRequestError("QA output is not the parent Home qa namespace")
    v8_report_path = output_dir / "f7-s2-half-cfl-initial-typed-qa-v8-report.json"
    v8 = _verify_canonical(v8_report_path, "ds02.stage2.f7-half-cfl-initial-typed-qa.v8")
    if v8.get("status") != "PASS_INITIAL_TYPED_QA_DEVELOPMENT_UNKNOWN":
        raise HalfCFLRequestError("v8 worker report is not a successful development QA")
    motion = v8.get("future_solver_gate", {}).get("motion_stage", {})
    staged = Path(str(motion.get("target", ""))).expanduser().resolve()
    if staged != output_dir / "solver_input" / MOTION_NAME or not staged.is_file():
        raise HalfCFLRequestError("QA motion target is not the exact staged solver input")
    if motion.get("target_sha256") != MOTION_SHA or sha256_file(staged) != MOTION_SHA:
        raise HalfCFLRequestError("QA staged motion SHA differs")
    half_evidence = v8.get("source_validation", {}).get("half_bi4", {})
    half_path = Path(str(half_evidence.get("path", ""))).expanduser().resolve()
    half_sha = str(half_evidence.get("sha256", ""))
    if not half_path.is_file() or len(half_sha) != 64:
        raise HalfCFLRequestError("QA lacks observed half BI4 content SHA")
    before = half_evidence.get("before")
    after = half_evidence.get("after")
    if not isinstance(before, Mapping) or before != after:
        raise HalfCFLRequestError("half BI4 changed during initial QA")
    v8_inputs = _verify_canonical(V8_REQUEST, "ds02.stage2.f7-half-cfl-initial-typed-qa-request.v8").get("inputs", {})
    if str(v8_inputs.get("half_generated_bi4", {}).get("path", "")) != str(half_path):
        raise HalfCFLRequestError("QA half BI4 does not match frozen v8 source")
    return qa, v8, v12_request, staged


def build(*, qa_report: Path, output: Path, output_root: Path | None = None) -> dict[str, Any]:
    if output.exists():
        raise HalfCFLRequestError(f"refusing existing request: {output}")
    qa, v8, v12_request, staged_motion = _qa_bindings(qa_report)
    v8_inputs = load_json(V8_REQUEST)["inputs"]
    half_xml = _require_file(Path(str(v8_inputs["half_generated_xml"]["path"])), "half generated XML")
    half_bi4 = _require_file(Path(str(v8_inputs["half_generated_bi4"]["path"])), "half generated BI4")
    half_sha = str(v8["source_validation"]["half_bi4"]["sha256"])
    if half_bi4.stat().st_size != int(v8["source_validation"]["half_bi4"]["before"]["bytes"]):
        raise HalfCFLRequestError("half BI4 stat differs from QA evidence")
    case = str(v8.get("case_id", "F7_OBSTACLE_QUINTIC_B08_A065"))
    attempt_id = "f7-s2-a065-half-cfl-savedt-v7-001"
    if output_root is None:
        output_root = EXTERNAL_ROOT / "F7" / "F7_S2_HALF_CFL_SAVEDT_V7" / attempt_id
    output_root = Path(output_root).expanduser().resolve()
    if output_root.exists():
        raise HalfCFLRequestError(f"new output namespace already exists: {output_root}")
    parent = _parent_binding()
    input_bindings: list[dict[str, Any]] = []
    input_sha: dict[str, str] = {}
    input_scope: dict[str, str] = {}

    def add(path: Path, role: str, *, expected_sha: str | None = None,
            hash_content: bool = True, scope: str = "post_reservation_hash") -> None:
        item = _binding(path, role, expected_sha=expected_sha, hash_content=hash_content, scope=scope)
        input_bindings.append(item)
        input_sha[item["path"]] = item["sha256"]
        input_scope[item["path"]] = scope

    # Source files that the native solver/materializer actually needs.  The
    # baseline BI4 is intentionally absent: it belongs to the initial QA only.
    add(half_xml, "half_generated_xml")
    add(half_bi4, "half_generated_bi4", expected_sha=half_sha, hash_content=False)
    add(staged_motion, "qa_staged_motion")
    for key, role in (("half_gencase_receipt", "half_gencase_receipt"),
                      ("half_gencase_stdout", "half_gencase_stdout"),
                      ("F7_motion_control", "original_motion_control"),
                      ("v5_same_cfl_receipt", "v5_predecessor_receipt"),
                      ("v5_same_cfl_RunPARTs", "v5_predecessor_RunPARTs"),
                      ("pinned_native_bi4_decoder", "pinned_bi4_decoder")):
        add(Path(str(v8_inputs[key]["path"])), role,
            expected_sha=str(v8_inputs[key].get("sha256")))
    add(Path(str(qa_report)), "v12_initial_qa_report")
    add(Path(str(V8_REQUEST)), "v8_initial_qa_request")
    add(V12_REQUEST, "v12_outer_request")
    add(V12_OUTER, "v12_outer_runner")
    add(CURRENT, "CURRENT336_catalog", scope="source_content")
    for path, role in ((V6_RUNNER, "v6_runner"), (V5_RUNNER, "v5_runner"),
                       (V4_RUNNER, "v4_runner"), (V1_RUNNER, "v1_runner"),
                       (RUNTIME, "shared_runtime"), (SOLVER, "official_solver"),
                       (OFFICIAL_LIBRARY_ROOT / "libdsphchrono.so", "libdsphchrono"),
                       (OFFICIAL_LIBRARY_ROOT / "libChronoEngine.so", "libChronoEngine")):
        add(path, role)

    command = [str(SOLVER), "-gpu:0", "{solver_input_root}/" + half_xml.stem,
               "{output_root}/solver_output", "-tmax:12.00003209155591", "-tout:0.01"]
    materialization = {
        "root_template": "{attempt_root}/solver_input",
        "files": [
            {"role": "half_generated_xml", "source": str(half_xml), "target": half_xml.name, "sha256": input_sha[str(half_xml)]},
            {"role": "half_generated_bi4", "source": str(half_bi4), "target": half_bi4.name, "sha256": half_sha},
            {"role": "qa_staged_motion", "source": str(staged_motion), "target": MOTION_NAME, "sha256": MOTION_SHA},
        ],
        "source_fallback": "FORBIDDEN",
        "purpose": "fresh case namespace; producer GenCase directory is immutable",
    }
    request: dict[str, Any] = {
        "schema": SCHEMA, "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F7", "case_id": case.lower().replace("_", "-"), "attempt_id": attempt_id,
        "kind": "qualification", "command": command,
        "cwd": str(half_xml.parent), "cpu_threads": 2,
        "max_wall_seconds": 3600.0, "estimated_peak_gpu_mib": 4096,
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
        "runtime_binding": {"path": str(RUNTIME), "sha256": sha256_file(RUNTIME), "role": "shared_runtime_v2"},
        "v1_runner_binding": {"path": str(V1_RUNNER), "sha256": sha256_file(V1_RUNNER)},
        "v4_runner_binding": {"path": str(V4_RUNNER), "sha256": sha256_file(V4_RUNNER)},
        "v5_runner_binding": {"path": str(V5_RUNNER), "sha256": sha256_file(V5_RUNNER)},
        "v6_runner_binding": {"path": str(V6_RUNNER), "sha256": sha256_file(V6_RUNNER)},
        "parent_resource_binding": parent,
        "storage_scope": {
            "external_filesystem": str(EXTERNAL_ROOT), "output_root": str(output_root),
            "external_product_reserved_bytes": 8 * 1024**3,
            "home_receipt_reserved_bytes": 8 * 1024**2,
            "new_storage_bytes": 8 * 1024**3 + 8 * 1024**2,
            "home_min_free_bytes": int(parent["limits"]["home_min_free_bytes"]),
            "external_min_free_bytes": 1,
        },
        "gpu": {"required": True, "gpu_uuid": None,
                "selection_policy": "parent_runtime_selected_uuid_must_be_recorded",
                "lease_root": str(Path(parent["data_root"]) / "leases")},
        "input_files": [item["path"] for item in input_bindings],
        "input_sha256": input_sha, "input_content_scope": input_scope,
        "solver_input_materialization": materialization,
        "execution": {
            "runner_schema": SCHEMA, "runner_script": str(V6_RUNNER),
            "native_bi4_open": True, "native_raw_hdf5_open": False,
            "reference_hdf5_open_forbidden": True, "model_invoked": False,
            "cfd_invoked": False, "actual_gpu_uuid_from_parent_runtime": True,
            "receipt_ledger_gpu_cutoff_same_value": True,
            "scientific_status": "DEVELOPMENT_SOURCE_BOUND",
        },
        "timing_contract": {
            "entry_to_terminal_deadline": True, "entry_time_includes_request_parse": True,
            "pre_and_post_input_hash_stat_included": True,
            "posthash_output_and_materialization_included": True,
            "gpu_cutoff": "single frozen post-product-measurement value reused by receipt and ledger",
            "receipt_finalization_scope": "bounded serialization/ledger cleanup after cutoff",
        },
        "qa_gate": {
            "v12_report_path": str(Path(qa_report).expanduser().resolve()),
            "v12_report_sha256": sha256_file(qa_report), "v12_request_sha256": v12_request["sha256"],
            "v8_report_path": str(Path(qa["output_dir"]) / "f7-s2-half-cfl-initial-typed-qa-v8-report.json"),
            "v8_report_sha256": sha256_file(Path(qa["output_dir"]) / "f7-s2-half-cfl-initial-typed-qa-v8-report.json"),
            "staged_motion_path": str(staged_motion), "staged_motion_sha256": MOTION_SHA,
            "half_bi4_observed_sha256": half_sha, "initial_qa_status": qa["status"],
            "scientific_qualification": dict(UNKNOWN),
        },
        "source_provenance": {
            "qa_report_is_required_predecessor": True,
            "half_cfl": True, "cflnumber": 0.1, "dp_m": 0.02,
            "physical_window_s": [0.0, 12.00003209155591], "save_interval_s": 0.01,
            "initial_particle_count": 70179, "fluid_particle_count": 40700,
            "initial_mass_semantics": "native MassFluid/MassBound from QA typed arrays; no rigid-body inference",
            "future_solver_receipt_not_required": True,
            "historical_same_cfl_v5_is_predecessor_evidence_only": True,
        },
        "launch_allowed": True, "raw_opened": False, "hdf5_opened": False,
        "split_role": "DEVELOPMENT_PROSPECTIVE_ONLY",
    }
    request["sha256"] = canonical_sha(request)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    try:
        value = build(qa_report=args.qa_report, output=args.output, output_root=args.output_root)
        print(json.dumps({"status": value["status"], "schema": value["schema"],
                          "sha256": value["sha256"], "input_count": len(value["input_files"])}, indent=2))
        return 0
    except (HalfCFLRequestError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
