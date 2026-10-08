#!/usr/bin/env python3
"""Build the source-bound mechanism and impact-bound ledger for 118 cases.

This forward-only audit consumes the completed scan/native sidecars already
bound by the all-118 impact-stream v2 manifest.  It deliberately does not
open trajectory H5 files, Part_*.bi4 frames, or start a decoder/solver.  A
native position or density exclusion identifies the numerical gate that
removed a source-visible particle; it does not identify a physical spill,
transport destination, re-entry, or a force/impulse error.  The report keeps
those quantities as explicit intervals/UNKNOWN values and records the first
missing bracket as a censoring interval.

The repair controls in the output are preregistered designs only.  They keep
mass, dp, geometry, motion, and physics fixed and vary at most the numerical
gate/domain factor named by the family.  No control is claimed to have run.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V2_MANIFEST_DEFAULT = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "omission-task-impact-stream-v2/omission-task-impact-stream-v2-manifest.json"
)
V2_REQUEST_DEFAULT = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "omission-task-impact-stream-v2/omission-task-impact-stream-v2-request.json"
)
V2_SCRIPT = SCRIPT.parent / "ds_data02_stage2_omission_task_impact_stream_v2.py"
V1_SCRIPT = SCRIPT.parent / "ds_data02_stage2_omission_task_impact_stream_v1.py"
RUNTIME_V4 = SCRIPT.parent / "ds_data02_runtime_v4.py"
RUNTIME_V2 = SCRIPT.parent / "ds_data02_runtime_v2.py"
DISPATCH_V4 = SCRIPT.parent / "ds_data02_stage2_dispatch_v4.py"
STRICT_V4 = SCRIPT.parent / "ds_data02_strict_dispatch_v4.py"
MANIFEST_SCHEMA = "ds02.stage2.omission-mechanism-bounds-manifest.v1"
OUTPUT_SCHEMA = "ds02.stage2.omission-mechanism-bounds.v1"
CASE_COUNTS = {"F2": 48, "F4": 22, "F6": 48}
MASS_GATE = 0.003


class MechanismBoundsError(RuntimeError):
    """Raised when source identity or the conservative-bound contract opens."""


def sha256(value: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(value).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise MechanismBoundsError(f"{label} is missing: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MechanismBoundsError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise MechanismBoundsError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise MechanismBoundsError(f"refuse to overwrite existing output: {path}")
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def file_binding(value: Path | str, label: str = "source") -> dict[str, Any]:
    path = require_file(value, label)
    if path.suffix.lower() in {".h5", ".hdf5"}:
        raise MechanismBoundsError(f"H5 content is forbidden in mechanism audit: {path}")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise MechanismBoundsError(f"cannot import source module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_v2(manifest_path: Path) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    manifest_path, manifest = read_json(manifest_path, "impact-stream v2 manifest")
    if manifest.get("schema") != "ds02.stage2.omission-task-impact-stream-v2-manifest.v1":
        raise MechanismBoundsError("source manifest schema is not impact-stream v2")
    if manifest.get("status") != "PREPARED_118_SOURCE_CLOSED_NO_H5":
        raise MechanismBoundsError("source impact manifest is not the prepared immutable no-H5 set")
    if int(manifest.get("case_count", -1)) != sum(CASE_COUNTS.values()) or manifest.get("family_case_counts") != CASE_COUNTS:
        raise MechanismBoundsError("source case membership is not exact F2=48/F4=22/F6=48")
    input_hashes = manifest.get("input_sha256")
    if not isinstance(input_hashes, dict) or not input_hashes:
        raise MechanismBoundsError("source impact manifest has no input hash map")
    for path_text, expected in input_hashes.items():
        path = require_file(path_text, "impact v2 input")
        if path.suffix.lower() in {".h5", ".hdf5"}:
            raise MechanismBoundsError(f"H5 entered source impact input set: {path}")
        if sha256(path) != expected:
            raise MechanismBoundsError(f"source impact input changed: {path}")
    source_v1 = manifest.get("source_v1_manifest")
    if not isinstance(source_v1, dict):
        raise MechanismBoundsError("source impact manifest lacks v1 source binding")
    v1_path = require_file(source_v1.get("path", ""), "v1 impact manifest")
    if sha256(v1_path) != source_v1.get("sha256"):
        raise MechanismBoundsError("v1 source manifest digest differs from v2 binding")
    _, v1_manifest = read_json(v1_path, "v1 impact manifest")
    if v1_manifest.get("schema") != "ds02.stage2.omission-task-impact-stream-manifest.v1" or v1_manifest.get("status") != "IMMUTABLE_SOURCE_SET":
        raise MechanismBoundsError("v1 source manifest is not immutable")
    if int(v1_manifest.get("case_count", -1)) != sum(CASE_COUNTS.values()) or v1_manifest.get("family_case_counts") != CASE_COUNTS:
        raise MechanismBoundsError("v1 source case membership differs")
    return manifest_path, manifest, v1_path, v1_manifest


def validate_source(manifest_path: Path) -> dict[str, Any]:
    """Validate all-118 source closure without reading H5 content."""
    manifest_path, manifest, v1_path, v1_manifest = _source_v2(manifest_path)
    v2 = _load_module(V2_SCRIPT, "stage2_impact_stream_v2_for_mechanism")
    # validate_manifest receives the v1 manifest path.  It validates the
    # completed scan receipt's declared H5 path/hash metadata but intentionally
    # never opens or hashes H5.  Keep that check separate from v2's input map.
    closure = v2.validate_manifest(v1_path)
    if len(closure.get("source_records", [])) != sum(CASE_COUNTS.values()):
        raise MechanismBoundsError("producer closure did not contain all 118 cases")
    entries = {entry["case_key"]: entry for entry in v1_manifest.get("entries", [])}
    if len(entries) != sum(CASE_COUNTS.values()):
        raise MechanismBoundsError("v1 manifest has duplicate or incomplete case keys")
    for key, entry in entries.items():
        if entry.get("family_id") not in CASE_COUNTS:
            raise MechanismBoundsError(f"unexpected family for {key}")
    return {
        "manifest_path": manifest_path,
        "manifest": manifest,
        "v1_path": v1_path,
        "v1_manifest": v1_manifest,
        "entries": entries,
        "producer_closure": closure,
        "input_hashes": input_hashes(manifest),
    }


def validate_prepared_manifest(manifest_path: Path) -> tuple[Path, dict[str, Any], Path]:
    """Validate this audit's immutable manifest and return its v2 source path."""
    prepared_path, prepared = read_json(manifest_path, "mechanism bounds manifest")
    if prepared.get("schema") != MANIFEST_SCHEMA or prepared.get("status") != "PREPARED_118_SOURCE_CLOSED_NO_H5":
        raise MechanismBoundsError("mechanism bounds manifest schema/status differs")
    if int(prepared.get("case_count", -1)) != sum(CASE_COUNTS.values()) or prepared.get("family_case_counts") != CASE_COUNTS:
        raise MechanismBoundsError("mechanism bounds manifest case membership differs")
    inputs = prepared.get("input_sha256")
    if not isinstance(inputs, dict) or not inputs:
        raise MechanismBoundsError("mechanism bounds manifest has no input hash map")
    for path_text, expected in inputs.items():
        path = require_file(path_text, "mechanism bounds input")
        if path.suffix.lower() in {".h5", ".hdf5"}:
            raise MechanismBoundsError(f"H5 entered mechanism bounds input set: {path}")
        if sha256(path) != expected:
            raise MechanismBoundsError(f"mechanism bounds input changed: {path}")
    source_binding = prepared.get("source_impact_manifest")
    if not isinstance(source_binding, dict) or not source_binding.get("path"):
        raise MechanismBoundsError("mechanism bounds manifest lacks impact v2 source binding")
    source_path = require_file(source_binding["path"], "impact v2 source manifest")
    if sha256(source_path) != source_binding.get("sha256"):
        raise MechanismBoundsError("impact v2 source manifest digest differs from mechanism binding")
    return prepared_path, prepared, source_path


