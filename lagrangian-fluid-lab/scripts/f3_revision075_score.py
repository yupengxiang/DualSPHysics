"""Score completed revision075 sources under the frozen F3 v2 operator.

The scorer is intentionally separate from the historical NP01--NP14 gate.  It
binds the prospective 0.0075 m recipe, the three existing nominal-resolution
sources (only as hash-bound evidence), and every new revision cell.  It never
launches a solver.  Owner authorization is required before it reads a
prospective execution result or publishes a revision gate.
"""

from __future__ import annotations

import argparse
import csv
from contextlib import ExitStack
from itertools import combinations
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

try:
    from scripts import f3_nopen_stage_score as base_score
    from scripts import f3_revision075_launch_gate as launch_gate
    from scripts.f3_observation_v2 import compare
    from scripts.f3_timestep_evidence import evidence as timestep_evidence
    from scripts.l1r_continuation_evidence import LAB, OUT
    from scripts.l1r_input_preflight import check_input
    from scripts.l1r_q2_mdbc_bridge import atomic_json, sha256, utc_now
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import f3_nopen_stage_score as base_score
    from scripts import f3_revision075_launch_gate as launch_gate
    from scripts.f3_observation_v2 import compare
    from scripts.f3_timestep_evidence import evidence as timestep_evidence
    from scripts.l1r_continuation_evidence import LAB, OUT
    from scripts.l1r_input_preflight import check_input
    from scripts.l1r_q2_mdbc_bridge import atomic_json, sha256, utc_now


RECIPE = launch_gate.RECIPE
HORIZON = base_score.HORIZON
METRICS = base_score.METRICS
SUMMARY = launch_gate.SUMMARY
EXISTING_CASES = {
    "REF-010": "F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_nopen",
    "REF-0075": "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen",
    "REF-006": "F3_CELL3_LONG_dp0p006_a1p000_noslip_visco1_nopen",
}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(LAB.resolve()))


def _bind(bindings: dict[str, str], path: Path) -> None:
    bindings[_relative(path)] = sha256(path)


def _revision_records() -> dict[str, dict[str, Any]]:
    _, summary = launch_gate.verify_preparation()
    records = {}
    for relative in summary["prepared_records"]:
        record_path = LAB / relative
        record = _read(record_path)
        if (record.get("revision_manifest_sha256") != summary["manifest_sha256"]
                or record.get("launch_allowed") is not False):
            raise ValueError(f"revision record is not bound to the prepared manifest: {record_path}")
        records[record["plan_case_id"]] = record
    if len(records) != 11:
        raise ValueError("revision preparation must contain all 11 cells")
    return records


