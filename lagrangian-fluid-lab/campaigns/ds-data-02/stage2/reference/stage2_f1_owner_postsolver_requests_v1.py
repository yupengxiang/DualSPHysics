#!/usr/bin/env python3
"""Build source-bound, launch-disabled F1 owner post-solver requests.

The builder reads only completed receipts and the small text metadata files
(``RunPARTs.csv``/Savedt logs).  It does not open or hash any native Part
payload.  A request therefore leaves the selected BI4 files deferred for the
parent guard, which must snapshot their pre/post stat and SHA before the
bounded decoder starts.  ``dp0025`` half-CFL is intentionally omitted until
its parent receipt reaches a completed terminal state; rerunning this builder
then emits the same immutable request shape for that run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1.owner-postsolver-request-builder.v1"
FAMILY = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
QUERY_TIMES = (0.0, 0.4, 0.8, 1.2, 1.6)
REPO = Path(__file__).resolve().parents[5]
DATA_REPO = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
BUILDER = Path(__file__).resolve()
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py"
SNAPSHOT_WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_source_snapshot_v2.py"
DT_WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_owner_savedt_metadata_v1.py"
CONTRACT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_owner_postsolver_observation_contract_v1.json"
DISPATCH = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py")
STRICT = DISPATCH.parent / "ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH.parent / "ds_data02_runtime_v4.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
OWNER = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/ecc_coarse/owner.json")
PHYSICAL_BINDING = OWNER.parent.parent / "ecc-physical-binding.json"
QUALITY = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/QUALITY_LABEL_SPLIT_ZH.md"
QA_PROOF = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_TWO_OWNER_RUNGS_INITIAL_NATIVE_QA_V2_ACTUAL_INDEPENDENT_VERIFICATION_001.json")
SUPPORT_DP005_PROOF = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_OWNER_DP005_V2_SUPPORT_CONTROL_ACTUAL_INDEPENDENT_VERIFICATION_001.json")
SUPPORT_DP0025_PROOF = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_OWNER_DP0025_SUPPORT_V5_ACTUAL_INDEPENDENT_VERIFICATION_001.json")
SOURCE_RUNS = {
    ("dp005", "same_cfl"): "f1-s1-owner-dp005-same_cfl-savedt-nvme-v2",
    ("dp005", "half_cfl"): "f1-s1-owner-dp005-half_cfl-savedt-nvme-v2",
    ("dp0025", "same_cfl"): "f1-s1-owner-dp0025-same_cfl-savedt-nvme-v2",
    ("dp0025", "half_cfl"): "f1-s1-owner-dp0025-half_cfl-savedt-nvme-v2",
}
DP_SOURCE = {
    "dp005": FAMILY / "F1_S1_OWNER_CENTERED_DP0p005000_V2/f1-s1-owner-centered-dp0p005000-v2-root-001-root-forward-030-001",
    "dp0025": FAMILY / "F1_S1_OWNER_CENTERED_DP0p002500_V3/f1-s1-owner-centered-dp0p002500-v3-root-001-root-forward-030-001",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, *, content: bool = True) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    value: dict[str, Any] = {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
    if content:
        value["sha256"] = sha256_file(path)
    return value


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def run_receipt(dp: str, mode: str) -> Path | None:
    parent = FAMILY / SOURCE_RUNS[(dp, mode)]
    receipts = sorted(parent.glob("*/execution-receipt.json"))
    completed: list[Path] = []
    for path in receipts:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("status") == "COMPLETED_DEVELOPMENT_UNKNOWN" and value.get("cfd_invoked") is True:
            completed.append(path)
    if len(completed) > 1:
        raise ValueError(f"multiple completed receipts for {dp}/{mode}: {completed}")
    return completed[0] if completed else None


def read_rows(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(lines, delimiter=";"):
        raw_part = (row.get("Part") or "").strip().split()[0]
        raw_time = (row.get("TimeStep [s]") or "").strip().split()[0]
        if not raw_part.isdigit():
            continue
        try:
            part, time_s = int(raw_part), float(raw_time)
        except ValueError:
            continue
        if not math.isfinite(time_s):
            raise ValueError(f"non-finite RunPARTs time: {path}")
        rows.append({"part": part, "time_s": time_s})
    if not rows or [row["part"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs is not contiguous from zero: {path}")
    if any(b["time_s"] <= a["time_s"] for a, b in zip(rows, rows[1:])):
        raise ValueError(f"RunPARTs saved times are not strictly increasing: {path}")
    return rows


def bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    if query < rows[0]["time_s"] or query > rows[-1]["time_s"]:
        return {"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW"}
    for index, row in enumerate(rows):
        if row["time_s"] == query:
            return {"query_time_s": query, "status": "EXACT", "lower_frame": row["part"], "upper_frame": row["part"], "lower_time_s": row["time_s"], "upper_time_s": row["time_s"], "bracket_width_s": 0.0, "field_interpolation": "FORBIDDEN"}
        if row["time_s"] > query:
            lower = rows[index - 1]
            return {"query_time_s": query, "status": "BRACKETED", "lower_frame": lower["part"], "upper_frame": row["part"], "lower_time_s": lower["time_s"], "upper_time_s": row["time_s"], "bracket_width_s": row["time_s"] - lower["time_s"], "field_interpolation": "FORBIDDEN"}
    raise AssertionError("unreachable query bracket")


def receipt_output_root(receipt: dict[str, Any], receipt_path: Path) -> Path:
    output = receipt.get("filesystem", {}).get("output_root")
    if not isinstance(output, str) or not output:
        raise ValueError(f"receipt has no filesystem.output_root: {receipt_path}")
    path = Path(output).expanduser().resolve()
    if not (path / "solver_output/RunPARTs.csv").is_file():
        raise FileNotFoundError(f"completed output missing RunPARTs.csv: {path}")
    return path


def input_prefix(receipt: dict[str, Any], receipt_path: Path) -> Path:
    argv = receipt.get("execution", {}).get("launch_argv", [])
    if not isinstance(argv, list):
        raise ValueError(f"launch_argv missing: {receipt_path}")
    for index, value in enumerate(argv[:-1]):
        if value in {"-gpu:0", "-gpu:1", "-gpu:2", "-gpu:3", "-gpu:4", "-gpu:5", "-gpu:7"}:
            prefix = Path(argv[index + 1]).expanduser().resolve()
            if prefix.suffix:
                raise ValueError(f"solver input prefix unexpectedly has suffix: {prefix}")
            return prefix
    raise ValueError(f"could not find solver input prefix in launch argv: {receipt_path}")


def parse_flag(receipt: dict[str, Any], name: str) -> float | str:
    for value in receipt.get("execution", {}).get("launch_argv", []):
        if isinstance(value, str) and value.startswith(name + ":"):
            try:
                return float(value.split(":", 1)[1])
            except ValueError:
                return value
    return "UNKNOWN"


def proof_for(dp: str) -> Path:
    return SUPPORT_DP005_PROOF if dp == "dp005" else SUPPORT_DP0025_PROOF


def make_observer(dp: str, mode: str, receipt_path: Path, output_dir: Path) -> tuple[dict[str, Any], Path, Path, Path]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    output_root = receipt_output_root(receipt, receipt_path)
    runparts = output_root / "solver_output/RunPARTs.csv"
    rows = read_rows(runparts)
    brackets = {str(query): bracket(rows, query) for query in QUERY_TIMES}
    outside = [value for value in brackets.values() if value["status"] == "OUTSIDE_SAVED_WINDOW"]
    if outside:
        raise ValueError(f"registered query outside {dp}/{mode} window: {outside}")
    selected = sorted({frame for value in brackets.values() for frame in (value.get("lower_frame"), value.get("upper_frame")) if frame is not None})
    prefix = input_prefix(receipt, receipt_path)
    solver_xml = prefix.with_suffix(".xml")
    if not solver_xml.is_file():
        raise FileNotFoundError(f"actual solver XML is missing: {solver_xml}")
    source_root = DP_SOURCE[dp]
    source_xml = source_root / "generated.xml"
    source_receipt = source_root / "execution-receipt.json"
    source_bi4_copy_receipt = (FAMILY / ("F1_S1_OWNER_DP005_BI4_COPY_V3" if dp == "dp005" else "F1_S1_OWNER_DP0025_BI4_COPY_V3"))
    copy_receipts = sorted(source_bi4_copy_receipt.glob("*/materialization-receipt.json"))
    if len(copy_receipts) != 1:
        raise ValueError(f"expected one materialization receipt for {dp}: {copy_receipts}")
    request_path = Path(receipt["request"]["path"]).expanduser().resolve()
    dtall = output_root / "solver_output/DtAllInfo.csv"
    dtinfo = output_root / "solver_output/DtInfo.csv"
    runout = output_root / "solver_output/Run.out"
    runcsv = output_root / "solver_output/Run.csv"
    support_proof = proof_for(dp)
    required = [
        WORKER, SNAPSHOT_WORKER, DT_WORKER, CONTRACT, DISPATCH, STRICT, RUNTIME,
        PYTHON, DECODER, DECODER_SOURCE, OWNER, PHYSICAL_BINDING, QUALITY,
        QA_PROOF, support_proof, source_xml, source_receipt, copy_receipts[0],
        solver_xml, request_path, receipt_path, runparts, dtall, dtinfo, runout, runcsv,
    ]
    required = list(dict.fromkeys(path.expanduser().resolve() for path in required))
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    output_name = f"f1_s1_owner_{dp}_{mode}_selected_native_observer_v1.json"
    observer_path = output_dir / output_name
    attempt_id = f"f1-s1-owner-{dp}-{mode}-selected-native-observer-v1-root-forward-001"
    raw_root = output_root / "solver_output/data"
    command = [
        str(PYTHON), str(WORKER), "--raw-root", str(raw_root), "--runparts", str(runparts),
        "--generated-xml", str(solver_xml), "--decoder", str(DECODER), "--decoder-source", str(DECODER_SOURCE),
        "--output", f"{{attempt_root}}/observer/{output_name}", "--scratch-root", "{attempt_root}/scratch/bi4_decode",
        "--expected-frame-count", str(len(rows)), "--expected-final-time-s", repr(rows[-1]["time_s"]),
        "--final-time-tolerance-s", "1e-12", "--frames", *(str(frame) for frame in selected),
        "--query-times", *(repr(query) for query in QUERY_TIMES),
    ]
    selected_stat_bytes = sum((raw_root / f"Part_{frame:04d}.bi4").stat().st_size for frame in selected)
    observer = {
        "schema": "ds02.request.v1", "family_id": "F1", "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": f"F1_S1_OWNER_{dp.upper()}_{mode.upper()}_SELECTED_NATIVE_OBSERVER_V1",
        "attempt_id": attempt_id, "kind": "cpu", "cpu_task_kind": "native_observer",
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 3600,
        "worktree_root": str(REPO), "cwd": str(REPO), "command": command,
        "qualification_stage": "stage2_f1_owner_postsolver_selected_native_pending_parent_cpu_guard",
        "query_times_s": list(QUERY_TIMES), "selected_native_frame_ids": selected,
        "input_files": [str(path) for path in required],
        "input_hashes": {str(path): ("PARENT_V4_GUARD_HASH_REQUIRED" if path == DECODER else sha256_file(path)) for path in required},
        "deferred_input_files": [str(raw_root), *[str(raw_root / f"Part_{frame:04d}.bi4") for frame in selected]],
        "deferred_hash_policy": {
            "parent_snapshot": "hash exactly selected Part files with pre/post complete-stat check before decode",
            "builder_bi4_read": False, "builder_bi4_hash": False,
            "full_raw_tree_hash": "NOT_COMPUTED_BY_BUILDER",
            "worker_scope": "selected native Part files only; no HDF5/full-tree scan",
        },
        "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_SELECTED_FRAME_BYTES",
        "selected_frame_stat_bytes_sum": selected_stat_bytes,
        "estimated_storage_bytes": max(1 << 30, 2 * selected_stat_bytes + (256 << 20)),
        "estimated_peak_memory_bytes": 1 << 30,
        "execution_allowed": False, "launch_disabled": True, "solver_started": False,
        "hdf5_read": False,
        "output": {
            "path": f"{{attempt_root}}/observer/{output_name}", "atomic": True, "refuse_overwrite": True,
            "fields": ["position", "velocity", "density", "mass", "valid", "type", "mkfluid_relative", "mk_absolute"],
            "pressure_status": "NOT_DECODED_BY_WORKER",
            "time_policy": "actual RunPARTs timestamps; EXACT/BRACKETED retained; no interpolation or extrapolation",
        },
        "source_binding": {
            "schema": SCHEMA, "family_id": "F1", "sentinel_id": "F1-S1",
            "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1", "resolution": dp, "cfl_variant": mode,
            "owner_contract": record(CONTRACT), "owner": record(OWNER), "physical_binding": record(PHYSICAL_BINDING),
            "quality_label_split": record(QUALITY), "initial_qa_proof": record(QA_PROOF),
            "support_control_proof": record(support_proof), "source_generated_xml": record(source_xml),
            "source_gencase_receipt": record(source_receipt), "materialization_receipt": record(copy_receipts[0]),
            "solver_input_xml": record(solver_xml), "solver_receipt": record(receipt_path),
            "parent_solver_request": record(request_path), "runparts": record(runparts),
            "run_out": record(runout), "run_csv": record(runcsv),
            "dtall_info": record(dtall), "dt_info": record(dtinfo),
            "raw_root": str(raw_root), "frame_count": len(rows), "last_saved_time_s": rows[-1]["time_s"],
            "query_brackets": brackets, "selected_native_frame_ids": selected,
            "requested_tmax_s": parse_flag(receipt, "-tmax"), "requested_tout_s": parse_flag(receipt, "-tout"),
            "launch_argv": receipt.get("execution", {}).get("launch_argv", "UNKNOWN"),
            "native_ids_are_run_local": True, "cross_grid_particle_id_pairing": "FORBIDDEN",
            "continuous_owner_mass_kg": 40.2, "particle_sample_mass_is_separate_diagnostic": True,
            "dtmin_warning_scope": "preserve RunPARTs DTsMin counts and Run.out DtMin aggregate; do not infer full per-step clamp history",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT),
            "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none",
            "solver_launch": "forbidden", "hdf5_read": "forbidden", "launch_disabled": True,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "comparison_contract": {
            "contract_path": str(CONTRACT), "position_task_tolerance_fraction": 0.02,
            "velocity_and_ke_task_tolerance_fraction": 0.05, "whole_initial_mass_budget_fraction": 0.03,
            "event_time_relative_budget_fraction": 0.01, "time_alignment_budget": "one-quarter of corresponding task tolerance",
            "output_reconstruction_budget": "one-quarter of corresponding task tolerance",
            "quarter_of_total_window_is_forbidden": True,
            "integration_vs_output_error_separate": True,
            "adjacent_grid_difference_is_not_truth": True,
        },
    }
    # Snapshot request is additive and points to the immutable observer request;
    # it performs the selected-file pre/post SHA/stat closure before decode.
    snapshot_name = f"f1_s1_owner_{dp}_{mode}_selected_native_snapshot_v1.json"
    snapshot = {
        "schema": "ds02.request.v1", "family_id": "F1", "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": f"F1_S1_OWNER_{dp.upper()}_{mode.upper()}_SELECTED_NATIVE_SNAPSHOT_V1",
        "attempt_id": f"f1-s1-owner-{dp}-{mode}-selected-native-snapshot-v1-root-forward-001",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 3600, "worktree_root": str(REPO), "cwd": str(REPO),
        "command": [str(PYTHON), str(SNAPSHOT_WORKER), "--observer-request", str(observer_path), "--output", f"{{attempt_root}}/snapshot/{snapshot_name}"],
        "input_files": [str(BUILDER), str(SNAPSHOT_WORKER), str(DISPATCH), str(STRICT), str(RUNTIME), str(observer_path)],
        "input_hashes": {str(path): sha256_file(path) for path in [BUILDER, SNAPSHOT_WORKER, DISPATCH, STRICT, RUNTIME]},
        "observer_request_hash": "REQUEST_HASH_AFTER_EMISSION",
        "deferred_input_files": [str(raw_root), *[str(raw_root / f"Part_{frame:04d}.bi4") for frame in selected]],
        "deferred_hash_policy": {"selected_files_only": True, "pre_post_stat_and_sha": "required; mutation rejects snapshot", "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER"},
        "output": {"path": f"{{attempt_root}}/snapshot/{snapshot_name}", "atomic": True, "refuse_overwrite": True},
        "source_binding": {"observer_request": {"path": str(observer_path), "sha256": "REQUEST_HASH_AFTER_EMISSION"}, "raw_root": str(raw_root), "selected_native_frame_ids": selected, "solver_receipt": record(receipt_path), "runparts": record(runparts)},
        "estimated_native_read_bytes": selected_stat_bytes, "estimated_storage_bytes": max(1 << 30, selected_stat_bytes + (256 << 20)), "estimated_peak_memory_bytes": 256 << 20,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "hdf5_read": False, "bi4_decode": False,
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden"},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    # Text-only Savedt audit request; it has no deferred native files.
    dt_name = f"f1_s1_owner_{dp}_{mode}_savedt_metadata_v1.json"
    dt_request = {
        "schema": "ds02.request.v1", "family_id": "F1", "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": f"F1_S1_OWNER_{dp.upper()}_{mode.upper()}_SAVEDT_METADATA_V1",
        "attempt_id": f"f1-s1-owner-{dp}-{mode}-savedt-metadata-v1-root-forward-001",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900,
        "worktree_root": str(REPO), "cwd": str(REPO),
        "command": [str(PYTHON), str(DT_WORKER), "--receipt", str(receipt_path), "--request", str(request_path), "--output-root", str(output_root), "--output", f"{{attempt_root}}/savedt/{dt_name}"],
        "input_files": [str(DT_WORKER), str(DISPATCH), str(STRICT), str(RUNTIME), str(receipt_path), str(request_path), str(runparts), str(runout), str(runcsv), str(dtall), str(dtinfo)],
        "input_hashes": {str(path): sha256_file(path) for path in [DT_WORKER, DISPATCH, STRICT, RUNTIME, receipt_path, request_path, runparts, runout, runcsv, dtall, dtinfo]},
        "output": {"path": f"{{attempt_root}}/savedt/{dt_name}", "atomic": True, "refuse_overwrite": True},
        "source_binding": {"solver_receipt": record(receipt_path), "parent_request": record(request_path), "runparts": record(runparts), "run_out": record(runout), "run_csv": record(runcsv), "dtall_info": record(dtall), "dt_info": record(dtinfo), "native_payload_read": False},
        "estimated_native_read_bytes": 0, "estimated_storage_bytes": 32 << 20, "estimated_peak_memory_bytes": 128 << 20,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "hdf5_read": False, "bi4_decode": False,
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden"},
        "savedt_semantics": {"dtsmin": "count/summary, not seconds", "dtall": "saved-window flush rows, not complete per-step trace", "nonzero_dtmin_warning": "preserve and report; do not silently pass or fail"},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return observer, snapshot, dt_request, observer_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    out = args.output_dir.expanduser().resolve()
    specs = []
    for dp, mode in SOURCE_RUNS:
        receipt_path = run_receipt(dp, mode)
        if receipt_path is None:
            continue
        specs.append((dp, mode, receipt_path))
    if not specs:
        raise RuntimeError("no completed F1 owner receipts found")
    if args.self_test:
        # Self-test only validates that the completed set is discoverable and
        # that no raw file is opened by this builder; request emission remains
        # an explicit caller action.
        print(json.dumps({"status": "PASS", "completed_runs": [f"{dp}/{mode}" for dp, mode, _ in specs]}, sort_keys=True))
        return 0
    out.mkdir(parents=True, exist_ok=True)
    emitted: list[dict[str, Any]] = []
    for dp, mode, receipt_path in specs:
        observer, snapshot, dt_request, observer_path = make_observer(dp, mode, receipt_path, out)
        snapshot_path = out / f"f1_s1_owner_{dp}_{mode}_selected_native_snapshot_v1.json"
        dt_path = out / f"f1_s1_owner_{dp}_{mode}_savedt_metadata_v1.json"
        observer_path = out / f"f1_s1_owner_{dp}_{mode}_selected_native_observer_v1.json"
        # Replace builder-local observer path with the actual immutable output
        # location before writing the paired snapshot request.
        observer["command"][observer["command"].index("--output") + 1] = f"{{attempt_root}}/observer/{observer_path.name}"
        snapshot["command"][snapshot["command"].index("--observer-request") + 1] = str(observer_path)
        snapshot["input_files"][-1] = str(observer_path)
        snapshot["input_hashes"][str(observer_path)] = "REQUEST_HASH_AFTER_EMISSION"
        snapshot["source_binding"]["observer_request"] = {"path": str(observer_path), "sha256": "REQUEST_HASH_AFTER_EMISSION"}
        dt_request["command"][dt_request["command"].index("--output") + 1] = f"{{attempt_root}}/savedt/{dt_path.name}"
        atomic_json(observer_path, observer)
        # The snapshot request is deliberately emitted after the observer so
        # that its input SHA can be closed over the exact observer bytes.
        snapshot["input_hashes"][str(observer_path)] = sha256_file(observer_path)
        snapshot["source_binding"]["observer_request"] = record(observer_path)
        atomic_json(snapshot_path, snapshot)
        atomic_json(dt_path, dt_request)
        emitted.append({"dp": dp, "mode": mode, "observer": str(observer_path), "snapshot": str(snapshot_path), "savedt": str(dt_path), "receipt": str(receipt_path)})
    print(json.dumps({"status": "PASS_REQUESTS_EMITTED", "count": len(emitted), "runs": emitted}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
