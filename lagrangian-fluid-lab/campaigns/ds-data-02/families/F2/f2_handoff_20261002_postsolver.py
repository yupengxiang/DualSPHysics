#!/usr/bin/env python3
"""Prepare and run evidence-bound F2 Gem post-solver jobs.

The six V2 Gem cases are a new physical scope.  This module consumes only a
terminal solver receipt and its completed GenCase artifact; it never launches
a solver.  ``materialize-owner`` derives an explicit generator record from the
frozen V2 metadata and the source geometry record.  ``materialize-conversion``
then writes one shared-runner CPU request.  ``convert`` uses the reviewed BI4
streaming converter and augments its HDF5 with a pose fitted to the saved
moving Type=1 nodes.  The prescribed motion file is retained as a comparison
only; it is never used to fill a missing pose.

Labels and the native exclusion ledger are separate CPU stages.  They are
materialized only from completed upstream artifacts, so an absent output can
never be represented by a placeholder path.  None of these stages grants Q-I,
Q-N, or production eligibility.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping


FAMILY = "F2"
SCOPE = "F2_SCOPE_GEM_COMMENSURATE_CELLCENTER_20261002_V2"
LAB_ROOT = Path(__file__).resolve().parents[4]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F2"
HANDOFF = FAMILY_ROOT / "handoff_20261002"
V2_ROOT = HANDOFF / "gridphase_v2"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DATA_FAMILY_ROOT = DATA_ROOT / "families/F2"
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
DIRECT_CONVERTER = INTEGRATION_LAB / "scripts/ds_data02_direct_convert.py"
LEGACY_CONVERTER = INTEGRATION_LAB / "scripts/ds_data02_convert.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
# ``PartVTKOut`` is the exclusion-file reader and rejects the ``-threads``
# argument used by the reviewed streaming converter.  The ordinary native
# frame validator is the sibling official ``PartVTK`` binary; both binaries
# are hash-identical in v5.4, but their executable names select different
# command-line modes.
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
POSE_IMPORT = LEGACY_CONVERTER
POSTSOLVER_QUALITY = FAMILY_ROOT / "quality_contract.json"
EVENT_DEFINITIONS = FAMILY_ROOT / "event_definitions.json"
SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"
MASS_SIDECAR = HANDOFF / "audits/mass-semantics-correction-20261002.json"

SOURCE_METADATA = {
    "center_catch": INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/production/definitions/F2_CENTER_P01.metadata.json",
    "offset_spill": INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/production/definitions/F2_OFFSET_P01.metadata.json",
}


class PostsolverError(RuntimeError):
    """Raised when a post-solver input is not evidence-bound."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise PostsolverError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PostsolverError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise PostsolverError(f"{label} must be an object: {path}")
    return value


