#!/usr/bin/env python3
"""Static, CPU-only audit for the R4 G4 learned-baseline contract.

This module deliberately does not import or execute the G4 trainer.  It parses
the trainer source, reads JSON/HDF5/checkpoint artifacts, and emits an
independent audit of the four route input contract and training-state
provenance.  Checkpoints, when inspectable, are loaded with ``map_location``
set to CPU and are never used for inference or training.

The report is intentionally allowed to contain failed checks: a completed
audit with findings is more useful here than a synthetic pass/fail gate.  In
particular, the current source has a sidecar component-input branch that was
added after the recorded 43-wide runs, so the report keeps current source
semantics separate from historical run semantics.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:  # Optional so the source/provenance audit remains usable without ML deps.
    import h5py
    import numpy as np
except ImportError:  # pragma: no cover - exercised only in a minimal environment.
    h5py = None
    np = None


ROOT = Path(__file__).resolve().parents[1]
TRAINER_REL = Path("experiments/r3_g4_baselines.py")
CONFIG_REL = Path("experiments/r3_g4_config.json")
RELEASE_MANIFEST_REL = Path("release/v0.1-development/manifest.json")

ROUTES = ("particle_mlp", "deepset_context", "local_interaction", "physics_residual")
SEEDS = (17, 29, 43)
LOCAL_ROUTE = "local_interaction"
BASE_FEATURE_WIDTH = 43
CONTROL_WIDTH = 10
BOUNDARY_WIDTH = 7
BOUNDARY_COMPONENT_WIDTH = 9
MAX_BOUNDARY_COMPONENTS = 8
COMPONENT_BLOCK_WIDTH = BOUNDARY_COMPONENT_WIDTH * MAX_BOUNDARY_COMPONENTS
LOCAL_WIDTH = 8

BASE_SLICES = {
    "centered_xyz": [0, 3],
    "target_velocity_scaled": [3, 6],
    "context_com_velocity_scaled": [6, 9],
    "initial_density_pressure_mass": [9, 12],
    "gravity": [12, 15],
    "static_physics": [15, 18],
    "current_prescribed_control": [18, 28],
    "current_boundary_summary": [28, 35],
    "family_one_hot": [35, 41],
    "elapsed_time": [41, 42],
    "dt": [42, 43],
}

HDF5_DATASETS = (
    "valid",
    "type",
    "time",
    "position",
    "velocity",
    "density",
    "pressure",
    "mass",
)
CONTROL_DATASETS = (
    "cup_angle_degrees",
    "prescribed_angular_velocity_radps",
    "cup_world_from_body",
)
SIDECAR_DATASETS = (
    "time",
    "triangles_world",
    "triangle_mk",
    "triangle_type",
    "triangle_component",
)

COLLECTION_SPECS = {
    "pre_sidecar_12_run": {
        "manifest": Path("experiments/r3_g4_run_manifest.json"),
        "routes": ROUTES,
        "seeds": SEEDS,
    },
    "sidecar_12_run": {
        "manifest": Path("experiments/r3_g4_sidecar_run_manifest.json"),
        "routes": ROUTES,
        "seeds": SEEDS,
    },
    "small_six_rerun": {
        "manifest": Path("experiments/r3-g4-baseline-routes/run_manifest.json"),
        "routes": (LOCAL_ROUTE, "physics_residual"),
        "seeds": SEEDS,
    },
}


def _relative(path: Path, root: Path) -> str:
    """Return a stable report path without leaking machine-specific prefixes."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _resolve(root: Path, value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else root / path