def input_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    values = manifest.get("input_sha256", {})
    if not isinstance(values, dict):
        raise MechanismBoundsError("source input hash map is not an object")
    return {str(path): str(digest) for path, digest in values.items()}


def _raw_rows(forensic_kind: str, forensic: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    if forensic_kind == "omission-forensics.v2":
        if forensic.get("schema") != "ds02.stage2.omission-forensics.v2" or forensic.get("status") != "CAUSES_RECONCILED":
            raise MechanismBoundsError("forensic source is not a completed v2 reconciliation")
        rows = forensic.get("excluded_particles", [])
    elif forensic_kind == "native-reconciliation.v1":
        if forensic.get("schema") != "ds02.stage2.native-exclusion-reconciliation.v1" or forensic.get("status") != "CAUSES_RECONCILED":
            raise MechanismBoundsError("legacy forensic source is not a completed reconciliation")
        rows = forensic.get("missing_fluid_ids", [])
    else:
        raise MechanismBoundsError(f"unsupported forensic kind: {forensic_kind}")
    result: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise MechanismBoundsError("forensic row is not an object")
        key = (int(row.get("zone", -1)), int(row.get("idp", -1)))
        if key in result:
            raise MechanismBoundsError(f"duplicate forensic identity: {key}")
        result[key] = row
    return result


def _finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MechanismBoundsError(f"{label} is not numeric") from exc
    if not math.isfinite(number):
        raise MechanismBoundsError(f"{label} is not finite")
    return number


def _interval(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise MechanismBoundsError(f"{label} is not a two-point interval")
    left, right = (_finite_number(value[0], f"{label}[0]"), _finite_number(value[1], f"{label}[1]"))
    if left > right:
        raise MechanismBoundsError(f"{label} is reversed")
    return [left, right]


def _endpoint_observation(row: dict[str, Any]) -> dict[str, Any]:
    native = row.get("native_record") if isinstance(row.get("native_record"), dict) else {}
    position = row.get("partvtkout_position_m", native.get("position_m"))
    density = row.get("partvtkout_density_kg_m3", native.get("density_kg_m3"))
    if position is not None:
        if not isinstance(position, (list, tuple)) or len(position) != 3:
            raise MechanismBoundsError("native endpoint position is not a 3-vector")
        position = [_finite_number(value, "native endpoint position") for value in position]
    if density is not None:
        density = _finite_number(density, "native endpoint density")
    return {
        "position_m": position,
        "density_kg_m3": density,
        "observed": position is not None or density is not None,
        "interpretation": "native decoder endpoint observation only; no physical destination or legal outflow inference",
    }


def _state_observation(row: dict[str, Any], prefix: str) -> dict[str, Any] | None:
    raw = row.get(prefix)
    if not isinstance(raw, dict):
        return None
    result: dict[str, Any] = {}
    for key in ("frame", "time_s", "density_kg_m3"):
        if key in raw:
            result[key] = _finite_number(raw[key], f"{prefix}.{key}") if key != "frame" else int(raw[key])
    for key in ("position_m", "velocity_m_s"):
        if key in raw:
            value = raw[key]
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                raise MechanismBoundsError(f"{prefix}.{key} is not a 3-vector")
            result[key] = [_finite_number(item, f"{prefix}.{key}") for item in value]
    return result


def _xml_mass_semantics(family: str, forensic: dict[str, Any]) -> dict[str, Any] | None:
    if family != "F6":
        return None
    provenance = forensic.get("source_provenance", {})
    xml_decl = provenance.get("generated_xml") if isinstance(provenance, dict) else None
    if not isinstance(xml_decl, dict) or not xml_decl.get("path"):
        return {"status": "UNKNOWN_XML_MASS_SOURCE_NOT_BOUND", "physical_rigid_body_mass_kg": "UNKNOWN"}
    xml_path = require_file(xml_decl["path"], "F6 generated XML")
    if sha256(xml_path) != xml_decl.get("sha256"):
        raise MechanismBoundsError(f"F6 generated XML digest differs: {xml_path}")
    text = xml_path.read_text(encoding="utf-8", errors="replace")
    body = [float(value) for value in re.findall(r"<massbody\b[^>]*\bvalue=[\"']([^\"']+)", text, flags=re.IGNORECASE)]
    fluid = [float(value) for value in re.findall(r"<massfluid\b[^>]*\bvalue=[\"']([^\"']+)", text, flags=re.IGNORECASE)]
    if not body or not fluid or any(not math.isfinite(value) for value in body + fluid):
        return {"status": "UNKNOWN_XML_MASS_FIELDS", "xml": file_binding(xml_path, "F6 XML"), "physical_rigid_body_mass_kg": "UNKNOWN"}
    if max(body) - min(body) > 1e-12 or max(fluid) - min(fluid) > 1e-12:
        raise MechanismBoundsError(f"F6 XML mass fields disagree: {xml_path}")
    return {
        "status": "XML_MASS_FIELDS_OBSERVED_SEPARATELY",
        "xml": file_binding(xml_path, "F6 XML"),
        "physical_rigid_body_mass_kg": float(body[0]),
        "xml_massfluid_per_particle_kg": float(fluid[0]),
        "sample_floating_mass_is_not_body_mass": True,
    }


def _mk_interval(missing_mass: float) -> dict[str, Any]:
    return {
        "status": "UNKNOWN_REQUIRES_BOUND_STATIC_MK_AUDIT",
        "source_mk_labels_observed": False,
        "missing_mass_constraint_kg": missing_mass,
        "admissible_mass_interval_kg_for_each_unidentified_mk": [0.0, missing_mass],
        "partition_constraint": "nonnegative source-MK contributions must sum to the case missing mass if a source-MK partition is later supplied",
        "per_mk_fraction": "UNKNOWN",
        "reason": "native Zone/Idp/type identity does not provide an independently source-bound initial mass partition by MK",
    }


def summarize_case(entry: dict[str, Any], impact: dict[str, Any], forensic: dict[str, Any], scan: dict[str, Any]) -> dict[str, Any]:
    """Turn a v1 typed/native join into conservative mechanism bounds.

    This function is intentionally independent of filesystem discovery and is
    therefore also used by manufactured counterexamples.  The v1 audit has
    already established identity, native motive, mass, and first-time joins.
    """
    family = str(entry.get("family_id", ""))
    if family not in CASE_COUNTS or impact.get("family_id") != family:
        raise MechanismBoundsError("case family differs between source and impact join")
    if impact.get("physical_case_id") != scan.get("physical_case_id"):
        raise MechanismBoundsError("case physical identity differs in mechanism join")
    raw = _raw_rows(str(entry.get("forensic_kind")), forensic)
    impact_particles = impact.get("particles")
    if not isinstance(impact_particles, list):
        raise MechanismBoundsError("impact particles are absent")
    if len(raw) != len(impact_particles) or len(raw) != int(impact.get("missing_fluid_count", -1)):
        raise MechanismBoundsError("forensic/impact particle counts differ")
    particles: list[dict[str, Any]] = []
    first_windows: list[list[float]] = []
    for joined in impact_particles:
        key = (int(joined.get("zone", -1)), int(joined.get("idp", -1)))
        if key not in raw:
            raise MechanismBoundsError(f"impact identity is absent from forensic source: {key}")
        row = raw[key]
        # The forensic producer must carry the timing evidence itself.  A
        # bracket copied only into the downstream impact join cannot close a
        # source mismatch or manufacture a censoring interval.
        bracket = _interval(row.get("first_missing_bracket_s"), "first_missing_bracket_s")
        first_windows.append(bracket)
        cause = str(joined.get("native_exit_cause", ""))
        motive = str(joined.get("native_motive", ""))
        expected = f"NUMERICAL_{motive.upper()}_EXCLUSION"
        if cause != expected:
            raise MechanismBoundsError(f"native cause/motive mismatch for {key}")
        mass = _finite_number(joined.get("initial_mass_kg"), "initial particle mass")
        if mass < 0:
            raise MechanismBoundsError("initial particle mass is negative")
        particles.append({
            "zone": key[0],
            "idp": key[1],
            "type_code": int(joined.get("type_code", 3)),
            "initial_mass_kg": mass,
            "native_motive": motive,
            "native_motive_code": int(joined.get("native_motive_code", 0)),
            "native_exit_cause": cause,
            "first_missing_frame": int(joined.get("first_missing_frame")),
            "first_missing_bracket_s": bracket,
            "first_gap_previous_state": _state_observation(row, "first_gap_previous_state"),
            "last_known_state": {
                key_name: value for key_name, value in {
                    "frame": row.get("last_known_frame"),
                    "time_s": row.get("last_known_time_s"),
                    "position_m": row.get("last_known_position_m"),
                    "velocity_m_s": row.get("last_known_velocity_m_s"),
                    "density_kg_m3": row.get("last_known_density_kg_m3"),
                }.items() if value is not None
            },
            "native_endpoint_observation": _endpoint_observation(row),
        })
    missing_mass = _finite_number(impact.get("missing_mass_lower_bound_kg"), "case missing mass")
    if not math.isclose(sum(row["initial_mass_kg"] for row in particles), missing_mass, rel_tol=2e-12, abs_tol=2e-12):
        raise MechanismBoundsError("case particle masses do not sum to impact mass")
    case_window = [min(bracket[0] for bracket in first_windows), max(bracket[1] for bracket in first_windows)] if first_windows else None
    scan_times = scan.get("time_s", [])
    scan_end = _finite_number(scan_times[-1], "scan final time") if scan_times else None
    floating = impact.get("f6_mass_semantics") if family == "F6" else None
    if family == "F6" and not isinstance(floating, dict):
        raise MechanismBoundsError("F6 floating/sample mass semantics are absent")
    xml_mass = _xml_mass_semantics(family, forensic)
    if family == "F6" and xml_mass is None:
        raise MechanismBoundsError("F6 XML mass semantics are absent")
    return {
        "case_key": entry["case_key"],
        "family_id": family,
        "physical_case_id": impact["physical_case_id"],
        "native_cause": {
            "motive_counts": dict(impact.get("native_motive_counts", {})),
            "exit_cause_counts": dict(impact.get("native_exit_cause_counts", {})),
            "credit_scope": "native PartVTKOut/RunPARTs motive only; endpoint predicates are diagnostic and not additional causes",
        },
        "mass_visibility": {
            "initial_fluid_mass_denominator_kg": _finite_number(impact.get("typed_initial_fluid_mass_kg"), "fluid mass denominator"),
            "missing_source_visible_mass_lower_bound_kg": missing_mass,
            "missing_source_visible_fraction_lower_bound": _finite_number(impact.get("missing_mass_fraction_lower_bound"), "mass fraction"),
            "screen": impact.get("mass_screen"),
            "screen_gate_fraction": MASS_GATE,
            "interpretation": "source-visible mass loss at the first missing join; this is not a physical mass-outflow or bounded dynamical-error estimate",
        },
        "event_censoring": {
            "first_missing_window_s": case_window,
            "per_particle_first_missing_windows": [
                {"zone": row["zone"], "idp": row["idp"], "window_s": row["first_missing_bracket_s"]} for row in particles
            ],
            "scan_final_time_s": scan_end,
            "post_gap_state": "UNOBSERVED_BY_SOURCE_TRAJECTORY_AFTER_FIRST_MISSING",
            "physical_event_presence": "UNKNOWN",
            "physical_event_time_s": "UNKNOWN; native censoring bracket is not a physical-event timestamp",
        },
        "region_transport": {
            "numerical_exclusion_observed": True,
            "physical_destination": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
            "conditional_physical_outflow_mass_interval_kg": [0.0, missing_mass],
            "conditional_in_domain_or_reentry_mass_interval_kg": [0.0, missing_mass],
            "interval_interpretation": "trivial admissible marginal intervals; no category allocation evidence exists after the first gap",
            "endpoint_observations_are_not_physical_fate": True,
        },
        "source_mk_weight": _mk_interval(missing_mass),
        "particles": particles,
        "f6_mass_semantics": {
            **floating,
            **(xml_mass or {}),
            "physical_rigid_body_mass_is_not_in_missing_fluid_mass": True,
            "dynamical_impact": "UNKNOWN",
        } if floating is not None else None,
        "observable_unknowns": [
            "fluid free-surface/pressure/velocity response after the first gap",
            "fluid-to-body force and impulse contribution",
            "rigid pose/omega response and any coupled downstream event",
            "physical destination, re-entry, or legal outflow classification",
        ],
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "source_bindings": {
            "forensic": file_binding(entry["forensic_path"], "forensic sidecar"),
            "scan": file_binding(entry["scan_path"], "scientific scan"),
            "scan_receipt": file_binding(entry["scan_receipt_path"], "scan receipt"),
            "forensic_kind": entry["forensic_kind"],
        },
    }


def repair_controls() -> dict[str, Any]:
    """Return preregistered one-factor designs, never execution results."""
    common = {
        "status": "PLANNED_NOT_EXECUTED",
        "frozen": ["CURRENT physical case identity", "initial BI4/source particle set", "mass matching", "dp", "CFL/time stepping", "fluid/rigid physics", "geometry and motion", "observation windows"],
        "must_compare": ["native motive/IDs", "first missing windows", "source-visible mass screen", "source-bound fluid/rigid observers when available"],
        "qualification": "a changed native count or mass screen is numerical-gate evidence only; physical fate, dynamics, QN and QE remain UNKNOWN",
        "launch": "root-only shared v4 guard request; no solver is launched by this ledger",
    }
    return {
        "F2": {
            **common,
            "control_id": "F2_NUMERICAL_DOMAIN_ONLY_PAIRED_CONTROL_V1",
            "changed_factor": "simulation-domain numerical bounds only",
            "preserve": ["wetted geometry/boundary", "pourer or moving-source motion", "XML/BI4 and massmatch", "dp/CFL/physics"],
            "forbidden_interpretation": "a recovered particle is not proof that the original exclusion was physical spill or that dynamics are repaired",
            "information_gain": "separates position-gate sensitivity from source/motion effects with one numerical factor",
        },
        "F4": {
            **common,
            "control_id": "F4_DENSITY_GATE_DIAGNOSTIC_CONTROL_V1",
            "changed_factor": "none in the current evidence ledger; optional future RhopOut sensitivity must be a separately guarded one-factor request",
            "preserve": ["RhopOut baseline declaration until a preregistered sensitivity request exists", "geometry/wetted wall", "massmatch", "dp/CFL/physics", "motion"],
            "forbidden_interpretation": "density endpoint/threshold proximity is not physical spill, transport, or a safe density-threshold widening",
            "information_gain": "first closes source-bound RhopOut/RunPARTs evidence; any threshold sensitivity is a distinct numerical-gate experiment",
        },
        "F6": {
            **common,
            "control_id": "F6_NUMERICAL_DOMAIN_ONLY_WALL_FIXED_CONTROL_V1",
            "changed_factor": "simulation-domain numerical bounds only, if a paired request is source-closed",
            "preserve": ["wetted wall/bottom and body geometry", "rigid initial pose/motion", "massmatch", "dp/CFL/physics", "XML/BI4"],
            "mass_semantics": "SPH sample/particle mass and XML physical rigid-body mass are separate quantities; never use the former as the latter",
            "forbidden_interpretation": "z/x/y endpoint exclusion is not legal outflow, wall crossing, or a bounded rigid impulse error",
            "information_gain": "tests numerical-domain sensitivity while retaining the same physical wall/body condition",
        },
    }


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    _, _, source_manifest_path = validate_prepared_manifest(manifest_path)
    source = validate_source(source_manifest_path)
    v1 = _load_module(V1_SCRIPT, "stage2_impact_stream_v1_for_mechanism")
    with tempfile.TemporaryDirectory(prefix="ds02-mechanism-bounds-v1-") as directory:
        v1_output = Path(directory) / "impact-v1.json"
        v1.audit(source["v1_path"], v1_output)
        impact = json.loads(v1_output.read_text(encoding="utf-8"))
    impact_by_case = {case["case_key"]: case for case in impact.get("cases", [])}
    if len(impact_by_case) != sum(CASE_COUNTS.values()):
        raise MechanismBoundsError("typed impact source did not produce 118 unique cases")
    cases: list[dict[str, Any]] = []
    for key in sorted(source["entries"]):
        entry = source["entries"][key]
        if key not in impact_by_case:
            raise MechanismBoundsError(f"typed impact case is absent: {key}")
        _, forensic = read_json(entry["forensic_path"], f"{key} forensic")
        _, scan = read_json(entry["scan_path"], f"{key} scan")
        cases.append(summarize_case(entry, impact_by_case[key], forensic, scan))
    family_aggregates: dict[str, Any] = {}
    for family in ("F2", "F4", "F6"):
        subset = [case for case in cases if case["family_id"] == family]
        causes: dict[str, int] = {}
        total_mass = 0.0
        denominator = 0.0
        first_window_values: list[float] = []
        for case in subset:
            for motive, count in case["native_cause"]["motive_counts"].items():
                causes[motive] = causes.get(motive, 0) + int(count)
            total_mass += float(case["mass_visibility"]["missing_source_visible_mass_lower_bound_kg"])
            denominator += float(case["mass_visibility"]["initial_fluid_mass_denominator_kg"])
            if case["event_censoring"]["first_missing_window_s"] is not None:
                first_window_values.extend(case["event_censoring"]["first_missing_window_s"])
        family_aggregates[family] = {
            "case_count": len(subset),
            "native_id_count": sum(len(case["particles"]) for case in subset),
            "native_motive_counts": dict(sorted(causes.items())),
            "missing_source_visible_mass_lower_bound_kg": total_mass,
            "typed_initial_fluid_mass_kg_sum": denominator,
            "weighted_missing_fraction_lower_bound": total_mass / denominator if denominator else None,
            "first_missing_window_s": [min(first_window_values), max(first_window_values)] if first_window_values else None,
            "source_mk_weight": "UNKNOWN_REQUIRES_BOUND_STATIC_MK_AUDIT",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        }
    result = {
        "schema": OUTPUT_SCHEMA,
        "status": "MECHANISM_BOUNDS_AUDITED_TYPED_NATIVE_SOURCE_CLOSED",
        "source_manifest": file_binding(source["manifest_path"], "impact v2 manifest"),
        "source_v1_manifest": file_binding(source["v1_path"], "impact v1 manifest"),
        "coverage": {"case_count": len(cases), "family_case_counts": CASE_COUNTS, "native_id_count": sum(len(case["particles"]) for case in cases)},
        "cases": cases,
        "family_aggregates": family_aggregates,
        "mass_screen": {"registered_gate_fraction": MASS_GATE, "interpretation": "source-visible missing mass screen only; no dynamical precision or QN/QE credit", "acceptance_granted": False},
        "mechanism_scope": {
            "native_cause": "source-bound PartVTKOut/RunPARTs motive and cause only",
            "region_transport": "physical destination/outflow/re-entry remains UNKNOWN",
            "event_censoring": "first_missing bracket is observed numerical-censoring timing; post-gap physical event timing remains UNKNOWN",
            "source_mk_weight": "per-MK contributions remain [0,total missing mass] until static source-MK initial audit",
        },
        "repair_controls": repair_controls(),
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "read_policy": {"h5_opened": False, "h5_content_hash_performed": False, "trajectory_content_opened": False, "partvtkout_started": False, "solver_started": False, "cfd_or_model_run": False},
        "next_evidence": {"required": ["source-bound static initial mass partition by MK/type", "paired one-factor numerical-domain/density controls", "time-aligned fluid/rigid observer evidence after the first gap", "physical destination/fate evidence"], "no_claim_from_mass_or_endpoint": True},
    }
    atomic_json(output_path, result)
    return {"status": result["status"], "output": str(output_path.resolve()), "case_count": len(cases), "native_id_count": result["coverage"]["native_id_count"], "h5_content_opened": False}


def prepare(output_dir: Path, source_manifest: Path = V2_MANIFEST_DEFAULT, variant: str = "v1") -> dict[str, Any]:
    if not re.fullmatch(r"v[0-9]+", variant):
        raise MechanismBoundsError(f"invalid request variant: {variant}")
    source_manifest, source_manifest_json, source_v1_path, _ = _source_v2(source_manifest)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    small_files = [SCRIPT, V2_SCRIPT, V1_SCRIPT, source_manifest, source_v1_path, V2_REQUEST_DEFAULT, RUNTIME_V4, RUNTIME_V2, DISPATCH_V4, STRICT_V4, VENV]
    small_files.extend(Path(path) for path in source_manifest_json.get("input_sha256", {}))
    unique: list[Path] = []
    seen: set[str] = set()
    for value in small_files:
        path = require_file(value, f"mechanism request input {Path(value).name}")
        if path.suffix.lower() in {".h5", ".hdf5"}:
            raise MechanismBoundsError(f"H5 input is forbidden in mechanism request: {path}")
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    hashes = {str(path): sha256(path) for path in unique}
    name = f"omission-mechanism-bounds-{variant}"
    manifest_path = output_dir / f"{name}-manifest.json"
    request_path = output_dir / f"{name}-request.json"
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_118_SOURCE_CLOSED_NO_H5",
        "physical_case_id": "F2_F4_F6_HISTORICAL_118",
        "case_count": sum(CASE_COUNTS.values()),
        "family_case_counts": CASE_COUNTS,
        "source_impact_manifest": file_binding(source_manifest, "impact v2 manifest"),
        "source_v1_manifest": file_binding(source_v1_path, "impact v1 manifest"),
        "input_files": sorted(hashes),
        "input_sha256": dict(sorted(hashes.items())),
        "source_case_membership": {"F2": 48, "F4": 22, "F6": 48, "native_ids": {"F2": 1078, "F4": 51, "F6": 199}},
        "repair_controls": repair_controls(),
        "read_policy": {"h5_opened": False, "h5_content_hash_performed": False, "trajectory_content_opened": False, "partvtkout_started": False, "solver_started": False, "cfd_or_model_run": False},
        "qualification": {"mass_screen_only": True, "source_mk_weight": "UNKNOWN_REQUIRES_BOUND_STATIC_MK_AUDIT", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    atomic_json(manifest_path, manifest)
    request_hashes = dict(hashes)
    request_hashes[str(manifest_path)] = sha256(manifest_path)
    request = {
        "schema": "ds02.request.v1",
        "family_id": "infra",
        "case_id": "STAGE2_OMISSION_MECHANISM_BOUNDS_118_V1",
        "physical_case_id": "F2_F4_F6_HISTORICAL_118",
        "attempt_id": f"{name}-primary-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "cwd": str(SCRIPT.parent),
        "worktree_root": str(WORKTREE_ROOT),
        "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", f"{{attempt_root}}/{name}.json"],
        "input_files": sorted(request_hashes),
        "input_sha256": dict(sorted(request_hashes.items())),
        "source_read_cost": {"h5_bytes_read": 0, "trajectory_bytes_read": 0, "partvtkout_bytes_read": 0, "solver_bytes_read": 0, "non_h5_input_pre_post_hash_bytes": 2 * sum(path.stat().st_size for path in unique), "estimated_output_bytes": 64 * 1024 * 1024},
        "source_scope": {"impact_v2_producer_closure_reused": True, "v1_typed_native_join_reused": True, "h5_content_read": False, "solver_started": False, "decoder_started": False},
        "source_case_membership": manifest["source_case_membership"],
        "mass_screen_gate_fraction": MASS_GATE,
        "repair_controls": {family: value["control_id"] for family, value in repair_controls().items()},
        "launch_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORKTREE_ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "canonical_ready": True,
        "launch": True,
        "launch_allowed": True,
        "execution_allowed": True,
        "launch_owner": "root",
        "primary_launch_owner": "root",
        "shared_lease_required": True,
        "foreign_process_protection_required": True,
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "request_note": "Forward-only source-bound 118-case mechanism/impact-bound ledger. Reads completed JSON/XML/native sidecars and hashes registered non-H5 inputs only; no H5, trajectory frame, PartVTKOut, solver, CFD, or model. Native endpoints identify numerical gate observations only. Repair controls are preregistered and unexecuted.",
    }
    atomic_json(request_path, request)
    return {"status": "prepared", "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "request": str(request_path), "request_sha256": sha256(request_path), "input_count": len(unique), "h5_content_opened": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--source-manifest", type=Path, default=V2_MANIFEST_DEFAULT)
    prep.add_argument("--variant", default="v1")
    aud = sub.add_parser("audit")
    aud.add_argument("--manifest", type=Path, required=True)
    aud.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.output_dir, args.source_manifest, args.variant) if args.action == "prepare" else audit(args.manifest, args.output)
    except MechanismBoundsError as exc:
        raise SystemExit(f"MechanismBoundsError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