def require_file(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise PostsolverError(f"{label} is missing: {path}")
    return path


def bindings(paths: Iterable[Path]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for raw in paths:
        path = require_file(Path(raw), "request input")
        result[str(path)] = {"path": str(path), "sha256": sha256(path)}
    return result


def _parameter_map(generated_xml: Path) -> dict[str, Any]:
    root = ET.parse(generated_xml).getroot()
    return {
        str(node.get("key")): node.get("value")
        for node in root.findall(".//execution/parameters/parameter")
        if node.get("key")
    }


def _motion_axis(generated_xml: Path) -> dict[str, list[float]]:
    root = ET.parse(generated_xml).getroot()
    rotation = root.find(".//execution/motion/objreal/mvrotfile") or root.find(".//mvrotfile")
    if rotation is None:
        raise PostsolverError(f"generated XML has no mvrotfile: {generated_xml}")
    p1 = rotation.find("./axisp1")
    p2 = rotation.find("./axisp2")
    if p1 is None or p2 is None:
        raise PostsolverError(f"generated XML mvrotfile has no complete axis: {generated_xml}")
    try:
        first = [float(p1.attrib[name]) for name in ("x", "y", "z")]
        second = [float(p2.attrib[name]) for name in ("x", "y", "z")]
    except (KeyError, ValueError) as error:
        raise PostsolverError(f"invalid moving axis in {generated_xml}") from error
    vector = [b - a for a, b in zip(first, second)]
    norm = sum(item * item for item in vector) ** 0.5
    if norm <= 0:
        raise PostsolverError(f"moving axis has zero length in {generated_xml}")
    return {"origin_m": first, "unit": [item / norm for item in vector]}


def _owner_geometry(source: Mapping[str, Any], v2: Mapping[str, Any]) -> dict[str, Any]:
    source_geometry = dict(source["geometry"])
    v2_geometry = v2["geometry"]
    source_geometry.update({
        "fluid_low_m": list(v2_geometry["continuous_fluid_low_m"]),
        "fluid_size_m": list(v2_geometry["continuous_fluid_size_m"]),
        "fluid_height_m": float(v2_geometry["continuous_fluid_size_m"][2]),
        "fluid_volume_m3": float(v2_geometry["continuous_fluid_volume_m3"]),
        "continuous_fluid_low_m": list(v2_geometry["continuous_fluid_low_m"]),
        "continuous_fluid_size_m": list(v2_geometry["continuous_fluid_size_m"]),
        "continuous_fluid_volume_m3": float(v2_geometry["continuous_fluid_volume_m3"]),
        "fluid_source_axis": str(v2_geometry["fluid_source_axis"]),
        "source_band_bounds_y_m": [list(item) for item in v2_geometry["source_band_bounds_y_m"]],
        "source_band_width_m": float(v2_geometry["source_band_width_m"]),
        "source_band_count": int(v2_geometry["source_band_count"]),
        "grid_origin_m": list(v2_geometry["numerical_grid_origin_m"]),
        "grid_origin_semantics": str(v2_geometry["grid_origin_semantics"]),
        "cell_center_rule": str(v2_geometry["cell_center_rule"]),
    })
    return source_geometry


def _physical_binding(*, v2: Mapping[str, Any], source: Mapping[str, Any], axis: Mapping[str, Any]) -> dict[str, Any]:
    g = source["geometry"]
    v2g = v2["geometry"]
    fluid_low = list(v2g["continuous_fluid_low_m"])
    fluid_size = list(v2g["continuous_fluid_size_m"])
    band = float(v2g["source_band_width_m"])
    band_low = float(fluid_low[1])
    source_regions = [
        {"low_m": [fluid_low[0], band_low + index * band, fluid_low[2]],
         "size_m": [fluid_size[0], band, fluid_size[2]], "label": f"source_layer_{index}"}
        for index in range(3)
    ]
    region = lambda name: {  # noqa: E731
        "low_m": list(g[f"{name}_low_m"]),
        "size_m": list(g[f"{name}_size_m"]),
        "label": name,
    }
    initial_mass = float(v2g["continuous_fluid_volume_m3"]) * 1000.0
    per_source = initial_mass / 3.0
    return {
        "schema": "ds-data-02.physical-binding.v1",
        "family_id": FAMILY,
        "physical_case_id": str(v2["physical_case_id"]),
        "mechanism_id": str(v2["background"]),
        "geometry_family_id": f"F2_GEOM_GEM_CUP_RECEIVER_{str(v2['background']).upper()}_V2",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_GEM_V2",
        "geometry": {
            "fluid": {"low_m": fluid_low, "size_m": fluid_size, "mkfluid": 0, "label": "continuous three-band liquid domain"},
            "cup": region("cup"), "receiver": region("receiver"), "tray": region("tray"),
        },
        "initial_state": {
            "source_regions": source_regions,
            "velocities_m_per_s": [[0.0, 0.0, 0.0]],
            "source_labels": [f"source_layer_{index}" for index in range(3)],
            "initial_mass_by_source_kg": [per_source] * 3,
            "continuum_mass_by_source_kg": [per_source] * 3,
            "initial_mass_total_kg": initial_mass,
            "mass_policy": "native BI4 header MassFluid is authoritative; continuous mass is an independent frozen reference",
        },
        "controls": {
            "step_algorithm": 2, "kernel": 2, "viscosity": 0.03,
            "density_dt": 3, "density_dt_value": 0.1,
            "boundary": "finite DBC rotating cup, fixed receiver, and finite catch tray; world top open",
        },
        "gravity_m_s2": [0.0, 0.0, -9.81],
        "density_kg_m3": 1000.0,
        "parameters": {
            "drive_mechanism": str(v2["background"]),
            "rotation_amplitude_deg": -105.0,
            "rotation_start_s": 0.5,
            "rotation_duration_s": 0.65,
            "rotation_end_s": 1.15,
            "cup_width_m": float(g["cup_width_m"]),
            "receiver_x_m": float(g["receiver_x_m"]),
            "receiver_y_m": float(g["receiver_y_m"]),
            "open_top": True,
            "motion_axis_origin_m": list(axis["origin_m"]),
            "motion_axis_unit": list(axis["unit"]),
        },
        "event_window": {
            "time_start_s": 0.0,
            "time_end_s": 4.0,
            "sequence": ["static_hold", "prescribed_rotation", "receiver_or_tray_transport", "post_stop_residence"],
            "expected_first_contact_range_s": [0.0, 4.0],
            "right_censor_policy": "saved 4 s window retains initial typed fluid denominator and keeps numerical unknown separate",
        },
        "lineage_group_id": f"F2_GEM_{str(v2['background']).upper()}_V2",
        "paired_background_id": "F2H10V2_OFFSET_V1" if v2["background"] == "center_catch" else "F2H10V2_CENTER_V1",
    }


def build_owner(*, v2_metadata: Path, generated_xml: Path, source_metadata: Path, output: Path) -> dict[str, Any]:
    v2 = load_json(v2_metadata, "V2 metadata")
    source = load_json(source_metadata, "source geometry metadata")
    generated_xml = require_file(generated_xml, "generated XML")
    motion_node = ET.parse(generated_xml).getroot().find(".//execution/motion/objreal/mvrotfile/file")
    if motion_node is None:
        motion_node = ET.parse(generated_xml).getroot().find(".//mvrotfile/file")
    if motion_node is None or not motion_node.get("name"):
        raise PostsolverError("generated XML has no declared motion control")
    motion = require_file(generated_xml.parent / motion_node.get("name"), "copied generated motion")
    axis = _motion_axis(generated_xml)
    geometry = _owner_geometry(source, v2)
    physical = _physical_binding(v2=v2, source=source, axis=axis)
    params = _parameter_map(generated_xml)
    owner = {
        "schema": "ds-data-02.f2.gem-handoff-20261002.generator.v1",
        "family_id": FAMILY,
        "scope_id": SCOPE,
        "case_id": str(v2["case_id"]),
        "physical_case_id": str(v2["physical_case_id"]),
        "mechanism_id": str(v2["background"]),
        "background": str(v2["background"]),
        "geometry_family_id": physical["geometry_family_id"],
        "control_family_id": physical["control_family_id"],
        "recipe_id": "F2_GEM_COMMENSURATE_ROTATING_CUP_V2",
        "lineage_group_id": physical["lineage_group_id"],
        "paired_background_id": physical["paired_background_id"],
        "resolution": str(v2["resolution"]),
        "dp_m": float(v2["dp_m"]),
        "solver_dimension": 3,
        "split": "reference",
        "target_role": "reference",
        "registry_role": "new_scope_new_physical_mother_outside_original_F2_48_registry",
        "definition": {"path": str(generated_xml.resolve()), "sha256": sha256(generated_xml)},
        "motion": {"path": str(motion.resolve()), "sha256": sha256(motion)},
        "source_definition": dict(v2["source_binding"]["frozen_definition"]),
        "source_motion": dict(v2["source_binding"]["frozen_motion"]),
        "source_geometry_metadata": {"path": str(source_metadata.resolve()), "sha256": sha256(source_metadata)},
        "geometry": geometry,
        "parameters": dict(source.get("parameter_values", {}), continuous_fluid_volume_m3=float(v2["geometry"]["continuous_fluid_volume_m3"]),
                            continuous_fluid_mass_kg=float(v2["geometry"]["continuous_fluid_volume_m3"]) * 1000.0),
        "event_window": dict(source["event_window"]),
        "solver_parameters": params,
        "quality_contract": source["quality_contract"],
        "source_mother": {
            "kind": "frozen_gem_source",
            "formal_reuse": False,
            "source_definition": dict(v2["source_binding"]["frozen_definition"]),
            "source_motion": dict(v2["source_binding"]["frozen_motion"]),
            "historical_asset_reuse": "none; W06 remains diagnostic only",
            "actual_solver_evidence_required": True,
        },
        "physical_binding": physical,
        "physical_condition_hash_declared": str(v2["physical_geometry_control_hash"]),
        "numerical_recipe_hash_declared": str(v2["numerical_recipe_hash"]),
        "mass_reference": {
            "continuous_volume_m3": float(v2["geometry"]["continuous_fluid_volume_m3"]),
            "continuous_mass_kg": float(v2["geometry"]["continuous_fluid_volume_m3"]) * 1000.0,
            "frozen_relative_budget_fraction": float(v2["mass_error_budget_fraction"]),
            "native_header_is_authority": True,
            "partvtk_csv_display_rounding_is_not_authority": True,
        },
        "qualification_claim": "none",
        "production_claim": "none",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    owner["physical_binding_sha256"] = canonical_hash(physical)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise PostsolverError(f"refusing to overwrite owner metadata: {output}")
    output.write_text(json.dumps(owner, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return owner


def _solver_paths(solver_receipt: Path) -> tuple[dict[str, Any], Path]:
    receipt = load_json(solver_receipt, "solver receipt")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise PostsolverError("solver receipt must be terminal completed with returncode=0")
    root = require_file(Path(str(receipt.get("output_root", ""))) / "solver_output/Run.out", "solver Run.out").parent
    for name in ("Run.csv", "RunPARTs.csv"):
        require_file(root / name, f"solver {name}")
    if not list((root / "data").glob("Part_[0-9][0-9][0-9][0-9].bi4")):
        raise PostsolverError(f"solver output has no native Part_*.bi4 frames: {root / 'data'}")
    return receipt, root


def _gencase_prefix(gencase_receipt: Path, generated_xml: Path) -> tuple[dict[str, Any], Path]:
    receipt = load_json(gencase_receipt, "GenCase receipt")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise PostsolverError("GenCase receipt must be terminal completed with returncode=0")
    prefix = generated_xml.with_suffix("").resolve()
    for suffix in (".xml", ".bi4"):
        require_file(Path(str(prefix) + suffix), f"GenCase prefix artifact {suffix}")
    return receipt, prefix


def _request_common(*, case_id: str, attempt_id: str, command: list[str], input_files: list[Path], output: Path,
                    task: str, estimate: int, physical_hash: str, numerical_hash: str, note: str) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.runner.request.v1", "family_id": FAMILY, "case_id": case_id,
        "attempt_id": attempt_id, "kind": "cpu", "cpu_task_kind": task,
        "command": command, "cwd": str(LAB_ROOT), "max_wall_seconds": 600,
        "cpu_threads": 4, "estimated_storage_bytes": estimate,
        "input_files": [str(path.resolve()) for path in input_files],
        "worktree_root": str(LAB_ROOT.parent), "raw_output_root": str(DATA_FAMILY_ROOT),
        "physical_condition_hash": physical_hash, "numerical_recipe_hash": numerical_hash,
        "event_window_s": 4.0, "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "request_note": note, "expected_outputs": {"receipt": str(output / "execution-receipt.json")},
        "source_bindings": bindings(input_files),
    }


def materialize_conversion(*, solver_receipt: Path, gencase_receipt: Path, generated_xml: Path, owner_metadata: Path,
                           request_path: Path, attempt_id: str | None = None) -> dict[str, Any]:
    solver, solver_output = _solver_paths(solver_receipt)
    gencase, prefix = _gencase_prefix(gencase_receipt, generated_xml)
    owner = load_json(owner_metadata, "owner metadata")
    case_id = str(owner["case_id"])
    if str(solver.get("request", {}).get("case_id", case_id)) != case_id:
        raise PostsolverError("owner case_id differs from solver receipt case_id")
    generated_xml = require_file(generated_xml, "generated XML")
    motion = require_file(generated_xml.parent / ET.parse(generated_xml).getroot().find(".//mvrotfile/file").get("name"), "copied motion")
    attempt_id = attempt_id or f"conversion-{case_id.lower()}-fullstate-pose-v1"
    output = DATA_FAMILY_ROOT / case_id / attempt_id
    command = [
        str(LAB_ROOT / ".venv/bin/python"), str(Path(__file__).resolve()), "convert",
        "--data-root", str(solver_output / "data"), "--generated-xml", str(generated_xml),
        "--solver-log", str(solver_output / "Run.out"), "--solver-receipt", str(solver_receipt.resolve()),
        "--gencase-receipt", str(gencase_receipt.resolve()), "--owner-metadata", str(owner_metadata.resolve()),
        "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json",
        "--pose-report", "{attempt_root}/rigid-body-state.json", "--validation-dir", "{attempt_root}/partvtk-validation",
    ]
    input_files = [
        Path(__file__), DIRECT_CONVERTER, LEGACY_CONVERTER, DECODER, PARTVTK, owner_metadata,
        generated_xml, motion, solver_receipt, gencase_receipt,
        solver_output / "Run.out", solver_output / "Run.csv", solver_output / "RunPARTs.csv",
        prefix.with_suffix(".bi4"),
        V2_ROOT / "manifest.json", V2_ROOT / "definitions" / case_id / f"{case_id}.metadata.json",
        POSTSOLVER_QUALITY, EVENT_DEFINITIONS, SAVE_PLAN, MASS_SIDECAR,
    ]
    request = _request_common(
        case_id=case_id, attempt_id=attempt_id, command=command, input_files=input_files, output=output,
        task="conversion", estimate=8 * 1024**3,
        physical_hash=str(owner.get("physical_condition_hash_declared", owner.get("physical_binding_sha256", ""))),
        numerical_hash=str(owner.get("numerical_recipe_hash_declared", "")),
        note="CPU-only full typed BI4 stream conversion with official PartVTK first/middle/last validation and actual saved moving-node pose augmentation; no solver/GPU/Q-I/Q-N claim.",
    )
    request.update({
        "solver_receipt": {"path": str(solver_receipt.resolve()), "sha256": sha256(solver_receipt)},
        "gencase_receipt": {"path": str(gencase_receipt.resolve()), "sha256": sha256(gencase_receipt)},
        "generated_xml": {"path": str(generated_xml), "sha256": sha256(generated_xml)},
        "gencase_prefix": str(prefix),
        "expected_outputs": {
            "receipt": str(output / "execution-receipt.json"),
            "trajectory": str(output / "trajectory.h5"),
            "conversion_report": str(output / "conversion-report.json"),
            "rigid_body_state_report": str(output / "rigid-body-state.json"),
        },
    })
    request_path = request_path.resolve()
    request_path.parent.mkdir(parents=True, exist_ok=True)
    if request_path.exists():
        raise PostsolverError(f"refusing to overwrite conversion request: {request_path}")
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def _load_legacy_converter():
    spec = importlib.util.spec_from_file_location("ds_data02_convert_f2_pose", LEGACY_CONVERTER)
    if spec is None or spec.loader is None:
        raise PostsolverError(f"cannot import reviewed pose helper: {LEGACY_CONVERTER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_times_from_h5(path: Path) -> list[float]:
    import h5py  # local import keeps materialization dependency-free
    with h5py.File(path, "r") as handle:
        return [float(value) for value in handle["time"][:]]


def _case_nmoving(run_out: Path) -> int:
    match = re.search(r"CaseNmoving\s*=\s*([0-9,]+)", run_out.read_text(errors="replace"), re.I)
    if not match:
        raise PostsolverError(f"Run.out has no CaseNmoving: {run_out}")
    return int(match.group(1).replace(",", ""))


def convert(*, data_root: Path, generated_xml: Path, solver_log: Path, solver_receipt: Path,
            gencase_receipt: Path, owner_metadata: Path, output: Path, report: Path,
            pose_report: Path, validation_dir: Path) -> dict[str, Any]:
    """Run direct conversion once, then add a strictly actual rigid pose."""
    for path, label in ((data_root, "solver BI4 data root"), (generated_xml, "generated XML"),
                        (solver_log, "Run.out"), (solver_receipt, "solver receipt"),
                        (gencase_receipt, "GenCase receipt"), (owner_metadata, "owner metadata")):
        if not Path(path).exists():
            raise PostsolverError(f"{label} is missing: {path}")
    output = output.resolve(); report = report.resolve(); pose_report = pose_report.resolve(); validation_dir = validation_dir.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    direct_command = [
        sys.executable, str(DIRECT_CONVERTER), "--data-root", str(data_root.resolve()),
        "--generated-xml", str(generated_xml.resolve()), "--output", str(output), "--report", str(report),
        "--solver-log", str(solver_log.resolve()), "--solver-receipt", str(solver_receipt.resolve()),
        "--gencase-receipt", str(gencase_receipt.resolve()), "--owner-metadata", str(owner_metadata.resolve()),
        "--decoder", str(DECODER), "--partvtk", str(PARTVTK), "--validation-dir", str(validation_dir),
        "--keep-validation-csv",
    ]
    completed = subprocess.run(direct_command, cwd=INTEGRATION_LAB, check=False)
    if completed.returncode != 0:
        raise PostsolverError(f"direct BI4 conversion failed with returncode={completed.returncode}")
    require_file(output, "direct conversion HDF5")
    require_file(report, "direct conversion report")
    legacy = _load_legacy_converter()
    root = ET.parse(generated_xml).getroot()
    declared = root.find(".//execution/motion/objreal/mvrotfile/file") or root.find(".//mvrotfile/file")
    if declared is None or not declared.get("name"):
        raise PostsolverError("generated XML has no motion file for pose fitting")
    motion = require_file(generated_xml.parent / declared.get("name"), "copied motion control")
    motion_spec = legacy._parse_motion_control(motion, generated_xml)
    if motion_spec is None:
        raise PostsolverError("motion control is not a rotation; F2 pose requires actual rotation state")
    pose = legacy._write_rigid_body_state(
        output,
        {"motion_control_spec": motion_spec, "population": {"case_nmoving": _case_nmoving(solver_log)}},
        _run_times_from_h5(output),
    )
    if pose.get("status") != "pass":
        raise PostsolverError(f"actual moving-node pose was not complete: {pose}")
    pose_payload = {
        "schema": "ds-data-02.f2.actual-moving-pose.v1",
        "status": "actual_saved_moving_node_pose_complete",
        "case_id": load_json(owner_metadata, "owner metadata")["case_id"],
        "trajectory": {"path": str(output), "sha256": sha256(output)},
        "generated_xml": {"path": str(generated_xml.resolve()), "sha256": sha256(generated_xml)},
        "motion_control": {"path": str(motion), "sha256": sha256(motion)},
        "pose": pose,
        "q_i_claim": "evidence_only; no Q-I/Q-N/production decision",
    }
    pose_report.parent.mkdir(parents=True, exist_ok=True)
    pose_report.write_text(json.dumps(pose_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    conversion = load_json(report, "direct conversion report")
    conversion["rigid_body_state"] = pose
    conversion["rigid_body_state_report"] = {"path": str(pose_report), "sha256": sha256(pose_report)}
    conversion["output_sha256"] = sha256(output)
    conversion["conversion_claim"] = "streaming BI4 adapter plus actual saved moving-node pose; no Q-I/Q-N/production claim"
    report.write_text(json.dumps(conversion, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "completed", "trajectory": str(output), "report": str(report), "pose_report": str(pose_report), "pose": pose}


def materialize_labels(*, conversion_receipt: Path, owner_metadata: Path, request_path: Path) -> dict[str, Any]:
    receipt = load_json(conversion_receipt, "conversion receipt")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise PostsolverError("conversion receipt is not terminal completed")
    conversion_root = Path(str(receipt["output_root"])).resolve()
    trajectory = require_file(conversion_root / "trajectory.h5", "converted trajectory")
    conversion_report = require_file(conversion_root / "conversion-report.json", "conversion report")
    pose_report = require_file(conversion_root / "rigid-body-state.json", "pose report")
    owner = load_json(owner_metadata, "owner metadata")
    case_id = str(owner["case_id"])
    attempt_id = f"labels-{case_id.lower()}-native-events-v1"
    output = DATA_FAMILY_ROOT / case_id / attempt_id
    native_labels = INTEGRATION_LAB / "scripts/f2_native_observations.py"
    command = [str(LAB_ROOT / ".venv/bin/python"), str(native_labels), "--trajectory", str(trajectory),
               "--owner-metadata", str(owner_metadata.resolve()), "--conversion-report", str(conversion_report),
               "--output", "{attempt_root}/f2-native-labels.h5", "--report", "{attempt_root}/f2-native-observations.json"]
    input_files = [native_labels, INTEGRATION_LAB / "scripts/ds_data02_integrity.py", owner_metadata,
                   trajectory, conversion_report, pose_report, conversion_receipt, POSTSOLVER_QUALITY,
                   EVENT_DEFINITIONS, SAVE_PLAN, MASS_SIDECAR]
    request = _request_common(
        case_id=case_id, attempt_id=attempt_id, command=command, input_files=input_files, output=output,
        task="labels", estimate=2 * 1024**3,
        physical_hash=str(owner.get("physical_condition_hash_declared", "")), numerical_hash=str(owner.get("numerical_recipe_hash_declared", "")),
        note="CPU-only native F2 source-layer, moving-cup, receiver, tray, and residence observations from actual saved full state and actual rigid pose; unknown remains numerical/physical unresolved and Q-N is not assessed.",
    )
    request.update({"conversion_receipt": {"path": str(conversion_receipt.resolve()), "sha256": sha256(conversion_receipt)},
                    "conversion_report": {"path": str(conversion_report), "sha256": sha256(conversion_report)},
                    "pose_report": {"path": str(pose_report), "sha256": sha256(pose_report)},
                    "expected_outputs": {"receipt": str(output / "execution-receipt.json"), "labels": str(output / "f2-native-labels.h5"), "labels_report": str(output / "f2-native-observations.json")}})
    request_path = request_path.resolve(); request_path.parent.mkdir(parents=True, exist_ok=True)
    if request_path.exists():
        raise PostsolverError(f"refusing to overwrite labels request: {request_path}")
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def materialize_native_ledger(*, labels_receipt: Path, conversion_receipt: Path,
                              solver_receipt: Path, gencase_receipt: Path,
                              generated_xml: Path, owner_metadata: Path,
                              request_path: Path, attempt_id: str | None = None) -> dict[str, Any]:
    """Write a CPU request for the full native exclusion/lifecycle audit.

    The request is deliberately downstream of the completed labels and
    conversion receipts.  The ledger reads the solver's complete RunPARTs
    timeline and, when present, the actual PartOut artifact; it therefore
    cannot infer a zero exclusion count from a missing output path.
    """
    labels = load_json(labels_receipt, "labels receipt")
    if labels.get("schema") != "ds02.execution-receipt.v1" or labels.get("status") != "completed" or labels.get("returncode") != 0:
        raise PostsolverError("labels receipt is not terminal completed")
    conversion = load_json(conversion_receipt, "conversion receipt")
    if conversion.get("schema") != "ds02.execution-receipt.v1" or conversion.get("status") != "completed" or conversion.get("returncode") != 0:
        raise PostsolverError("conversion receipt is not terminal completed")
    solver, solver_output = _solver_paths(solver_receipt)
    gencase, prefix = _gencase_prefix(gencase_receipt, generated_xml)
    generated_xml = require_file(generated_xml, "generated XML")
    owner = load_json(owner_metadata, "owner metadata")
    case_id = str(owner["case_id"])
    if str(labels.get("request", {}).get("case_id", case_id)) != case_id:
        raise PostsolverError("labels receipt case_id differs from owner metadata")
    if str(conversion.get("request", {}).get("case_id", case_id)) != case_id:
        raise PostsolverError("conversion receipt case_id differs from owner metadata")
    labels_root = Path(str(labels["output_root"])).resolve()
    label_h5 = require_file(labels_root / "f2-native-labels.h5", "native labels HDF5")
    label_report = require_file(labels_root / "f2-native-observations.json", "native labels report")
    conversion_root = Path(str(conversion["output_root"])).resolve()
    trajectory = require_file(conversion_root / "trajectory.h5", "converted trajectory")
    conversion_report = require_file(conversion_root / "conversion-report.json", "conversion report")
    pose_report = require_file(conversion_root / "rigid-body-state.json", "pose report")
    motion_node = ET.parse(generated_xml).getroot().find(".//execution/motion/objreal/mvrotfile/file")
    if motion_node is None:
        motion_node = ET.parse(generated_xml).getroot().find(".//mvrotfile/file")
    if motion_node is None or not motion_node.get("name"):
        raise PostsolverError("generated XML has no copied motion control")
    motion = require_file(generated_xml.parent / motion_node.get("name"), "copied generated motion")
    attempt_id = attempt_id or f"native-ledger-{case_id.lower()}-v1"
    output = DATA_FAMILY_ROOT / case_id / attempt_id
    ledger_script = Path(__file__).resolve().with_name("f2_handoff_20261002_native_ledger.py")
    command = [
        str(LAB_ROOT / ".venv/bin/python"), str(ledger_script),
        "--trajectory", str(trajectory), "--labels", str(label_h5),
        "--owner-metadata", str(owner_metadata.resolve()), "--conversion-report", str(conversion_report),
        "--solver-output", str(solver_output), "--gencase-prefix", str(prefix),
        "--partvtkout", str(Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64")),
        "--output-dir", "{attempt_root}",
    ]
    input_files = [
        Path(__file__), ledger_script, owner_metadata, generated_xml, motion,
        prefix.with_suffix(".bi4"), prefix.with_suffix(".xml"),
        solver_receipt, gencase_receipt, labels_receipt, conversion_receipt,
        solver_output / "Run.out", solver_output / "Run.csv", solver_output / "RunPARTs.csv",
        trajectory, conversion_report, pose_report, label_h5, label_report,
        Path(command[command.index("--partvtkout") + 1]),
        V2_ROOT / "manifest.json", V2_ROOT / "definitions" / case_id / f"{case_id}.metadata.json",
        POSTSOLVER_QUALITY, EVENT_DEFINITIONS, SAVE_PLAN, MASS_SIDECAR,
    ]
    input_files.extend(sorted((solver_output / "data").glob("PartOut_*.obi4")))
    request = _request_common(
        case_id=case_id, attempt_id=attempt_id, command=command, input_files=input_files, output=output,
        task="audit", estimate=4 * 1024**3,
        physical_hash=str(owner.get("physical_condition_hash_declared", "")),
        numerical_hash=str(owner.get("numerical_recipe_hash_declared", "")),
        note="CPU-only full-timeline native exclusion/lifecycle audit; RunPARTs counters are summed over every save interval and PartVTKOut records are typed by Zone/Idp. Physical spill remains a separate label and no Q-I/Q-N/production claim is made.",
    )
    request.update({
        "solver_receipt": {"path": str(solver_receipt.resolve()), "sha256": sha256(solver_receipt)},
        "gencase_receipt": {"path": str(gencase_receipt.resolve()), "sha256": sha256(gencase_receipt)},
        "labels_receipt": {"path": str(labels_receipt.resolve()), "sha256": sha256(labels_receipt)},
        "conversion_receipt": {"path": str(conversion_receipt.resolve()), "sha256": sha256(conversion_receipt)},
        "generated_xml": {"path": str(generated_xml), "sha256": sha256(generated_xml)},
        "gencase_prefix": str(prefix),
        "labels_report": {"path": str(label_report), "sha256": sha256(label_report)},
        "expected_outputs": {"receipt": str(output / "execution-receipt.json"),
                             "native_ledger": str(output / "native-exclusion-ledger.json")},
    })
    request_path = request_path.resolve(); request_path.parent.mkdir(parents=True, exist_ok=True)
    if request_path.exists():
        raise PostsolverError(f"refusing to overwrite native ledger request: {request_path}")
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    owner = sub.add_parser("materialize-owner")
    owner.add_argument("--v2-metadata", type=Path, required=True)
    owner.add_argument("--generated-xml", type=Path, required=True)
    owner.add_argument("--source-metadata", type=Path, required=True)
    owner.add_argument("--output", type=Path, required=True)
    conversion = sub.add_parser("materialize-conversion")
    conversion.add_argument("--solver-receipt", type=Path, required=True)
    conversion.add_argument("--gencase-receipt", type=Path, required=True)
    conversion.add_argument("--generated-xml", type=Path, required=True)
    conversion.add_argument("--owner-metadata", type=Path, required=True)
    conversion.add_argument("--request", type=Path, required=True)
    conversion.add_argument("--attempt-id")
    labels = sub.add_parser("materialize-labels")
    labels.add_argument("--conversion-receipt", type=Path, required=True)
    labels.add_argument("--owner-metadata", type=Path, required=True)
    labels.add_argument("--request", type=Path, required=True)
    ledger = sub.add_parser("materialize-ledger")
    ledger.add_argument("--labels-receipt", type=Path, required=True)
    ledger.add_argument("--conversion-receipt", type=Path, required=True)
    ledger.add_argument("--solver-receipt", type=Path, required=True)
    ledger.add_argument("--gencase-receipt", type=Path, required=True)
    ledger.add_argument("--generated-xml", type=Path, required=True)
    ledger.add_argument("--owner-metadata", type=Path, required=True)
    ledger.add_argument("--request", type=Path, required=True)
    ledger.add_argument("--attempt-id")
    run = sub.add_parser("convert")
    for name in ("data-root", "generated-xml", "solver-log", "solver-receipt", "gencase-receipt", "owner-metadata", "output", "report", "pose-report", "validation-dir"):
        run.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "materialize-owner":
            build_owner(v2_metadata=args.v2_metadata, generated_xml=args.generated_xml,
                        source_metadata=args.source_metadata, output=args.output)
            print(json.dumps({"status": "owner_ready", "path": str(args.output.resolve()), "sha256": sha256(args.output.resolve())}, indent=2))
        elif args.action == "materialize-conversion":
            result = materialize_conversion(solver_receipt=args.solver_receipt, gencase_receipt=args.gencase_receipt,
                                            generated_xml=args.generated_xml, owner_metadata=args.owner_metadata,
                                            request_path=args.request, attempt_id=args.attempt_id)
            print(json.dumps({"status": "request_ready", "path": str(args.request.resolve()), "sha256": sha256(args.request.resolve()), "case_id": result["case_id"]}, indent=2))
        elif args.action == "materialize-labels":
            result = materialize_labels(conversion_receipt=args.conversion_receipt, owner_metadata=args.owner_metadata, request_path=args.request)
            print(json.dumps({"status": "request_ready", "path": str(args.request.resolve()), "sha256": sha256(args.request.resolve()), "case_id": result["case_id"]}, indent=2))
        elif args.action == "materialize-ledger":
            result = materialize_native_ledger(labels_receipt=args.labels_receipt, conversion_receipt=args.conversion_receipt,
                                               solver_receipt=args.solver_receipt, gencase_receipt=args.gencase_receipt,
                                               generated_xml=args.generated_xml, owner_metadata=args.owner_metadata,
                                               request_path=args.request, attempt_id=args.attempt_id)
            print(json.dumps({"status": "request_ready", "path": str(args.request.resolve()), "sha256": sha256(args.request.resolve()), "case_id": result["case_id"]}, indent=2))
        else:
            print(json.dumps(convert(data_root=args.data_root, generated_xml=args.generated_xml, solver_log=args.solver_log,
                                     solver_receipt=args.solver_receipt, gencase_receipt=args.gencase_receipt,
                                     owner_metadata=args.owner_metadata, output=args.output, report=args.report,
                                     pose_report=args.pose_report, validation_dir=args.validation_dir), indent=2))
    except (PostsolverError, OSError, ValueError, KeyError, ET.ParseError, subprocess.SubprocessError) as error:
        print(f"f2_handoff_20261002_postsolver: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