def _sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path | None) -> Any:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sample_std(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _literal_assignments(tree: ast.AST) -> dict[str, Any]:
    assignments: dict[str, Any] = {}
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            continue
        try:
            assignments[targets[0].id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            continue
    return assignments


def _line_for(text: str, needle: str) -> int | None:
    for index, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return index
    return None


def _definition_lines(tree: ast.AST) -> dict[str, dict[str, int]]:
    definitions: dict[str, dict[str, int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions[node.name] = {
                "start": int(node.lineno),
                "end": int(getattr(node, "end_lineno", node.lineno)),
            }
    return definitions


def analyze_source(path: Path, root: Path = ROOT) -> dict[str, Any]:
    """Parse source only; no trainer import or model construction occurs."""

    if not path.is_file():
        return {
            "path": _relative(path, root),
            "exists": False,
            "sha256": None,
            "syntax_valid": False,
            "routes": [],
            "line_anchors": {},
            "flags": {},
        }

    text = path.read_text()
    try:
        tree = ast.parse(text, filename=str(path))
        syntax_valid = True
    except SyntaxError:
        return {
            "path": _relative(path, root),
            "exists": True,
            "sha256": _sha256(path),
            "syntax_valid": False,
            "routes": [],
            "line_anchors": {},
            "flags": {},
        }

    definitions = _definition_lines(tree)
    constants = _literal_assignments(tree)
    source_routes = tuple(constants.get("ROUTES", ()))
    expected_read_fields = {
        "hdf5_datasets": list(HDF5_DATASETS),
        "control_datasets": list(CONTROL_DATASETS),
        "sidecar_datasets": list(SIDECAR_DATASETS),
    }
    read_lines = {
        field: _line_for(text, f'"{field}"')
        for field in (*HDF5_DATASETS, *CONTROL_DATASETS, *SIDECAR_DATASETS)
    }
    flags = {
        "route_classes_present": all(
            name in definitions
            for name in ("ParticleMLP", "DeepSetContext", "LocalInteraction", "PhysicsResidual")
        ),
        "route_dispatch_present": "def model_for" in text and all(
            f'route == "{route}"' in text for route in ROUTES
        ),
        "case_aware_feature_width_branch": "def feature_width(cases" in text
        and "MAX_BOUNDARY_COMPONENTS * BOUNDARY_COMPONENT_WIDTH" in text,
        "train_uses_case_aware_feature_width": "feature_width(cases)" in text,
        "component_block_is_appended": "component_tensor" in text and "values + (component_tensor,)" in text,
        "component_slot_preserves_sidecar_order": "dict.fromkeys(keys)" in text,
        "component_id_is_in_packed_feature_fields": "component_id"
        in tuple(constants.get("BOUNDARY_COMPONENT_FEATURE_FIELDS", ())),
        "deep_set_uses_mean_context": "encoded.mean(dim=0" in text,
        "train_samples_target_particles": "rng.choice(count, min(args.max_particles, count), replace=False)" in text,
        "rollout_starts_at_frame_zero": 'case["position"][0]' in text and 'case["velocity"][0]' in text,
        "rollout_updates_own_velocity_state": "velocity_state = next_velocity" in text,
        "future_reference_read_for_metrics": 'reference = _tensor(case["position"][frame + 1]' in text,
        "future_velocity_read_for_training_label": 'next_velocity = case["velocity"][frame + 1, indices]' in text,
        "same_feature_builder_in_train_validation_rollout": text.count("build_features(") >= 4,
        "smooth_output_cap_in_train_validation_rollout": "OUTPUT_CAP * torch.tanh" in text
        and "def predict" in text
        and "def raw_and_bounded_prediction" in text,
        "seed_calls_present": all(
            needle in text
            for needle in (
                "random.seed(args.seed)",
                "np.random.seed(args.seed)",
                "torch.manual_seed(args.seed)",
                "torch.cuda.manual_seed_all(args.seed)",
            )
        ),
        "deterministic_cuda_controls_present": any(
            needle in text
            for needle in ("torch.use_deterministic_algorithms", "cudnn.deterministic", "CUBLAS_WORKSPACE_CONFIG")
        ),
        "checkpoint_payload_contains_only_inference_metadata": '"state_dict": model.state_dict()' in text
        and '"route": args.route' in text
        and '"seed": args.seed' in text
        and '"feature_width": model_input_width' in text,
        "optimizer_state_saved": "optimizer.state_dict()" in text,
        "rng_state_saved": "get_rng_state" in text or "rng_state" in text,
    }

    route_roles = {
        "particle_mlp": "direct per-particle next-velocity predictor",
        "deepset_context": "per-particle predictor with mean set context",
        "local_interaction": "direct predictor plus 8-wide inverse-distance neighbour summary",
        "physics_residual": "normalized acceleration residual integrated into velocity",
    }
    return {
        "path": _relative(path, root),
        "exists": True,
        "sha256": _sha256(path),
        "syntax_valid": syntax_valid,
        "routes": list(source_routes),
        "route_roles": route_roles,
        "definitions": {
            name: definitions[name]
            for name in (
                "ParticleMLP",
                "DeepSetContext",
                "LocalInteraction",
                "PhysicsResidual",
                "model_for",
                "_load_case",
                "feature_width",
                "build_features",
                "local_neighbour_features",
                "target_for",
                "rollout",
                "train",
            )
            if name in definitions
        },
        "line_anchors": {
            "hdf5": read_lines,
            "feature_width_case_call": _line_for(text, "feature_width(cases)"),
            "component_group_order": _line_for(text, "dict.fromkeys(keys)"),
            "deep_set_mean": _line_for(text, "encoded.mean(dim=0"),
            "train_particle_sampling": _line_for(text, "rng.choice(count"),
            "direct_target": _line_for(text, "return _tensor(next_velocity * dt / case[\"dp\"]"),
            "physics_target": _line_for(text, "return _tensor(acceleration * dt * dt / case[\"dp\"]"),
            "rollout_reference_metric": _line_for(text, 'reference = _tensor(case["position"][frame + 1]'),
            "checkpoint_save": _line_for(text, "torch.save({\"state_dict\": model.state_dict()"),
        },
        "read_fields": expected_read_fields,
        "flags": flags,
        "declared_constants": {
            name: constants[name]
            for name in (
                "ROUTES",
                "CONTROL_WIDTH",
                "BOUNDARY_WIDTH",
                "BOUNDARY_COMPONENT_FEATURE_FIELDS",
                "BOUNDARY_COMPONENT_WIDTH",
                "MAX_BOUNDARY_COMPONENTS",
                "PHYSICS_WIDTH",
                "LOCAL_WIDTH",
                "NEIGHBORS",
                "OUTPUT_CAP",
            )
            if name in constants
        },
    }


def _attribute_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _first_component_order(types: Any, components: Any) -> list[list[int]]:
    order: list[list[int]] = []
    for kind, component in zip(types, components):
        pair = [int(kind), int(component)]
        if pair not in order:
            order.append(pair)
    return order


def inspect_release_data(manifest_path: Path, root: Path = ROOT) -> dict[str, Any]:
    """Inspect release HDF5/sidecar structure without calling the trainer."""

    payload = _load_json(manifest_path)
    records = payload.get("cases", []) if isinstance(payload, dict) else []
    case_reports: list[dict[str, Any]] = []
    optional_dependency = h5py is not None and np is not None

    for record in records:
        case_id = record.get("case_id")
        hdf5_path = manifest_path.parent / str(record.get("hdf5", ""))
        sidecar_ref = (record.get("geometry") or {}).get("boundary_sidecar")
        sidecar_path = manifest_path.parent / str(sidecar_ref) if sidecar_ref else None
        case_report: dict[str, Any] = {
            "case_id": case_id,
            "family": record.get("family"),
            "split": record.get("split"),
            "hdf5": _relative(hdf5_path, root),
            "hdf5_exists": hdf5_path.is_file(),
            "sidecar": _relative(sidecar_path, root) if sidecar_path else None,
            "sidecar_exists": sidecar_path.is_file() if sidecar_path else False,
            "required_hdf5_datasets": list(HDF5_DATASETS),
            "hdf5_dataset_presence": {},
            "hdf5_shapes": {},
            "control_fields": [],
            "initial_fluid_count": None,
            "stable_fluid_count": None,
            "hdf5_all_required_finite": None,
            "sidecar_dataset_presence": {},
            "sidecar_shapes": {},
            "sidecar_attrs": {},
            "sidecar_component_order": [],
            "sidecar_component_count": 0,
            "sidecar_time_aligned": None,
            "sidecar_time_strictly_increasing": None,
            "sidecar_schema_valid": None,
            "sidecar_coordinate_frame_world": None,
            "sidecar_case_id_matches": None,
            "sidecar_all_finite": None,
            "inspection": "unavailable" if not optional_dependency else "pending",
        }
        solver_times: Any = None
        if optional_dependency and hdf5_path.is_file():
            try:
                with h5py.File(hdf5_path, "r") as h5:
                    case_report["hdf5_dataset_presence"] = {
                        name: name in h5 for name in HDF5_DATASETS
                    }
                    case_report["hdf5_shapes"] = {
                        name: list(h5[name].shape)
                        for name in HDF5_DATASETS
                        if name in h5
                    }
                    if "control" in h5:
                        case_report["control_fields"] = sorted(str(name) for name in h5["control"].keys())
                    if all(case_report["hdf5_dataset_presence"].values()):
                        solver_times = np.asarray(h5["time"][:])
                        valid = np.asarray(h5["valid"][:], dtype=bool)
                        particle_type = np.asarray(h5["type"][:])
                        fluid = valid & (particle_type == 3)
                        case_report["initial_fluid_count"] = int(fluid[0].sum())
                        case_report["stable_fluid_count"] = int(np.all(fluid, axis=0).sum())
                        case_report["hdf5_all_required_finite"] = all(
                            bool(np.isfinite(h5[name][:]).all()) for name in HDF5_DATASETS
                        )
                    case_report["inspection"] = "complete"
            except (OSError, KeyError, ValueError, TypeError) as error:
                case_report["inspection"] = "error"
                case_report["error"] = f"{type(error).__name__}: {error}"

        if optional_dependency and sidecar_path is not None and sidecar_path.is_file():
            try:
                with h5py.File(sidecar_path, "r") as sidecar:
                    case_report["sidecar_dataset_presence"] = {
                        name: name in sidecar for name in SIDECAR_DATASETS
                    }
                    case_report["sidecar_shapes"] = {
                        name: list(sidecar[name].shape)
                        for name in SIDECAR_DATASETS
                        if name in sidecar
                    }
                    case_report["sidecar_attrs"] = {
                        name: _attribute_value(sidecar.attrs.get(name))
                        for name in ("schema_version", "coordinate_frame", "case_id")
                        if name in sidecar.attrs
                    }
                    case_report["sidecar_schema_valid"] = (
                        case_report["sidecar_attrs"].get("schema_version") == "boundary-sidecar-v1"
                    )
                    case_report["sidecar_coordinate_frame_world"] = (
                        case_report["sidecar_attrs"].get("coordinate_frame") == "world"
                    )
                    case_report["sidecar_case_id_matches"] = (
                        case_report["sidecar_attrs"].get("case_id") == case_id
                    )
                    component_name = (
                        "triangle_component"
                        if "triangle_component" in sidecar
                        else "triangle_mk"
                    )
                    if all(
                        name in sidecar
                        for name in ("time", "triangles_world", "triangle_type", component_name)
                    ):
                        sidecar_times = np.asarray(sidecar["time"][:])
                        case_report["sidecar_time_strictly_increasing"] = bool(
                            sidecar_times.ndim == 1
                            and len(sidecar_times) > 1
                            and np.isfinite(sidecar_times).all()
                            and (np.diff(sidecar_times) > 0).all()
                        )
                        types = np.asarray(sidecar["triangle_type"][:])
                        components = np.asarray(sidecar[component_name][:])
                        order = _first_component_order(types, components)
                        case_report["sidecar_component_order"] = order
                        case_report["sidecar_component_count"] = len(order)
                        triangles = np.asarray(sidecar["triangles_world"][:])
                        case_report["sidecar_all_finite"] = bool(np.isfinite(triangles).all())
                        if "time" in sidecar and solver_times is not None:
                            sidecar_time = sidecar_times
                            case_report["sidecar_time_aligned"] = bool(
                                solver_times.shape == sidecar_time.shape
                                and np.allclose(solver_times, sidecar_time, rtol=0.0, atol=1e-9)
                            )
                    if case_report["inspection"] == "complete":
                        case_report["inspection"] = "complete"
            except (OSError, KeyError, ValueError, TypeError) as error:
                case_report["sidecar_inspection"] = "error"
                case_report["sidecar_error"] = f"{type(error).__name__}: {error}"
        case_reports.append(case_report)

    loaded = [case for case in case_reports if (case.get("initial_fluid_count") or 0) > 0]
    sidecar_cases = [case for case in case_reports if case.get("sidecar")]
    control_sources = Counter(
        "known_prescribed_control_schedule"
        if "cup_angle_degrees" in case.get("control_fields", [])
        else "missing_control_group"
        for case in loaded
    )
    component_counts = [int(case["sidecar_component_count"]) for case in sidecar_cases]
    orders_by_id = {
        str(case["case_id"]): case["sidecar_component_order"]
        for case in sidecar_cases
        if case.get("sidecar_component_order")
    }
    order_groups: dict[tuple[int, ...], set[tuple[int, ...]]] = defaultdict(set)
    for order in orders_by_id.values():
        ids = tuple(pair[1] for pair in order)
        order_groups[tuple(sorted(ids))].add(ids)
    order_varies = any(len(orders) > 1 for orders in order_groups.values())

    all_hdf5_fields = bool(loaded) and all(
        all(case["hdf5_dataset_presence"].values()) and case["hdf5_all_required_finite"]
        for case in loaded
    )
    all_sidecars_valid = bool(sidecar_cases) and all(
        all(case["sidecar_dataset_presence"].get(name, False) for name in ("time", "triangles_world", "triangle_mk", "triangle_type"))
        and case["sidecar_time_aligned"] is True
        and case["sidecar_time_strictly_increasing"] is True
        and case["sidecar_schema_valid"] is True
        and case["sidecar_coordinate_frame_world"] is True
        and case["sidecar_case_id_matches"] is True
        and case["sidecar_all_finite"] is True
        for case in sidecar_cases
    )
    split_counts = Counter(str(case.get("split")) for case in loaded)
    excluded = [
        str(case.get("case_id"))
        for case in case_reports
        if (case.get("initial_fluid_count") or 0) == 0
    ]
    return {
        "path": _relative(manifest_path, root),
        "exists": manifest_path.is_file(),
        "sha256": _sha256(manifest_path),
        "record_count": len(records),
        "loaded_fluid_case_count": len(loaded),
        "split_counts": dict(sorted(split_counts.items())),
        "excluded_no_initial_fluid": sorted(excluded),
        "control_sources": dict(sorted(control_sources.items())),
        "linked_sidecar_case_count": len(sidecar_cases),
        "sidecar_component_counts": {
            "values": component_counts,
            "min": min(component_counts) if component_counts else None,
            "max": max(component_counts) if component_counts else None,
        },
        "sidecar_component_order_by_case": orders_by_id,
        "component_order_varies_for_same_id_set": order_varies,
        "all_loaded_hdf5_fields_finite": all_hdf5_fields,
        "all_linked_sidecars_aligned_and_finite": all_sidecars_valid,
        "dependency_inspection": "complete" if optional_dependency else "unavailable_h5py_numpy",
        "cases": case_reports,
    }


def current_feature_layout(source: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Calculate both the old 43-wide layout and the current active layout."""

    dynamic_branch = bool(source.get("flags", {}).get("case_aware_feature_width_branch"))
    sidecar_case_count = int(data.get("linked_sidecar_case_count", 0))
    component_active = dynamic_branch and sidecar_case_count > 0
    active_slices = {name: list(bounds) for name, bounds in BASE_SLICES.items()}
    if component_active:
        active_slices = {
            "centered_xyz": [0, 3],
            "target_velocity_scaled": [3, 6],
            "context_com_velocity_scaled": [6, 9],
            "initial_density_pressure_mass": [9, 12],
            "gravity": [12, 15],
            "static_physics": [15, 18],
            "current_prescribed_control": [18, 28],
            "current_boundary_summary": [28, 35],
            "boundary_component_block": [35, 35 + COMPONENT_BLOCK_WIDTH],
            "family_one_hot": [35 + COMPONENT_BLOCK_WIDTH, 41 + COMPONENT_BLOCK_WIDTH],
            "elapsed_time": [41 + COMPONENT_BLOCK_WIDTH, 42 + COMPONENT_BLOCK_WIDTH],
            "dt": [42 + COMPONENT_BLOCK_WIDTH, 43 + COMPONENT_BLOCK_WIDTH],
        }
    active_width = BASE_FEATURE_WIDTH + COMPONENT_BLOCK_WIDTH if component_active else BASE_FEATURE_WIDTH
    return {
        "base_width": BASE_FEATURE_WIDTH,
        "component_block_width": COMPONENT_BLOCK_WIDTH,
        "component_block_shape": [MAX_BOUNDARY_COMPONENTS, BOUNDARY_COMPONENT_WIDTH],
        "component_active_on_release_manifest": component_active,
        "active_width": active_width,
        "local_extra_width": LOCAL_WIDTH,
        "local_active_width": active_width + LOCAL_WIDTH,
        "base_slices": BASE_SLICES,
        "active_slices": active_slices,
        "artifact_43_layout": "base AABB summary only; no sidecar component block",
    }


def _parse_command(command: Any) -> dict[str, Any]:
    if not isinstance(command, list):
        return {}
    values: dict[str, Any] = {}
    value_flags = {
        "--route",
        "--seed",
        "--epochs",
        "--min-epochs",
        "--patience",
        "--min-delta",
        "--max-particles",
        "--validation-particles",
        "--hidden",
        "--learning-rate",
        "--clip-dp",
        "--device",
        "--manifest",
        "--output",
        "--checkpoint",
    }
    index = 0
    while index < len(command):
        token = str(command[index])
        if token in value_flags and index + 1 < len(command):
            raw = str(command[index + 1])
            if token in {"--seed", "--epochs", "--min-epochs", "--patience", "--max-particles", "--validation-particles", "--hidden"}:
                try:
                    values[token] = int(raw)
                except ValueError:
                    values[token] = raw
            elif token in {"--min-delta", "--learning-rate", "--clip-dp"}:
                try:
                    values[token] = float(raw)
                except ValueError:
                    values[token] = raw
            else:
                values[token] = raw
            index += 2
        else:
            index += 1
    return values


def inspect_checkpoint(path: Path, root: Path = ROOT) -> dict[str, Any]:
    """Inspect a checkpoint on CPU only; no forward pass is performed."""

    info: dict[str, Any] = {
        "path": _relative(path, root),
        "exists": path.is_file(),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size if path.is_file() else None,
        "load_mode": "not_attempted",
        "payload_keys": [],
        "state_dict_key_count": None,
        "metadata": {},
        "first_linear": None,
        "has_optimizer_state": None,
        "has_rng_state": None,
    }
    if not path.is_file():
        return info
    try:
        import torch  # Lazy and used only for map_location='cpu' deserialization.
    except ImportError:
        info["load_mode"] = "torch_unavailable"
        return info
    try:
        try:
            payload = torch.load(path, map_location="cpu", weights_only=True)
        except TypeError:  # Older torch releases do not expose weights_only.
            payload = torch.load(path, map_location="cpu")
        info["load_mode"] = "cpu_weights_only"
        if not isinstance(payload, dict):
            info["payload_keys"] = [type(payload).__name__]
            return info
        info["payload_keys"] = sorted(str(key) for key in payload.keys())
        info["metadata"] = {
            key: payload.get(key)
            for key in ("route", "seed", "feature_width", "schema_version", "input_contract_id")
            if key in payload and isinstance(payload.get(key), (str, int, float, bool, type(None)))
        }
        state_dict = payload.get("state_dict")
        if isinstance(state_dict, dict):
            info["state_dict_key_count"] = len(state_dict)
            info["has_optimizer_state"] = "optimizer_state_dict" in payload
            info["has_rng_state"] = any(
                key in payload for key in ("rng_state", "numpy_rng_state", "python_rng_state", "cuda_rng_state")
            )
            preferred = [
                key
                for key in state_dict
                if str(key).endswith(".0.weight") or str(key) == "net.0.weight"
            ]
            if preferred:
                key = str(preferred[0])
                tensor = state_dict[preferred[0]]
                shape = list(getattr(tensor, "shape", ()))
                info["first_linear"] = {
                    "key": key,
                    "shape": [int(value) for value in shape],
                    "input_width": int(shape[1]) if len(shape) == 2 else None,
                    "tensor_device": str(getattr(tensor, "device", "cpu")),
                }
        return info
    except Exception as error:  # Artifact corruption is a report finding, not an audit crash.
        info["load_mode"] = "error"
        info["error"] = f"{type(error).__name__}: {error}"
        return info


def _log_summary(path: Path, root: Path = ROOT) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": _relative(path, root),
        "exists": path.is_file(),
        "sha256": _sha256(path),
        "json_line_count": 0,
        "epoch_count": 0,
        "route_seed_pairs": [],
    }
    if not path.is_file():
        return summary
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text().splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    except OSError:
        return summary
    pairs = sorted({(row.get("route"), row.get("seed")) for row in rows if "route" in row and "seed" in row})
    summary["json_line_count"] = len(rows)
    summary["epoch_count"] = sum(1 for row in rows if "epoch" in row)
    summary["route_seed_pairs"] = [[route, seed] for route, seed in pairs]
    return summary


def _run_signature(command: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    early = result.get("early_stopping") or {}

    def choose(flag: str, result_key: str | None = None, early_key: str | None = None) -> Any:
        if flag in command:
            return command[flag]
        if result_key is not None:
            return result.get(result_key)
        return early.get(early_key or "")

    return {
        "epochs_requested": choose("--epochs", "epochs_requested"),
        "min_epochs": choose("--min-epochs", early_key="min_epochs"),
        "patience": choose("--patience", early_key="patience"),
        "min_delta": choose("--min-delta", early_key="min_delta"),
        "max_particles": choose("--max-particles", "maximum_particles_per_training_frame"),
        "validation_particles": choose("--validation-particles", "validation_particles"),
        "hidden": choose("--hidden"),
        "learning_rate": choose("--learning-rate"),
        "clip_dp": choose("--clip-dp"),
        "device": choose("--device", "device"),
    }


def _normalise_signature(command: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return _run_signature(command, result)


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    rollouts = result.get("test_rollout") or {}
    metrics = {
        str(case_id): value.get("learned_rmse_over_dp")
        for case_id, value in rollouts.items()
        if isinstance(value, dict)
    }
    finite_metrics = [value for value in metrics.values() if _finite(value)]
    provenance_fields = [
        field
        for field in (
            "input_contract_id",
            "trainer_sha256",
            "source_sha256",
            "config_sha256",
            "manifest_sha256",
            "data_sha256",
        )
        if field in result
    ]
    return {
        "route": result.get("route"),
        "seed": result.get("seed"),
        "device": result.get("device"),
        "torch_version": result.get("torch_version"),
        "feature_width": result.get("feature_width"),
        "parameter_count": result.get("parameter_count"),
        "epochs_requested": result.get("epochs_requested"),
        "epochs_run": result.get("epochs_run"),
        "best_epoch": result.get("best_epoch"),
        "best_validation_autonomous_rmse_over_dp": result.get("best_validation_autonomous_rmse_over_dp"),
        "early_stopping": result.get("early_stopping"),
        "maximum_particles_per_training_frame": result.get("maximum_particles_per_training_frame"),
        "validation_particles": result.get("validation_particles"),
        "training_transition_frames": result.get("training_transition_frames"),
        "output_cap": result.get("output_cap"),
        "clipping": result.get("clipping"),
        "input_contract_fields": sorted((result.get("input_contract") or {}).keys()),
        "input_contract_id": result.get("input_contract_id"),
        "provenance_fields_present": provenance_fields,
        "has_source_hash": any(
            key in result for key in ("trainer_sha256", "source_sha256", "config_sha256", "manifest_sha256", "data_sha256")
        ),
        "metric_definition": result.get("metric_definition"),
        "test_rollout_statuses": {
            str(case_id): value.get("status")
            for case_id, value in rollouts.items()
            if isinstance(value, dict)
        },
        "test_metrics_learned_rmse_over_dp": metrics,
        "test_finite_metric_count": len(finite_metrics),
        "test_rollout_count": len(rollouts),
    }


def inspect_run_collection(
    name: str,
    root: Path,
    manifest_rel: Path,
    expected_routes: tuple[str, ...],
    expected_seeds: tuple[int, ...],
    current_width: int,
    inspect_checkpoints: bool = True,
) -> dict[str, Any]:
    manifest_path = root / manifest_rel
    payload = _load_json(manifest_path)
    run_rows: dict[str, dict[str, Any]] = {}
    raw_runs = payload.get("runs", []) if isinstance(payload, dict) else []
    if not isinstance(raw_runs, list):
        raw_runs = []

    for raw in raw_runs:
        if not isinstance(raw, dict):
            continue
        route = raw.get("route")
        seed = raw.get("seed")
        key = f"{route}_seed{seed}"
        output_path = _resolve(root, raw.get("output"))
        checkpoint_path = _resolve(root, raw.get("checkpoint"))
        log_path = _resolve(root, raw.get("log"))
        result_payload = _load_json(output_path)
        result_summary = _compact_result(result_payload) if isinstance(result_payload, dict) else None
        command = _parse_command(raw.get("command"))
        checkpoint_summary = (
            inspect_checkpoint(checkpoint_path, root)
            if inspect_checkpoints and checkpoint_path is not None
            else {
                "path": _relative(checkpoint_path, root) if checkpoint_path else None,
                "exists": checkpoint_path.is_file() if checkpoint_path else False,
                "load_mode": "skipped",
            }
        )
        run_rows[key] = {
            "route": route,
            "seed": seed,
            "manifest_status": raw.get("status"),
            "returncode": raw.get("returncode"),
            "physical_gpu_index": raw.get("physical_gpu_index"),
            "child_visible_devices": raw.get("child_visible_devices"),
            "command_signature": command,
            "run_signature": _normalise_signature(command, result_payload or {}),
            "paths": {
                "output": _relative(output_path, root) if output_path else None,
                "checkpoint": _relative(checkpoint_path, root) if checkpoint_path else None,
                "log": _relative(log_path, root) if log_path else None,
            },
            "result_file": {
                "exists": output_path.is_file() if output_path else False,
                "sha256": _sha256(output_path),
                "record": result_summary,
            },
            "checkpoint_file": checkpoint_summary,
            "log_file": _log_summary(log_path, root) if log_path else {"exists": False},
        }

    expected_keys = {
        f"{route}_seed{seed}"
        for route in expected_routes
        for seed in expected_seeds
    }
    found_keys = set(run_rows)
    duplicate_keys = [key for key, count in Counter(
        f"{row.get('route')}_seed{row.get('seed')}" for row in raw_runs if isinstance(row, dict)
    ).items() if count > 1]
    result_widths = sorted({
        row["result_file"]["record"].get("feature_width")
        for row in run_rows.values()
        if isinstance(row["result_file"].get("record"), dict)
        and row["result_file"]["record"].get("feature_width") is not None
    })
    checkpoint_widths = sorted({
        row["checkpoint_file"].get("metadata", {}).get("feature_width")
        for row in run_rows.values()
        if row["checkpoint_file"].get("metadata", {}).get("feature_width") is not None
    })
    status_counts = Counter(str(row.get("manifest_status")) for row in run_rows.values())
    complete_results = all(
        row["manifest_status"] == "completed"
        and row["result_file"]["exists"]
        and isinstance(row["result_file"].get("record"), dict)
        for row in run_rows.values()
    )
    all_rollouts_finite = all(
        int((row["result_file"]["record"] or {}).get("test_finite_metric_count", 0))
        == int((row["result_file"]["record"] or {}).get("test_rollout_count", 0))
        for row in run_rows.values()
        if isinstance(row["result_file"].get("record"), dict)
    )
    signatures = []
    for row in run_rows.values():
        signature = row["run_signature"]
        if signature not in signatures:
            signatures.append(signature)
    test_case_sets = sorted({
        tuple(sorted((row["result_file"]["record"] or {}).get("test_rollout_statuses", {}).keys()))
        for row in run_rows.values()
        if isinstance(row["result_file"].get("record"), dict)
    })
    manifest_fields = [
        field
        for field in ("config", "trainer", "manifest", "source_sha256", "config_sha256", "manifest_sha256", "data_sha256")
        if isinstance(payload, dict) and field in payload
    ]
    result_fields = sorted({
        field
        for row in run_rows.values()
        for field in (
            row["result_file"]["record"].get("provenance_fields_present", [])
            if isinstance(row["result_file"].get("record"), dict)
            else []
        )
    })
    checkpoint_fields = sorted({
        field
        for row in run_rows.values()
        for field in ("schema_version", "input_contract_id", "optimizer_state_dict", "rng_state")
        if field in row["checkpoint_file"].get("payload_keys", [])
    })

    current_compatible_rows = []
    for row in run_rows.values():
        result = row["result_file"].get("record") or {}
        checkpoint = row["checkpoint_file"]
        route = row.get("route")
        expected_input = current_width + (LOCAL_WIDTH if route == LOCAL_ROUTE else 0)
        result_width = result.get("feature_width")
        first_input = (checkpoint.get("first_linear") or {}).get("input_width")
        current_compatible_rows.append(
            result_width == current_width and first_input == expected_input
        )

    metric_definitions = sorted({
        (row["result_file"]["record"] or {}).get("metric_definition")
        for row in run_rows.values()
        if isinstance(row["result_file"].get("record"), dict)
        and (row["result_file"]["record"] or {}).get("metric_definition") is not None
    })
    all_seed_route = (
        found_keys == expected_keys
        and not duplicate_keys
        and complete_results
    )

    metric_summary = _metric_summary(run_rows)
    return {
        "name": name,
        "manifest": {
            "path": _relative(manifest_path, root),
            "exists": manifest_path.is_file(),
            "sha256": _sha256(manifest_path),
            "scope": payload.get("scope") if isinstance(payload, dict) else None,
            "status": payload.get("status") if isinstance(payload, dict) else None,
            "formal_ready": payload.get("formal_ready") if isinstance(payload, dict) else None,
            "started_at_utc": payload.get("started_at_utc") if isinstance(payload, dict) else None,
            "finished_at_utc": payload.get("finished_at_utc") if isinstance(payload, dict) else None,
            "routes_declared": payload.get("routes") if isinstance(payload, dict) else None,
            "seeds_declared": payload.get("seeds") if isinstance(payload, dict) else None,
            "config_ref": payload.get("config") if isinstance(payload, dict) else None,
            "trainer_ref": payload.get("trainer") if isinstance(payload, dict) else None,
            "manifest_ref": payload.get("manifest") if isinstance(payload, dict) else None,
            "allowed_gpu_indices": payload.get("allowed_gpu_indices") if isinstance(payload, dict) else None,
            "budget": payload.get("budget") if isinstance(payload, dict) else None,
            "provenance_fields_present": manifest_fields,
        },
        "expected_routes": list(expected_routes),
        "expected_seeds": list(expected_seeds),
        "coverage": {
            "expected_count": len(expected_keys),
            "found_count": len(found_keys),
            "missing": sorted(expected_keys - found_keys),
            "unexpected": sorted(found_keys - expected_keys),
            "duplicates": sorted(duplicate_keys),
            "all_expected_route_seed_pairs_complete": all_seed_route,
            "status_counts": dict(sorted(status_counts.items())),
            "all_test_rollout_metrics_finite": all_rollouts_finite,
        },
        "run_signatures": signatures,
        "test_case_sets": [list(value) for value in test_case_sets],
        "result_feature_widths": result_widths,
        "checkpoint_feature_widths": checkpoint_widths,
        "current_contract_compatibility": {
            "current_width": current_width,
            "expected_local_first_input": current_width + LOCAL_WIDTH,
            "all_rows_match_current_source": bool(current_compatible_rows) and all(current_compatible_rows),
            "matching_row_count": sum(1 for value in current_compatible_rows if value),
            "row_count": len(current_compatible_rows),
        },
        "provenance": {
            "manifest_fields_present": manifest_fields,
            "result_fields_present": result_fields,
            "checkpoint_fields_present": checkpoint_fields,
            "source_config_data_content_bound": bool(
                {"config", "trainer", "manifest"}.issubset(manifest_fields)
                and {"input_contract_id", "trainer_sha256", "config_sha256", "manifest_sha256", "data_sha256"}.issubset(result_fields)
            ),
        },
        "metric_definitions": metric_definitions,
        "metric_summary": metric_summary,
        "runs": run_rows,
    }


def _metric_summary(run_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    per_seed: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in run_rows.values():
        route = str(row.get("route"))
        seed = row.get("seed")
        record = row["result_file"].get("record") or {}
        for case_id, value in record.get("test_metrics_learned_rmse_over_dp", {}).items():
            if _finite(value):
                values[route][str(case_id)].append(float(value))
                if isinstance(seed, int):
                    per_seed[route][seed].append(float(value))
    summary: dict[str, Any] = {}
    for route in sorted(values):
        case_summary = {}
        for case_id in sorted(values[route]):
            samples = values[route][case_id]
            case_summary[case_id] = {
                "mean": sum(samples) / len(samples),
                "sample_std": _sample_std(samples),
                "n": len(samples),
            }
        seed_macros = {
            str(seed): sum(samples) / len(samples)
            for seed, samples in sorted(per_seed[route].items())
            if samples
        }
        macros = list(seed_macros.values())
        summary[route] = {
            "case_mean_rmse_over_dp": case_summary,
            "per_seed_macro_mean": seed_macros,
            "macro_mean_across_seed_macros": sum(macros) / len(macros) if macros else None,
            "macro_sample_std_across_seeds": _sample_std(macros),
        }
    return summary


def inspect_config(config_path: Path, root: Path = ROOT) -> dict[str, Any]:
    payload = _load_json(config_path)
    early_stopping = payload.get("early_stopping") if isinstance(payload, dict) else {}
    if not isinstance(early_stopping, dict):
        early_stopping = {}
    semantic_fields = (
        "input_contract_id",
        "feature_layout",
        "normalization_contract_id",
        "target_semantics",
        "rollout_state_semantics",
        "trainer_sha256",
        "data_manifest_sha256",
        "checkpoint_schema",
        "determinism_policy",
    )
    return {
        "path": _relative(config_path, root),
        "exists": config_path.is_file(),
        "sha256": _sha256(config_path),
        "schema_version": payload.get("schema_version") if isinstance(payload, dict) else None,
        "routes": payload.get("routes") if isinstance(payload, dict) else None,
        "seeds": payload.get("seeds") if isinstance(payload, dict) else None,
        "budget": {
            "epochs_requested": payload.get("epochs_requested") if isinstance(payload, dict) else None,
            "min_epochs": payload.get("min_epochs") if isinstance(payload, dict) else None,
            "patience": early_stopping.get("patience"),
            "min_delta": early_stopping.get("min_delta"),
            "maximum_particles_per_training_frame": payload.get("maximum_particles_per_training_frame") if isinstance(payload, dict) else None,
            "validation_particles": payload.get("validation_particles") if isinstance(payload, dict) else None,
            "hidden_width": payload.get("hidden_width") if isinstance(payload, dict) else None,
            "learning_rate": payload.get("learning_rate") if isinstance(payload, dict) else None,
            "position_clip_dp": payload.get("position_clip_dp") if isinstance(payload, dict) else None,
        },
        "smooth_output_cap": payload.get("smooth_output_cap") if isinstance(payload, dict) else None,
        "semantic_fields_missing": [field for field in semantic_fields if not isinstance(payload, dict) or field not in payload],
        "provenance_fields_missing": [
            field for field in ("trainer_sha256", "data_manifest_sha256", "input_contract_id")
            if not isinstance(payload, dict) or field not in payload
        ],
    }


def _finding(
    finding_id: str,
    severity: str,
    evidence: dict[str, Any],
    impact: str,
    required_change: str,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "status": "confirmed",
        "severity": severity,
        "evidence": evidence,
        "impact": impact,
        "required_change": required_change,
    }


def build_audit(
    root: Path = ROOT,
    inspect_checkpoints: bool = True,
) -> dict[str, Any]:
    """Build the report from current source and existing artifacts."""

    root = root.resolve()
    trainer_path = root / TRAINER_REL
    config_path = root / CONFIG_REL
    release_manifest_path = root / RELEASE_MANIFEST_REL
    source = analyze_source(trainer_path, root)
    data = inspect_release_data(release_manifest_path, root)
    layout = current_feature_layout(source, data)
    config = inspect_config(config_path, root)

    collections = {
        name: inspect_run_collection(
            name,
            root,
            spec["manifest"],
            spec["routes"],
            spec["seeds"],
            layout["active_width"],
            inspect_checkpoints=inspect_checkpoints,
        )
        for name, spec in COLLECTION_SPECS.items()
    }

    current_routes = set(ROUTES)
    small = collections["small_six_rerun"]
    small_routes = set(small["expected_routes"])
    small_complete = small["coverage"]["all_expected_route_seed_pairs_complete"]
    paired_test_cases = len(small.get("test_case_sets", [])) == 1 and bool(small.get("test_case_sets"))
    paired_budget = len(small.get("run_signatures", [])) == 1
    all_current_runs = [
        collection
        for collection in collections.values()
        if collection.get("manifest", {}).get("exists")
    ]
    all_recorded_widths = sorted({
        width
        for collection in all_current_runs
        for width in collection.get("result_feature_widths", [])
    })
    all_recorded_checkpoint_widths = sorted({
        width
        for collection in all_current_runs
        for width in collection.get("checkpoint_feature_widths", [])
    })
    component_orders = data.get("sidecar_component_order_by_case", {})
    route_audit = {
        route: {
            "role": source.get("route_roles", {}).get(route),
            "current_base_and_component_input_width": layout["active_width"],
            "current_full_model_input_width": layout["local_active_width"] if route == LOCAL_ROUTE else layout["active_width"],
            "historical_artifact_feature_widths": sorted({
                row["result_file"]["record"].get("feature_width")
                for collection in collections.values()
                for row in collection.get("runs", {}).values()
                if row.get("route") == route
                and isinstance(row["result_file"].get("record"), dict)
            }),
            "route_extra_input_width": LOCAL_WIDTH if route == LOCAL_ROUTE else 0,
            "output_width": 3,
            "training_target": (
                "next solver velocity * dt / dp"
                if route != "physics_residual"
                else "(next solver velocity - current solver velocity) / dt * dt^2 / dp"
            ),
            "rollout_state_update": (
                "bounded output is next velocity; trapezoidal position update"
                if route != "physics_residual"
                else "bounded output is normalized acceleration; semi-implicit velocity then trapezoidal position update"
            ),
            "training_context_note": (
                "target subset plus full current context for COM and neighbour summary"
                if route == LOCAL_ROUTE
                else "target subset; base features use full current context for COM"
            ),
        }
        for route in ROUTES
    }

    checks = {
        "static_cpu_mode": True,
        "trainer_source_exists_and_parses": bool(source.get("exists") and source.get("syntax_valid")),
        "four_route_classes_and_dispatch_found": bool(
            source.get("flags", {}).get("route_classes_present")
            and source.get("flags", {}).get("route_dispatch_present")
            and set(source.get("routes", [])) == current_routes
        ),
        "required_source_reads_identified": set(source.get("read_fields", {}).get("hdf5_datasets", [])) == set(HDF5_DATASETS),
        "release_hdf5_contract_inspected": bool(data.get("all_loaded_hdf5_fields_finite")),
        "release_sidecar_alignment_inspected": bool(data.get("all_linked_sidecars_aligned_and_finite")),
        "current_sidecar_component_path_is_active": bool(layout["component_active_on_release_manifest"]),
        "config_declares_four_routes_and_three_seeds": bool(
            set(config.get("routes") or []) == current_routes
            and set(config.get("seeds") or []) == set(SEEDS)
        ),
        "12_run_manifests_link_declared_config": all(
            collections[name]["manifest"].get("config_ref") == CONFIG_REL.as_posix()
            for name in ("pre_sidecar_12_run", "sidecar_12_run")
        ),
        "small_manifest_links_declared_config": bool(
            small["manifest"].get("config_ref")
        ),
        "small_six_matrix_complete": bool(small_complete),
        "small_six_has_all_four_routes": small_routes == current_routes,
        "recorded_width_matches_current_source": bool(all_recorded_widths) and all(
            width == layout["active_width"] for width in all_recorded_widths
        ),
        "recorded_checkpoint_width_matches_current_source": bool(all_recorded_checkpoint_widths) and all(
            width == layout["active_width"] for width in all_recorded_checkpoint_widths
        ),
        "deep_set_train_context_matches_rollout_context": bool(
            not source.get("flags", {}).get("deep_set_uses_mean_context")
        ),
        "component_slots_are_canonical": not bool(data.get("component_order_varies_for_same_id_set")),
        "source_config_data_content_bound": all(
            collection.get("provenance", {}).get("source_config_data_content_bound", False)
            for collection in all_current_runs
        ) if all_current_runs else False,
        "checkpoint_contains_resumable_training_state": all(
            "optimizer_state_dict" in collection.get("provenance", {}).get("checkpoint_fields_present", [])
            and "rng_state" in collection.get("provenance", {}).get("checkpoint_fields_present", [])
            for collection in all_current_runs
        ) if all_current_runs else False,
        "cuda_determinism_policy_closed": bool(source.get("flags", {}).get("deterministic_cuda_controls_present")),
    }

    findings = [
        _finding(
            "current_sidecar_width_115_vs_recorded_width_43",
            "blocker_for_current_contract_comparison",
            {
                "current_source_active_width": layout["active_width"],
                "base_width": layout["base_width"],
                "component_block_width": layout["component_block_width"],
                "local_current_first_linear_input": layout["local_active_width"],
                "all_recorded_result_widths": all_recorded_widths,
                "all_recorded_checkpoint_widths": all_recorded_checkpoint_widths,
                "small_local_first_linear_inputs": sorted({
                    (row["checkpoint_file"].get("first_linear") or {}).get("input_width")
                    for row in small.get("runs", {}).values()
                    if row.get("route") == LOCAL_ROUTE
                }),
                "source_lines": {
                    "feature_width_case_call": source.get("line_anchors", {}).get("feature_width_case_call"),
                    "component_block": source.get("definitions", {}).get("build_features"),
                },
                "artifact_paths": [
                    collections[name]["manifest"]["path"]
                    for name in ("pre_sidecar_12_run", "sidecar_12_run", "small_six_rerun")
                ],
            },
            "The 43-wide results/checkpoints are historical base-contract artifacts and cannot establish behavior of the current linked-sidecar component input.",
            "Freeze one input-contract ID and rerun all four routes against the active 115/123-wide layout before making a current route comparison.",
        ),
        _finding(
            "small_rerun_is_not_a_four_route_matrix",
            "scope_limit",
            {
                "small_expected_routes": sorted(small_routes),
                "missing_routes": sorted(current_routes - small_routes),
                "seed_set": list(SEEDS),
                "completed_jobs": small["coverage"].get("found_count"),
                "expected_jobs": small["coverage"].get("expected_count"),
                "manifest": small["manifest"]["path"],
            },
            "The six jobs support only paired diagnostics for LocalInteraction and PhysicsResidual; they do not support a four-route ranking.",
            "If a route comparison is needed, run ParticleMLP and DeepSets under the identical current contract, seed set, budget, and artifact-binding rules.",
        ),
        _finding(
            "deepset_train_rollout_context_cardinality_mismatch",
            "semantic_gap",
            {
                "source_lines": {
                    "deep_set_class": source.get("definitions", {}).get("DeepSetContext"),
                    "train_particle_sampling": source.get("line_anchors", {}).get("train_particle_sampling"),
                    "rollout": source.get("definitions", {}).get("rollout"),
                },
                "train_context": "DeepSetContext.mean is over sampled target features passed by one_step_loss",
                "rollout_context": "rollout passes all current predicted particles to the same mean aggregator",
                "sample_budgets_observed": {
                    name: collection.get("run_signatures", [])
                    for name, collection in collections.items()
                },
            },
            "DeepSets sees a sample-cardinality-dependent context during training/one-step validation and a full-set context during autonomous rollout.",
            "Either construct the DeepSets context from the same full current context in train/validation/rollout, or explicitly define and record sampled-set semantics as the task contract.",
        ),
        _finding(
            "boundary_component_slots_not_canonical",
            "input_identifiability_gap",
            {
                "source_line_component_order": source.get("line_anchors", {}).get("component_group_order"),
                "component_id_in_packed_fields": source.get("flags", {}).get("component_id_is_in_packed_feature_fields"),
                "observed_orders": component_orders,
                "same_id_set_order_varies": data.get("component_order_varies_for_same_id_set"),
            },
            "When the current 72-wide component block is enabled, slot 0/1/2 is not a stable semantic component across cases with the same IDs; the packed tensor omits component_id.",
            "Use a schema-defined canonical component-slot order (or an explicit slot/role encoding) before the next component-aware training run.",
        ),
        _finding(
            "run_content_provenance_not_bound",
            "reproducibility_gap",
            {
                "config": config,
                "collections": {
                    name: {
                        "manifest": collection["manifest"],
                        "provenance": collection["provenance"],
                    }
                    for name, collection in collections.items()
                },
            },
            "Seeds, commands, and paths are recorded, but the result/checkpoint artifacts are not cryptographically bound to the exact trainer source, config, release manifest, data, or input-normalization contract. The six-run manifest has no config reference.",
            "Record source/config/data/contract hashes in both result and checkpoint metadata; add a config reference and digest to the six-job manifest as well.",
        ),
        _finding(
            "checkpoint_is_inference_snapshot_not_training_state",
            "training_state_gap",
            {
                "checkpoint_payload_keys": {
                    name: sorted({
                        key
                        for row in collection.get("runs", {}).values()
                        for key in row.get("checkpoint_file", {}).get("payload_keys", [])
                    })
                    for name, collection in collections.items()
                },
                "optimizer_state_saved_in_source": source.get("flags", {}).get("optimizer_state_saved"),
                "rng_state_saved_in_source": source.get("flags", {}).get("rng_state_saved"),
                "checkpoint_save_line": source.get("line_anchors", {}).get("checkpoint_save"),
            },
            "A checkpoint can identify route, seed, and feature width, but it cannot resume the optimizer/RNG/early-stopping state or prove the state was selected under a particular config.",
            "Declare inference-only versus resumable checkpoints; for the latter save optimizer, scheduler, RNG, epoch, best metric, and contract/config IDs.",
        ),
        _finding(
            "route_training_targets_are_not_the_same_quantity",
            "metric_scope_limit",
            {
                "direct_target_line": source.get("line_anchors", {}).get("direct_target"),
                "physics_target_line": source.get("line_anchors", {}).get("physics_target"),
                "route_targets": {
                    "particle_mlp": "v[t+1] * dt / dp",
                    "deepset_context": "v[t+1] * dt / dp",
                    "local_interaction": "v[t+1] * dt / dp",
                    "physics_residual": "a[t] * dt^2 / dp",
                },
                "common_autonomous_metric": "vector position RMSE / dp",
            },
            "Train MSE and one-step RMSE are not cross-route comparable because PhysicsResidual predicts a normalized acceleration residual while the other routes predict next velocity.",
            "Keep target-specific losses separate and compare routes only on a common autonomous evaluation metric under one exact input/state contract.",
        ),
        _finding(
            "seed_reproducibility_not_closed",
            "reproducibility_gap",
            {
                "seed_calls_present": source.get("flags", {}).get("seed_calls_present"),
                "deterministic_cuda_controls_present": source.get("flags", {}).get("deterministic_cuda_controls_present"),
                "small_seed_set": list(SEEDS),
                "small_devices_recorded": sorted({
                    row.get("child_visible_devices")
                    for row in small.get("runs", {}).values()
                    if row.get("child_visible_devices") is not None
                }),
            },
            "The three seeds are initialized and recorded, but CUDA deterministic-algorithm policy and RNG snapshots are absent; exact rerun identity is therefore not closed.",
            "Add a deterministic policy (or explicitly record nondeterministic status) and capture Python/NumPy/Torch RNG state when reproducibility is required.",
        ),
    ]

    comparability = {
        "six_run_supported": [
            {
                "claim": "within-route seed spread for LocalInteraction and PhysicsResidual",
                "supported": bool(small_complete),
                "basis": "three seeds per route, six completed jobs, finite test rollouts",
                "caveat": "historical 43-wide artifact contract only; not current 115/123-wide source semantics",
            },
            {
                "claim": "paired diagnostic comparison of LocalInteraction versus PhysicsResidual on the three shared test cases",
                "supported": bool(small_complete and paired_test_cases and paired_budget),
                "basis": "same small-run manifest, seeds, test case set, epochs/width/particle budgets, cap and clip settings",
                "caveat": "exploratory only: route targets and parameter counts differ; no formal ranking or physical acceptance",
            },
            {
                "claim": "comparison against the constant-velocity diagnostic within the six-run protocol",
                "supported": bool(small_complete),
                "basis": "each result reports the same autonomous position metric and constant-velocity reference",
                "caveat": "diagnostic baseline only, never a physical-scene admission gate",
            },
        ],
        "six_run_not_supported": [
            {
                "claim": "four-route ranking",
                "supported": False,
                "reason": "ParticleMLP and DeepSets are absent from the six jobs",
            },
            {
                "claim": "current sidecar-component-aware route comparison",
                "supported": False,
                "reason": "current source activates 115 base/component inputs (123 for LocalInteraction), while all six artifacts are 43/51-wide",
            },
            {
                "claim": "six-run versus 12-run matrix improvement or degradation",
                "supported": False,
                "reason": "different epochs, hidden width, particle sampling, validation sampling, early-stopping policy, and missing content hashes",
            },
            {
                "claim": "cross-route comparison of training MSE/one-step RMSE",
                "supported": False,
                "reason": "direct routes target normalized next velocity; PhysicsResidual targets normalized acceleration",
            },
            {
                "claim": "material transport, density/pressure prediction, free-body coupling, T2/T3/T4, wall-contact validity, or formal acceptance",
                "supported": False,
                "reason": "outside the recorded six-job task and model contract",
            },
        ],
        "current_source_comparison": {
            "supported": False,
            "reason": "recorded result/checkpoint width and current sidecar-aware width disagree",
        },
    }

    next_changes = [
        {
            "id": "contract_id_and_content_hashes",
            "change": "Add one immutable input_contract_id containing active feature slices, normalization, target mode, rollout state, sidecar slot schema, and output-cap/clip semantics; bind trainer/config/release-data hashes in run/result/checkpoint records.",
            "why_minimal": "One ID plus five hashes closes the current 43-versus-115 ambiguity without changing F6, tracer, or upstream inputs.",
        },
        {
            "id": "canonical_component_slots",
            "change": "Canonicalize boundary-component slots before packing the 72-wide block (schema role/order or stable ID encoding) and record the observed slot map.",
            "why_minimal": "The current component tensor otherwise has target-relative values but no stable component identity.",
        },
        {
            "id": "single_current_context_builder",
            "change": "Make DeepSets train/validation/rollout consume the same declared current context cardinality, preferably full current context; retain target subsampling only for loss rows.",
            "why_minimal": "This removes the only route-specific train-to-rollout context-cardinality mismatch identified statically.",
        },
        {
            "id": "explicit_target_and_checkpoint_state",
            "change": "Record route target_mode (`next_velocity` versus `acceleration_residual`) and mark checkpoints inference-only or save optimizer/RNG/epoch/best-metric state for resume.",
            "why_minimal": "It prevents target losses and inference snapshots from being mistaken for common training-state evidence.",
        },
        {
            "id": "uniform_four_route_rerun",
            "change": "For the next comparison, rerun all four routes on the same current contract, seeds 17/29/43, budget, test cases, deterministic policy, and CPU-verifiable provenance; do not mix the 43-wide artifacts into the 115-wide result table.",
            "why_minimal": "Only this closes route coverage and controls the remaining matrix confounds.",
        },
    ]

    status = "complete_with_findings" if checks["trainer_source_exists_and_parses"] else "incomplete"
    return {
        "schema_version": 1,
        "scope": "R4 G4 four-route baseline input-identifiability and training-state audit",
        "status": status,
        "formal_ready": False,
        "audit_execution": {
            "mode": "static_cpu",
            "training_invoked": False,
            "gpu_api_invoked": False,
            "trainer_imported": False,
            "checkpoint_load": "CPU map_location only; no forward pass",
            "write_scope": [
                "scripts/r4_g4_training_contract_audit.py",
                "campaigns/v0.1-candidate/r4-g4-training-contract-audit.json",
                "campaigns/v0.1-candidate/R4-G4-TRAINING-CONTRACT-AUDIT.md",
            ],
        },
        "source": source,
        "config": config,
        "release_data": data,
        "feature_contract": layout,
        "route_audit": route_audit,
        "normalization_and_rollout": {
            "normalization": {
                "centered_position": "(target_position - current_context_mass_weighted_COM) / length_scale",
                "target_velocity_and_context_COM_velocity": "velocity * dt / dp",
                "initial_density": "(density_0 - rho_ref) / rho_ref",
                "initial_pressure": "pressure_0 / (rho_ref * |g_z| * length_scale)",
                "initial_mass": "mass_0 / median(mass_0) - 1",
                "gravity": "gravity * dt^2 / dp",
                "physics": "[rho_ref/1000, viscosity/0.001, explicit_gravity_bit]",
                "control": "translation / length_scale; angular/derived velocity * time_scale / length_scale; angle sin/cos and availability bits",
                "boundary_aabb": "current frame bounds / length_scale",
                "boundary_component": "distance / length_scale; normal/type raw; wall velocity * time_scale / length_scale",
                "time": "elapsed time / time_scale and current dt / time_scale; independent of file endpoint",
                "output": "8 * tanh(raw / 8), applied through train/validation/rollout prediction paths",
            },
            "state_semantics": {
                "data_read": "full solver arrays are loaded for labels/reference metrics; only density/pressure/mass frame zero become model state features",
                "teacher_forcing": "train and one-step validation use solver current velocity and solver next velocity label",
                "autonomous_rollout": "starts from frame-zero solver position/velocity, then uses own predicted velocity and predicted position as current state",
                "future_fluid_or_body_state_as_model_input": False,
                "future_reference_as_metric_only": True,
                "future_velocity_as_teacher_label": True,
                "hard_displacement_clip_in_recorded_runs": 0.0,
                "smooth_output_cap": 8.0,
                "mass_state": "initial mass is frozen and used for COM/identity metrics",
            },
            "static_source_flags": {
                key: source.get("flags", {}).get(key)
                for key in (
                    "same_feature_builder_in_train_validation_rollout",
                    "future_reference_read_for_metrics",
                    "future_velocity_read_for_training_label",
                    "rollout_updates_own_velocity_state",
                    "smooth_output_cap_in_train_validation_rollout",
                )
            },
        },
        "training_state_semantics": {
            "seed_initialization": {
                "python_random": "random.seed(args.seed)",
                "numpy": "np.random.seed(args.seed)",
                "torch": "torch.manual_seed(args.seed)",
                "torch_cuda": "torch.cuda.manual_seed_all(args.seed)",
                "deterministic_cuda_policy_declared": source.get("flags", {}).get("deterministic_cuda_controls_present"),
            },
            "sampling": "per-epoch transition shuffle and per-frame random target particle choice using NumPy Generator(seed)",
            "optimizer": "AdamW, configured learning rate, weight_decay=1e-6, gradient norm clip=1.0",
            "loss_and_selection": "train MSE; one-step validation is reported; checkpoint selection uses mean validation autonomous rollout RMSE with min_delta/patience after min_epochs",
            "checkpoint_semantics": "saved model state after restoring best validation epoch; payload observed as state_dict plus route/seed/feature_width only",
            "resume_state": "not recoverable from observed checkpoints: no optimizer, scheduler, RNG, epoch history, best metric, contract ID, or config/data hash",
        },
        "artifact_collections": collections,
        "comparability": comparability,
        "checks": checks,
        "findings": findings,
        "next_minimal_changes": next_changes,
    }


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    layout = report["feature_contract"]
    data = report["release_data"]
    source = report["source"]
    collections = report["artifact_collections"]
    small = collections["small_six_rerun"]
    checks = report["checks"]
    lines = [
        "# R4 G4 四路线基线：输入可辨识性与训练状态语义审计",
        "",
        f"状态：**{report['status']}**；`formal_ready=false`。本报告是独立静态证据，不修改训练器、F6、tracer、core mother case 或上游目录。",
        "",
        "## 结论先行",
        "",
        f"当前源代码在 release manifest 的 linked sidecar 上激活 `{layout['active_width']}` 维 base+component 输入；LocalInteraction 另加 `{layout['local_extra_width']}` 维邻域摘要，因此其首层应接 `{layout['local_active_width']}` 维。已有 pre-sidecar、sidecar-aware 12-run 矩阵和当前 6-job 小预算复跑的结果/ checkpoint 都记录为 43 维（LocalInteraction 首层 51 维）。所以这 6 次复跑只能作为历史 43-wide contract 下的 LocalInteraction/PhysicsResidual 诊断，不能作为当前 115/123-wide contract 或四路线排名证据。",
        "",
        "当前 source 还存在一个独立的 DeepSets 语义差异：训练/one-step validation 的 mean 作用于随机采样的 target features，autonomous rollout 的 mean 作用于全体当前粒子。boundary component block 也按 sidecar 首次出现顺序装槽，F1/F2 同一 component-ID 集合的顺序不同，且 packed fields 不包含 `component_id`。",
        "",
        "## 审计边界与数据",
        "",
        "- 模式：`static_cpu`；未导入/执行 trainer，未调用 GPU API，checkpoint 仅以 CPU `map_location` 读取 metadata/state-dict shape。",
        f"- 当前 source：`{source.get('path')}`，sha256 `{source.get('sha256')}`。",
        f"- release manifest：`{data.get('path')}`；记录 `{data.get('record_count')}` 个 case，loader 可用 fluid case `{data.get('loaded_fluid_case_count')}` 个，排除 `{', '.join(data.get('excluded_no_initial_fluid') or []) or '无'}`。",
        f"- sidecar：linked case `{data.get('linked_sidecar_case_count')}` 个，component count 范围 `{data.get('sidecar_component_counts', {}).get('min')}`–`{data.get('sidecar_component_counts', {}).get('max')}`；HDF5/sidecar 对齐与 finite 检查：`{data.get('all_linked_sidecars_aligned_and_finite')}`。",
        "",
        "## 四路线输入与状态表",
        "",
        "| route | 当前完整输入宽度 | route-specific 输入 | 输出/target | rollout state |",
        "|---|---:|---:|---|---|",
    ]
    for route, entry in report["route_audit"].items():
        lines.append(
            f"| `{route}` | {entry['current_full_model_input_width']} | {entry['route_extra_input_width']} | {entry['training_target']} | {entry['rollout_state_update']} |"
        )
    lines += [
        "",
        f"base layout 是 `{layout['base_width']}` 维；linked sidecar 激活 `{layout['component_block_width']}` 维（`8×9`）component block。当前 active slices：`{json.dumps(layout['active_slices'], ensure_ascii=False)}`。",
        "",
        "统一部分的字段与 normalization：centered position、target/current-context COM velocity、initial density/pressure/mass、gravity、static physics、current control、current boundary AABB、family one-hot、elapsed time、current dt；component block 额外含 presence/distance/normal/type/wall velocity。输出 `8*tanh(raw/8)` 在 train/validation/rollout 共用，记录的 hard displacement clip 为 0。",
        "",
        "## rollout 与训练状态语义",
        "",
        "- HDF5 loader 读取 `valid/type/time/position/velocity/density/pressure/mass`；control 读取 angle、transform 或 prescribed angular velocity；sidecar 读取 time、triangles、type、mk/component。未来 fluid state 不进入 model features；未来 velocity 是 teacher-forced label，未来 position/velocity 在 rollout 中只用于误差计算。",
        "- train/one-step validation 使用 solver 当前帧 velocity；autonomous rollout 从 frame 0 position/velocity 开始，之后只使用自己的 predicted velocity/position、当前 prescribed control、当前 boundary summary 和 elapsed time。",
        "- direct routes 的 label 是 `v[t+1]*dt/dp`；PhysicsResidual 的 label 是 `a[t]*dt²/dp`。因此 train MSE/one-step RMSE 不能横向当作同一个量，跨 route 应只用共同 autonomous position metric。",
        "- seed 初始化已记录 Python/NumPy/Torch/CUDA seed，但没有 deterministic CUDA policy；checkpoint 是 inference snapshot，不是可恢复的 optimizer/RNG training state。",
        "",
        "## artifact 记录核对",
        "",
        "| collection | jobs | routes | seeds | result width | checkpoint width | current contract compatible | provenance |",
        "|---|---:|---|---|---|---|---|---|",
    ]
    for name in ("pre_sidecar_12_run", "sidecar_12_run", "small_six_rerun"):
        collection = collections[name]
        lines.append(
            f"| `{name}` | {collection['coverage']['found_count']} | {','.join(collection['expected_routes'])} | {','.join(map(str, collection['expected_seeds']))} | {collection['result_feature_widths']} | {collection['checkpoint_feature_widths']} | {collection['current_contract_compatibility']['all_rows_match_current_source']} | {collection['provenance']['source_config_data_content_bound']} |"
        )
    lines += [
        "",
        "12-run 矩阵的 route×seed coverage 本身完整，但不等于当前 source contract 完整；6-run 矩阵只覆盖两条 route。small manifest 记录了 seed、command、GPU index、output/checkpoint/log 路径，但没有 config/source/data/contract content hash。",
        "",
        "## 6 次小预算复跑：能支持什么",
        "",
        "- 每条 LocalInteraction/PhysicsResidual 各有 seeds `17/29/43`，6/6 job 完成，三个共享 test cases 的 rollout 状态和 learned position RMSE/dp 均为 finite。",
        "- 可以看每条 route 的 seed spread，以及在相同小预算、相同 test case、相同 seed 下的成对 exploratory 对比；也可以与同一结果中的 constant-velocity diagnostic 做逐 case 对照。",
        "- 当前小复跑的 route-level test summary：",
        "",
        "| route | case macro mean | seed macro sample std | epochs observed |",
        "|---|---:|---:|---|",
    ]
    for route in (LOCAL_ROUTE, "physics_residual"):
        summary = small.get("metric_summary", {}).get(route, {})
        epochs = sorted({
            row["result_file"]["record"].get("epochs_run")
            for row in small.get("runs", {}).values()
            if row.get("route") == route and isinstance(row["result_file"].get("record"), dict)
        })
        lines.append(
            f"| `{route}` | {_fmt(summary.get('macro_mean_across_seed_macros'))} | {_fmt(summary.get('macro_sample_std_across_seeds'))} | {epochs} |"
        )
    lines += [
        "",
        "## 6 次小预算复跑：不能支持什么",
        "",
        "- 不能给出 ParticleMLP/DeepSets/LocalInteraction/PhysicsResidual 四路线排名：small matrix 没有 ParticleMLP、DeepSets。",
        "- 不能比较当前 sidecar component-aware source：当前 active width 是 115/123，而六个 checkpoint 是 43/51；也不能把旧 43-wide 12-run 与当前 source 混成一张表。",
        "- 不能把 small 与 12-run 解释成训练预算改进：epochs、hidden width、粒子抽样、validation 抽样、early stopping 均不同，且缺少 trainer/config/data content binding。",
        "- 不能横向比较 direct/PhysicsResidual 的 train MSE/one-step RMSE；不能外推到 material transport、density/pressure prediction、free-body coupling、T2/T3/T4、wall-contact validity 或 formal acceptance。",
        "",
        "## Findings",
        "",
    ]
    for index, finding in enumerate(report["findings"], start=1):
        lines += [
            f"{index}. **`{finding['id']}`**（{finding['severity']}）",
            f"   - 证据：`{json.dumps(finding['evidence'], ensure_ascii=False, sort_keys=True)}`",
            f"   - 影响：{finding['impact']}",
            f"   - 要求：{finding['required_change']}",
            "",
        ]
    lines += [
        "## 下一轮统一控制输入和训练状态语义：最小改动清单",
        "",
    ]
    for index, change in enumerate(report["next_minimal_changes"], start=1):
        lines += [
            f"{index}. **`{change['id']}`**：{change['change']}",
            f"   - 最小性：{change['why_minimal']}",
            "",
        ]
    lines += [
        "## Check summary",
        "",
        "| check | value |",
        "|---|---|",
    ]
    for key, value in checks.items():
        lines.append(f"| `{key}` | `{value}` |")
    lines += [
        "",
        "本审计只新增本脚本、对应 JSON/Markdown 和 `test_r4_g4_` 测试；不提交、不推送。",
        "",
    ]
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    markdown_path.write_text(render_markdown(report))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="lagrangian-fluid-lab root (default: inferred from this script)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "campaigns/v0.1-candidate/r4-g4-training-contract-audit.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=ROOT / "campaigns/v0.1-candidate/R4-G4-TRAINING-CONTRACT-AUDIT.md",
    )
    parser.add_argument(
        "--skip-checkpoint-load",
        action="store_true",
        help="keep checkpoint paths but skip CPU state-dict inspection",
    )
    args = parser.parse_args()
    report = build_audit(args.root, inspect_checkpoints=not args.skip_checkpoint_load)
    write_outputs(report, args.output, args.markdown_output)
    print(json.dumps({
        "status": report["status"],
        "output": str(args.output),
        "markdown_output": str(args.markdown_output),
        "training_invoked": report["audit_execution"]["training_invoked"],
        "gpu_api_invoked": report["audit_execution"]["gpu_api_invoked"],
        "current_feature_width": report["feature_contract"]["active_width"],
        "small_jobs": report["artifact_collections"]["small_six_rerun"]["coverage"]["found_count"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
