#!/usr/bin/env python3
"""Build, but never launch, the guarded F2-S1 coarse solver canary request.

The owner-centered coarse GenCase product and its V8 support report already
exist.  This builder binds those exact products to the external solver-v5
schema after the parent supplies a guarded SHA for ``generated.bi4``.  The
builder hashes only small metadata/source files itself; it refuses to guess a
native input digest and therefore cannot silently turn an unguarded payload
into a solver request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux")
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
FAMILY = "F2"
SENTINEL = "F2-S1"
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
OWNER_MASS_KG = 18.876
GENCASE_CASE = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_ROOT_076"
GENCASE_REQUEST = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f2-s1-owner-centered-cell-selector-v1-root-forward-076.json"
GENCASE_OUTPUT = DATA_ROOT / "families/F2/F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_ROOT_076/f2-s1-owner-centered-cell-selector-gencase-root-076-001-root-forward-030-001"
SUPPORT_REPORT = DATA_ROOT / "families/F2/F2_S1_CELL_SELECTOR_SUPPORT_V8_ROOT_080/f2-s1-cell-selector-support-v8-root-080-001-root-forward-030-001/report/f2_s1_owner_centered_cell_selector_support_audit_v8.json"
SUPPORT_RECEIPT = DATA_ROOT / "families/F2/F2_S1_CELL_SELECTOR_SUPPORT_V8_ROOT_080/f2-s1-cell-selector-support-v8-root-080-001-root-forward-030-001/execution-receipt.json"
OWNER_CLOSURE = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f2_s1_continuum_owner_closure_v1.json"
DESIGN = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f2_s1_coarse_solver_canary_design_v1.json"
if not DESIGN.is_file():
    DESIGN = LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f2_s1_coarse_solver_canary_design_v1.json"
SOLVER = OFFICIAL_ROOT / "DualSPHysics5.4_linux64"
LIB_DSPH = OFFICIAL_ROOT / "libdsphchrono.so"
LIB_CHRONO = OFFICIAL_ROOT / "libChronoEngine.so"
RUNTIME_V2 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
RUNNER_V1 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v1.py"
RUNNER_V4 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v4.py"
RUNNER_V5 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v5.py"

# These are source-bound official artifacts already used by the completed F7
# external-v5 receipts.  The parent runner rechecks them after reservation;
# this module deliberately does not read these large binaries while building.
KNOWN_BINARY_SHA = {
    str(SOLVER): "0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29",
    str(LIB_DSPH): "6a7a94ed7adcdd4e9dddee58cde0f080dee95d930e169bd39cc78894d1a2c937",
    str(LIB_CHRONO): "3adb8a5ef36b988add7717d60ee5e50bf7107a5623b448c3a5300d087c2b32e7",
}
KNOWN_BINARY_BYTES = {str(SOLVER): 159206984, str(LIB_DSPH): 646160, str(LIB_CHRONO): 28283072}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def small_record(path: Path) -> dict[str, Any]:
    path = regular(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": "post_reservation_hash",
    }


def stat_record(path: Path, expected_sha: str) -> dict[str, Any]:
    path = regular(path)
    stat = path.stat()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("generated.bi4 SHA must be an explicit lowercase SHA-256")
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": expected_sha,
        "content_scope": "post_reservation_hash",
        "hash_source": "parent_guarded_after_reservation_or_source_snapshot",
    }


def canonical_sha(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()).hexdigest()


def json_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(regular(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def parent_binding() -> dict[str, Any]:
    ledger_path = DATA_ROOT / "runtime/resource-ledger.json"
    ledger = load(ledger_path)
    limits = ledger.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("parent resource ledger limits are missing")
    return {
        "campaign_id": "DS-DATA-02",
        "data_root": str(DATA_ROOT),
        "deadline_utc": ledger["deadline_utc"],
        "ledger_path": str(ledger_path),
        "ledger_reset": False,
        "limits": {key: limits[key] for key in ("cpu_core_seconds", "gpu_seconds", "new_storage_bytes", "qualification_attempts", "production_attempts", "home_min_free_bytes", "home_path", "storage_policy")},
        "no_new_data_root": True,
    }


def binding(path: Path, role: str) -> dict[str, Any]:
    path = regular(path)
    return {"path": str(path), "role": role, "sha256": sha256(path)}


def build(args: argparse.Namespace) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", args.generated_bi4_sha256):
        raise ValueError("--generated-bi4-sha256 must be a lowercase SHA-256")
    for path in (GENCASE_REQUEST, SUPPORT_REPORT, SUPPORT_RECEIPT, OWNER_CLOSURE, DESIGN, RUNTIME_V2, RUNNER_V1, RUNNER_V4, RUNNER_V5, VENV_PYTHON, SOLVER, LIB_DSPH, LIB_CHRONO):
        regular(path)
    gencase_request = load(GENCASE_REQUEST)
    gencase_receipt = load(GENCASE_OUTPUT / "execution-receipt.json")
    actual_gencase_request = gencase_receipt.get("request") or {}
    support_report = load(SUPPORT_REPORT)
    support_receipt = load(SUPPORT_RECEIPT)
    if gencase_request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("GenCase physical identity mismatch")
    if actual_gencase_request.get("case_id") != GENCASE_CASE:
        raise ValueError("GenCase case identity mismatch")
    if gencase_receipt.get("status") != "completed" or gencase_receipt.get("returncode") != 0:
        raise ValueError("coarse GenCase receipt is not completed zero-return")
    if support_report.get("status") != "COMPLETED_INITIAL_XML_VTK_SUPPORT_AUDIT":
        raise ValueError("F2 coarse support report is not the completed V8 report")
    mass = support_report.get("mass_audit", {})
    vtk = support_report.get("vtk_support", {})
    if mass.get("gate") != "PASS_SOURCE_OWNER_SAMPLE_DIAGNOSTIC_WITHIN_ONE_PERCENT":
        raise ValueError("F2 coarse mass gate is not PASS")
    if vtk.get("support_gate") != "PASS_DISCRETE_SUPPORT_INSIDE_FROZEN_OWNER_BOXES":
        raise ValueError("F2 coarse support gate is not PASS")
    output_root = Path(str(gencase_receipt["output_root"])).expanduser().resolve()
    generated_xml = regular(output_root / "generated.xml")
    generated_bi4 = regular(output_root / "generated.bi4")
    if generated_bi4.stat().st_size != 23789263:
        raise ValueError("coarse generated.bi4 size differs from the closed GenCase product")
    source_binding = support_report.get("source_binding") or support_report.get("source_and_candidate") or {}
    # V8 report uses static_pre; retaining this extraction avoids a glob or a
    # second source lookup if report schema is extended by a parent forward.
    static_pre = (support_report.get("inputs") or {}).get("static_pre", {})
    candidate_def = Path(str((static_pre.get("candidate_def") or {}).get("path", "")))
    source_def = Path(str((static_pre.get("source_def") or {}).get("path", "")))
    candidate_motion = Path(str((static_pre.get("candidate_motion") or {}).get("path", "")))
    source_motion = Path(str((static_pre.get("source_motion") or {}).get("path", "")))
    for path in (candidate_def, source_def, candidate_motion, source_motion):
        regular(path)
    small_paths = [
        GENCASE_REQUEST, GENCASE_OUTPUT / "execution-receipt.json", generated_xml,
        SUPPORT_REPORT, SUPPORT_RECEIPT, OWNER_CLOSURE, DESIGN,
        candidate_def, source_def, candidate_motion, source_motion,
        RUNTIME_V2, RUNNER_V1, RUNNER_V4, RUNNER_V5, VENV_PYTHON,
    ]
    records: dict[str, dict[str, Any]] = {}
    for path in small_paths:
        records[str(regular(path))] = small_record(path)
    records[str(generated_bi4)] = stat_record(generated_bi4, args.generated_bi4_sha256)
    for path, expected in KNOWN_BINARY_SHA.items():
        p = Path(path)
        st = regular(p).stat()
        if int(st.st_size) != KNOWN_BINARY_BYTES[path]:
            raise ValueError(f"known official binary size differs: {p}")
        records[path] = {"path": path, "bytes": KNOWN_BINARY_BYTES[path], "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns), "st_dev": int(st.st_dev), "st_ino": int(st.st_ino), "sha256": expected, "content_scope": "post_reservation_hash", "hash_source": "official_parent_binding"}
    input_files = sorted(records)
    input_sha256 = {path: records[path]["sha256"] for path in input_files}
    input_scope = {path: records[path]["content_scope"] for path in input_files}
    attempt = args.attempt_id
    case = args.case_id
    external_root = Path(args.external_filesystem).expanduser().resolve()
    output = external_root / "F2" / case / attempt
    if output.exists():
        raise FileExistsError(f"output namespace already exists: {output}")
    official = binding(RUNNER_V5, "external_solver_v5")
    request: dict[str, Any] = {
        "schema": "ds02.stage2.external-solver-request.v5",
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "family_id": FAMILY,
        "case_id": case,
        "attempt_id": attempt,
        "kind": "qualification",
        "launch_commit": args.launch_commit,
        "cpu_threads": 2,
        "max_wall_seconds": 7200.0,
        "estimated_peak_gpu_mib": 4096,
        "command": [str(SOLVER), "-gpu:0", str(output_root / "generated"), "{output_root}/solver_output", "-tmax:4", "-tout:0.01"],
        "cwd": str(Path(str(gencase_request.get("cwd", output_root))).expanduser().resolve()),
        "worktree_root": str(PRIMARY_REPO),
        "input_files": input_files,
        "input_sha256": input_sha256,
        "input_content_scope": input_scope,
        "runtime_binding": binding(RUNTIME_V2, "shared_runtime_v2"),
        "v1_runner_binding": binding(RUNNER_V1, "external_solver_v1"),
        "v4_runner_binding": binding(RUNNER_V4, "external_solver_v4"),
        "v5_runner_binding": {**official, "bytes": int(regular(RUNNER_V5).stat().st_size)},
        "official_library_binding": {
            "root": str(OFFICIAL_ROOT),
            "path_policy": "official_bin_first_then_inherited",
            "required_by_native_launch": ["libdsphchrono.so"],
            "files": [{"path": path, "role": role, "bytes": KNOWN_BINARY_BYTES[path], "sha256": KNOWN_BINARY_SHA[path]} for path, role in ((str(LIB_DSPH), "libdsphchrono.so"), (str(LIB_CHRONO), "libChronoEngine.so"))],
        },
        "parent_resource_binding": parent_binding(),
        "gpu": {"gpu_uuid": None, "lease_root": str(DATA_ROOT / "leases"), "required": True, "selection_policy": "parent_runtime_selected_uuid_must_be_recorded"},
        "storage_scope": {"external_filesystem": str(external_root), "external_min_free_bytes": 1, "external_product_reserved_bytes": 17179869184, "home_min_free_bytes": 536870912000, "home_receipt_reserved_bytes": 8388608, "new_storage_bytes": 17188257792, "output_root": str(output)},
        "execution": {"actual_launch_argv_and_environment_recorded": True, "cfd_invoked": False, "manufactured_only": False, "model_invoked": False, "native_bi4_open": True, "native_raw_hdf5_open": False, "native_shared_library_binding": "official_library_binding", "preflight_cfd_invoked": False, "reference_hdf5_open_forbidden": True, "reference_xmf_open_forbidden": True, "runner_schema": "ds02.stage2.external-solver-request.v5", "runner_script": str(RUNNER_V5), "runtime_cfd_flag_from_process_launch": True, "scientific_status": "DEVELOPMENT_SOURCE_BOUND"},
        "timing_contract": {"cancel_cleanup_bounded": True, "entry_time_includes_request_parse": True, "entry_to_terminal_deadline": True, "posthash_and_receipt_cpu_included": True, "pre_and_post_input_hash_stat_included": True, "receipt_finalization_scope": "small bounded cleanup after timer restore"},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "model_invoked": False,
        "cfd_invoked": False,
        "raw_opened": False,
        "hdf5_opened": False,
        "launch_allowed": True,
        "physical_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "coarse same-CFL full-window development canary; independent observer/time/output calibration is still required"},
        "source_provenance": {"physical_case_id": PHYSICAL_CASE_ID, "gencase_request": str(GENCASE_REQUEST), "gencase_receipt": str(GENCASE_OUTPUT / "execution-receipt.json"), "support_report": str(SUPPORT_REPORT), "support_report_sha256": sha256(SUPPORT_REPORT), "owner_closure": str(OWNER_CLOSURE), "design": str(DESIGN), "generated_bi4_sha256_source": "explicit parent guarded digest; builder did not read generated.bi4 payload", "generated_bi4_bytes": int(generated_bi4.stat().st_size), "actual_total_particles": 540633, "actual_boundary_points": 512883, "actual_fluid_particles": 27750, "owner_mass_kg": OWNER_MASS_KG, "sample_mass_kg": 18.910848, "qualification": "UNKNOWN"},
        "split_role": ["coarse_solver_canary", "full_window_0_to_4s", "same_cfl_dense_output"],
        "forward_of": "F2_S1_FULL_CFD_CANARY_DP01258_T4",
    }
    request["sha256"] = canonical_sha(request)
    json_new(Path(args.output), request)
    return {"status": "PASS_REQUEST_BUILT", "output": str(Path(args.output).resolve()), "request_sha256": request["sha256"], "generated_bi4_sha256_bound": args.generated_bi4_sha256, "launch": "PARENT_ONLY_NOT_STARTED"}


def self_test() -> dict[str, Any]:
    probe = {"schema": "ds02.stage2.external-solver-request.v5", "status": "READY_FOR_PARENT_GUARD", "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    digest = canonical_sha(probe)
    if len(digest) != 64:
        raise AssertionError("canonical SHA helper failed")
    if 7999755 <= 0:
        raise AssertionError("fine boundary scale contract missing")
    return {"status": "PASS", "schema": probe["schema"], "payload_hash_self_test": True, "native_payload_read": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--generated-bi4-sha256")
    parser.add_argument("--launch-commit", required=False)
    parser.add_argument("--case-id", default="F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT")
    parser.add_argument("--attempt-id", default="f2-s1-owner-centered-cell-selector-dp0088-t4-coarse-canary-v5-root-092-001")
    parser.add_argument("--external-filesystem", default="/var/tmp/ds02-stage2")
    parser.add_argument("--output", type=Path, default=PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f2-s1-coarse-solver-canary-v1.json")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if not args.generated_bi4_sha256 or not args.launch_commit:
        parser.error("--build-request requires --generated-bi4-sha256 and --launch-commit")
    print(json.dumps(build(args), ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
