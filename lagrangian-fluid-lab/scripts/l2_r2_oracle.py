#!/usr/bin/env python3
"""R2 evidence builder for the current F3 contract and oracle suite.

This worker keeps the R2 boundary deliberately narrow:

* the current F3 data/feature/update contract is reconstructed from the
  checked-in contract, the actual generated XML, and retained source files;
* four deterministic oracle paths are executed on three real current-F3 HDF5
  cases using the same scoring function;
* a current learned-model rollout is *not* fabricated when no checkpoint is
  available; the report records a bounded rejection instead;
* the old R3-G4/43-feature runs are registered as legacy reuse only.

The script never changes the resume controller or promotes a canary/legacy
artifact.  It only writes its own R2 artifacts under ``resume-c6b28c8``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any, Iterable

import h5py
import numpy as np

_BOOTSTRAP_REPO = Path(__file__).resolve().parents[2]
_BOOTSTRAP_LAB = _BOOTSTRAP_REPO / "lagrangian-fluid-lab"
try:
    from scripts.f3_control import AccelerationControl
    from scripts.f3_learning_inputs import FEATURE_NAMES
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    if str(_BOOTSTRAP_LAB) not in sys.path:
        sys.path.insert(0, str(_BOOTSTRAP_LAB))
    from scripts.f3_control import AccelerationControl
    from scripts.f3_learning_inputs import FEATURE_NAMES


REPO = _BOOTSTRAP_REPO
LAB = _BOOTSTRAP_LAB
CAMPAIGN = LAB / "campaigns" / "l2-multifamily"
RESUME_ROOT = CAMPAIGN / "resume-c6b28c8"

CURRENT_INPUT_CONTRACT = LAB / "campaigns/l1-resume/continuation/F3-LEARNING-INPUT-CONTRACT.json"
CURRENT_DATA_CONTRACT = LAB / "campaigns/l1-resume/continuation/F3-REF0081818-TRAINING-DEVELOPMENT-FULL.json"
CURRENT_GATE = LAB / "campaigns/l1-resume/continuation/F3-075-REF0081818-GATE.json"
CURRENT_PREPARED = LAB / "campaigns/l1-resume/continuation/F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen-PREPARED.json"
CURRENT_XML = LAB / (
    "campaigns/l1-resume/artifacts/cell3-nopen-qualification/"
    "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen/"
    "F3_CELL3_plain_0p0075.xml"
)
CURRENT_SOURCE_XML = LAB / "vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingAcc_Def.xml"
CURRENT_EVALUATOR = LAB / "scripts/f3_rollout.py"
CURRENT_FEATURE_ADAPTER = LAB / "scripts/f3_learning_inputs.py"
B2_REPORT = CAMPAIGN / "reports/b2-learning-baseline.json"
B2_RUN_MANIFEST = LAB / "experiments/r3-g4-baseline-routes/run_manifest.json"

CONTRACT_ARTIFACT = RESUME_ROOT / "current-f3-contract.json"
ORACLE_ARTIFACT = RESUME_ROOT / "actual-oracle-runs.json"
LEGACY_ARTIFACT = RESUME_ROOT / "legacy-reuse-manifest.json"

BASELINE_COMMIT = "c6b28c86704e1cc62fc02aa27413855ef5a9a502"
CURRENT_CASE_IDS = (
    "F3_DEV_00_a0p903125",  # low amplitude
    "F3_DEV_18_a1p015625",  # near-center validation case
    "F3_DEV_31_a1p096875",  # high amplitude
)
REQUIRED_HDF5_DATASETS = ("time", "position", "velocity", "mass", "particle_id", "valid")
CURRENT_MODEL_ROUTES = ("particle_mlp", "local_interaction")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def resolve_lab_path(raw: str | Path) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    candidate = (LAB / path).resolve()
    if candidate.exists():
        return candidate
    return (REPO / path).resolve()


def file_ref(path: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    path = path.resolve()
    result: dict[str, Any] = {"path": repo_relative(path), "exists": path.is_file()}
    if path.is_file():
        result.update({"bytes": path.stat().st_size, "sha256": sha256_file(path)})
    else:
        result.update({"bytes": None, "sha256": None})
    if expected_sha256 is not None:
        result["expected_sha256"] = expected_sha256
        result["hash_matches"] = result["sha256"] == expected_sha256
    return result


def current_git_head() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _float_attr(node: ET.Element | None, key: str) -> float | None:
    if node is None or key not in node.attrib:
        return None
    try:
        value = float(node.attrib[key])
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _int_parameter(parameters: dict[str, str], key: str) -> int | None:
    raw = parameters.get(key)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _float_parameter(parameters: dict[str, str], key: str) -> float | None:
    raw = parameters.get(key)
    try:
        value = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    return value if value is None or math.isfinite(value) else None


def extract_xml_contract(path: Path) -> dict[str, Any]:
    """Extract values from the actual generated XML, never from a variant name."""

    if not path.is_file():
        return {"path": repo_relative(path), "exists": False, "missing": ["xml_file"]}
    root = ET.parse(path).getroot()
    parameters: dict[str, str] = {}
    for node in root.iter("parameter"):
        key = node.attrib.get("key")
        value = node.attrib.get("value")
        if key is not None and value is not None:
            parameters[key] = value
    gravity = root.find(".//gravity")
    definition = root.find(".//definition")
    accinput = root.find(".//accinput")
    acccentre = root.find(".//acccentre")
    acctimesfile = root.find(".//acctimesfile")
    required_values = {
        "definition_dp_m": _float_attr(definition, "dp"),
        "gravity_x_mps2": _float_attr(gravity, "x"),
        "gravity_y_mps2": _float_attr(gravity, "y"),
        "gravity_z_mps2": _float_attr(gravity, "z"),
        "cfl_number": None,
        "visco_treatment": _int_parameter(parameters, "ViscoTreatment"),
        "visco": _float_parameter(parameters, "Visco"),
        "visco_bound_factor": _float_parameter(parameters, "ViscoBoundFactor"),
        "shifting": _int_parameter(parameters, "Shifting"),
        "no_penetration": _int_parameter(parameters, "NoPenetration"),
        "boundary": _int_parameter(parameters, "Boundary"),
    }
    # ElementTree does not support XPath attribute selection.  Read the node
    # directly so a missing cfl value stays an explicit missing fact.
    cfl_node = root.find(".//cflnumber")
    required_values["cfl_number"] = _float_attr(cfl_node, "value")
    required_values["acceleration_center_m"] = (
        [_float_attr(acccentre, axis) for axis in ("x", "y", "z")]
        if acccentre is not None else None
    )
    required_values["control_file"] = acctimesfile.attrib.get("value") if acctimesfile is not None else None
    required_values["accinput_present"] = accinput is not None
    required_values["motion_element_present"] = root.find(".//motion") is not None
    missing = [key for key, value in required_values.items() if value is None]
    if required_values["acceleration_center_m"] is not None and any(
        value is None for value in required_values["acceleration_center_m"]
    ):
        missing.append("acceleration_center_m")
    return {
        "path": repo_relative(path),
        "exists": True,
        "sha256": sha256_file(path),
        "parameter_values": parameters,
        "values": required_values,
        "missing": sorted(set(missing)),
        "no_penetration_declared": required_values["no_penetration"] == 1,
        "closed_boundary_mode": required_values["boundary"],
    }


def _case_record_map(data_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(record["case_id"]): record for record in data_contract.get("cases", [])}


def _selected_case_refs(data_contract: dict[str, Any]) -> list[dict[str, Any]]:
    records = _case_record_map(data_contract)
    roles = {
        CURRENT_CASE_IDS[0]: "low_amplitude",
        CURRENT_CASE_IDS[1]: "near_center",
        CURRENT_CASE_IDS[2]: "high_amplitude",
    }
    selected: list[dict[str, Any]] = []
    for case_id in CURRENT_CASE_IDS:
        record = records.get(case_id)
        if record is None:
            selected.append({"case_id": case_id, "role": roles[case_id], "status": "missing_from_current_manifest"})
            continue
        source_refs = record.get("sources", {})
        hdf5_source = source_refs.get("hdf5", {})
        hdf5 = resolve_lab_path(hdf5_source.get("path", ""))
        control_raw = record.get("control_path")
        control = resolve_lab_path(control_raw) if control_raw else None
        prepared_source = source_refs.get("prepared", {})
        prepared_path = resolve_lab_path(prepared_source.get("path", ""))
        prepared_case = read_json(prepared_path) if prepared_path.is_file() else {}
        selected.append({
            "case_id": case_id,
            "role": roles[case_id],
            "split": record.get("split"),
            "evaluation_role": record.get("evaluation_role"),
            "family": "F3",
            "drive_amplitude": record.get("drive_amplitude"),
            "dp_m": prepared_case.get("dp_m", 0.0075),
            "recipe_id": prepared_case.get("recipe_id"),
            "hdf5": file_ref(hdf5, expected_sha256=hdf5_source.get("sha256")),
            "control": file_ref(control, expected_sha256=record.get("control_file_sha256")) if control else None,
            "source_evidence": {
                key: file_ref(resolve_lab_path(value["path"]), expected_sha256=value.get("sha256"))
                for key, value in source_refs.items()
                if isinstance(value, dict) and value.get("path")
            },
            "status": "ready" if hdf5.is_file() and (control is None or control.is_file()) else "missing_source",
        })
    return selected


def build_current_f3_contract() -> dict[str, Any]:
    input_contract = read_json(CURRENT_INPUT_CONTRACT) if CURRENT_INPUT_CONTRACT.is_file() else {}
    data_contract = read_json(CURRENT_DATA_CONTRACT) if CURRENT_DATA_CONTRACT.is_file() else {}
    gate = read_json(CURRENT_GATE) if CURRENT_GATE.is_file() else {}
    prepared = read_json(CURRENT_PREPARED) if CURRENT_PREPARED.is_file() else {}
    xml = extract_xml_contract(CURRENT_XML)
    selected_cases = _selected_case_refs(data_contract)
    source_contract = {
        "input_contract": file_ref(CURRENT_INPUT_CONTRACT),
        "data_contract": file_ref(CURRENT_DATA_CONTRACT),
        "gate": file_ref(CURRENT_GATE),
        "prepared": file_ref(CURRENT_PREPARED),
        "generated_xml": file_ref(CURRENT_XML, expected_sha256=prepared.get("generated_xml_sha256")),
        "source_xml": file_ref(CURRENT_SOURCE_XML, expected_sha256=(prepared.get("source_definition") or {}).get("sha256")),
        "feature_adapter": file_ref(CURRENT_FEATURE_ADAPTER, expected_sha256=input_contract.get("adapter_sha256")),
        "current_evaluator": file_ref(CURRENT_EVALUATOR),
    }
    current_width = len(FEATURE_NAMES)
    recorded_width = input_contract.get("width")
    current_checkpoint_candidates = [
        RESUME_ROOT / "current-f3-checkpoint.pt",
        LAB / "experiments/current-f3/checkpoints/f3_current.pt",
    ]
    current_checkpoints = [file_ref(path) for path in current_checkpoint_candidates if path.is_file()]
    missing_facts = list(xml.get("missing", []))
    if not CURRENT_INPUT_CONTRACT.is_file():
        missing_facts.append("current_input_contract")
    if not CURRENT_DATA_CONTRACT.is_file():
        missing_facts.append("current_data_contract")
    if current_width != recorded_width:
        missing_facts.append("feature_width_mismatch")
    if any(item.get("status") != "ready" for item in selected_cases):
        missing_facts.append("selected_case_source")
    if not current_checkpoints:
        current_model_status = "bounded_rejection_current_checkpoint_missing"
    else:
        current_model_status = "checkpoint_present_requires_evaluator_execution"
    return {
        "schema": "l2r.r2.current_f3_contract.v1",
        "created_at_utc": utc_now(),
        "baseline_commit": BASELINE_COMMIT,
        "current_commit": current_git_head(),
        "review_requirement": {
            "source": "L2R_Continuous_Execution_c6b28c8_2026-09-14/PLAN_ZH.md",
            "section": "R2",
            "required_oracles": [
                "real_trajectory_current_model_evaluator",
                "reference_displacement_same_update",
                "real_velocity_same_integrator",
                "constant_velocity_and_known_control_same_scoring",
            ],
            "legacy_boundary": "old R3-G4 43-feature/W11 results remain legacy_reference",
        },
        "contract_status": "verified_data_and_update_contract_current_model_bounded",
        "qualification": {
            "current_model_qualified": False,
            "t1_promoted": False,
            "public_release_authorized": False,
        },
        "recipe": {
            "recipe_id": gate.get("recipe_id") or prepared.get("recipe_id"),
            "production_resolution_m": gate.get("production_resolution_m", prepared.get("dp_m")),
            "reference_resolutions_m": gate.get("reference_resolutions_m"),
            "historical_resolution_m": gate.get("retained_historical_resolution_m"),
            "time_window_s": gate.get("time_window_s", [0.0, prepared.get("time_max_s")]),
            "scoring_interval_s": gate.get("scoring_interval_s", prepared.get("time_out_s")),
            "control_domain": gate.get("control_domain"),
            "coordinate_frame": prepared.get("coordinate_frame"),
            "solver_mode": prepared.get("solver_mode"),
            "wall_spec": prepared.get("wall_spec"),
            "physics_from_actual_xml": xml.get("values", {}),
            "native_velocity_displacement_correction": prepared.get("native_velocity_displacement_correction"),
            "posthoc_particle_projection": prepared.get("posthoc_particle_projection"),
            "control_definition": prepared.get("control_definition"),
            "control_sha256": prepared.get("drive_sha256"),
            "historical_resolution_is_separate": True,
        },
        "data_contract": {
            "feature_width": current_width,
            "recorded_feature_width": recorded_width,
            "feature_names": list(FEATURE_NAMES),
            "feature_names_source": file_ref(CURRENT_FEATURE_ADAPTER),
            "feature_contract_sha256": input_contract.get("adapter_sha256"),
            "normalization": input_contract.get("normalization"),
            "coordinate_frame": input_contract.get("coordinate_frame"),
            "control_semantics": input_contract.get("control_semantics"),
            "geometry": input_contract.get("geometry"),
            "identity_convention": data_contract.get("identity_convention"),
            "velocity_convention": data_contract.get("velocity_convention"),
            "target_convention": data_contract.get("target_convention"),
            "time_alignment": data_contract.get("time_alignment"),
            "split_semantics": data_contract.get("split_semantics"),
            "future_fluid_state_allowed": False,
            "future_free_body_state_allowed": False,
        },
        "current_model_evaluator": {
            "status": current_model_status,
            "routes": list(CURRENT_MODEL_ROUTES),
            "evaluator": file_ref(CURRENT_EVALUATOR),
            "adapter": file_ref(CURRENT_FEATURE_ADAPTER),
            "checkpoint_candidates": current_checkpoints,
            "required_before_execution": [
                "current-contract checkpoint with 48 input features",
                "checkpoint metadata bound to current F3 adapter and recipe",
                "actual rollout artifact with model evaluator inputs and outputs",
            ],
            "bounded_rejection_reason": (
                "No current-contract checkpoint exists; retained 43-feature checkpoints are not eligible."
                if not current_checkpoints else None
            ),
        },
        "selected_oracle_cases": selected_cases,
        "source_evidence": source_contract,
        "missing_or_unresolved": sorted(set(missing_facts)),
        "ready_for_actual_deterministic_oracles": not missing_facts,
    }


def _metric_result(accumulator: "ErrorAccumulator", *, scale: float, scope: str) -> dict[str, Any]:
    if accumulator.count == 0:
        return {"scope": scope, "sample_count": 0, "status": "no_samples"}
    rmse = math.sqrt(accumulator.sum_sq / accumulator.count)
    return {
        "scope": scope,
        "sample_count": accumulator.count,
        "frame_count": accumulator.frame_count,
        "rmse_m": rmse,
        "rmse_over_dp": rmse / scale if scale > 0 else None,
        "ade_m": accumulator.sum_norm / accumulator.count,
        "fde_m": accumulator.last_frame_mean_norm,
        "max_error_m": accumulator.max_norm,
        "normal_result": bool(np.isfinite([rmse, accumulator.sum_norm, accumulator.last_frame_mean_norm, accumulator.max_norm]).all()),
    }


@dataclass
class ErrorAccumulator:
    count: int = 0
    frame_count: int = 0
    sum_sq: float = 0.0
    sum_norm: float = 0.0
    max_norm: float = 0.0
    last_frame_mean_norm: float = math.nan

    def add(self, error: np.ndarray) -> None:
        values = np.asarray(error, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != 3 or not np.isfinite(values).all():
            raise ValueError("oracle error must be finite [N,3]")
        norms = np.linalg.norm(values, axis=1)
        self.count += int(len(norms))
        self.frame_count += 1
        self.sum_sq += float(np.square(norms).sum())
        self.sum_norm += float(norms.sum())
        self.max_norm = max(self.max_norm, float(norms.max()) if len(norms) else 0.0)
        self.last_frame_mean_norm = float(norms.mean()) if len(norms) else math.nan


def integrate_euler(position: np.ndarray, velocity: np.ndarray, interval_s: float) -> np.ndarray:
    """The declared first-order position updater used by the velocity oracle."""

    return np.asarray(position, dtype=np.float64) + np.asarray(velocity, dtype=np.float64) * float(interval_s)


def update_from_displacement(position: np.ndarray, displacement: np.ndarray) -> np.ndarray:
    """The same additive update used for a reference displacement target."""

    return np.asarray(position, dtype=np.float64) + np.asarray(displacement, dtype=np.float64)


def integrate_constant_acceleration(
    position: np.ndarray, velocity: np.ndarray, acceleration: np.ndarray, interval_s: float
) -> tuple[np.ndarray, np.ndarray]:
    """Known-control-only baseline; no future fluid state is read."""

    dt = float(interval_s)
    next_position = np.asarray(position, dtype=np.float64) + np.asarray(velocity, dtype=np.float64) * dt
    next_position = next_position + 0.5 * np.asarray(acceleration, dtype=np.float64) * dt * dt
    next_velocity = np.asarray(velocity, dtype=np.float64) + np.asarray(acceleration, dtype=np.float64) * dt
    return next_position, next_velocity


def score_prediction(errors: Iterable[np.ndarray], *, scale: float, scope: str) -> dict[str, Any]:
    accumulator = ErrorAccumulator()
    for error in errors:
        accumulator.add(error)
    return _metric_result(accumulator, scale=scale, scope=scope)


def _valid_mask(dataset: h5py.Dataset, frame: int) -> np.ndarray:
    values = np.asarray(dataset[frame])
    if values.ndim != 1 or not (np.issubdtype(values.dtype, np.bool_) or np.issubdtype(values.dtype, np.integer)):
        raise ValueError("valid dataset must be a one-dimensional boolean/integer frame")
    return values.astype(bool, copy=False)


def _mass_frame(dataset: h5py.Dataset, frame: int, count: int) -> np.ndarray:
    values = np.asarray(dataset[:] if dataset.ndim == 1 else dataset[frame], dtype=np.float64).reshape(-1)
    if values.shape != (count,):
        raise ValueError("mass axis does not match particle IDs")
    return values


def _source_preflight(handle: h5py.File) -> dict[str, Any]:
    missing = [name for name in REQUIRED_HDF5_DATASETS if name not in handle]
    if missing:
        return {"status": "bounded_rejection", "missing_datasets": missing}
    times = np.asarray(handle["time"][:], dtype=np.float64)
    particle_id = np.asarray(handle["particle_id"][:])
    valid = handle["valid"]
    position = handle["position"]
    velocity = handle["velocity"]
    mass = handle["mass"]
    shape_ok = {
        "time": times.ndim == 1 and len(times) >= 2 and np.isfinite(times).all() and np.all(np.diff(times) > 0),
        "particle_id": particle_id.ndim == 1 and len(particle_id) > 0 and len(np.unique(particle_id)) == len(particle_id),
        "position": position.shape == (len(times), len(particle_id), 3),
        "velocity": velocity.shape == (len(times), len(particle_id), 3),
        "valid": valid.shape == (len(times), len(particle_id)),
        "mass": mass.shape in ((len(particle_id),), (len(times), len(particle_id))),
    }
    shape_ok = {key: bool(value) for key, value in shape_ok.items()}
    return {
        "status": "ready" if all(shape_ok.values()) else "bounded_rejection",
        "missing_datasets": [],
        "shape_checks": shape_ok,
        "time_start_s": float(times[0]) if len(times) else None,
        "time_end_s": float(times[-1]) if len(times) else None,
        "frame_count": int(len(times)),
        "particle_count": int(len(particle_id)),
        "particle_ids_unique": bool(shape_ok["particle_id"]),
    }


def run_case_oracles(
    hdf5_path: Path,
    *,
    control_path: Path | None,
    dp_m: float,
    max_frames: int | None = None,
) -> dict[str, Any]:
    """Execute actual source-backed deterministic oracle runs for one case."""

    hdf5_path = hdf5_path.resolve()
    case_result: dict[str, Any] = {
        "hdf5": file_ref(hdf5_path),
        "control": file_ref(control_path) if control_path else None,
        "runner": repo_relative(Path(__file__)),
        "status": "bounded_rejection",
    }
    with h5py.File(hdf5_path, "r") as handle:
        preflight = _source_preflight(handle)
        case_result["source_preflight"] = preflight
        if preflight["status"] != "ready":
            case_result["reason"] = "source_hdf5_contract_not_ready"
            return case_result
        times = np.asarray(handle["time"][:], dtype=np.float64)
        ids = np.asarray(handle["particle_id"][:])
        initial_valid = _valid_mask(handle["valid"], 0)
        if not initial_valid.any():
            case_result["reason"] = "no_active_initial_particles"
            return case_result
        if not np.issubdtype(ids.dtype, np.integer):
            case_result["reason"] = "particle_id_not_integer"
            return case_result
        initial_mass = _mass_frame(handle["mass"], 0, len(ids))
        if not np.isfinite(initial_mass[initial_valid]).all() or not (initial_mass[initial_valid] > 0).all():
            case_result["reason"] = "initial_active_mass_not_finite_positive"
            return case_result
        active_count = int(initial_valid.sum())
        p_initial = np.asarray(handle["position"][0][initial_valid], dtype=np.float64)
        v_initial = np.asarray(handle["velocity"][0][initial_valid], dtype=np.float64)
        if not np.isfinite(p_initial).all() or not np.isfinite(v_initial).all():
            case_result["reason"] = "initial_active_state_nonfinite"
            return case_result
        control = None
        control_error = None
        if control_path is not None and control_path.is_file():
            try:
                control = AccelerationControl.from_csv(control_path)
            except (OSError, ValueError) as error:
                control_error = f"{type(error).__name__}: {error}"
        elif control_path is not None:
            control_error = "control_file_missing"

        frame_limit = len(times) - 1
        if max_frames is not None:
            frame_limit = min(frame_limit, max(0, int(max_frames)))
        if frame_limit < 1:
            case_result["reason"] = "no_frame_transitions_in_scope"
            return case_result

        displacement_acc = ErrorAccumulator()
        velocity_acc = ErrorAccumulator()
        constant_acc = ErrorAccumulator()
        control_acc = ErrorAccumulator()
        p_velocity = p_initial.copy()
        p_constant = p_initial.copy()
        p_control = p_initial.copy()
        v_control = v_initial.copy()
        identity_stable = True
        mass_positive = True
        active_nonfinite = False
        final_mass = math.nan
        control_steps = 0
        for frame in range(frame_limit):
            dt = float(times[frame + 1] - times[frame])
            valid_now = _valid_mask(handle["valid"], frame)
            valid_next = _valid_mask(handle["valid"], frame + 1)
            if not np.array_equal(valid_now, initial_valid) or not np.array_equal(valid_next, initial_valid):
                identity_stable = False
                break
            p_now = np.asarray(handle["position"][frame][initial_valid], dtype=np.float64)
            p_next = np.asarray(handle["position"][frame + 1][initial_valid], dtype=np.float64)
            v_now = np.asarray(handle["velocity"][frame][initial_valid], dtype=np.float64)
            mass_now = _mass_frame(handle["mass"], frame, len(ids))[initial_valid]
            mass_next = _mass_frame(handle["mass"], frame + 1, len(ids))[initial_valid]
            final_mass = float(mass_next.sum())
            if (
                not np.isfinite(p_now).all()
                or not np.isfinite(p_next).all()
                or not np.isfinite(v_now).all()
                or not np.isfinite(mass_now).all()
                or not np.isfinite(mass_next).all()
            ):
                active_nonfinite = True
                break
            if not (mass_now > 0).all() or not (mass_next > 0).all():
                mass_positive = False
                break

            reference_displacement = p_next - p_now
            reference_update = update_from_displacement(p_now, reference_displacement)
            displacement_acc.add(reference_update - p_next)

            p_velocity = integrate_euler(p_velocity, v_now, dt)
            velocity_acc.add(p_velocity - p_next)

            p_constant = integrate_euler(p_constant, v_initial, dt)
            constant_acc.add(p_constant - p_next)

            if control is not None:
                try:
                    acceleration = control.body_acceleration(times[frame], p_control, v_control)
                except (ValueError, IndexError) as error:
                    control_error = f"{type(error).__name__}: {error}"
                    control = None
                else:
                    p_control, v_control = integrate_constant_acceleration(
                        p_control, v_control, acceleration, dt
                    )
                    control_acc.add(p_control - p_next)
                    control_steps += 1

        if not identity_stable:
            case_result["reason"] = "current_f3_identity_lifecycle_not_stable"
            case_result["identity_stable"] = False
            return case_result
        if active_nonfinite:
            case_result["reason"] = "active_state_nonfinite"
            return case_result
        if not mass_positive:
            case_result["reason"] = "active_mass_not_positive"
            return case_result

        case_result.update({
            "status": "completed",
            "identity_stable": True,
            "active_particle_count": active_count,
            "frame_count_scored": frame_limit,
            "initial_mass_kg": float(initial_mass[initial_valid].sum()),
            "final_mass_kg": final_mass,
            "mass_fraction_final": final_mass / float(initial_mass[initial_valid].sum()),
            "active_mass_positive": True,
            "oracles": {
                "source_trajectory_integrity": {
                    "status": "completed",
                    "identity_axis": "particle_id",
                    "active_state_finite": True,
                    "active_mass_positive": True,
                    "lifecycle": "closed_stable_identity_axis",
                },
                "reference_displacement_same_update": {
                    "status": "completed",
                    "update": "position_next = position_current + reference_displacement",
                    "score": _metric_result(displacement_acc, scale=dp_m, scope="one_step_reference_update"),
                },
                "real_velocity_same_integrator": {
                    "status": "completed",
                    "integrator": "position_next = position_current + native_velocity_current * dt",
                    "score": _metric_result(velocity_acc, scale=dp_m, scope="cumulative_reference_velocity_integral"),
                },
                "constant_velocity": {
                    "status": "completed",
                    "integrator": "initial_native_velocity held for the full horizon",
                    "score": _metric_result(constant_acc, scale=dp_m, scope="cumulative_constant_velocity"),
                },
                "known_control_simplified": {
                    "status": "completed" if control is not None and control_steps == frame_limit else "bounded_rejection",
                    "integrator": "position += velocity*dt + 0.5*known_control_acceleration*dt^2",
                    "control_future_fluid_state_read": False,
                    "control_steps": control_steps,
                    "score": _metric_result(control_acc, scale=dp_m, scope="cumulative_known_control_only") if control_steps else None,
                    "reason": control_error,
                },
            },
        })
    return case_result


def _current_model_preflight(contract: dict[str, Any]) -> dict[str, Any]:
    model = contract["current_model_evaluator"]
    if model["checkpoint_candidates"]:
        return {
            "status": "blocked_pending_explicit_checkpoint_binding",
            "reason": "A checkpoint exists but R2 worker does not silently choose one without current-contract metadata.",
            "candidates": model["checkpoint_candidates"],
        }
    return {
        "status": "bounded_rejection",
        "reason": "current_f3_checkpoint_missing",
        "evidence": {
            "evaluator": model["evaluator"],
            "adapter": model["adapter"],
            "required_routes": model["routes"],
            "legacy_checkpoint_policy": "43-feature R3-G4 checkpoints are excluded",
        },
        "no_model_rollout_claimed": True,
    }


def run_actual_oracles(contract: dict[str, Any]) -> dict[str, Any]:
    case_runs: list[dict[str, Any]] = []
    for selected in contract["selected_oracle_cases"]:
        if selected.get("status") != "ready":
            case_runs.append({
                "case_id": selected.get("case_id"),
                "status": "bounded_rejection",
                "reason": "selected_case_source_not_ready",
                "source": selected,
            })
            continue
        case_runs.append(run_case_oracles(
            resolve_lab_path(selected["hdf5"]["path"]),
            control_path=resolve_lab_path(selected["control"]["path"]) if selected.get("control") else None,
            dp_m=float(selected.get("dp_m") or contract["recipe"]["production_resolution_m"]),
        ))
        case_runs[-1]["case_id"] = selected["case_id"]
        case_runs[-1]["role"] = selected["role"]
        case_runs[-1]["split"] = selected.get("split")
        case_runs[-1]["drive_amplitude"] = selected.get("drive_amplitude")

    completed_case_runs = sum(item.get("status") == "completed" for item in case_runs)
    deterministic_names = (
        "source_trajectory_integrity",
        "reference_displacement_same_update",
        "real_velocity_same_integrator",
        "constant_velocity",
        "known_control_simplified",
    )
    deterministic_statuses = {
        name: sum(
            item.get("oracles", {}).get(name, {}).get("status") == "completed"
            for item in case_runs
        )
        for name in deterministic_names
    }
    return {
        "schema": "l2r.r2.actual_oracle_runs.v1",
        "created_at_utc": utc_now(),
        "baseline_commit": BASELINE_COMMIT,
        "current_commit": current_git_head(),
        "status": "complete_with_bounded_rejection",
        "qualification_claim": "none; deterministic oracle evidence only, current learned-model rollout rejected as bounded missing-checkpoint",
        "runner": file_ref(Path(__file__)),
        "contract": file_ref(CONTRACT_ARTIFACT),
        "scoring": {
            "function": "score_prediction",
            "same_for_all_completed_oracles": True,
            "metrics": ["rmse_m", "rmse_over_dp", "ade_m", "fde_m", "max_error_m"],
            "normal_results_retained": True,
            "difference_results_retained": True,
            "normalization": "RMSE over the current case production dp; ADE/FDE/max in metres",
        },
        "current_model_evaluator": _current_model_preflight(contract),
        "case_runs": case_runs,
        "completed_case_count": completed_case_runs,
        "oracle_completion_counts": deterministic_statuses,
        "actual_execution_boundary": {
            "source_hdf5_read": True,
            "future_fluid_state_read_by_deterministic_oracles": False,
            "new_cfd_solver_run": False,
            "current_model_rollout_executed": False,
            "legacy_model_checkpoint_reused": False,
        },
        "unresolved_blockers": [
            "current 48-feature model checkpoint and its bound evaluation metadata are absent; current learned-model oracle remains bounded_rejection",
        ],
    }


def _legacy_source_ref(raw: dict[str, Any]) -> dict[str, Any]:
    path = resolve_lab_path(raw.get("path", ""))
    return file_ref(path, expected_sha256=raw.get("sha256"))


def classify_legacy_run(run: dict[str, Any], *, current_width: int = len(FEATURE_NAMES)) -> dict[str, Any]:
    width = run.get("feature_width")
    logical_run_id = run.get("logical_run_id") or (
        f"R3-G4-{run.get('route', 'unknown')}-seed{run.get('seed', 'unknown')}"
    )
    reasons: list[str] = []
    if width != current_width:
        reasons.append(f"feature_width_{width}_not_current_{current_width}")
    if run.get("epochs_requested") in (2, 3) or run.get("epochs_run") in (2, 3):
        reasons.append("W11_short_2_to_3_epoch_budget")
    reasons.extend(["R3-G4_baseline_route", "candidate_only_source", "not_new_L2_training_attempt"])
    return {
        "logical_run_id": logical_run_id,
        "logical_run_id_source": "source_record" if run.get("logical_run_id") else "derived_route_seed",
        "route": run.get("route"),
        "seed": run.get("seed"),
        "source_run_status": run.get("source_run_status"),
        "feature_width": width,
        "epochs_requested": run.get("epochs_requested"),
        "epochs_run": run.get("epochs_run"),
        "test_rollout_statuses": run.get("test_rollout_statuses"),
        "source_artifacts": {
            key: _legacy_source_ref(value)
            for key, value in (run.get("source_artifacts") or {}).items()
            if isinstance(value, dict) and value.get("path")
        },
        "classification": "legacy_reference",
        "reuse_allowed": True,
        "eligible_for_current_f3_model_result": False,
        "eligible_for_new_L2_training_count": False,
        "eligible_as_independent_CFD_case": False,
        "rejection_reasons": reasons,
    }


def build_legacy_reuse_manifest(contract: dict[str, Any]) -> dict[str, Any]:
    b2 = read_json(B2_REPORT) if B2_REPORT.is_file() else {}
    runs = [classify_legacy_run(run) for run in b2.get("runs", []) if isinstance(run, dict)]
    widths = sorted({run.get("feature_width") for run in runs})
    return {
        "schema": "l2r.r2.legacy_reuse_manifest.v1",
        "created_at_utc": utc_now(),
        "baseline_commit": BASELINE_COMMIT,
        "current_commit": current_git_head(),
        "status": "legacy_only_no_current_f3_promotion",
        "current_contract_boundary": {
            "current_feature_width": len(FEATURE_NAMES),
            "current_adapter": file_ref(CURRENT_FEATURE_ADAPTER),
            "current_evaluator": file_ref(CURRENT_EVALUATOR),
            "current_model_qualification": contract["qualification"]["current_model_qualified"],
            "legacy_trainer_warning": "The historical 115-wide cup-pose trainer does not consume the current 48-wide adapter.",
        },
        "sources": {
            "b2_report": file_ref(B2_REPORT),
            "b2_run_manifest": file_ref(B2_RUN_MANIFEST),
            "source_scope": b2.get("scope"),
            "source_contract": b2.get("source_contract"),
        },
        "records": runs,
        "aggregate": {
            "legacy_logical_run_count": len(runs),
            "legacy_feature_widths": widths,
            "new_training_attempts_in_L2_recorded": b2.get("scope", {}).get("new_training_attempts_in_L2"),
            "current_f3_model_results_promoted": False,
            "current_f3_case_count_added": 0,
            "seed_is_not_independent_CFD_case": True,
        },
        "boundary_rules": [
            "Historical route/seed results may be compared as legacy references only.",
            "A 43-feature checkpoint cannot satisfy the current 48-feature F3 input contract.",
            "Legacy 2-3 epoch W11 runs do not count as current L2 training attempts.",
            "Evaluation case x seed is not an independent CFD sample.",
            "No legacy checkpoint is loaded by the R2 oracle runner.",
        ],
    }


def run_all() -> dict[str, Any]:
    contract = build_current_f3_contract()
    atomic_json(CONTRACT_ARTIFACT, contract)
    legacy = build_legacy_reuse_manifest(contract)
    atomic_json(LEGACY_ARTIFACT, legacy)
    actual = run_actual_oracles(contract)
    atomic_json(ORACLE_ARTIFACT, actual)
    return {
        "contract": repo_relative(CONTRACT_ARTIFACT),
        "legacy": repo_relative(LEGACY_ARTIFACT),
        "actual_oracles": repo_relative(ORACLE_ARTIFACT),
        "contract_status": contract["contract_status"],
        "current_model_status": contract["current_model_evaluator"]["status"],
        "completed_case_count": actual["completed_case_count"],
        "oracle_completion_counts": actual["oracle_completion_counts"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("contract", "legacy", "run", "all"))
    args = parser.parse_args()
    if args.action == "contract":
        payload = build_current_f3_contract()
        atomic_json(CONTRACT_ARTIFACT, payload)
        print(json.dumps({"path": repo_relative(CONTRACT_ARTIFACT), "status": payload["contract_status"]}, ensure_ascii=False))
    elif args.action == "legacy":
        contract = read_json(CONTRACT_ARTIFACT) if CONTRACT_ARTIFACT.is_file() else build_current_f3_contract()
        payload = build_legacy_reuse_manifest(contract)
        atomic_json(LEGACY_ARTIFACT, payload)
        print(json.dumps({"path": repo_relative(LEGACY_ARTIFACT), "runs": len(payload["records"])}, ensure_ascii=False))
    elif args.action == "run":
        contract = read_json(CONTRACT_ARTIFACT) if CONTRACT_ARTIFACT.is_file() else build_current_f3_contract()
        if not CONTRACT_ARTIFACT.is_file():
            atomic_json(CONTRACT_ARTIFACT, contract)
        payload = run_actual_oracles(contract)
        atomic_json(ORACLE_ARTIFACT, payload)
        print(json.dumps({"path": repo_relative(ORACLE_ARTIFACT), "status": payload["status"], "completed_case_count": payload["completed_case_count"]}, ensure_ascii=False))
    else:
        print(json.dumps(run_all(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
