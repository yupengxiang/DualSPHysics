#!/usr/bin/env python3
"""Register additive F5 native conversion and transport-label work.

The two reference-009 solver attempts are immutable, complete 0--16 s
native outputs.  This producer verifies those terminal outputs, binds every
raw Part frame and source/control artifact, and writes CPU-only conversion and
label requests for the shared runner.  It does not run GenCase, PartVTK,
conversion, labels, a solver, or a GPU job.
"""
from __future__ import annotations

import hashlib
import json
import math
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
from typing import Any


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
WORKTREE_ROOT = SCRIPT.parents[2]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F5"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
INTEGRATION_PYTHON = INTEGRATION_LAB / ".venv/bin/python"
RUNNER_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
MATURE_CONVERTER = LAB_ROOT / "scripts/ds_data02_f5_native.py"
CONVERTER_ADAPTER = LAB_ROOT / "scripts/ds_data02_f5_bi4.py"
REFERENCE_ADAPTER = LAB_ROOT / "scripts/ds_data02_f5_native_reference_009.py"
EVENT_DEFINITIONS = FAMILY_ROOT / "event_definitions.json"
QUALITY_CONTRACT = FAMILY_ROOT / "quality_contract.json"
SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"
BED = FAMILY_ROOT / "definitions/assets/f5_continuous_bed_profile_slope_0p280.stl"
OUT_ROOT = FAMILY_ROOT / "native_conversion/domain_repair_011"
EXPECTED_FRAMES = 801
TMAX_S = 16.0
SAVE_INTERVAL_S = 0.02
BYTES_PER_PARTICLE_FRAME = 64
GIB = 1024**3


