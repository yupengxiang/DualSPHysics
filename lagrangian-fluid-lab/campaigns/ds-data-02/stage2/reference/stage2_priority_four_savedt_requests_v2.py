#!/usr/bin/env python3
"""Prepare forward v2 full-window SaveDt requests for four priority sentinels.

The v1 pair requests and overlays are immutable historical inputs.  This
builder creates new request JSON only, correcting the missing sentinel IDs,
binding the exact CURRENT physical identity and completed source receipt, and
using the shared v4 guard/runtime.  It reuses the already materialized
same-CFL and half-CFL overlays; it never starts a solver or reads BI4/H5
payloads.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DISPATCH_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DISPATCH = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
PAIR_BINDING = REFERENCE / "stage2_savedt_cfl_pair_binding_v1.json"
PAIR_COST = REFERENCE / "stage2_original_cfl_pair_cost_manifest_v2.json"
QUALITY = REFERENCE / "stage2_reference_quality_cost_v2.json"
MINIMAL = REFERENCE / "stage2_minimal14_study_graph_v2.json"
INSTRUMENTATION = REFERENCE / "stage2_savedt_instrumentation_audit_v1.json"
OUT_ROOT = STAGE2 / "requests/stage2-priority-four-savedt-v2"
BUILDER = Path(__file__).resolve()
SCHEMA = "ds02.stage2.priority-four-savedt-request.v2"
PRIORITY = ("F1-S1", "F7-S2", "F3-S1", "F5-S1")
MODES = ("same_cfl", "half_cfl")
PROTECTED_GPU = {
    "index": 6,
    "uuid": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec",
    "pid": 601689,
    "action": "do_not_touch",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, *, hash_file: bool = True) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    result: dict[str, Any] = {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
    result["sha256"] = sha256(path) if hash_file else "PARENT_V4_GUARD_REQUIRED"
    return result


def atomic_json(path: Path, value: Any) -> None:
    encoded = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == encoded:
            return
        raise FileExistsError(f"refuse overwrite: {path}")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def load_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    binding = json.loads(PAIR_BINDING.read_text(encoding="utf-8"))
    cost = json.loads(PAIR_COST.read_text(encoding="utf-8"))
    quality = json.loads(QUALITY.read_text(encoding="utf-8"))
    minimal = json.loads(MINIMAL.read_text(encoding="utf-8"))
    if binding.get("status") != "PREPARED_SOURCE_BOUND_SAVEDT_CFL_PAIR_REQUESTS":
        raise ValueError(f"unexpected SaveDt binding status: {binding.get('status')}")
    return binding, cost, quality, minimal


def xml_parameters(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    result: dict[str, Any] = {}
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() == "parameter" and node.get("key"):
            raw = node.get("value")
            try:
                result[node.get("key")] = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                result[node.get("key")] = raw
    for name in ("cflnumber", "dp", "h", "massfluid"):
        node = next((item for item in root.iter() if item.tag.rsplit("}", 1)[-1].lower() == name), None)
        if node is not None and node.get("value") is not None:
            try:
                result[name] = float(node.get("value"))
            except ValueError:
                result[name] = node.get("value")
    return result


def unique_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def source_effective_controls(source: dict[str, Any], current_xml: Path, old_binding: dict[str, Any]) -> dict[str, Any]:
    controls = source["source_solver_controls"]
    receipt = controls["receipt"]
    parsed = xml_parameters(current_xml)
    cli_tmax = float(controls["tmax_s"])
    cli_tout = float(controls["tout_s"])
    xml_tmax = parsed.get("TimeMax")
    xml_tout = parsed.get("TimeOut")
    conflict = None
    if source["sentinel_id"] == "F5-S1":
        conflict = {
            "status": "EXPLICIT_XML_CLI_TIME_MAX_DIFFERENCE",
            "xml_TimeMax_s": xml_tmax,
            "actual_completed_receipt_cli_tmax_s": cli_tmax,
            "effective_time_max_for_reference": "completed source receipt CLI tmax=16 s; XML TimeMax=26 is retained as a source diagnostic",
            "xml_TimeOut_s": xml_tout,
            "actual_completed_receipt_cli_tout_s": cli_tout,
        }
    return {
        "receipt": record(Path(receipt["path"])),
        "receipt_status": controls.get("status"),
        "returncode": controls.get("returncode"),
        "termination_reason": controls.get("termination_reason"),
        "actual_completed_command": controls.get("command"),
        "actual_cli_tmax_s": cli_tmax,
        "actual_cli_tout_s": cli_tout,
        "actual_terminal_time_s": float(source["window_end_s"]),
        "xml_parameters": parsed,
        "effective_condition_conflict": conflict,
        "preserved_non_gpu_flags": old_binding.get("source", {}).get("solver_control", {}).get("preserved_non_gpu_flags", []),
        "control_provenance": "CURRENT quality manifest source_solver_controls plus immutable source XML; no review fallback",
    }


def build_one(binding_row: dict[str, Any], source: dict[str, Any], cost_row: dict[str, Any], mode: str, source_commit: str) -> tuple[Path, dict[str, Any]]:
    old_path = Path(binding_row["request_path"])
    old = json.loads(old_path.read_text(encoding="utf-8"))
    if old.get("launch_disabled") is not True or old.get("solver_started") not in (None, False):
        raise ValueError(f"historical request is not launch-disabled: {old_path}")
    overlay = binding_row["overlay_xml"]
    overlay_xml = Path(overlay["path"])
    overlay_bi4 = Path(binding_row["overlay_bi4"]["path"])
    current_xml = Path(source["source_xml"]["path"])
    if not overlay_xml.is_file() or not overlay_bi4.is_file() or not current_xml.is_file():
        raise FileNotFoundError(f"missing source-bound overlay/input for {source['sentinel_id']} {mode}")
    source_controls = source_effective_controls(source, current_xml, old["source_binding"])
    candidate_tmax = float(source["window_end_s"])
    candidate_tout = float(binding_row["requested_tout_s"])
    expected_frames = int(binding_row["planned_frames"])
    family = source["family_id"]
    sid = source["sentinel_id"]
    mode_token = "SAMECFL" if mode == "same_cfl" else "HALFCFL"
    case_id = f"{sid.replace('-', '_')}_ORIGINAL_{mode_token}_DENSE_SAVEDT_V2"
    attempt_id = case_id.lower() + "-root-002"
    old_input_paths = [Path(item) for item in old["input_files"]]
    # The old v1 request is provenance only.  Replace consumed v2 runtime and
    # request-builder entries with current v4 paths and add all v2 manifests.
    paths = [path for path in old_input_paths if "runtime_v2.py" not in str(path) and "stage2_savedt_cfl_pair_requests_v1.py" not in str(path)]
    paths.extend([DISPATCH, STRICT, RUNTIME, BUILDER, PAIR_BINDING, PAIR_COST, QUALITY, MINIMAL, INSTRUMENTATION])
    paths = unique_paths(paths)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"{sid}/{mode} missing inputs: {missing}")
    input_files = [str(path) for path in paths]
    input_hashes: dict[str, str] = {}
    for path in paths:
        if path == SOLVER or path.suffix.lower() == ".bi4":
            input_hashes[str(path)] = "PARENT_V4_GUARD_REQUIRED"
        else:
            input_hashes[str(path)] = sha256(path)
    old_source = copy.deepcopy(old.get("source_binding", {}))
    historical_gencase = old.get("gencase_receipt")
    if isinstance(historical_gencase, dict):
        historical_gencase_path = Path(historical_gencase["path"])
        historical_gencase_sha = historical_gencase.get("sha256")
    elif isinstance(historical_gencase, str):
        historical_gencase_path = Path(historical_gencase)
        historical_gencase_sha = old.get("gencase_receipt_sha256")
    else:
        raise ValueError(f"historical request has no gencase receipt: {old_path}")
    if not historical_gencase_path.is_file():
        raise FileNotFoundError(historical_gencase_path)
    historical_gencase_record = record(historical_gencase_path)
    if historical_gencase_sha and historical_gencase_sha != historical_gencase_record["sha256"]:
        raise ValueError(f"historical gencase receipt SHA mismatch: {historical_gencase_path}")
    old_source.update({
        "schema": "ds02.stage2.priority-four-savedt-binding.v2",
        "sentinel_id": sid,
        "family_id": family,
        "physical_case_id": source["physical_case_id"],
        "historical_v1_request": {"path": str(old_path.resolve()), "sha256": sha256(old_path), "sentinel_id_field": old.get("sentinel_id")},
        "current_source_exact": {
            "source_xml": record(current_xml),
            "gencase_receipt": historical_gencase_record,
            "source_solver_receipt": source_controls["receipt"],
            "source_solver_controls": source_controls,
            "source_particles": source["source_particles"],
            "source_fluid_particles": source["source_fluid_particles"],
            "source_sample_mass_kg": source["source_sample_mass_kg"],
            "effective_time_window_s": source["effective_time_window_s"],
            "source_cfl": source["source_cfl"],
            "half_cfl": source["half_cfl"],
            "dense_output_cadence_s": source["review_dense_cadence_s"],
        },
        "overlay_exact": {
            "mode": mode,
            "xml": record(overlay_xml),
            "bi4": record(overlay_bi4, hash_file=False),
            "binding_manifest": record(Path(binding_row["overlay_manifest"]["path"])),
            "xml_diff_proof": binding_row["xml_diff_proof"],
        },
        "motion_and_auxiliary_source": binding_row.get("overlay_manifest", {}).get("motion_or_auxiliary_dependencies", []),
        "input_identity_policy": "intentional dp/h/mass/count remain resolution semantics; continuous geometry/control and source motion/acceleration dependencies are source-bound",
    })
    old_plan = copy.deepcopy(old.get("output_plan", {}))
    old_plan.update({
        "native_raw": "{attempt_root}/solver_output/data/Part_*.bi4; retain every saved frame over the complete physical window",
        "full_physical_window_s": [0.0, candidate_tmax],
        "query_times_s": [0.0, 0.25 * candidate_tmax, 0.5 * candidate_tmax, 0.75 * candidate_tmax, candidate_tmax],
        "time_policy": "EXACT/EXACT_OR_LEFT/BRACKETED from actual RunPARTs/typed time axis; no frame indices or extrapolation",
        "downsample": "derived only after raw retention; not a solver replacement",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    })
    request = {
        "schema": "ds02.request.v1",
        "family_id": family,
        "sentinel_id": sid,
        "physical_case_id": source["physical_case_id"],
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "qualification",
        "qualification_stage": "stage2_priority_four_full_window_savedt_v2_source_exact_pending_primary_dispatch",
        "cpu_task_kind": "solver",
        "cpu_threads": old.get("cpu_threads", 2),
        "omp_threads": old.get("omp_threads", 2),
        "max_wall_seconds": old.get("max_wall_seconds", 7200),
        "estimated_storage_bytes": int(cost_row["request_storage_reservation_bytes"]),
        "estimated_peak_gpu_mib": old.get("estimated_peak_gpu_mib", 4096),
        "worktree_root": str(REPO),
        "cwd": str(overlay_xml.parent),
        "command": [str(SOLVER), str(overlay_xml.with_suffix("")), "{attempt_root}/solver_output", f"-tmax:{candidate_tmax:.17g}", f"-tout:{candidate_tout:.17g}"],
        "gencase_receipt": str(historical_gencase_path.resolve()),
        "gencase_receipt_sha256": historical_gencase_record["sha256"],
        "expected_particles": source["source_particles"],
        "expected_fluid_particles": source["source_fluid_particles"],
        "expected_native_frames": expected_frames,
        "expected_dimension": 3,
        "physical_window_s": [0.0, candidate_tmax],
        "save_interval_s": candidate_tout,
        "source_binding": old_source,
        "effective_conditions": {
            "cfl_mode": mode,
            "source_cfl": source["source_cfl"],
            "effective_cfl": source["source_cfl"] if mode == "same_cfl" else source["half_cfl"],
            "actual_cli_tmax_s": candidate_tmax,
            "actual_cli_tout_s": candidate_tout,
            "xml_parameters": source_controls["xml_parameters"],
            "source_control_status": "ACTUAL_COMPLETED_CURRENT_RECEIPT_AND_XML_BOUND",
            "f5_time_conflict": source_controls["effective_condition_conflict"],
        },
        "dt_observability": {
            "required_before_dispatch": True,
            "savedt_overlay": {"active": True, "start_s": 0.0, "finish_s": 0.0, "interval_s": candidate_tout, "fullinfo": 0, "alldt": 1},
            "RunPARTs_DTsMin": "count only, not seconds or full per-step trace",
            "clamp_status": "UNKNOWN_UNTIL_TERMINAL_RECEIPT",
            "terminal_step_flush": "UNKNOWN_UNTIL_TERMINAL_RECEIPT",
        },
        "output_plan": old_plan,
        "cost": {
            "source_cost_manifest_row": cost_row,
            "proxy_warning": "manifest cost is planning only; parent v4 terminal tree/receipt is authoritative",
        },
        "historical_v1_request": {"path": str(old_path.resolve()), "sha256": sha256(old_path), "sentinel_id_was": old.get("sentinel_id")},
        "launch_policy": {
            "launch_disabled": True,
            "execution_allowed": False,
            "solver_launch_owner": "root",
            "primary_gpu_dispatch_required": True,
            "gpu_uuid_authorization": "PENDING_PRIMARY_LEDGER",
            "protected_external_gpu": PROTECTED_GPU,
            "parent_guard": str(DISPATCH),
        },
        "input_files": input_files,
        "input_hashes": input_hashes,
        "deferred_parent_hashes": [{"path": path, "reason": "parent v4 must hash exact binary immediately before any launch"} for path, value in input_hashes.items() if value == "PARENT_V4_GUARD_REQUIRED"],
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "launch_commit": source_commit,
            "cpu_parent_binding": "required",
            "gpu_uuid_lease": "primary only; none granted in preparation",
            "source_output_protection": "new attempt output only; immutable CURRENT, old pair requests and completed source receipt",
            "source_request_builder": str(BUILDER),
        },
        "scope": {
            "sentinel_id": sid,
            "family_id": family,
            "physical_case_id": source["physical_case_id"],
            "mode": mode,
            "full_physical_window": True,
            "solver_started": False,
            "gpu_started": False,
            "hdf5_read_in_preparation": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }
    path = OUT_ROOT / f"{sid.lower().replace('-', '_')}_{mode}_savedt_v2.json"
    atomic_json(path, request)
    return path, request


def prepare() -> dict[str, Any]:
    binding, cost, quality, minimal = load_inputs()
    source_commit = git_head()
    source_by_sid = {row["sentinel_id"]: row for row in quality["sources"]}
    binding_rows = {(row["sentinel_id"], row["mode"]): row for row in binding["requests"]}
    cost_rows = {(row["sentinel_id"], row["mode"]): row for row in cost["requests"]}
    if any((sid, mode) not in binding_rows or (sid, mode) not in cost_rows for sid in PRIORITY for mode in MODES):
        raise ValueError("priority four does not have a closed pair binding/cost row")
    outputs = []
    for sid in PRIORITY:
        for mode in MODES:
            path, request = build_one(binding_rows[(sid, mode)], source_by_sid[sid], cost_rows[(sid, mode)], mode, source_commit)
            outputs.append({"path": str(path.resolve()), "sha256": sha256(path), "sentinel_id": sid, "mode": mode, "storage_bytes": request["estimated_storage_bytes"], "expected_native_frames": request["expected_native_frames"]})
    report = {
        "schema": SCHEMA,
        "status": "PREPARED_PRIORITY_FOUR_EIGHT_REQUESTS_LAUNCH_DISABLED",
        "generated_at_commit": source_commit,
        "source_manifests": {key: str(path.resolve()) for key, path in {"pair_binding": PAIR_BINDING, "pair_cost": PAIR_COST, "quality": QUALITY, "minimal14": MINIMAL, "instrumentation": INSTRUMENTATION, "builder": BUILDER}.items()},
        "priority_order": list(PRIORITY),
        "modes": list(MODES),
        "requests": outputs,
        "historical_policy": "v1 pair requests remain immutable; v2 corrects sentinel identity and v4 source/runtime binding",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "solver_started": False,
        "gpu_started": False,
        "hdf5_read": False,
    }
    report_path = REFERENCE / "stage2_priority_four_savedt_requests_v2.json"
    atomic_json(report_path, report)
    return {"report": report_path, "requests": outputs}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if not args.prepare:
        parser.error("use --prepare")
    result = prepare()
    print(json.dumps({"status": "PREPARED_PRIORITY_FOUR_EIGHT_REQUESTS_LAUNCH_DISABLED", "report": str(result["report"]), "requests": result["requests"]}, ensure_ascii=False))
