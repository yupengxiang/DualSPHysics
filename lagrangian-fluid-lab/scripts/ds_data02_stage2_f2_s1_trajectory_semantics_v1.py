#!/usr/bin/env python3
"""Validate conservative labels for the F2-S1 trajectory/XYZ comparison.

This is a forward-only semantic consumer.  It reads the small JSON report from
the guarded ``trajectory-labels-v1`` job, the already completed expanded-XYZ
native-weighted report, the typed conversion report, and the expanded solver's
small ``Run.out``.  It never opens H5, ``Part_*.bi4``, or a solver output
container.

The two observations have different meanings.  The trajectory report contains
saved-frame finite-aperture brackets and open-lifecycle identity censoring.  The
expanded report contains official native PartVTKOut exclusions.  Neither is a
physical spill/fate observation.  The fine expanded run also changes particle
resolution and particle mass relative to the original trajectory case, so this
consumer records it as a numerical visibility comparison, not a domain-only
causal control.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any


SCRIPT = Path(__file__).resolve()
PHYSICAL_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
SCHEMA = "ds02.stage2.f2-s1-trajectory-semantics.v1"
CONTRACT_SCHEMA = "ds02.stage2.f2-s1-trajectory-semantics-contract.v1"
TRAJECTORY_SCHEMA = "ds02.stage2.f2-s1-trajectory-labels.v1"
EXPANDED_SCHEMA = "ds02.stage2.f2-s1-fine-expanded-native-weighted.v1"
EXPECTED_FLUID_COUNT = 21_114
EXPECTED_FLUID_BLOCKS = {1: 7_038, 2: 7_038, 3: 7_038}
EXPECTED_PARTICLE_MASS_KG = 0.0010000000474974513
EXPECTED_WHOLE_INITIAL_MASS_KG = EXPECTED_FLUID_COUNT * EXPECTED_PARTICLE_MASS_KG
EXPECTED_SOURCE_DOMAIN = ((-1.4, 3.0), (-1.2, 1.2), (-0.5, 2.2))
EXPECTED_EXPANDED_NATIVE_COUNT = 111
EXPECTED_EXPANDED_FACE_COUNTS = {
    "x_low": 56,
    "z_low": 35,
    "y_low": 12,
    "z_high": 4,
    "y_high": 4,
}
EXPECTED_TIME_TOLERANCE_S = 1e-8


class SemanticError(RuntimeError):
    """Raised when a source-bound semantic contract is not exact."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise SemanticError(f"{label} is missing: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SemanticError(f"{label} is not a JSON object: {path}")
    return path, payload


