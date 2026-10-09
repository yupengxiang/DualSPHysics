#!/usr/bin/env python3
"""Build, but never launch, the F3-S2 ROOT120 external-v5 canary.

ROOT120 is a completed GenCase producer.  This builder binds its generated
XML/BI4, the ROOT120 forcing receipt, the completed initial-support report and
the official v5 runner to one new external-solver request.  The builder hashes
small JSON/XML/code inputs.  It does not read the generated BI4 or forcing
CSV; their explicit SHA values must come from the parent guarded snapshot or
ROOT120 terminal receipt.  The executable command is an attempt-contained
materializer, so the ROOT120 output tree remains immutable and the forcing CSV
is copied only after the v5 parent has reserved storage and completed its
source pre-hash.

The request is development/UNKNOWN.  A parent process owns the GPU UUID,
reservation, launch, timeout, terminal RunPARTs/Run.out evidence and charge.
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
SOLVER = OFFICIAL_ROOT / "DualSPHysics5.4_linux64"
LIB_DSPH = OFFICIAL_ROOT / "libdsphchrono.so"
LIB_CHRONO = OFFICIAL_ROOT / "libChronoEngine.so"
RUNNER_V1 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v1.py"
RUNNER_V4 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v4.py"
RUNNER_V5 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v5.py"
RUNTIME_V2 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
WRAPPER = Path(__file__).resolve().with_name("stage2_f3_s2_external_solver_v5_materialize.py")
FAMILY = "F3"
SENTINEL = "F3-S2"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
ROOT120_CASE = "F3_S2_OWNER_CENTERED_DP015_GENCASE_ROOT_120"
ROOT120_RECEIPT_ROOT = DATA_ROOT / "families/F3" / ROOT120_CASE / "f3-s2-owner-centered-dp015-gencase-v2-root-120-001-root-forward-030-001"
DEFAULT_SOURCE_XML = DATA_ROOT / ("families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/"
                                  "root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/"
                                  "prepared/pitch120_ay0750/F3_STAGE1_DP006_P1200_AY0750.xml")
DEFAULT_SOURCE_CONTROL = DATA_ROOT / ("families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/"
                                      "root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/"
                                      "prepared/pitch120_ay0750/CaseSloshingAccData.csv")
COST_BASIS_RECEIPT = DATA_ROOT / ("families/F3/F3_CELL3_LONG_DP0015_ADAPTIVE_CFL05_COEF005/"
                                  "root-cell3-adaptive-coarse-full835-native-spatial-025/execution-receipt.json")
TMAX = "8.350016881886734"
TOUT = "0.01"
ESTIMATED_NATIVE_FRAMES = "UNKNOWN_UNTIL_TERMINAL_RUNPARTS"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}

# These are the binary bindings already used by the completed external-v5
# receipts.  The builder records them and the v5 runner re-hashes them after
# reservation; it does not read them to rediscover a potentially new binary.
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


def regular(path: Path, label: str = "input") -> Path:
    # Request input bindings follow the shared v5 runner's canonical path
    # rule.  In particular, the venv's ``bin/python`` is a symlink; resolve it
    # for input SHA lookup while the executable wrapper's shebang retains the
    # literal venv path used at launch.
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def small_record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": "post_reservation_hash",
        "content_read_by_builder": True,
    }


def stat_record(path: Path, expected_sha: str, label: str, *, authority: str) -> dict[str, Any]:
    path = regular(path, label)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError(f"{label} expected SHA must be an explicit lowercase SHA-256")
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": expected_sha,
        "content_scope": "post_reservation_hash",
        "content_read_by_builder": False,
        "sha_authority": authority,
    }


def canonical_sha(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()).hexdigest()


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def parent_binding() -> dict[str, Any]:
    ledger_path = DATA_ROOT / "runtime/resource-ledger.json"
    ledger = load_json(ledger_path, "parent resource ledger")
    limits = ledger.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("parent resource ledger limits are missing")
    keys = ("cpu_core_seconds", "gpu_seconds", "new_storage_bytes", "qualification_attempts",
            "production_attempts", "home_min_free_bytes", "home_path", "storage_policy")
    return {
        "campaign_id": "DS-DATA-02",
        "data_root": str(DATA_ROOT),
        "deadline_utc": ledger["deadline_utc"],
        "ledger_path": str(ledger_path),
        "ledger_reset": False,
        "limits": {key: limits[key] for key in keys},
        "no_new_data_root": True,
    }


def binding(path: Path, role: str) -> dict[str, Any]:
    path = regular(path, role)
    return {"path": str(path), "role": role, "sha256": sha256(path)}


def producer_control_sha(receipt: dict[str, Any], control: Path) -> str:
    found: dict[str, str] = {}
    for key in ("input_hashes_at_launch", "input_hashes_after_run"):
        mapping = receipt.get(key)
        if not isinstance(mapping, dict):
            continue
        for path, value in mapping.items():
            if isinstance(path, str) and Path(path).name == control.name and isinstance(value, str) and len(value) == 64:
                found[key] = value
                break
    if set(found) != {"input_hashes_at_launch", "input_hashes_after_run"} or len(set(found.values())) != 1:
        raise ValueError("ROOT120 forcing receipt does not close launch/end SHA equality")
    return found["input_hashes_at_launch"]


def _actual_support_status(report: dict[str, Any]) -> str:
    status = str(report.get("status", ""))
    if not status.startswith("COMPLETED_F3_S2_INITIAL_SUPPORT_AUDIT"):
        raise ValueError(f"support report is not a completed F3-S2 initial audit: {status}")
    return status


def build(args: argparse.Namespace) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", args.generated_bi4_sha256):
        raise ValueError("--generated-bi4-sha256 must be a lowercase SHA-256")
    gencase_q = regular(args.gencase_request, "ROOT120 GenCase request")
    receipt_path = regular(args.receipt, "ROOT120 GenCase receipt")
    receipt = load_json(receipt_path, "ROOT120 GenCase receipt")
    gencase_q_value = load_json(gencase_q, "ROOT120 GenCase request")
    q_scope = gencase_q_value.get("scope") if isinstance(gencase_q_value.get("scope"), dict) else {}
    if (gencase_q_value.get("physical_case_id") or q_scope.get("physical_case_id")) != PHYSICAL_CASE_ID:
        raise ValueError("ROOT120 GenCase request physical identity mismatch")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None):
        raise ValueError("ROOT120 receipt is not completed zero-return")
    if str((receipt.get("request") or {}).get("case_id", ROOT120_CASE)) != ROOT120_CASE:
        raise ValueError("ROOT120 receipt request case identity mismatch")
    receipt_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    generated_xml = regular(args.generated_xml, "ROOT120 generated XML")
    generated_bi4 = regular(args.generated_bi4, "ROOT120 generated BI4")
    if generated_xml.parent != receipt_root or generated_bi4.parent != receipt_root:
        raise ValueError("ROOT120 generated XML/BI4 must remain in the terminal producer root")
    source_xml = regular(args.source_xml or DEFAULT_SOURCE_XML, "F3 source XML")
    source_control = regular(args.source_control or DEFAULT_SOURCE_CONTROL, "F3 forcing CSV")
    expected_control_sha = producer_control_sha(receipt, source_control)
    support_report_path = regular(args.support_report, "F3 ROOT121 support report")
    support_report = load_json(support_report_path, "F3 ROOT121 support report")
    support_status = _actual_support_status(support_report)
    cost_basis = regular(args.cost_basis_receipt or COST_BASIS_RECEIPT, "F3 cost-basis receipt")
    cost_basis_value = load_json(cost_basis, "F3 cost-basis receipt")
    basis_bytes = int(cost_basis_value.get("bytes", 0) or 0)
    if basis_bytes <= 0:
        raise ValueError("F3 cost-basis receipt has no positive terminal bytes")

    # The parent may supply a fresh case/attempt, but the request remains
    # source-bound to ROOT120 and one new external output namespace.
    wrapper = regular(WRAPPER, "F3 v5 materialization wrapper")
    for path in (RUNTIME_V2, RUNNER_V1, RUNNER_V4, RUNNER_V5, VENV_PYTHON, SOLVER, LIB_DSPH, LIB_CHRONO):
        regular(path, "official/runtime binding")
    control_record = stat_record(
        source_control, expected_control_sha, "F3 forcing CSV",
        authority="ROOT120_execution_receipt_input_hashes_at_launch_and_after_run",
    )
    control_record.update({
        "producer_receipt_sha256_at_launch": expected_control_sha,
        "producer_receipt_sha256_after_run": expected_control_sha,
        "producer_receipt_pre_post_sha_equal": True,
        "content_scope": "parent_after_reservation_pre_post_hash",
    })
    bi4_record = stat_record(
        generated_bi4, args.generated_bi4_sha256, "ROOT120 generated BI4",
        authority="parent_guarded_snapshot_or_after_reservation_hash",
    )
    records: dict[str, dict[str, Any]] = {}
    for path, label in (
        (gencase_q, "ROOT120 GenCase request"), (receipt_path, "ROOT120 GenCase receipt"),
        (generated_xml, "ROOT120 generated XML"), (source_xml, "F3 source XML"),
        (support_report_path, "ROOT121 support report"), (cost_basis, "F3 full-window cost-basis receipt"),
        (wrapper, "F3 v5 materialization wrapper"), (RUNTIME_V2, "shared runtime v2"),
        (RUNNER_V1, "external solver v1"), (RUNNER_V4, "external solver v4"),
        (RUNNER_V5, "external solver v5"), (VENV_PYTHON, "stage2 literal venv interpreter"),
    ):
        records[str(regular(path, label))] = small_record(path, label)
    records[str(source_control)] = control_record
    records[str(generated_bi4)] = bi4_record
    for path_text, label in ((str(SOLVER), "official DualSPHysics solver"), (str(LIB_DSPH), "libdsphchrono.so"), (str(LIB_CHRONO), "libChronoEngine.so")):
        path = Path(path_text)
        stat = regular(path, label).stat()
        if int(stat.st_size) != KNOWN_BINARY_BYTES[path_text]:
            raise ValueError(f"official binary size differs from bound v5 artifact: {path}")
        records[path_text] = {
            "path": path_text, "label": label, "bytes": KNOWN_BINARY_BYTES[path_text],
            "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns),
            "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino),
            "sha256": KNOWN_BINARY_SHA[path_text], "content_scope": "post_reservation_hash",
            "content_read_by_builder": False, "sha_authority": "completed_external_v5_binary_binding",
        }
    input_files = sorted(records)
    input_hashes = {path: records[path]["sha256"] for path in input_files}
    input_scope = {path: records[path]["content_scope"] for path in input_files}
    external_root = Path(args.external_filesystem).expanduser().resolve()
    case_id = args.case_id
    attempt_id = args.attempt_id
    output = external_root / FAMILY / case_id / attempt_id
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output namespace already exists: {output}")

    command = [
        str(wrapper), "--solver", str(SOLVER), "--output-root", "{output_root}",
        "--generated-xml", str(generated_xml), "--generated-bi4", str(generated_bi4),
        "--forcing-csv", str(source_control),
        "--expected-generated-xml-sha", records[str(generated_xml)]["sha256"],
        "--expected-generated-bi4-sha", args.generated_bi4_sha256,
        "--expected-forcing-sha", expected_control_sha,
        "--tmax", TMAX, "--tout", TOUT, "--mdbc-noslip", "1",
    ]
    request: dict[str, Any] = {
        "schema": "ds02.stage2.external-solver-request.v5",
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "qualification",
        "launch_commit": args.launch_commit,
        "cpu_threads": 2,
        "max_wall_seconds": float(args.max_wall_seconds),
        "estimated_peak_gpu_mib": 4096,
        "command": command,
        "cwd": str(wrapper.parent),
        "worktree_root": str(PRIMARY_REPO),
        "input_files": input_files,
        "input_sha256": input_hashes,
        "input_content_scope": input_scope,
        "runtime_binding": binding(RUNTIME_V2, "shared_runtime_v2"),
        "v1_runner_binding": binding(RUNNER_V1, "external_solver_v1"),
        "v4_runner_binding": binding(RUNNER_V4, "external_solver_v4"),
        "v5_runner_binding": {**binding(RUNNER_V5, "external_solver_v5"), "bytes": int(RUNNER_V5.stat().st_size)},
        "official_library_binding": {
            "root": str(OFFICIAL_ROOT), "path_policy": "official_bin_first_then_inherited",
            "required_by_native_launch": ["libdsphchrono.so", "libChronoEngine.so"],
            "files": [{"path": path, "role": role, "bytes": KNOWN_BINARY_BYTES[path], "sha256": KNOWN_BINARY_SHA[path]} for path, role in ((str(LIB_DSPH), "libdsphchrono.so"), (str(LIB_CHRONO), "libChronoEngine.so"))],
        },
        "parent_resource_binding": parent_binding(),
        "gpu": {"gpu_uuid": None, "lease_root": str(DATA_ROOT / "leases"), "required": True, "selection_policy": "parent_runtime_selected_uuid_must_be_recorded"},
        "storage_scope": {
            "external_filesystem": str(external_root), "external_min_free_bytes": 1,
            "external_product_reserved_bytes": int(args.external_reserve_bytes),
            "home_min_free_bytes": 536870912000, "home_receipt_reserved_bytes": int(args.home_receipt_reserve_bytes),
            "new_storage_bytes": int(args.external_reserve_bytes) + int(args.home_receipt_reserve_bytes),
            "output_root": str(output),
            "reservation_basis": {
                "actual_cost_basis_receipt": str(cost_basis),
                "actual_cost_basis_receipt_sha256": records[str(cost_basis)]["sha256"],
                "actual_cost_basis_terminal_bytes": basis_bytes,
                "new_canary_reserve_is_not_a_wall_or_frame_guarantee": True,
                "expected_native_frames": ESTIMATED_NATIVE_FRAMES,
            },
        },
        "execution": {
            "actual_launch_argv_and_environment_recorded": True,
            "cfd_invoked": False, "manufactured_only": False, "model_invoked": False,
            "native_bi4_open": True, "native_raw_hdf5_open": False,
            "native_shared_library_binding": "official_library_binding",
            "preflight_cfd_invoked": False, "reference_hdf5_open_forbidden": True,
            "reference_xmf_open_forbidden": True,
            "runner_schema": "ds02.stage2.external-solver-request.v5",
            "runner_script": str(RUNNER_V5),
            "materializer_schema": "ds02.stage2.f3.s2.external-solver-materialization.v1",
            "scientific_status": "DEVELOPMENT_SOURCE_BOUND",
        },
        "timing_contract": {
            "cancel_cleanup_bounded": True, "entry_time_includes_request_parse": True,
            "entry_to_terminal_deadline": True, "posthash_and_receipt_cpu_included": True,
            "pre_and_post_input_hash_stat_included": True,
            "receipt_finalization_scope": "small bounded cleanup after timer restore",
            "physical_window_s": [0.0, float(TMAX)],
            "requested_output_cadence_s": float(TOUT),
            "terminal_time_source": "actual RunPARTs/Run.out only",
            "frame_count": ESTIMATED_NATIVE_FRAMES,
            "no_endpoint_extrapolation": True,
        },
        "qualification": dict(UNKNOWN),
        "model_invoked": False, "cfd_invoked": False, "raw_opened": False,
        "hdf5_opened": False, "launch_allowed": True,
        "physical_qualification": {**UNKNOWN, "reason": "single source-bound coarse full-window canary; actual RunPARTs, dt/clamp and observer/output calibration remain pending"},
        "source_provenance": {
            "sentinel_id": SENTINEL, "physical_case_id": PHYSICAL_CASE_ID,
            "gencase_request": str(gencase_q), "gencase_receipt": str(receipt_path),
            "gencase_output_root": str(receipt_root), "generated_xml": records[str(generated_xml)],
            "generated_bi4": {**bi4_record, "payload_read_by_builder": False},
        "source_xml": records[str(source_xml)], "source_control": {**control_record, "producer_pre_post_sha_equal": True},
            "support_report": records[str(support_report_path)], "support_report_status": support_status,
            "continuous_owner_mass_kg": 14.58, "sample_mass_kg": "from support report; diagnostic only",
            "mass_rescale": False, "root120_output_immutable": True,
        },
        "split_role": ["F3-S2 coarse full-window canary", "same source control", "native raw output cost/dt evidence"],
        "solver_plan": {
            "window_s": [0.0, float(TMAX)], "tout_s": float(TOUT),
            "expected_native_frames": ESTIMATED_NATIVE_FRAMES,
            "dense_or_half_cfl_not_started": True,
            "actual_effective_dt_and_clamp": "UNKNOWN until terminal RunPARTs/Run.out/DtAllInfo/official DTsMin evidence",
        },
    }
    request["sha256"] = canonical_sha(request)
    write_new(Path(args.output), request)
    return {
        "status": "PASS_REQUEST_BUILT",
        "output": str(Path(args.output).resolve()),
        "request_sha256": request["sha256"],
        "generated_bi4_sha256_bound": args.generated_bi4_sha256,
        "forcing_sha256_inherited_from_root120": expected_control_sha,
        "forcing_csv_builder_read": False,
        "solver_started": False,
        "launch": "PARENT_ONLY_NOT_STARTED",
    }


def self_test() -> dict[str, Any]:
    probe = {"schema": "ds02.stage2.external-solver-request.v5", "qualification": dict(UNKNOWN), "frame_count": ESTIMATED_NATIVE_FRAMES}
    if len(canonical_sha(probe)) != 64:
        raise AssertionError("canonical request SHA helper failed")
    if Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python").as_posix() != str(VENV_PYTHON):
        raise AssertionError("literal venv interpreter binding changed")
    if TMAX != "8.350016881886734" or TOUT != "0.01":
        raise AssertionError("F3 exact window/output contract changed")
    return {"status": "PASS", "schema": probe["schema"], "native_payload_read": False, "forcing_csv_builder_read": False, "expected_native_frames": ESTIMATED_NATIVE_FRAMES, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--gencase-request", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--generated-bi4", type=Path)
    parser.add_argument("--generated-bi4-sha256")
    parser.add_argument("--source-xml", type=Path, default=DEFAULT_SOURCE_XML)
    parser.add_argument("--source-control", type=Path, default=DEFAULT_SOURCE_CONTROL)
    parser.add_argument("--support-report", type=Path)
    parser.add_argument("--cost-basis-receipt", type=Path, default=COST_BASIS_RECEIPT)
    parser.add_argument("--launch-commit", required=False)
    parser.add_argument("--case-id", default="F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT_122")
    parser.add_argument("--attempt-id", default="f3-s2-owner-centered-dp015-full-cfd-canary-v5-root-122-001")
    parser.add_argument("--external-filesystem", default="/var/tmp/ds02-stage2")
    parser.add_argument("--external-reserve-bytes", type=int, default=2 * 1024**3)
    parser.add_argument("--home-receipt-reserve-bytes", type=int, default=8 * 1024**2)
    parser.add_argument("--max-wall-seconds", type=float, default=1800.0)
    parser.add_argument("--output", type=Path, default=PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-owner-centered-dp015-full-cfd-canary-v5-root-122-001.json")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = (args.gencase_request, args.receipt, args.generated_xml, args.generated_bi4, args.generated_bi4_sha256, args.support_report, args.launch_commit)
    if any(value is None for value in required):
        parser.error("--build-request requires q/receipt/generated XML+BI4/BI4 SHA/support report/launch commit")
    print(json.dumps(build(args), ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