def _source_from_files(label: str, record_path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    record = _read(record_path)
    check_input(record)
    case_id = record["id"]
    audit_path = OUT / f"{case_id}-AUDIT.json"
    solver_path = OUT / f"{case_id}-SOLVER.json"
    preflight_path = OUT / f"{case_id}-INPUT-PREFLIGHT.json"
    for path in (audit_path, solver_path, preflight_path):
        if not path.is_file():
            raise ValueError(f"completed source evidence is missing: {path}")
    audit, solver, preflight = map(_read, (audit_path, solver_path, preflight_path))
    if (solver.get("status") != "completed"
            or audit.get("audit_status") != "pass_diagnostic"
            or audit.get("issues") != [] or audit.get("unknowns") != []):
        raise ValueError(f"source hard audit is not a clean pass: {case_id}")
    if (audit.get("time_start_s") != 0
            or not HORIZON <= audit.get("time_end_s", -1) < HORIZON + .01
            or audit.get("frames") != round(HORIZON / record["time_out_s"]) + 1):
        raise ValueError(f"source does not cover the full registered window: {case_id}")
    for field in ("identities_introduced_after_initial", "initial_identities_missing_at_final",
                  "identities_reappeared_after_gap", "excluded_particles_from_solver_log",
                  "finite_bad_value_rows"):
        if audit.get(field) != 0:
            raise ValueError(f"source lifecycle gate is nonzero: {case_id}:{field}")
    penetration = audit.get("penetration", {})
    for field in ("frames_with_penetration", "frames_with_runtime_domain_outside", "swept_crossing_count"):
        if penetration.get(field) != 0:
            raise ValueError(f"source wall gate is nonzero: {case_id}:{field}")
    if penetration.get("runtime_domain_status") != "checked":
        raise ValueError(f"source runtime domain is unchecked: {case_id}")
    hdf5_path = LAB / audit["hdf5"]
    if not hdf5_path.is_file() or sha256(hdf5_path) != audit.get("hdf5_sha256"):
        raise ValueError(f"source HDF5 changed or is missing: {case_id}")
    if preflight.get("status") != "passed":
        raise ValueError(f"source input preflight is not passed: {case_id}")
    native = timestep_evidence(case_id)
    bindings = {}
    for path in (record_path, audit_path, solver_path, preflight_path, hdf5_path,
                 Path(solver["attempt_directory"]) / "Run.out",
                 Path(solver["attempt_directory"]) / "RunPARTs.csv",
                 LAB / record["generated_prefix"]):
        if path.is_file():
            _bind(bindings, path)
    bindings[_relative(LAB / native["csv_path"])] = native["csv_sha256"]
    source = {
        "label": label,
        "case_id": case_id,
        "record": record,
        "audit": audit,
        "hdf5_path": hdf5_path,
        "entry": {"dp_m": record["dp_m"], "output_interval_s": record["time_out_s"]},
        "native_timestep": native,
    }
    return source, bindings


def _existing_source(label: str, case_id: str) -> tuple[dict[str, Any], dict[str, str]]:
    return _source_from_files(label, OUT / f"{case_id}-PREPARED.json")


def _revision_source(label: str, record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    return _source_from_files(label, OUT / f"{record['id']}-PREPARED.json")


def _row(first, second, time_s: float) -> dict[str, Any]:
    metrics = compare(first, second)
    if set(metrics) != set(METRICS):
        raise ValueError("v2 operator returned an incomplete metric set")
    return {"time_s": float(time_s), **{k: float(metrics[k]) for k in METRICS}}


def _series(source, handle) -> list[dict[str, Any]]:
    return [base_score.observe_arrays(*handle.state(float(t))[:3], handle.initial_mass)
            for t in base_score.target_grid(.01)]


def _panel_from_series(name_a, series_a, name_b, series_b, kind, threshold):
    rows = [_row(a, b, t) for t, a, b in zip(base_score.target_grid(.01), series_a, series_b)]
    return base_score._panel(kind, [name_a, name_b], rows, threshold, grid_step_s=.01)


def _panel(first, second, kind, threshold, *, step_s=.01, same_ids=False):
    return base_score.score_pair(first, second, kind=kind, step_s=step_s,
                                 threshold=threshold, same_ids=same_ids)


def _audit_and_gate(sources: dict[str, dict[str, Any]], bindings: dict[str, str]) -> dict[str, Any]:
    panels = []
    with ExitStack() as stack:
        handles = {key: stack.enter_context(base_score.CachedSource(source))
                   for key, source in sources.items()}
        nominal = handles["REF-0075"]
        # Production controls: all three controls share the .0075 m initial state.
        _same_initial = base_score._same_initial
        _same_initial(nominal, handles["R075-ZERO"])
        _same_initial(nominal, handles["R075-TIME"])
        _same_initial(nominal, handles["R075-OUTPUT"])
        zero = _series(sources["R075-ZERO"], handles["R075-ZERO"])
        initial = [zero[0]] * len(zero)
        panels.append(_panel_from_series("R075-ZERO", zero, "initial", initial,
                                         "zero_drive_vs_initial", .01))
        panels.append(_panel(nominal, handles["R075-OUTPUT"], "output_interpolation", .01,
                             step_s=.002, same_ids=True))
        panels.append(_panel(nominal, handles["R075-TIME"], "temporal", .01,
                             step_s=.01, same_ids=True))
        first_dt = handles["REF-0075"].source["native_timestep"]
        second_dt = handles["R075-TIME"].source["native_timestep"]
        ratios = {key: second_dt[key] / first_dt[key] for key in ("dt_min_s", "dt_max_s")}
        temporal_halving = {
            "status": "passed" if all(abs(value - .5) <= 1e-12 for value in ratios.values()) else "failed",
            "actual_ratios": ratios,
            "expected_ratio": .5,
        }

        # Existing nominal sources are bound as evidence, but the failed
        # REF-010↔REF-006 pair is intentionally not treated as a gate panel.
        ref_series = {key: _series(sources[key], handles[key])
                      for key in ("REF-010", "REF-0075", "REF-006")}
        panels.append(_panel_from_series("REF-010", ref_series["REF-010"],
                                         "REF-0075", ref_series["REF-0075"],
                                         "nominal_reference_spatial", .05))
        panels.append(_panel_from_series("REF-0075", ref_series["REF-0075"],
                                         "REF-006", ref_series["REF-006"],
                                         "nominal_reference_spatial", .05))

        for prefix, label in (("R075-ENDPOINT-LOW", "endpoint_low"),
                              ("R075-ENDPOINT-HIGH", "endpoint_high")):
            keys = [f"{prefix}-{dp}" for dp in ("010", "0075", "006")]
            series = {key: _series(sources[key], handles[key]) for key in keys}
            for a, b in combinations(keys, 2):
                panels.append(_panel_from_series(a, series[a], b, series[b], label, .05))
        internal = ["R075-INTERNAL-0075", "R075-INTERNAL-006"]
        series = {key: _series(sources[key], handles[key]) for key in internal}
        panels.append(_panel_from_series(internal[0], series[internal[0]],
                                         internal[1], series[internal[1]],
                                         "independent_internal_spatial", .05))
        frame_loads = {key: handle.frame_loads for key, handle in handles.items()}
    return {"panels": panels, "frame_loads": frame_loads, "temporal_halving": temporal_halving}


def score() -> dict[str, Any]:
    """Read, score, and publish the revision gate after authorized runs."""
    auth = launch_gate.verify_authorization()
    revision = _revision_records()
    sources, bindings = {}, {}
    for label, case_id in EXISTING_CASES.items():
        source, bound = _existing_source(label, case_id)
        sources[label] = source
        bindings.update(bound)
    for cell_id, record in revision.items():
        source, bound = _revision_source(cell_id, record)
        sources[cell_id] = source
        bindings.update(bound)
    result = _audit_and_gate(sources, bindings)
    for name in ("scripts/f3_revision075_score.py", "scripts/f3_nopen_stage_score.py",
                 "scripts/f3_observation_v2.py", "scripts/f3_reference_score.py",
                 "scripts/f3_timestep_evidence.py", "scripts/l1r_q2_mdbc_bridge.py"):
        _bind(bindings, LAB / name)
    report = {
        "schema": "f3.revision075.stage_scores.v1",
        "recipe_id": RECIPE,
        "created_at_utc": utc_now(),
        "status": "passed" if (all(p["status"] == "passed" for p in result["panels"])
                                 and result["temporal_halving"]["status"] == "passed") else "failed",
        "time_window_s": [0.0, HORIZON],
        "coordinate_frame": "fixed tank computational coordinates",
        "control_domain": [0.9, 1.1],
        "production_resolution_m": 0.0075,
        "reference_resolutions_m": [0.01, 0.006],
        "panels": result["panels"],
        "native_frame_loads": result["frame_loads"],
        "temporal_halving": result["temporal_halving"],
        "evidence_sha256": bindings,
        "owner_authorization_sha256": sha256(launch_gate.DEFAULT_AUTHORIZATION),
        "scope": "full-window numerical recipe gate; no material or learning qualification",
    }
    data = (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    report_path = OUT / f"F3-075-REVISION-SCORES-{digest}.json"
    report_path.write_bytes(data)
    gate = {
        "schema": "f3.revision075.gate.v1",
        "recipe_id": RECIPE,
        "status": report["status"],
        "production_resolution_m": 0.0075,
        "reference_resolutions_m": [0.01, 0.006],
        "time_window_s": [0.0, HORIZON],
        "control_domain": [0.9, 1.1],
        "coordinate_frame": "fixed tank computational coordinates",
        "scoring_evidence_path": _relative(report_path),
        "scoring_evidence_sha256": digest,
        "full_goal_complete": False,
        "development_launch_allowed": False,
        "material_production_allowed": False,
        "training_launch_allowed": False,
    }
    atomic_json(OUT / "F3-075-REVISION-GATE.json", gate)
    return gate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("score",))
    args = parser.parse_args(argv)
    try:
        result = score()
    except (PermissionError, ValueError, KeyError, FileNotFoundError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
