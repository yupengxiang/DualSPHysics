#!/usr/bin/env python3
"""Prepare launch-disabled full-solver candidates from three GenCase probes.

The requests are source-bound preparation artifacts for root's v4 dispatcher.
They materialize a new half-CFL XML and a hard link to the immutable GenCase
BI4; no solver, GPU, native Part, or HDF5 work is performed here.  The
quality audit remains a precondition report: F1-S2 is blocked by its whole
initial mass gate, while F6-S1 and F7-S1 require review because their total
mass is marginal.  None of the requests grants QI/QN/QE credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
WRAPPER = Path(__file__).resolve()
AUDIT = REFERENCE / "stage2_infogain_gencase_audit_v2.json"
STATUS = REFERENCE / "stage2_fourteen_reference_status_v2.json"
INPUT_ROOT = REFERENCE / "stage2_infogain_full_solver_inputs_v2"
REQUEST_ROOT = STAGE2 / "requests/stage2-infogain-full-solver-v2"
SCHEMA = "ds02.stage2.infogain-full-solver-request.v2"
DISPATCH_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DISPATCH = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
PROTECTED_GPU = {"index": 6, "uuid": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec", "pid": 601689, "action": "do_not_touch"}
OBSERVER_RESERVATION = 512 * 1024 * 1024
TEMPORARY_MARGIN = 2 * 1024 * 1024 * 1024
GIB = 1024 ** 3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, *, hash_file: bool = True) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    result: dict[str, Any] = {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if hash_file:
        result["sha256"] = sha256_file(path)
    return result


def atomic_bytes(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.is_file() and path.read_bytes() == payload:
            return
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def safe_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")


def load() -> tuple[dict[str, Any], dict[str, Any]]:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    if audit.get("status") != "COMPLETED_SMALL_XML_RECEIPT_AUDIT":
        raise ValueError("quality audit is not terminal")
    wanted = {"F1-S2", "F6-S1", "F7-S1"}
    rows = {row["sentinel_id"]: row for row in audit["results"]}
    sentinels = {row["sentinel_id"]: row for row in status["sentinels"]}
    if set(rows) != wanted or not wanted <= set(sentinels):
        raise ValueError("expected exact three audit/status rows")
    return audit, {sid: sentinels[sid] for sid in wanted}


def source_xml_from_audit(row: dict[str, Any]) -> Path:
    return Path(row["source"]["file"]["path"])


def candidate_root_from_audit(row: dict[str, Any]) -> Path:
    return Path(row["candidate"]["file"]["path"]).parent


def candidate_receipt(row: dict[str, Any]) -> Path:
    return Path(row["candidate_receipt"]["file"]["path"])


def actual_tmax(sentinel: dict[str, Any]) -> float:
    return float(sentinel["control_window"]["source_full_window_s"][1])


def cadence(sentinel: dict[str, Any]) -> float:
    return float(sentinel["control_window"]["source_dense_output_cadence_s"])


def frame_count(tmax: float, tout: float) -> int:
    return int(math.ceil(tmax / tout - 1.0e-12) + 1)


def candidate_mass_gate(audit_row: dict[str, Any]) -> str:
    return str(audit_row["whole_initial_mass"]["gate"])


def eligibility(gate: str) -> str:
    if gate == "HARD_FAIL_GT2PCT":
        return "BLOCKED_WHOLE_INITIAL_MASS_GT2PCT"
    if gate == "MARGINAL_1_TO_2PCT":
        return "REVIEW_REQUIRED_MARGINAL_WHOLE_INITIAL_MASS"
    if gate == "PASS_TARGET_1PCT_DIAGNOSTIC":
        return "PREPARED_REVIEW_REQUIRED_NO_SCIENTIFIC_CREDIT"
    return "UNKNOWN_REQUIRES_REVIEW"


def make_half_overlay(sentinel_id: str, candidate_root: Path, candidate_xml: Path) -> dict[str, Any]:
    text = candidate_xml.read_text(encoding="utf-8")
    old_values = re.findall(r'<cflnumber\s+value="([^"]+)"', text)
    if len(old_values) != 2:
        raise ValueError(f"{candidate_xml}: expected two cflnumber values, got {old_values}")
    half_values = [f"{float(value) / 2.0:.17g}" for value in old_values]
    index = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal index
        value = half_values[index]
        index += 1
        return f'{match.group(1)}{value}{match.group(2)}'

    overlay_text, count = re.subn(r'(<cflnumber\s+value=")[^"]+("[^>]*/>)', replace, text)
    if count != 2 or index != 2:
        raise ValueError(f"{candidate_xml}: cfl replacement count {count}/{index}")
    stem = safe_token(sentinel_id).lower() + "_infogain_half_cfl"
    destination = INPUT_ROOT / safe_token(sentinel_id) / "half_cfl"
    overlay_xml = destination / f"{stem}.xml"
    overlay_bi4 = destination / f"{stem}.bi4"
    atomic_bytes(overlay_xml, overlay_text.encode("utf-8"))
    if overlay_bi4.exists():
        if os.stat(overlay_bi4).st_ino != os.stat(candidate_root / "generated.bi4").st_ino:
            raise FileExistsError(overlay_bi4)
    else:
        destination.mkdir(parents=True, exist_ok=True)
        os.link(candidate_root / "generated.bi4", overlay_bi4)
    motion_files: list[dict[str, Any]] = []
    for path in candidate_root.iterdir():
        if path.is_file() and path.name != "generated.bi4" and path.name != "generated.xml" and path.name.endswith((".dat", ".csv")):
            destination_path = destination / path.name
            if not destination_path.exists():
                os.link(path, destination_path)
            motion_files.append({"name": path.name, "source": record(path), "overlay": record(destination_path)})
    return {"xml": record(overlay_xml), "bi4": record(overlay_bi4, hash_file=False), "motion_files": motion_files, "cfl_old": old_values, "cfl_new": half_values}


def source_input_files(audit_row: dict[str, Any], candidate_root: Path, candidate_xml: Path, overlay: dict[str, Any] | None) -> tuple[list[Path], list[Path]]:
    source_xml = source_xml_from_audit(audit_row)
    source_receipt = Path(audit_row["source_receipt"]["file"]["path"])
    candidate_receipt_path = candidate_receipt(audit_row)
    paths = [DISPATCH, STRICT, RUNTIME, SOLVER, WRAPPER, AUDIT, STATUS, source_xml, source_receipt, candidate_xml, candidate_receipt_path, candidate_root / "generated.bi4"]
    paths.extend(candidate_root / row["name"] for row in (audit_row["motion_dependency"]["files"] if "motion_dependency" in audit_row else []))
    if overlay is not None:
        paths.extend([Path(overlay["xml"]["path"]), Path(overlay["bi4"]["path"])])
        paths.extend(Path(row["overlay"]["path"]) for row in overlay["motion_files"])
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.resolve()
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    deferred = [path for path in unique if path.suffix.lower() == ".bi4" or path == SOLVER]
    hashed = [path for path in unique if path not in deferred]
    return hashed, deferred


def planning_cost(audit_row: dict[str, Any], sentinel: dict[str, Any], mode: str) -> dict[str, Any]:
    source_part0 = int(sentinel["prior_v1_snapshot"]["source"]["source_part0_bytes"])
    source_particles = int(sentinel["initial_state"]["source_particles"])
    producer_receipt = json.loads(Path(audit_row["candidate_receipt"]["file"]["path"]).read_text(encoding="utf-8"))
    candidate_particles = int(producer_receipt.get("total_particles") or (audit_row["candidate"]["total_fluid_particles"] + (audit_row["candidate"]["floating_contract"]["floating_particle_count"] or 0)))
    ratio = candidate_particles / source_particles
    tmax = actual_tmax(sentinel)
    tout = cadence(sentinel)
    frames = frame_count(tmax, tout)
    scaled_raw = source_part0 * frames * ratio
    # This is an explicit planning proxy.  It is deliberately separate from
    # the parent terminal reservation and is not presented as an upper bound.
    unreserved = int(math.ceil(scaled_raw))
    safety = 1.25 if mode == "same_cfl" else 1.50
    reserved = int(math.ceil((unreserved * safety + OBSERVER_RESERVATION + TEMPORARY_MARGIN) / GIB) * GIB)
    source_receipt = json.loads(Path(audit_row["source_receipt"]["file"]["path"]).read_text(encoding="utf-8"))
    source_gpu = float(source_receipt.get("gpu_seconds") or source_receipt.get("elapsed_seconds") or 0.0)
    mode_factor = 1.0 if mode == "same_cfl" else 2.0
    gpu_proxy = source_gpu * ratio * mode_factor
    return {
        "source_part0_bytes": source_part0,
        "planned_frames": frames,
        "candidate_total_particles": candidate_particles,
        "source_total_particles": source_particles,
        "candidate_to_source_particle_ratio": ratio,
        "raw_native_scaled_proxy_bytes": unreserved,
        "safety_factor": safety,
        "estimated_storage_bytes": reserved,
        "source_gpu_seconds": source_gpu,
        "gpu_seconds_proxy": gpu_proxy,
        "gpu_hours_proxy": gpu_proxy / 3600.0,
        "planning_warning": "Part_0 scaling plus safety is a planning proxy; actual parent v4 terminal storage and receipt are authoritative",
    }


def make_request(audit_row: dict[str, Any], sentinel: dict[str, Any], mode: str, overlay: dict[str, Any] | None, source_code_commit: str) -> dict[str, Any]:
    sid = audit_row["sentinel_id"]
    candidate_root = candidate_root_from_audit(audit_row)
    candidate_xml = candidate_root / "generated.xml"
    input_xml = candidate_xml if mode == "same_cfl" else Path(overlay["xml"]["path"])
    input_prefix = input_xml.with_suffix("")
    tmax = actual_tmax(sentinel)
    tout = cadence(sentinel)
    mode_token = "samecfl" if mode == "same_cfl" else "halfcfl"
    case_id = f"{safe_token(sid)}_INFOGAIN_DP{str(audit_row['candidate_dp_m']).replace('.', 'p')}_V2_{mode_token.upper()}_DENSE_T{str(tmax).replace('.', 'p')}"
    attempt_id = case_id.lower() + "-root-001"
    request_path = REQUEST_ROOT / f"{safe_token(sid).lower()}_infogain_{mode}.json"
    hashed, deferred = source_input_files(audit_row, candidate_root, candidate_xml, overlay)
    input_files = [str(path.resolve()) for path in hashed + deferred]
    input_hashes = {str(path.resolve()): sha256_file(path) for path in hashed}
    for path in deferred:
        input_hashes[str(path.resolve())] = "PARENT_V4_GUARD_REQUIRED"
    cost = planning_cost(audit_row, sentinel, mode)
    gate = candidate_mass_gate(audit_row)
    candidate_contract = audit_row["geometry_control_h_rigid_comparison"]
    receipt_path = candidate_receipt(audit_row)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    request = {
        "schema": "ds02.request.v1",
        "family_id": audit_row["family_id"],
        "case_id": case_id,
        "physical_case_id": audit_row["physical_case_id"],
        "sentinel_id": sid,
        "attempt_id": attempt_id,
        "kind": "qualification_candidate",
        "qualification_stage": "stage2_infogain_candidate_full_solver_pending_primary_review",
        "cpu_task_kind": "solver",
        "cpu_threads": 2,
        "omp_threads": 2,
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": cost["estimated_storage_bytes"],
        "estimated_peak_gpu_mib": 4096,
        "worktree_root": str(REPO),
        "cwd": str(input_xml.parent),
        "command": [str(SOLVER), str(input_prefix), "{attempt_root}/solver_output", f"-tmax:{tmax:.15g}", f"-tout:{tout:.15g}"],
        "gencase_receipt": str(receipt_path),
        "gencase_receipt_sha256": sha256_file(receipt_path),
        "expected_particles": int(receipt.get("total_particles") or (audit_row["candidate"]["total_fluid_particles"] + (audit_row["candidate"]["floating_contract"]["floating_particle_count"] or 0))),
        "expected_fluid_particles": int(audit_row["candidate"]["total_fluid_particles"]),
        "expected_native_frames": cost["planned_frames"],
        "expected_dimension": 3,
        "physical_window_s": [0.0, tmax],
        "save_interval_s": tout,
        "source_binding": {
            "schema": "ds02.stage2.infogain-candidate-binding.v2",
            "sentinel_id": sid,
            "family_id": audit_row["family_id"],
            "physical_case_id": audit_row["physical_case_id"],
            "candidate_grid": {"label": audit_row["candidate_label"], "dp_m": audit_row["candidate_dp_m"], "generated_xml": audit_row["candidate"]["file"], "generated_bi4": record(candidate_root / "generated.bi4", hash_file=False)},
            "current_source": {"xml": audit_row["source"]["file"], "solver_receipt": audit_row["source_receipt"]["file"], "source_sample_mass_target_kg": audit_row["whole_initial_mass"]["source_sample_mass_target_kg"]},
            "gencase_producer": {"receipt": audit_row["candidate_receipt"]["file"], "status": receipt.get("status"), "returncode": receipt.get("returncode"), "input_digest_stable": audit_row["candidate_receipt"]["input_digest_stable"]},
            "quality_gate": {"whole_initial_mass": audit_row["whole_initial_mass"], "eligibility": eligibility(gate), "per_material_diagnostics": audit_row["per_material_diagnostics"], "no_mass_rescale": True},
            "geometry_control_h_rigid": candidate_contract,
            "effective_conditions": {"cfl_mode": mode, "source_cfl": audit_row["candidate"]["cfl"], "effective_cfl": audit_row["candidate"]["cfl"] if mode == "same_cfl" else audit_row["candidate"]["cfl"] / 2.0, "dp_m": audit_row["candidate"]["definition_dp_m"], "h_m": audit_row["candidate"]["h_m"], "massfluid_kg": audit_row["candidate"]["massfluid_kg"], "time_max_s": tmax, "time_out_s": tout, "savedt_or_dtallinfo": "UNKNOWN_UNTIL_SEPARATE_OVERLAY_OR_GUARDED_RECEIPT"},
            "output_control": {"full_physical_window_retained": True, "tout_is_saved_output_cadence": True, "dt_sequence": "UNKNOWN", "dt_clamp_events": "UNKNOWN", "no_frame_number_hardcoding": True},
            "quality_audit": {"path": str(AUDIT.resolve()), "sha256": sha256_file(AUDIT)},
        },
        "cost": cost,
        "output_plan": {"native_raw": "{attempt_root}/solver_output/data/Part_*.bi4; retain every saved frame over the complete physical window", "native_source_role": "immutable primary candidate array source; no deletion or favorable-subset pruning", "stream_observer": {"mode": "one sequential pass after solver; separate root task", "status": "PENDING_CONSUMER_CALIBRATION"}, "typed": {"mode": "selected query-time anchors only after raw retention", "time_policy": "EXACT/BRACKETED using actual saved timestamps; no frame-number hardcoding or extrapolation"}, "downsample": "derived after raw retention; no solver replacement"},
        "launch_policy": {"launch_disabled": True, "execution_allowed": False, "solver_launch_owner": "root", "primary_gpu_dispatch_required": True, "gpu_uuid_authorization": "PENDING_PRIMARY_LEDGER", "protected_external_gpu": PROTECTED_GPU, "parent_guard": str(DISPATCH)},
        "input_files": input_files,
        "input_hashes": input_hashes,
        "deferred_parent_hashes": [{"path": str(path.resolve()), "reason": "binary input deliberately not hashed by preparation worker; parent v4 must hash before any launch"} for path in deferred],
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "launch_commit": source_code_commit, "cpu_parent_binding": "required", "gpu_uuid_lease": "primary only; none granted in preparation", "source_output_protection": "new attempt output only; immutable CURRENT and completed GenCase artifacts", "estimated_cpu_core_hours": 2 * 7200 / 3600.0, "estimated_gpu_hours_proxy": cost["gpu_hours_proxy"], "estimated_new_storage_bytes": cost["estimated_storage_bytes"]},
        "scope": {"physical_case_id": audit_row["physical_case_id"], "sentinel_id": sid, "candidate_label": audit_row["candidate_label"], "candidate_dp_m": audit_row["candidate_dp_m"], "cfl_mode": mode, "full_time_hdf5_read_in_preparation": False, "solver_started": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "eligibility": eligibility(gate)},
    }
    return request


def prepare() -> dict[str, Any]:
    audit, sentinels = load()
    source_code_commit = git_head()
    rows: list[dict[str, Any]] = []
    request_paths: list[str] = []
    for audit_row in audit["results"]:
        sid = audit_row["sentinel_id"]
        candidate_root = candidate_root_from_audit(audit_row)
        overlay = make_half_overlay(sid, candidate_root, candidate_root / "generated.xml")
        for mode in ("same_cfl", "half_cfl"):
            request = make_request(audit_row, sentinels[sid], mode, overlay if mode == "half_cfl" else None, source_code_commit)
            path = REQUEST_ROOT / f"{safe_token(sid).lower()}_infogain_{mode}.json"
            atomic_json(path, request)
            request_paths.append(str(path.resolve()))
            rows.append({"path": str(path.resolve()), "sha256": sha256_file(path), "sentinel_id": sid, "mode": mode, "eligibility": request["scope"]["eligibility"], "storage_bytes": request["estimated_storage_bytes"], "input_hash_policy": "parent v4 required for .bi4/solver binary"})
    report = {"schema": "ds02.stage2.infogain-full-solver-request-manifest.v2", "status": "PREPARED_LAUNCH_DISABLED_6_REQUESTS_V2", "generated_at_commit": source_code_commit, "audit": {"path": str(AUDIT.resolve()), "sha256": sha256_file(AUDIT)}, "scope": {"sentinels": [row["sentinel_id"] for row in audit["results"]], "requests": len(rows), "solver_started": False, "gpu_started": False, "native_or_hdf5_read": False, "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}, "policy": {"whole_initial_mass": "frozen discrete CURRENT sample target; F1 hard fail remains blocked; F6/F7 marginal require parent review", "per_material": "diagnostic only", "floating": "particle sample mass and physical massbody/inertia/COM are separate", "dt": "UNKNOWN until separately instrumented/savedt guarded run", "launch_owner": "root"}, "requests": rows}
    atomic_json(REFERENCE / "stage2_infogain_full_solver_request_manifest_v2.json", report)
    return {"report": report, "request_paths": request_paths}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if not args.prepare:
        parser.error("choose --prepare")
    result = prepare()
    print(json.dumps({"status": result["report"]["status"], "report": result["report"], "request_count": len(result["request_paths"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
