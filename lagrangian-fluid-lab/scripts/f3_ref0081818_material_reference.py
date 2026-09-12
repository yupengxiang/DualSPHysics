"""Read-only material handoff for the qualified F3 ref0081818 recipe.

The historical :mod:`f3_material_reference` entry point is tied to the old
NoPen stage gates and calls the old stage scorer before it can register a
material attempt.  This module is the revision-bound adapter.  It only
constructs a material plan after an explicit, passed ref0081818 gate has
opted in to material production; it never prepares a worker, starts a solver,
charges a material configuration, or launches training.

The adapter deliberately binds the new material thresholds, the complete
ref0081818 score report, and the existing ``.0075 m`` production source.  A
missing gate, a failed gate, a stale report, or a changed source therefore
fails closed before any material-side operation can be attempted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - direct CLI invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import f3_material_reference_score as material_score
from scripts import f3_ref0081818_prepare as preparation
from scripts.l1r_continuation_evidence import LAB, OUT
from scripts.l1r_q2_mdbc_bridge import SOLVER, sha256


RECIPE = "F3_CELL3_NS_visco1_native_nopen_revision075_ref0081818"
GATE_NAME = "F3-075-REF0081818-GATE.json"
GATE_SCHEMA = "f3.revision075.ref0081818.gate.v1"
SCORE_SCHEMA = "f3.revision075.ref0081818.stage_scores.v1"
PRODUCTION_CASE = "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen"
PRODUCTION_DP_M = 0.0075
HORIZON_S = 8.35
OUTPUT_INTERVAL_S = 0.01
CONTROL_DOMAIN = [0.9, 1.1]
COORDINATE_FRAME = "fixed tank computational coordinates"

# These values are the prospective material definitions from the material
# scorer.  Keeping an explicit copy here prevents a later edit to the legacy
# module from silently changing the ref008 handoff.
NEW_MATERIAL_THRESHOLDS = {
    "mass_closure_relative": 1e-12,
    "unknown_fraction_per_source": 0.01,
    "terminal_and_passage_bound_difference": 0.02,
    "mean_residence_bound_difference_s": 0.167,
    "observed_event_weighted_mae_s": 0.02,
    "path_rms_m": 0.003,
    "path_p95_m": 0.006,
    "path_max_m": 0.012,
    "temporal_budget_fraction": 0.2,
}


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PermissionError(f"missing required ref008 material evidence: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"evidence record must be an object: {path}")
    return value


def _path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (LAB / path).resolve()
    resolved.relative_to(LAB.resolve())
    return resolved


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(LAB.resolve()))


def _fingerprint(path: Path) -> dict[str, str]:
    return {"path": _relative(path), "sha256": sha256(path)}


def _assert_digest(path: Path, expected: str, message: str) -> None:
    if not path.is_file() or sha256(path) != expected:
        raise ValueError(message + ": " + _relative(path))


def _verify_material_thresholds() -> dict[str, Any]:
    actual = dict(material_score.THRESHOLDS)
    if actual != NEW_MATERIAL_THRESHOLDS:
        raise ValueError("ref008 material thresholds differ from the registered definitions")
    if any(not isinstance(value, (int, float)) or value < 0 for value in actual.values()):
        raise ValueError("ref008 material thresholds must be finite nonnegative numbers")
    return actual


def _score_path(gate: dict[str, Any]) -> Path:
    relative = gate.get("scoring_evidence_path")
    if not isinstance(relative, str):
        raise ValueError("ref008 gate has no scoring evidence path")
    return _path(relative)


def verify_revision_gate(gate_path: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Return a passed material-enabled gate and its bound score report.

    ``material_production_allowed`` is checked independently from
    ``development_launch_allowed``.  A passed numerical gate that has not
    explicitly opened material production remains blocked.
    """
    gate_file = _path(gate_path or (OUT / GATE_NAME))
    gate = _read(gate_file)
    if (gate.get("schema") != GATE_SCHEMA or gate.get("status") != "passed"
            or gate.get("recipe_id") != RECIPE):
        raise PermissionError("a passed ref0081818 qualification gate is required")
    if gate.get("material_production_allowed") is not True:
        raise PermissionError("ref0081818 gate has not opted in to material production")
    if (gate.get("production_resolution_m") != PRODUCTION_DP_M
            or gate.get("reference_resolutions_m") != [preparation.DP, .0075, .006]
            or gate.get("time_window_s") != [0.0, HORIZON_S]
            or gate.get("control_domain") != CONTROL_DOMAIN
            or gate.get("coordinate_frame") != COORDINATE_FRAME
            or gate.get("production_source_case_id") != PRODUCTION_CASE):
        raise ValueError("ref008 gate does not describe the registered material domain")
    score_file = _score_path(gate)
    _assert_digest(score_file, gate.get("scoring_evidence_sha256", ""),
                   "ref008 score report changed")
    score = _read(score_file)
    if (score.get("schema") != SCORE_SCHEMA or score.get("status") != "passed"
            or score.get("recipe_id") != RECIPE
            or score.get("production_resolution_m") != PRODUCTION_DP_M
            or score.get("production_source_case_id") != PRODUCTION_CASE
            or score.get("time_window_s") != [0.0, HORIZON_S]
            or score.get("coordinate_frame") != COORDINATE_FRAME
            or score.get("control_domain") != CONTROL_DOMAIN):
        raise ValueError("ref008 score report is not the bound passed report")
    evidence = score.get("evidence_sha256")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("ref008 score report has no hash-bound evidence")
    for relative, digest in evidence.items():
        _assert_digest(_path(relative), digest, "ref008 score evidence changed")
    return gate, score, score_file