CASE_SPECS: dict[str, dict[str, Any]] = {
    "runup_return": {
        "case_id": "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009",
        "source_case_id": "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007",
        "mechanism_id": "runup_return",
        "background": "runup_return",
        "motion_name": "piston_f91973457a049db5_regular_piston.dat",
        "metadata": FAMILY_ROOT / "definitions/F5_REF_RUNUP_NOMINAL_MEDIUM.metadata.json",
        "source_definition": FAMILY_ROOT / "definitions/F5_REF_RUNUP_NOMINAL_MEDIUM.xml",
        "solver_attempt": "qualification-f5-runup_return-phase-exact-007-native-reference-009-domain-repair-011",
        "root_request_name": "runup_return_solver_request_011.json",
        "root_proof_name": "runup_return_domain_proof_011.json",
    },
    "weir_pair": {
        "case_id": "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009",
        "source_case_id": "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007",
        "mechanism_id": "weir_pair",
        "background": "weir_pair",
        "motion_name": "piston_4c73cd98b7230035_regular_piston.dat",
        "metadata": FAMILY_ROOT / "definitions/F5_REF_WEIR_NOMINAL_MEDIUM.metadata.json",
        "source_definition": FAMILY_ROOT / "definitions/F5_REF_WEIR_NOMINAL_MEDIUM.xml",
        "solver_attempt": "qualification-f5-weir_pair-phase-exact-007-native-reference-009-domain-repair-011",
        "root_request_name": "weir_pair_solver_request_011.json",
        "root_proof_name": "weir_pair_domain_proof_011.json",
    },
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def write_json(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite additive F5 artifact: {path}")
    partial = path.with_name(path.name + f".{__import__('os').getpid()}.partial")
    partial.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def git_head() -> str:
    return subprocess.run(
        ["git", "-C", str(WORKTREE_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def paths(spec: dict[str, Any]) -> dict[str, Any]:
    case_root = DATA_ROOT / spec["case_id"]
    input_root = case_root / "native_inputs_domain_repair_011"
    solver_root = case_root / spec["solver_attempt"]
    output = solver_root / "solver_output"
    generated_prefix = input_root / spec["source_case_id"]
    original_gencase = DATA_ROOT / spec["source_case_id"] / (
        "gencase-" + ("f5-runup_return" if spec["mechanism_id"] == "runup_return" else "f5-weir_pair")
        + "-cellcentre-phase-exact-dp025-007"
    )
    original_gencase_receipt = original_gencase / "execution-receipt.json"
    root_proof_root = INTEGRATION_LAB / "campaigns/ds-data-02/families/F5/initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_PHASE_EXACT_DP025_007/native_reference_009/root_native_domain_repair_011"
    root_launch_root = INTEGRATION_LAB / "campaigns/ds-data-02/families/F5/initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_PHASE_EXACT_DP025_007/native_reference_009/root_solver_launch_010"
    return {
        "case_root": case_root,
        "input_root": input_root,
        "generated_prefix": generated_prefix,
        "generated_xml": generated_prefix.with_suffix(".xml"),
        "generated_bi4": generated_prefix.with_suffix(".bi4"),
        "staged_motion": input_root / spec["motion_name"],
        "staged_bed": input_root / "assets/f5_continuous_bed_profile_slope_0p280.stl",
        "solver_root": solver_root,
        "solver_output": output,
        "partout_files": sorted(output.glob("data/PartOut_*.obi4")),
        "solver_receipt": solver_root / "execution-receipt.json",
        "run_out": output / "Run.out",
        "run_parts": output / "RunPARTs.csv",
        "run_csv": output / "Run.csv",
        "gencase_receipt": original_gencase_receipt,
        "source_generated_xml": original_gencase / f"{spec['source_case_id']}.xml",
        "source_generated_bi4": original_gencase / f"{spec['source_case_id']}.bi4",
        "source_motion": FAMILY_ROOT / "definitions" / spec["motion_name"],
        "root_request": root_proof_root / spec["root_request_name"],
        "root_proof": root_proof_root / spec["root_proof_name"],
        "root_launch_request": root_launch_root / spec["mechanism_id"] / "solver_request_010.json",
        # The independent grid audit is bound to the immutable v7 mother
        # case, beside the original GenCase receipt.  It is not regenerated
        # under the later domain-repair-011 solver output tree.
        "grid_audit": DATA_ROOT / spec["source_case_id"] / "root-double-native-grid-audit-001/native-grid-audit.json",
        "grid_audit_receipt": DATA_ROOT / spec["source_case_id"] / "root-double-native-grid-audit-001/execution-receipt.json",
        "solid_audit": case_root / "root-native-union-solid-coverage-003/native-solid-coverage.json",
        "solid_audit_receipt": case_root / "root-native-union-solid-coverage-003/execution-receipt.json",
    }


def _integer(value: str | None) -> int:
    """Parse DualSPHysics CSV integers, which may contain thousands commas."""
    if value is None or not str(value).strip():
        return 0
    return int(float(str(value).replace(",", "").strip()))


def _float(value: str | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    return float(str(value).replace(",", "").strip())


def _run_csv_accounting(path: Path) -> dict[str, Any]:
    """Read the one-row Run.csv summary without treating PartsOut as proof.

    DualSPHysics writes the header with a leading ``#`` and uses comma-grouped
    integer fields.  The result is deliberately a source accounting record:
    the later PartVTKOut/typed conversion must still audit particle identity
    and any actual exclusion payload.
    """
    lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    header_index = next((index for index, line in enumerate(lines) if line.startswith("#RunName;")), None)
    if header_index is None or header_index + 1 >= len(lines):
        raise ValueError(f"Run.csv lacks a header/data pair: {path}")
    header = [field.lstrip("#") for field in lines[header_index].split(";")]
    values = lines[header_index + 1].split(";")
    if len(values) < len(header):
        raise ValueError(f"Run.csv data row is shorter than its header: {path}")
    row = dict(zip(header, values))
    part_files = _integer(row.get("PartFiles"))
    parts_out = _integer(row.get("PartsOut"))
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "part_files": part_files,
        "parts_out": parts_out,
        "physical_time_s": _float(row.get("PhysicalTime")),
        "case_particles": _integer(row.get("Np")),
        "fixed_particles": _integer(row.get("Nfixed")),
        "dp_m": _float(row.get("Dp")),
        "header_fields": len(header),
    }


def _runparts_accounting(path: Path) -> dict[str, Any]:
    """Summarize every native save row and all four exclusion counters."""
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        rows = list(csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")), delimiter=";"))
    rows = [row for row in rows if str(row.get("Part", "")).strip().isdigit()]
    if not rows:
        raise ValueError(f"RunPARTs has no numeric save rows: {path}")
    counters = ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")
    summary: dict[str, Any] = {}
    for key in counters:
        values = [_integer(row.get(key)) for row in rows]
        summary[key] = {
            "sum": sum(values),
            "max": max(values),
            "nonzero_rows": sum(value != 0 for value in values),
        }
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "row_count": len(rows),
        "first_part": _integer(rows[0].get("Part")),
        "last_part": _integer(rows[-1].get("Part")),
        "first_time_s": _float(rows[0].get("TimeStep [s]")),
        "last_time_s": _float(rows[-1].get("TimeStep [s]")),
        "np_sim_first": _integer(rows[0].get("NpSim")),
        "np_sim_last": _integer(rows[-1].get("NpSim")),
        "np_bound_first": _integer(rows[0].get("NpbSim")),
        "np_bound_last": _integer(rows[-1].get("NpbSim")),
        "np_fluid_first": _integer(rows[0].get("NpfSim")),
        "np_fluid_last": _integer(rows[-1].get("NpfSim")),
        "exclusion_counters": summary,
        "all_exclusion_counters_zero": all(item["sum"] == 0 and item["max"] == 0 and item["nonzero_rows"] == 0 for item in summary.values()),
    }


def exclusion_accounting(spec: dict[str, Any], p: dict[str, Any], runparts: dict[str, Any], run_csv: dict[str, Any]) -> dict[str, Any]:
    partout = []
    for path in p["partout_files"]:
        partout.append({
            "path": str(path.resolve()),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "role": "native PartOut artifact retained for later PartVTKOut/typed exclusion audit",
        })
    if not partout:
        raise FileNotFoundError(f"F5 {spec['mechanism_id']} has no native PartOut_*.obi4 artifact")
    return {
        "schema": "ds-data-02.f5.native-exclusion-accounting.v1",
        "case_id": spec["case_id"],
        "mechanism_id": spec["mechanism_id"],
        "saved_frame_contract": {
            "expected_frames": EXPECTED_FRAMES,
            "runparts_rows": runparts["row_count"],
            "run_csv_part_files": run_csv["part_files"],
            "first_part": runparts["first_part"],
            "last_part": runparts["last_part"],
            "full_window_s": [runparts["first_time_s"], runparts["last_time_s"]],
        },
        "solver_counters": runparts,
        "run_csv": run_csv,
        "native_partout_artifacts": partout,
        "partvtkout_accounting_required": True,
        "motive_accounting_required": True,
        "unknown_exclusion_policy": "RunPARTs counters and Run.csv PartsOut are retained as solver accounting only; every PartOut artifact is hash-bound and its particle identity/provenance remains unknown until official PartVTKOut plus typed HDF5 conversion audit.",
        "q_i_status": "pending_typed_conversion_partvtkout_and_motive_audit",
        "q_n_status": "not_assessed",
    }


def require_terminal(spec: dict[str, Any], p: dict[str, Path]) -> dict[str, Any]:
    required = ["generated_xml", "generated_bi4", "staged_motion", "staged_bed", "solver_receipt", "run_out", "run_parts", "run_csv", "gencase_receipt", "root_request", "root_proof"]
    for key in required:
        if not p[key].is_file():
            raise FileNotFoundError(f"F5 {spec['mechanism_id']} missing {key}: {p[key]}")
    receipt = json.loads(p["solver_receipt"].read_text(encoding="utf-8"))
    if receipt.get("status") not in {"completed", "success"}:
        raise ValueError(f"F5 solver receipt is not terminal completed: {p['solver_receipt']}")
    run_text = p["run_out"].read_text(encoding="utf-8", errors="replace")
    if not re.search(r"Finished execution \(code=0\)", run_text):
        raise ValueError(f"F5 Run.out lacks code=0 completion marker: {p['run_out']}")
    frames = sorted(p["solver_output"].glob("data/Part_*.bi4"))
    if len(frames) != EXPECTED_FRAMES:
        raise ValueError(f"F5 {spec['mechanism_id']} expected {EXPECTED_FRAMES} native frames, got {len(frames)}")
    runparts = _runparts_accounting(p["run_parts"])
    run_csv = _run_csv_accounting(p["run_csv"])
    if runparts["row_count"] != EXPECTED_FRAMES or run_csv["part_files"] != EXPECTED_FRAMES:
        raise ValueError(f"F5 native save accounting mismatch: RunPARTs={runparts['row_count']} Run.csv PartFiles={run_csv['part_files']}")
    if run_csv["parts_out"] != 0:
        raise ValueError(f"F5 Run.csv reports unexpected PartsOut={run_csv['parts_out']}: {p['run_csv']}")
    accounting = exclusion_accounting(spec, p, runparts, run_csv)
    proof = json.loads(p["root_proof"].read_text(encoding="utf-8"))
    root_request = json.loads(p["root_request"].read_text(encoding="utf-8"))
    # The domain proof carries the repair semantics while the immutable root
    # request carries the authoritative native typed counts.
    native = root_request.get("actual_native", proof.get("actual_native", {}))
    if native.get("solver_dimension") != 3 or native.get("fluid_particles") != 150528 or abs(float(native.get("fluid_mass_kg", -1.0)) - 2352.0) > 1e-9:
        raise ValueError(f"F5 root native proof does not match frozen fluid contract: {p['root_proof']}")
    root_review = root_request.get("root_review", proof.get("root_review", {}))
    if not root_review.get("independent_raw_initial_grid_pass", False):
        raise ValueError(f"F5 root native grid audit is not passed: {p['root_proof']}")
    return {
        "receipt": receipt,
        "frames": frames,
        "run_parts_rows": runparts["row_count"],
        "runparts_accounting": runparts,
        "run_csv_accounting": run_csv,
        "exclusion_accounting": accounting,
        "partout_files": p["partout_files"],
        "actual_native": native,
        "solver_elapsed_seconds": receipt.get("elapsed_seconds"),
        "solver_output_bytes": sum(path.stat().st_size for path in frames),
        "run_finished_code_zero": True,
    }


def unique_existing(values: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for value in values:
        value = Path(value).resolve()
        if str(value) in seen:
            continue
        if not value.is_file():
            raise FileNotFoundError(value)
        seen.add(str(value))
        result.append(value)
    return result


def raw_tree_binding(frames: list[Path]) -> dict[str, Any]:
    def frame_binding(frame: Path) -> dict[str, Any]:
        return {"path": str(frame.resolve()), "bytes": frame.stat().st_size, "sha256": sha256(frame)}

    # The immutable native tree contains 1602 medium-sized files.  Bounded
    # read-only workers avoid paying a filesystem open/latency round-trip for
    # every frame serially; map preserves sorted frame order for the tree hash.
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(frames)))) as pool:
        inventory = list(pool.map(frame_binding, frames))
    tree = hashlib.sha256()
    for item in inventory:
        frame = Path(item["path"])
        tree.update(f"{frame.name}\0{item['bytes']}\0{item['sha256']}\n".encode("utf-8"))
    return {
        "frame_count": len(inventory),
        "bytes": sum(item["bytes"] for item in inventory),
        "tree_sha256": tree.hexdigest(),
        "frames": inventory,
    }


def source_inputs(spec: dict[str, Any], p: dict[str, Any], terminal: dict[str, Any], owner_path: Path, exclusion_path: Path, frame_binding: dict[str, Any]) -> tuple[list[Path], dict[str, Any]]:
    frames = terminal["frames"]
    gauges = sorted(p["solver_output"].glob("Gauges*.csv"))
    fixed = [
        SCRIPT, REFERENCE_ADAPTER, MATURE_CONVERTER, CONVERTER_ADAPTER,
        INTEGRATION_PYTHON, RUNNER_V2, DECODER, PARTVTK,
        EVENT_DEFINITIONS, QUALITY_CONTRACT, SAVE_PLAN,
        spec["metadata"], spec["source_definition"], p["source_motion"], BED,
        p["generated_xml"], p["generated_bi4"], p["staged_motion"], p["staged_bed"],
        p["gencase_receipt"], p["solver_receipt"], p["run_out"], p["run_parts"], p["run_csv"],
        p["root_request"], p["root_proof"], p["grid_audit"], p["grid_audit_receipt"],
        p["solid_audit"], p["solid_audit_receipt"], owner_path, exclusion_path,
    ]
    values = unique_existing(fixed + list(p["partout_files"]) + frames + gauges)
    # Reuse the frame inventory already computed for owner metadata.  The raw
    # trees are tens of GiB; hashing them a second time during registration is
    # unnecessary and makes the read-only registration needlessly expensive.
    files = {str(item["path"]): item["sha256"] for item in frame_binding["raw_frames"]["frames"]}
    files.update({str(path): sha256(path) for path in values if str(path) not in files})
    return values, {
        "input_sha256": files,
        "raw_frames": frame_binding["raw_frames"],
        "gauge_csv_count": len(gauges),
        "native_exclusion_accounting": terminal["exclusion_accounting"],
        "exclusion_accounting_path": str(exclusion_path),
    }


def physical_binding(spec: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.physical-binding.v1",
        "family_id": "F5",
        "physical_case_id": metadata["physical_case_id"],
        "lineage_group_id": metadata["lineage_group_id"],
        "paired_background_id": metadata["paired_background_id"],
        "mechanism_id": spec["mechanism_id"],
        "geometry_family_id": metadata["geometry_family_id"],
        "control_family_id": metadata["control_family_id"],
        "geometry": {
            "initial_fluid": {"low_m": [-0.9, -0.7, 0.02], "size_m": [4.2, 1.4, 0.4], "mkfluid": 0, "label": "frozen continuous initial fluid box"},
            "finite_tank": {"low_m": [-1.1, -0.8, -0.25], "size_m": [11.9, 1.6, 1.45], "mkfluid": None, "label": "finite solver tank envelope"},
            "continuous_bed": {"low_m": [-1.1, -0.72, -0.25], "size_m": [11.95, 1.44, 1.09], "mkfluid": None, "label": "continuous finite bed STL envelope"},
            "return_region": {"low_m": [7.15, -0.72, 0.08], "size_m": [3.7, 1.44, 0.4], "mkfluid": 0, "label": "finite downstream return destination"},
        },
        "initial_state": {
            "source_regions": ["initial_fluid"],
            "source_labels": ["upstream_reservoir"],
            "velocities_m_per_s": [[0.0, 0.0, 0.0]],
            "continuum_mass_by_source_kg": [2352.0],
            "initial_mass_total_kg": 2352.0,
            "mass_policy": "native BI4 MassFluid times initial fluid cohort; no rescaling",
        },
        "controls": {
            "step_algorithm": 2,
            "kernel": 2,
            "viscosity": 0.01,
            "density_dt": 2,
            "density_dt_value": 0.1,
            "boundary": "finite DBC floor, finite sidewalls, finite prescribed piston, no periodic y",
        },
        "gravity_m_s2": [0.0, 0.0, -9.81],
        "density_kg_m3": 1000.0,
        "parameters": {
            "initial_depth_m": metadata.get("initial_depth_m"),
            "slope_ratio": metadata.get("slope_ratio"),
            "coordinate_components": 3,
            "finite_source": "upstream_reservoir",
            "finite_destination": "downstream return region and lateral notch for weir_pair",
        },
        "event_window": {
            "time_start_s": 0.0,
            "time_end_s": TMAX_S,
            "sequence": ["toe_first_arrival", "runup_or_crest_first_passage", "return_crossing", "terminal_destination"],
            "expected_first_contact_range_s": [0.0, TMAX_S],
            "right_censor_policy": "unseen events at 16 s remain censored and retain the 2352 kg denominator",
        },
        "open_inlet": False,
        "periodic_boundary": False,
        "mass_policy": "native per-particle mass from BI4 header; type-aware ledger",
    }


def owner_metadata(spec: dict[str, Any], p: dict[str, Any], terminal: dict[str, Any], frame_binding: dict[str, Any], exclusion_path: Path) -> dict[str, Any]:
    metadata = json.loads(Path(spec["metadata"]).read_text(encoding="utf-8"))
    source_bindings = {
        "source_definition": bind(spec["source_definition"], "immutable F5 physical source XML"),
        "source_metadata": bind(spec["metadata"], "immutable F5 physical source metadata"),
        "generated_xml": bind(p["generated_xml"], "fresh co-located domain-repair XML"),
        "generated_bi4": bind(p["generated_bi4"], "fresh co-located domain-repair BI4"),
        "staged_motion": bind(p["staged_motion"], "co-located motion referenced by XML"),
        "source_motion": bind(p["source_motion"], "immutable source motion"),
        "source_bed": bind(BED, "immutable finite bed STL"),
        "solver_receipt": bind(p["solver_receipt"], "completed full-window solver receipt"),
        "gencase_receipt": bind(p["gencase_receipt"], "completed original GenCase receipt"),
        "root_domain_proof": bind(p["root_proof"], "root domain repair and finite union evidence"),
        "root_grid_audit": bind(p["grid_audit"], "independent native grid audit"),
        "root_solid_audit": bind(p["solid_audit"], "independent union finite-solid audit"),
        "native_exclusion_accounting": bind(exclusion_path, "RunPARTs/Run.csv/PartOut source accounting; no Q-I claim"),
        "native_partout_artifacts": [bind(path, "native PartOut artifact retained for PartVTKOut audit") for path in p["partout_files"]],
        "event_definitions": bind(EVENT_DEFINITIONS, "frozen F5 event definitions"),
        "quality_contract": bind(QUALITY_CONTRACT, "frozen F5 quality contract"),
    }
    return {
        "schema": "ds-data-02.f5.native-owner-metadata.v2",
        "family_id": "F5",
        "case_id": spec["case_id"],
        "mechanism_id": spec["mechanism_id"],
        "background": spec["background"],
        "resolution": "medium",
        "physical_case_id": metadata["physical_case_id"],
        "lineage_group_id": metadata["lineage_group_id"],
        "paired_background_id": metadata["paired_background_id"],
        "geometry_family_id": metadata["geometry_family_id"],
        "control_family_id": metadata["control_family_id"],
        "recipe_id": metadata["recipe_id"],
        "physical_binding": physical_binding(spec, metadata),
        "source_contract": {
            "finite_source": "initial upstream fluid box x=-0.90..3.30, y=-0.70..0.70, z=0.02..0.42",
            "finite_destinations": ["upstream", "slope_crest", "downstream_return", "weir_notch" if spec["mechanism_id"] == "weir_pair" else "runup_return"],
            "no_posthoc_destination_assignment": True,
            "solver_dimension_required": 3,
            "domain_repair_semantics": "numerical simulation-domain envelope extension only; fluid lattice, finite bed/walls, piston control, and 2352 kg denominator remain frozen",
        },
        "source_bindings": source_bindings,
        "raw_solver_tree": {
            "frame_count": frame_binding["raw_frames"]["frame_count"],
            "bytes": frame_binding["raw_frames"]["bytes"],
            "tree_sha256": frame_binding["raw_frames"]["tree_sha256"],
            "time_window_s": [0.0, TMAX_S],
            "save_interval_s": SAVE_INTERVAL_S,
            "typed_native": terminal["actual_native"],
            "runparts_accounting": terminal["runparts_accounting"],
            "run_csv_accounting": terminal["run_csv_accounting"],
            "exclusion_accounting": terminal["exclusion_accounting"],
        },
        "qualification_claim": "none; complete native macro reference only",
        "q_i_status": "pending immutable conversion and root review",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
        "written_at_utc": now(),
    }


def conversion_request(spec: dict[str, Any], p: dict[str, Path], terminal: dict[str, Any], owner_path: Path, inputs: list[Path], input_info: dict[str, Any], launch_commit: str) -> dict[str, Any]:
    total_particles = int(terminal["actual_native"]["total_particles"])
    raw_bytes = int(input_info["raw_frames"]["bytes"])
    estimated = max(32 * GIB, int(math.ceil((raw_bytes * 1.75 + 4 * GIB) / GIB) * GIB))
    output = "{attempt_root}/native"
    command = [
        str(INTEGRATION_PYTHON), str(REFERENCE_ADAPTER), "convert",
        "--case-id", spec["case_id"],
        "--data-root", str(p["solver_output"] / "data"),
        "--generated-xml", str(p["generated_xml"]),
        "--solver-receipt", str(p["solver_receipt"]),
        "--gencase-receipt", str(p["gencase_receipt"]),
        "--owner-metadata", str(owner_path),
        "--decoder", str(DECODER),
        "--partvtk", str(PARTVTK),
        "--motion", str(p["staged_motion"]),
        "--solver-output", str(p["solver_output"]),
        "--event-definitions", str(EVENT_DEFINITIONS),
        "--quality-contract", str(QUALITY_CONTRACT),
        "--output", output + "/native_all_types.h5",
        "--report", output + "/conversion-report.json",
        "--validation-dir", output + "/partvtk-validation",
        "--audit", output + "/transport-audit.json",
        "--preview", output + "/preview.json",
    ]
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F5",
        "case_id": spec["case_id"],
        "mechanism_id": spec["mechanism_id"],
        "attempt_id": f"native-conversion-{spec['mechanism_id']}-domain-repair-011-001",
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "command": command,
        "cwd": str(LAB_ROOT),
        "max_wall_seconds": 5400,
        "cpu_threads": 4,
        "estimated_storage_bytes": estimated,
        "input_files": [str(path) for path in inputs],
        "input_sha256": input_info["input_sha256"],
        "worktree_root": str(WORKTREE_ROOT),
        "launch_commit": launch_commit,
        "conversion_version": "ds-data-02.f5.native-conversion.reference-009.v2",
        "input_binding": {
            "mode": "all immutable raw Part_*.bi4 frames plus PartOut artifacts and complete solver/GenCase/control/geometry/tool provenance",
            "file_count": len(inputs),
            "raw_frame_count": EXPECTED_FRAMES,
            "raw_tree_sha256": input_info["raw_frames"]["tree_sha256"],
            "raw_total_bytes": raw_bytes,
            "raw_tree_read_only": True,
            "native_exclusion_accounting": input_info["native_exclusion_accounting"],
            "exclusion_accounting_path": input_info["exclusion_accounting_path"],
        },
        "partvtkout_motive_prerequisites": {
            "partvtkout_required": True,
            "motive_required": True,
            "partout_artifacts": terminal["exclusion_accounting"]["native_partout_artifacts"],
            "runparts_counter_policy": "retain all NpOut/NpOutPos/NpOutRho/NpOutMov rows and sums; do not infer absence of exclusions from Run.csv PartsOut=0",
            "identity_policy": "PartVTKOut and converted typed HDF5 must account for (Zone,Idp), type, mk and any excluded particle source/destination; unknown remains explicit until audit",
            "status": "pending_conversion_partvtkout_and_motive_audit",
        },
        "actual_source": {
            "solver_attempt": str(p["solver_root"]),
            "generated_prefix": str(p["generated_prefix"]),
            "generated_xml_sha256": sha256(p["generated_xml"]),
            "generated_bi4_sha256": sha256(p["generated_bi4"]),
            "gencase_receipt": str(p["gencase_receipt"]),
            "solver_receipt": str(p["solver_receipt"]),
            "root_domain_proof": str(p["root_proof"]),
            "solver_dimension": 3,
            "native_particles": total_particles,
            "native_fluid_particles": int(terminal["actual_native"]["fluid_particles"]),
            "native_fluid_mass_kg": float(terminal["actual_native"]["fluid_mass_kg"]),
            "event_window_s": [0.0, TMAX_S],
            "expected_frames": EXPECTED_FRAMES,
            "runparts_rows": terminal["runparts_accounting"]["row_count"],
            "run_csv_part_files": terminal["run_csv_accounting"]["part_files"],
            "run_csv_parts_out": terminal["run_csv_accounting"]["parts_out"],
            "all_solver_exclusion_counters_zero": terminal["runparts_accounting"]["all_exclusion_counters_zero"],
            "native_partout_artifact_count": len(terminal["partout_files"]),
        },
        "resource_review": {
            "estimated_h5_and_sidecars_bytes": estimated,
            "raw_frame_bytes": raw_bytes,
            "formula": "max(32 GiB, ceil((raw Part bytes*1.75 + 4 GiB)/GiB)*GiB)",
            "reason": "801 complete typed frames; full fixed/moving/fluid axis, PartVTK validation, HDF5, audit and preview",
            "max_concurrent_conversion_requests": 2,
            "current_slot_status": "deferred_due_to_F4_conversion_slots",
        },
        "qualification_claim": "none",
        "q_i_status": "conversion evidence pending shared runner and root review",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }


def label_request(spec: dict[str, Any], p: dict[str, Any], owner_path: Path, exclusion_path: Path, conversion_request_path: Path, launch_commit: str) -> dict[str, Any]:
    output = "{attempt_root}/labels"
    command = [
        str(INTEGRATION_PYTHON), str(REFERENCE_ADAPTER), "label",
        "--case-id", spec["case_id"],
        "--hdf5", "{conversion_attempt_root}/native/native_all_types.h5",
        "--owner-metadata", str(owner_path),
        "--motion", str(p["staged_motion"]),
        "--solver-output", str(p["solver_output"]),
        "--event-definitions", str(EVENT_DEFINITIONS),
        "--quality-contract", str(QUALITY_CONTRACT),
        "--output", output + "/transport-audit.json",
        "--preview", output + "/preview.json",
        "--labels", output + "/transport-labels.h5",
    ]
    input_files = [
        REFERENCE_ADAPTER, MATURE_CONVERTER, CONVERTER_ADAPTER, INTEGRATION_PYTHON,
        owner_path, exclusion_path, p["staged_motion"], p["solver_receipt"], p["run_out"], p["run_parts"], p["run_csv"],
        *p["partout_files"], EVENT_DEFINITIONS, QUALITY_CONTRACT, conversion_request_path,
    ]
    input_files = unique_existing(input_files)
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F5",
        "case_id": spec["case_id"],
        "mechanism_id": spec["mechanism_id"],
        "attempt_id": f"native-label-audit-{spec['mechanism_id']}-domain-repair-011-001",
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "command": command,
        "cwd": str(LAB_ROOT),
        "max_wall_seconds": 1800,
        "cpu_threads": 4,
        "estimated_storage_bytes": 8 * GIB,
        "input_files": [str(path) for path in input_files],
        "input_sha256": {str(path): sha256(path) for path in input_files},
        "deferred_inputs": {
            "conversion_request": str(conversion_request_path),
            "conversion_output": "{conversion_attempt_root}/native/native_all_types.h5",
            "conversion_output_sha256_required": True,
            "partvtkout_motive_audit_required": True,
            "native_exclusion_accounting": str(exclusion_path),
        },
        "worktree_root": str(WORKTREE_ROOT),
        "launch_commit": launch_commit,
        "status": "deferred_until_conversion_terminal_and_slot_available",
        "raw_tree_read_only": True,
        "qualification_claim": "none",
        "q_i_status": "pending typed HDF5 and event-label audit",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }


def macro_plan(spec: dict[str, Any], p: dict[str, Any], owner_path: Path, exclusion_path: Path, conversion_path: Path, label_path: Path, terminal: dict[str, Any], input_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f5.native-macro-operator-plan.v1",
        "family_id": "F5",
        "case_id": spec["case_id"],
        "mechanism_id": spec["mechanism_id"],
        "status": "deferred_until_native_h5_and_labels_are_terminal",
        "qualification_claim": "none",
        "q_n_status": "not_assessed",
        "source_contract": {
            "continuous_fluid_mass_denominator_kg": 2352.0,
            "native_fluid_particles": 150528,
            "solver_dimension": 3,
            "time_window_s": [0.0, TMAX_S],
            "save_interval_s": SAVE_INTERVAL_S,
            "finite_source": "upstream_reservoir",
            "finite_destinations": ["upstream_source", "slope_crest", "downstream_return", "weir_notch" if spec["mechanism_id"] == "weir_pair" else "runup_return"],
            "mass_policy": "retain the frozen 2352 kg denominator; unseen events are right-censored",
        },
        "input_templates": {
            "native_h5": "{conversion_attempt_root}/native/native_all_types.h5",
            "conversion_report": "{conversion_attempt_root}/native/conversion-report.json",
            "transport_audit": "{label_attempt_root}/labels/transport-audit.json",
            "transport_labels": "{label_attempt_root}/labels/transport-labels.h5",
            "runparts": str(p["run_parts"]),
            "run_csv": str(p["run_csv"]),
            "event_definitions": str(EVENT_DEFINITIONS),
            "native_exclusion_accounting": str(exclusion_path),
        },
        "operators": [
            {"name": "typed_identity_integrity", "definition": "all saved fixed/moving/fluid cohorts retain (Zone,Idp), type and mk ledgers"},
            {"name": "initial_mass", "definition": "native BI4 fluid cohort mass against 2352 kg continuous denominator"},
            {"name": "moving_piston_control", "definition": "saved moving type-1 centroid and velocity against the hash-bound 0--16 s motion file"},
            {"name": "gauge_response", "definition": "WG1..WG4 and mechanism-specific crest/runup gauges over all 801 saved frames"},
            {"name": "first_passage", "definition": "toe, crest/notch/runup and return crossings with saved-frame interpolation and right censoring"},
            {"name": "residence_and_destination", "definition": "finite source/destination residence and terminal destination using initial fluid identities"},
            {"name": "boundary_exclusion", "definition": "RunPARTs full-window NpOut/NpOutPos/NpOutRho/NpOutMov plus retained PartOut artifacts; unknown particle provenance stays explicit until PartVTKOut/typed audit"},
            {"name": "partvtkout_motive_accounting", "definition": "official PartVTKOut validation and native Motive/typed identity ledger for fixed, moving, fluid and any excluded particles; no solver counter is promoted to Q-I"},
        ],
        "source_bindings": {
            "owner_metadata": str(owner_path),
            "conversion_request": str(conversion_path),
            "label_request": str(label_path),
            "raw_tree_sha256": input_info["raw_frames"]["tree_sha256"],
            "solver_receipt": str(p["solver_receipt"]),
            "actual_native": terminal["actual_native"],
            "native_exclusion_accounting": terminal["exclusion_accounting"],
            "partout_artifacts": terminal["exclusion_accounting"]["native_partout_artifacts"],
        },
        "outputs": {"macro_summary": "{macro_attempt_root}/f5-native-macro-summary.json", "preview": "{macro_attempt_root}/f5-native-macro-preview.json"},
        "review_gates": ["conversion HDF5 schema and three PartVTK frames", "full 801-frame time axis", "label source hash", "RunPARTs complete 0--16 s", "PartVTKOut/Motive accounting of retained PartOut artifact", "finite face/controls provenance"],
    }


def register() -> dict[str, Any]:
    launch_commit = git_head()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for mechanism, spec in CASE_SPECS.items():
        p = paths(spec)
        terminal = require_terminal(spec, p)
        owner_path = OUT_ROOT / f"{spec['case_id']}.owner-metadata.json"
        exclusion_path = OUT_ROOT / f"{spec['case_id']}.native-exclusion-accounting.json"
        frame_binding = {"raw_frames": raw_tree_binding(terminal["frames"])}
        write_json(exclusion_path, terminal["exclusion_accounting"])
        owner = owner_metadata(spec, p, terminal, frame_binding, exclusion_path)
        write_json(owner_path, owner)
        inputs, input_info = source_inputs(spec, p, terminal, owner_path, exclusion_path, frame_binding)
        conversion = conversion_request(spec, p, terminal, owner_path, inputs, input_info, launch_commit)
        conversion_path = OUT_ROOT / f"{spec['case_id']}.conversion-request.json"
        write_json(conversion_path, conversion)
        label = label_request(spec, p, owner_path, exclusion_path, conversion_path, launch_commit)
        label_path = OUT_ROOT / f"{spec['case_id']}.label-request.json"
        write_json(label_path, label)
        plan = macro_plan(spec, p, owner_path, exclusion_path, conversion_path, label_path, terminal, input_info)
        plan_path = OUT_ROOT / f"{spec['case_id']}.macro-operator-plan.json"
        write_json(plan_path, plan)
        rows.append({
            "mechanism_id": mechanism,
            "case_id": spec["case_id"],
            "owner_metadata": str(owner_path),
            "conversion_request": str(conversion_path),
            "label_request": str(label_path),
            "macro_operator_plan": str(plan_path),
            "raw_frame_count": len(terminal["frames"]),
            "raw_frame_bytes": input_info["raw_frames"]["bytes"],
            "raw_tree_sha256": input_info["raw_frames"]["tree_sha256"],
            "runparts_rows": terminal["runparts_accounting"]["row_count"],
            "run_csv_part_files": terminal["run_csv_accounting"]["part_files"],
            "run_csv_parts_out": terminal["run_csv_accounting"]["parts_out"],
            "all_solver_exclusion_counters_zero": terminal["runparts_accounting"]["all_exclusion_counters_zero"],
            "native_partout_artifact_count": len(terminal["partout_files"]),
            "solver_status": terminal["receipt"].get("status"),
            "solver_elapsed_seconds": terminal["solver_elapsed_seconds"],
            "conversion_status": "deferred_due_to_F4_conversion_slots",
            "q_i_status": "pending_conversion",
            "q_n_status": "not_assessed",
        })
    manifest = {
        "schema": "ds-data-02.f5.native-conversion-registration.reference-009.v1",
        "family_id": "F5",
        "scope": "domain-repair-011 complete 0--16 s native macro references",
        "registered_at_utc": now(),
        "launch_commit": launch_commit,
        "requests": rows,
        "raw_solver_reuse": "immutable complete 801-frame native outputs; no solver rerun",
        "concurrency": {"max_simultaneous_conversion_requests": 2, "runner_required": True, "current_status": "deferred_due_to_F4_conversion_slots"},
        "qualification_claim": "none",
        "q_i_status": "pending conversion, labels, root review",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }
    manifest_path = OUT_ROOT / "registration-index-011.json"
    write_json(manifest_path, manifest)
    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("register", nargs="?", default="register")
    args = parser.parse_args()
    if args.register != "register":
        raise SystemExit(f"unsupported command: {args.register}")
    print(json.dumps(register(), ensure_ascii=False, indent=2, sort_keys=True))