def bind(item: Any, label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(item, dict) or not item.get("path"):
        raise SemanticError(f"{label} lacks an exact path binding")
    path = require_file(item["path"], label)
    actual = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
    if item.get("bytes") is not None and int(item["bytes"]) != actual["bytes"]:
        raise SemanticError(f"{label} byte count differs")
    if item.get("sha256") and str(item["sha256"]) != actual["sha256"]:
        raise SemanticError(f"{label} SHA256 differs")
    return path, actual


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise SemanticError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
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


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SemanticError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise SemanticError(f"{label} is not finite")
    return result


def _same(actual: Any, expected: float, label: str, tol: float = 1e-10) -> None:
    if abs(_finite(actual, label) - expected) > tol:
        raise SemanticError(f"{label} differs: {actual!r} != {expected!r}")


def _read_runout_bounds(path: Path) -> tuple[tuple[float, float], ...]:
    text = path.read_text(encoding="utf-8", errors="strict")
    match = re.search(r"MapRealPos\(final\)=\(([^)]+)\)-\(([^)]+)\)", text)
    if not match:
        raise SemanticError("expanded Run.out lacks MapRealPos(final)")
    low = tuple(_finite(part.strip(), "expanded MapRealPos lower bound") for part in match.group(1).split(","))
    high = tuple(_finite(part.strip(), "expanded MapRealPos upper bound") for part in match.group(2).split(","))
    if len(low) != 3 or len(high) != 3 or any(low[i] >= high[i] for i in range(3)):
        raise SemanticError("expanded MapRealPos(final) bounds are malformed")
    return tuple((low[i], high[i]) for i in range(3))


def _derive_whole_initial(conversion: dict[str, Any]) -> dict[str, Any]:
    typed = conversion.get("typed_identity")
    if not isinstance(typed, dict):
        raise SemanticError("conversion report lacks typed_identity")
    blocks = typed.get("blocks")
    if not isinstance(blocks, list):
        raise SemanticError("conversion report lacks typed blocks")
    fluid: dict[int, dict[str, Any]] = {}
    for block in blocks:
        if not isinstance(block, dict) or block.get("tag") != "fluid" or int(block.get("type", -1)) != 3:
            continue
        mk = int(block.get("mk", -1))
        if mk in fluid:
            raise SemanticError(f"duplicate fluid source MK block: {mk}")
        fluid[mk] = block
    if set(fluid) != set(EXPECTED_FLUID_BLOCKS):
        raise SemanticError(f"fluid source MK blocks differ: {sorted(fluid)}")
    total_count = 0
    for mk, expected_count in EXPECTED_FLUID_BLOCKS.items():
        block = fluid[mk]
        count = int(block.get("count", -1))
        if count != expected_count:
            raise SemanticError(f"fluid MK{mk} count differs: {count}")
        if int(block.get("begin", -1)) < 0:
            raise SemanticError(f"fluid MK{mk} begin is invalid")
        total_count += count
    if total_count != EXPECTED_FLUID_COUNT:
        raise SemanticError(f"fluid count differs: {total_count}")
    mass_min = _finite(typed.get("initial_mass_min_kg"), "typed initial mass minimum")
    mass_max = _finite(typed.get("initial_mass_max_kg"), "typed initial mass maximum")
    if abs(mass_max - mass_min) > 1e-15:
        raise SemanticError("typed fluid mass is not constant; per-MK mass is not closed")
    _same(mass_min, EXPECTED_PARTICLE_MASS_KG, "typed particle mass", 1e-15)
    total_mass = total_count * mass_min
    return {
        "fluid_count": total_count,
        "particle_mass_kg": mass_min,
        "source_mk_counts": {str(mk): fluid[mk]["count"] for mk in sorted(fluid)},
        "whole_initial_mass_kg": total_mass,
        "basis": "typed fluid blocks with constant native MassFluid; this is the trajectory mass gate",
    }


def _validate_trajectory(report: dict[str, Any], whole: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema") != TRAJECTORY_SCHEMA:
        raise SemanticError("trajectory report schema differs")
    if report.get("physical_case_id") != PHYSICAL_CASE:
        raise SemanticError("trajectory physical case identity differs")
    trajectory = report.get("trajectory")
    if not isinstance(trajectory, dict):
        raise SemanticError("trajectory report lacks trajectory summary")
    _same(trajectory.get("initial_fluid_mass_kg"), whole["whole_initial_mass_kg"], "trajectory whole initial mass", 1e-9)
    screen = report.get("mass_screen")
    if not isinstance(screen, dict):
        raise SemanticError("trajectory report lacks mass_screen")
    _same(screen.get("initial_fluid_mass_kg"), whole["whole_initial_mass_kg"], "trajectory mass-screen denominator", 1e-9)
    if screen.get("decision") != "screening_only; no physical-fate or dynamics credit":
        raise SemanticError("trajectory mass screen grants an impermissible qualification")
    unknown_scope = report.get("unknown_scope")
    if not isinstance(unknown_scope, dict):
        raise SemanticError("trajectory report lacks unknown_scope")
    if "UNKNOWN" not in str(unknown_scope.get("dynamics", "")):
        raise SemanticError("trajectory dynamics scope is not UNKNOWN")
    if "UNKNOWN" not in str(unknown_scope.get("missing_identity", "")):
        raise SemanticError("trajectory missing-identity fate scope is not UNKNOWN")
    events = report.get("events")
    if not isinstance(events, list) or not events:
        raise SemanticError("trajectory report lacks event summaries")
    event_rows: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            raise SemanticError("trajectory event summary is malformed")
        direction = event.get("entry_direction")
        if direction not in {"+x", "-x", "+y", "-y", "+z", "-z"}:
            raise SemanticError(f"trajectory event direction is not explicit: {direction!r}")
        if event.get("operator_column_semantics") != "column0=negative-to-positive along selected axis; column1=positive-to-negative":
            raise SemanticError("trajectory event sign semantics are not source-closed")
        if "saved-frame finite-aperture bracket" not in str(event.get("semantics", "")):
            raise SemanticError("trajectory event is presented as an exact continuous event")
        event_rows.append({
            "id": event.get("id"),
            "axis": event.get("axis"),
            "entry_direction": direction,
            "entry_direction_mass_kg": event.get("entry_direction_mass_kg"),
            "exit_direction_mass_kg": event.get("exit_direction_mass_kg"),
            "entry_direction_net_flux_mass_kg": event.get("entry_direction_net_flux_mass_kg"),
            "repeated_crossing_particles": event.get("repeated_crossing_particles"),
            "semantics": "saved-frame bracket only; hidden continuous crossings and exact event time UNKNOWN",
        })
    missing = report.get("missing_identity_observations", {})
    if not isinstance(missing, dict) or "first saved-frame gap bracket only" not in str(missing.get("semantics", "")):
        raise SemanticError("trajectory missing identity is not explicitly censored")
    return {
        "status": report.get("status"),
        "frames": trajectory.get("frames"),
        "identities": trajectory.get("identities"),
        "time_window_s": trajectory.get("time_window_s"),
        "whole_initial_mass_kg": whole["whole_initial_mass_kg"],
        "missing_identity_mass_kg": screen.get("missing_identity_mass_kg"),
        "missing_identity_mass_fraction": screen.get("missing_identity_mass_fraction"),
        "unknown_final_destination_mass_kg": screen.get("unknown_final_destination_mass_kg"),
        "events": event_rows,
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "qualification": "saved-frame observational labels only; no QN/QE credit",
    }


def _validate_expanded(report: dict[str, Any], runout: Path) -> dict[str, Any]:
    if report.get("schema") != EXPANDED_SCHEMA:
        raise SemanticError("expanded native report schema differs")
    if report.get("physical_case_id") != PHYSICAL_CASE:
        raise SemanticError("expanded physical case identity differs")
    if report.get("status") != "EXPANDED_NATIVE_WEIGHTED_RECONCILED":
        raise SemanticError("expanded report is not a completed native reconciliation")
    decoder = report.get("official_expanded_decoder")
    if not isinstance(decoder, dict) or decoder.get("status") != "completed" or decoder.get("returncode") != 0:
        raise SemanticError("expanded official PartVTKOut receipt is not completed")
    if decoder.get("h5_opened") is not False or decoder.get("trajectory_opened") is not False:
        raise SemanticError("expanded native report does not prove no H5/trajectory input")
    paired = report.get("paired_weighted_impact")
    if not isinstance(paired, dict):
        raise SemanticError("expanded report lacks paired weighted impact")
    if paired.get("physical_fate") != "UNKNOWN" or paired.get("dynamical_impact") != "UNKNOWN":
        raise SemanticError("expanded native report grants physical or dynamical credit")
    expanded = paired.get("expanded")
    original = paired.get("original")
    if not isinstance(expanded, dict) or not isinstance(original, dict):
        raise SemanticError("expanded report lacks original/expanded native summaries")
    rows = expanded.get("records")
    if not isinstance(rows, list) or len(rows) != EXPECTED_EXPANDED_NATIVE_COUNT:
        raise SemanticError(f"expanded native record count differs: {len(rows) if isinstance(rows, list) else None}")
    if int(expanded.get("native_count", -1)) != len(rows):
        raise SemanticError("expanded native_count does not match records")
    if int(original.get("native_count", -1)) != 175:
        raise SemanticError("original native count differs")
    expanded_bounds = _read_runout_bounds(runout)
    face_counts: dict[str, int] = {}
    face_by_mk: dict[str, dict[str, int]] = {}
    seen: set[int] = set()
    multi_face = 0
    inside = 0
    times: list[float] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SemanticError(f"expanded native row {index} is malformed")
        idp = int(row.get("idp", -1))
        if idp in seen:
            raise SemanticError(f"expanded native Idp repeats: {idp}")
        seen.add(idp)
        if int(row.get("motive", -1)) != 1 or row.get("motive_name") != "position":
            raise SemanticError(f"expanded row {idp} is not a position exclusion")
        mk = int(row.get("mk_absolute", -1))
        if mk not in (1, 2, 3):
            raise SemanticError(f"expanded row {idp} has invalid native source MK")
        position = row.get("position")
        if not isinstance(position, list) or len(position) != 3:
            raise SemanticError(f"expanded row {idp} position is malformed")
        point = [_finite(value, f"expanded row {idp} coordinate") for value in position]
        faces: list[str] = []
        for axis, (lower, upper), value in zip("xyz", expanded_bounds, point):
            if value < lower:
                faces.append(f"{axis}_low")
            elif value > upper:
                faces.append(f"{axis}_high")
        if not faces:
            inside += 1
        if len(faces) > 1:
            multi_face += 1
        for face in faces:
            face_counts[face] = face_counts.get(face, 0) + 1
            by_mk = face_by_mk.setdefault(face, {})
            by_mk[str(mk)] = by_mk.get(str(mk), 0) + 1
        times.append(_finite(row.get("time_s"), f"expanded row {idp} saved time"))
    if face_counts != EXPECTED_EXPANDED_FACE_COUNTS or inside != 0 or multi_face != 0:
        raise SemanticError(f"expanded MapRealPos face classification differs: {face_counts}, inside={inside}, multi={multi_face}")
    diagnostic_basis = _finite(expanded.get("initial_mass_denominator_kg"), "expanded diagnostic mass denominator")
    particle_mass = _finite(expanded.get("particle_mass_kg"), "expanded diagnostic particle mass")
    _same(expanded.get("native_mass_lower_bound_kg"), len(rows) * particle_mass, "expanded native mass lower bound", 1e-10)
    fraction = len(rows) * particle_mass / diagnostic_basis
    _same(expanded.get("native_mass_fraction_lower_bound"), fraction, "expanded native mass fraction", 1e-12)
    # This comparison uses the fine run's own generated particle mass.  It is
    # deliberately not substituted for the original trajectory's whole-initial
    # mass gate.
    return {
        "case_id": expanded.get("case_id"),
        "native_count": len(rows),
        "original_native_count": int(original["native_count"]),
        "native_count_difference": len(rows) - int(original["native_count"]),
        "native_id_set_comparison": paired.get("native_id_set_comparison"),
        "saved_time_s": {"first": min(times), "last": max(times)},
        "runout_final_bounds_printed": [[low, high] for low, high in expanded_bounds],
        "strict_printed_boundary_faces": face_counts,
        "strict_printed_boundary_faces_by_source_mk": face_by_mk,
        "inside_count": inside,
        "multi_face_count": multi_face,
        "boundary_semantics": "strict coordinate comparison against printed MapRealPos(final); exact binary gate precision UNKNOWN",
        "diagnostic_particle_mass_kg": particle_mass,
        "diagnostic_initial_mass_denominator_kg": diagnostic_basis,
        "native_mass_lower_bound_kg": expanded.get("native_mass_lower_bound_kg"),
        "native_mass_fraction_lower_bound": expanded.get("native_mass_fraction_lower_bound"),
        "native_cause": "official PartVTKOut NUMERICAL_POSITION_EXCLUSION visibility; physical destination/fate UNKNOWN",
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
    }


def analyze(contract_path: Path | str) -> dict[str, Any]:
    _, contract = read_json(contract_path, "trajectory semantics contract")
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise SemanticError("trajectory semantics contract schema differs")
    if contract.get("physical_case_id") != PHYSICAL_CASE:
        raise SemanticError("trajectory semantics physical case differs")
    _, conversion = bind(contract.get("conversion_report"), "typed conversion report")
    conversion_payload = read_json(conversion["path"], "typed conversion report")[1]
    if conversion_payload.get("conversion_status") != "completed":
        raise SemanticError("typed conversion report is not completed")
    whole = _derive_whole_initial(conversion_payload)
    trajectory_path, trajectory_binding = bind(contract.get("trajectory_report"), "trajectory labels report")
    trajectory_payload = read_json(trajectory_path, "trajectory labels report")[1]
    expanded_path, expanded_binding = bind(contract.get("expanded_native_report"), "expanded native report")
    expanded_payload = read_json(expanded_path, "expanded native report")[1]
    runout_path, runout_binding = bind(contract.get("expanded_runout"), "expanded Run.out")
    trajectory = _validate_trajectory(trajectory_payload, whole)
    expanded = _validate_expanded(expanded_payload, runout_path)
    return {
        "schema": SCHEMA,
        "status": "SEMANTICS_VALIDATED_SOURCE_BOUND",
        "physical_case_id": PHYSICAL_CASE,
        "source_bindings": {
            "contract": {"path": str(Path(contract_path).resolve()), "bytes": Path(contract_path).stat().st_size, "sha256": sha256(contract_path)},
            "conversion_report": conversion,
            "trajectory_report": trajectory_binding,
            "expanded_native_report": expanded_binding,
            "expanded_runout": runout_binding,
        },
        "whole_initial_mass_basis": whole,
        "trajectory_saved_frame_labels": trajectory,
        "expanded_xyz_native_visibility": expanded,
        "comparison_limits": {
            "expanded_run_changes_particle_resolution_and_particle_mass": True,
            "expanded_run_is_not_a_domain_only_causal_control": True,
            "native_position_exclusion_is_not_physical_spill": True,
            "unclassified_or_unknown_destination_is_not_lost": True,
            "missing_identity_is_open_lifecycle_censoring": True,
            "first_passage_is_saved_chord_bracket": True,
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "not_assessed",
            "QE": "not_assessed",
        },
        "next_control_plan": {
            "status": "PREPARE_ONLY",
            "hypothesis": "If a domain-only repair is tested, retain BI4, MassFluid, CFL/dp, physics, geometry, motion, and save cadence; vary only numerical xyz bounds.",
            "required_pair_inputs": ["same typed initial IDs and source-MK mapping", "same actual saved time window", "same RunPARTs/Run.out source closure", "strict native PartVTKOut CSV identity join"],
            "decision_rule": "Compare native visibility and saved-bracket labels; never convert a reduced count into physical-fate or dynamics credit.",
            "launch": "not launched by this worker",
        },
        "read_policy": {
            "h5_opened": False,
            "trajectory_content_opened": False,
            "part_bi4_opened": False,
            "solver_started": False,
            "cfd_or_model_run": False,
        },
    }


def make_contract(trajectory_report: Path | str, conversion_report: Path | str,
                  expanded_native_report: Path | str, expanded_runout: Path | str,
                  output: Path | str) -> dict[str, Any]:
    """Create a new exact small-input contract after v1 report completion.

    The trajectory report is intentionally supplied at this point rather than
    guessed before the guarded v1 attempt.  The command hashes only these four
    small files; it never follows the report's H5 path.
    """
    contract = {
        "schema": CONTRACT_SCHEMA,
        "physical_case_id": PHYSICAL_CASE,
        "trajectory_report": bind({"path": str(trajectory_report)}, "trajectory labels report")[1],
        "conversion_report": bind({"path": str(conversion_report)}, "typed conversion report")[1],
        "expanded_native_report": bind({"path": str(expanded_native_report)}, "expanded native report")[1],
        "expanded_runout": bind({"path": str(expanded_runout)}, "expanded Run.out")[1],
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "solver_started": False},
    }
    path = Path(output).expanduser().resolve()
    atomic_json(path, contract)
    return {"status": "CONTRACT_CREATED", "contract": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="validate an exact four-file semantic contract")
    run.add_argument("--contract", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    make = subparsers.add_parser("make-contract", help="bind the completed v1 report and small native evidence")
    make.add_argument("--trajectory-report", type=Path, required=True)
    make.add_argument("--conversion-report", type=Path, required=True)
    make.add_argument("--expanded-native-report", type=Path, required=True)
    make.add_argument("--expanded-runout", type=Path, required=True)
    make.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "make-contract":
        result = make_contract(args.trajectory_report, args.conversion_report, args.expanded_native_report, args.expanded_runout, args.output)
    else:
        result = analyze(args.contract)
        atomic_json(args.output, result)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