def _verify_source_assets(record: dict[str, Any]) -> list[Path]:
    prefix = _path(record["generated_prefix"])
    assets = record.get("input_assets")
    if not isinstance(assets, dict):
        raise ValueError("production source has no input asset bindings")
    required = {prefix.name + suffix for suffix in (".xml", "_Def.xml", ".bi4")}
    required.add("CaseSloshingAccData.csv")
    if not required.issubset(assets):
        raise ValueError("production source input assets are incomplete")
    paths = []
    for name, digest in assets.items():
        if Path(name).name != name:
            raise ValueError("production source asset escapes its artifact directory")
        asset = prefix.parent / name
        _assert_digest(asset, digest, "production source input asset changed")
        paths.append(asset)
    if record.get("generated_xml_sha256") != sha256(prefix.with_suffix(".xml")):
        raise ValueError("production source generated XML changed")
    return paths


def verify_production_source(gate: dict[str, Any]) -> dict[str, Any]:
    """Verify and fingerprint the immutable nominal ``.0075 m`` source."""
    source_id = gate.get("production_source_case_id")
    if source_id != PRODUCTION_CASE:
        raise ValueError("ref008 gate selected an unexpected production source")
    record_path = OUT / f"{PRODUCTION_CASE}-PREPARED.json"
    audit_path = OUT / f"{PRODUCTION_CASE}-AUDIT.json"
    solver_path = OUT / f"{PRODUCTION_CASE}-SOLVER.json"
    preflight_path = OUT / f"{PRODUCTION_CASE}-INPUT-PREFLIGHT.json"
    record, audit, solver, preflight = map(_read, (record_path, audit_path, solver_path, preflight_path))
    expected = {
        "id": PRODUCTION_CASE, "case_id": PRODUCTION_CASE, "dp_m": PRODUCTION_DP_M,
        "drive_amplitude": 1.0, "time_max_s": HORIZON_S, "time_out_s": OUTPUT_INTERVAL_S,
        "cfl_number": 0.05, "coef_dt_min": 0.05, "solver_mode": "-mdbc_noslip:1",
        "expected_slip_mode": "No-slip", "expected_no_penetration": True,
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError("production source does not match the ref008 recipe")
    _verify_source_assets(record)
    if (solver.get("case_id") != PRODUCTION_CASE or solver.get("status") != "completed"
            or solver.get("resource_category") != "qualification"
            or solver.get("source_record") != record
            or solver.get("solver_sha256") != sha256(SOLVER)):
        raise ValueError("production source solver evidence is not bound and completed")
    if (preflight.get("status") != "passed"
            or (preflight.get("record_id") is not None
                and preflight.get("record_id") != PRODUCTION_CASE)
            or (preflight.get("record_sha256") is not None
                and preflight.get("record_sha256") != sha256(record_path))):
        raise ValueError("production source input preflight is not bound")
    if (audit.get("case_id") != PRODUCTION_CASE
            or audit.get("audit_status") != "pass_diagnostic"
            or audit.get("issues") != [] or audit.get("unknowns") != []
            or audit.get("time_start_s") != 0
            or not HORIZON_S <= audit.get("time_end_s", -1) < HORIZON_S + .01
            or audit.get("frames") != round(HORIZON_S / OUTPUT_INTERVAL_S) + 1):
        raise ValueError("production source audit is not a full-window diagnostic pass")
    for field in ("identities_introduced_after_initial", "initial_identities_missing_at_final",
                  "identities_reappeared_after_gap", "excluded_particles_from_solver_log",
                  "finite_bad_value_rows"):
        if audit.get(field) != 0:
            raise ValueError("production source lifecycle audit is nonzero: " + field)
    penetration = audit.get("penetration", {})
    for field in ("frames_with_penetration", "frames_with_runtime_domain_outside", "swept_crossing_count"):
        if penetration.get(field) != 0:
            raise ValueError("production source wall audit is nonzero: " + field)
    if penetration.get("runtime_domain_status") != "checked":
        raise ValueError("production source runtime domain is unchecked")
    hdf5 = _path(audit.get("hdf5", ""))
    _assert_digest(hdf5, audit.get("hdf5_sha256", ""), "production source HDF5 changed")
    evidence = [_fingerprint(path) for path in
                (record_path, audit_path, solver_path, preflight_path, hdf5)]
    evidence.extend(_fingerprint(path) for path in _verify_source_assets(record))
    return {
        "case_id": PRODUCTION_CASE,
        "resolution_m": PRODUCTION_DP_M,
        "time_window_s": [0.0, HORIZON_S],
        "output_interval_s": OUTPUT_INTERVAL_S,
        "initial_fluid_mass_kg": audit.get("initial_fluid_mass_kg"),
        "record": _fingerprint(record_path),
        "audit": _fingerprint(audit_path),
        "solver": _fingerprint(solver_path),
        "preflight": _fingerprint(preflight_path),
        "hdf5": _fingerprint(hdf5),
        "evidence": evidence,
    }


def configurations(source_case_id: str = PRODUCTION_CASE) -> list[dict[str, Any]]:
    """Return the bounded material-only controls for the qualified source."""
    return [
        {"config_id": "REF008-0075-NOMINAL-s2", "source_case_id": source_case_id,
         "dp_m": PRODUCTION_DP_M, "amplitude": 1.0, "output_interval_s": .01,
         "substeps": 2, "role": "nominal_saved_frame"},
        {"config_id": "REF008-0075-NOMINAL-s4", "source_case_id": source_case_id,
         "dp_m": PRODUCTION_DP_M, "amplitude": 1.0, "output_interval_s": .01,
         "substeps": 4, "role": "nominal_substep_sensitivity"},
        {"config_id": "REF008-0075-CADENCE-s4", "source_case_id": source_case_id,
         "dp_m": PRODUCTION_DP_M, "amplitude": 1.0, "output_interval_s": .002,
         "substeps": 4, "role": "registered_output_cadence"},
    ]


def plan() -> dict[str, Any]:
    """Build a read-only material handoff; no files are written."""
    gate, score, score_path = verify_revision_gate()
    source = verify_production_source(gate)
    thresholds = _verify_material_thresholds()
    code = {
        "adapter_sha256": sha256(Path(__file__)),
        "material_score_sha256": sha256(Path(material_score.__file__)),
        "material_labels_sha256": sha256(LAB / "scripts/f3_material_labels.py"),
        "material_neighbors_sha256": sha256(LAB / "scripts/f3_material_neighbors.py"),
        "passive_tracers_sha256": sha256(LAB / "scripts/passive_tracers.py"),
    }
    return {
        "schema": "f3.ref0081818.material_reference_plan.v1",
        "status": "ready_after_ref0081818_material_gate",
        "launch": False,
        "worker_runs": 0,
        "solver_runs": 0,
        "training_runs": 0,
        "recipe_id": RECIPE,
        "qualification_gate": _fingerprint(_path(OUT / GATE_NAME)),
        "score_report": _fingerprint(score_path),
        "production_source": source,
        "production_resolution_m": PRODUCTION_DP_M,
        "reference_resolutions_m": [preparation.DP, PRODUCTION_DP_M, .006],
        "time_window_s": [0.0, HORIZON_S],
        "output_interval_s": OUTPUT_INTERVAL_S,
        "coordinate_frame": COORDINATE_FRAME,
        "control_domain": CONTROL_DOMAIN,
        "thresholds": thresholds,
        "threshold_origin": "new prospective CFD material definitions",
        "code_sha256": code,
        "configurations": configurations(),
        "configuration_charge": 0,
        "qualified_T2_macro": False,
        "qualified_T2_path": False,
        "formal_release": False,
        "material_production_allowed": True,
        "training_allowed": False,
        "score_status": score["status"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan",))
    args = parser.parse_args(argv)
    try:
        value = plan()
    except (PermissionError, ValueError, KeyError, FileNotFoundError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(value, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
