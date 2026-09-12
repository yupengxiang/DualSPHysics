"""Score the exact-tiling prospective F3 reference branch.

This scorer is separate from the failed revision075 scorer.  It keeps the
historical .010 failure immutable, reuses only hash-bound controls and
production evidence, and scores the new three-resolution ladder
``0.008181818.../.0075/.006``.  It never launches a solver.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from itertools import combinations
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

try:
    from scripts import f3_ref0081818_prepare as preparation
    from scripts import f3_revision075_score as old_score
    from scripts import l1r_branch_runner
    from scripts.f3_nopen_stage_score import CachedSource, _panel, _same_initial, score_pair, target_grid
    from scripts.f3_observation_v2 import compare, observe_arrays
    from scripts.l1r_continuation_evidence import LAB, OUT
    from scripts.l1r_q2_mdbc_bridge import SOLVER, atomic_json, sha256, utc_now
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import f3_ref0081818_prepare as preparation
    from scripts import f3_revision075_score as old_score
    from scripts import l1r_branch_runner
    from scripts.f3_nopen_stage_score import CachedSource, _panel, _same_initial, score_pair, target_grid
    from scripts.f3_observation_v2 import compare, observe_arrays
    from scripts.l1r_continuation_evidence import LAB, OUT
    from scripts.l1r_q2_mdbc_bridge import SOLVER, atomic_json, sha256, utc_now


RECIPE = preparation.RECIPE
MANIFEST = preparation.MANIFEST
SUMMARY = OUT / "F3-075-REF0081818-PREPARATION-SUMMARY.json"
AUTHORIZATION = OUT / "F3-075-REF0081818-AUTHORIZATION.json"
HORIZON = old_score.HORIZON
METRICS = old_score.METRICS
EXISTING_CASES = old_score.EXISTING_CASES
ENDPOINT_LADDER = ("R0081818", "R075-0075", "R075-006")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(LAB.resolve()))


def _bind(bindings: dict[str, str], path: Path) -> None:
    bindings[_relative(path)] = sha256(path)


def _verify_authorization() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Verify the owner authorization and all immutable preparation bindings."""
    if not AUTHORIZATION.is_file():
        raise PermissionError("ref0081818 owner authorization is required before scoring")
    manifest = _read(MANIFEST)
    summary = _read(SUMMARY)
    authorization = _read(AUTHORIZATION)
    manifest_sha = sha256(MANIFEST)
    summary_sha = sha256(SUMMARY)
    if authorization.get("status") != "owner_authorized" or authorization.get("recipe_id") != RECIPE:
        raise PermissionError("ref0081818 authorization is not owner-authorized")
    if authorization.get("manifest_sha256") != manifest_sha or authorization.get("summary_sha256") != summary_sha:
        raise PermissionError("ref0081818 authorization is bound to another preparation")
    if authorization.get("resource_limits") != {
        "cpu_core_hours": 896,
        "gpu_hours": 64,
        "qualification_attempts": 80,
    }:
        raise PermissionError("ref0081818 authorization caps differ from approved caps")
    # The shared runner performs the detailed cell, summary, record, asset and
    # preflight checks.  Calling it here is read-only for prepared records.
    records = _prepared_records(manifest, summary)
    for record in records.values():
        l1r_branch_runner._verify_ref008_authorization(record)
    return authorization, manifest, summary


def _prepared_records(manifest: dict[str, Any], summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if manifest.get("recipe_id") != RECIPE or manifest.get("launch_allowed") is not False:
        raise ValueError("ref0081818 manifest is not a prepared-only manifest")
    if (summary.get("recipe_id") != RECIPE or summary.get("launch_allowed") is not False
            or summary.get("manifest_sha256") != sha256(MANIFEST)
            or summary.get("solver_attempts") != 0
            or summary.get("qualification_attempts_charged") != 0
            or summary.get("qualified") is not False
            or summary.get("formal_release") is not False):
        raise ValueError("ref0081818 preparation summary is stale or not prepared-only")
    cells = {cell["cell_id"]: cell for cell in manifest.get("cells", [])}
    if set(summary.get("cell_ids", [])) != set(cells) or len(cells) != 3:
        raise ValueError("ref0081818 preparation must contain exactly three cells")
    records: dict[str, dict[str, Any]] = {}
    for relative in summary["prepared_records"]:
        path = LAB / relative
        record = _read(path)
        cell_id = record.get("plan_case_id")
        cell = cells.get(cell_id)
        expected = {
            "id": cell_id,
            "case_id": cell_id,
            "plan_case_id": cell_id,
            "recipe_id": RECIPE,
            "role": cell.get("role") if cell else None,
            "dp_m": cell.get("dp_m") if cell else None,
            "drive_amplitude": cell.get("amplitude") if cell else None,
            "revision_manifest_sha256": summary["manifest_sha256"],
            "resource_category": "qualification",
            "launch_allowed": False,
            "qualified": False,
            "formal_release": False,
        }
        if cell is None or any(record.get(key) != value for key, value in expected.items()):
            raise ValueError(f"ref0081818 record is not bound to the prepared cell: {path}")
        if cell_id in records:
            raise ValueError(f"duplicate ref0081818 cell: {cell_id}")
        records[cell_id] = record
    if set(records) != set(cells):
        raise ValueError("ref0081818 preparation is missing a cell")
    return records


def _new_source(label: str, record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    source, bindings = old_score._source_from_files(label, OUT / f"{record['id']}-PREPARED.json", revision=True)
    preflight = _read(OUT / f"{record['id']}-INPUT-PREFLIGHT.json")
    if (preflight.get("record_id") != record["id"]
            or preflight.get("record_sha256") != sha256(OUT / f"{record['id']}-PREPARED.json")
            or preflight.get("recipe_id") != RECIPE
            or preflight.get("revision_manifest_sha256") != sha256(MANIFEST)):
        raise ValueError(f"ref0081818 preflight binding is stale: {record['id']}")
    return source, bindings


def _row(first: dict[str, Any], second: dict[str, Any], time_s: float) -> dict[str, Any]:
    metrics = compare(first, second)
    if set(metrics) != set(METRICS):
        raise ValueError("v2 operator returned an incomplete metric set")
    return {"time_s": float(time_s), **{key: float(metrics[key]) for key in METRICS}}


def _series(source: dict[str, Any], handle: CachedSource) -> list[dict[str, Any]]:
    return [observe_arrays(*handle.state(float(time_s))[:3], handle.initial_mass)
            for time_s in target_grid(.01)]


def _panel_from_series(name_a: str, series_a: list[dict[str, Any]], name_b: str,
                       series_b: list[dict[str, Any]], kind: str, threshold: float) -> dict[str, Any]:
    rows = [_row(first, second, time_s)
            for time_s, first, second in zip(target_grid(.01), series_a, series_b)]
    return _panel(kind, [name_a, name_b], rows, threshold, grid_step_s=.01)


def _panel_pair(first: dict[str, Any], second: CachedSource, kind: str, threshold: float,
                *, step_s: float = .01, same_ids: bool = False) -> dict[str, Any]:
    return score_pair(first, second, kind=kind, step_s=step_s,
                      threshold=threshold, same_ids=same_ids)


def _audit_and_gate(sources: dict[str, dict[str, Any]], bindings: dict[str, str]) -> dict[str, Any]:
    panels: list[dict[str, Any]] = []
    with ExitStack() as stack:
        handles = {key: stack.enter_context(CachedSource(source))
                   for key, source in sources.items()}
        nominal = handles["REF-0075"]
        _same_initial(nominal, handles["R075-ZERO"])
        _same_initial(nominal, handles["R075-TIME"])
        _same_initial(nominal, handles["R075-OUTPUT"])
        zero = _series(sources["R075-ZERO"], handles["R075-ZERO"])
        panels.append(_panel_from_series("R075-ZERO", zero, "initial", [zero[0]] * len(zero),
                                         "zero_drive_vs_initial", .01))
        panels.append(_panel_pair(sources["REF-0075"], handles["R075-OUTPUT"],
                                  "output_interpolation", .01, step_s=.002, same_ids=True))
        panels.append(_panel_pair(sources["REF-0075"], handles["R075-TIME"],
                                  "temporal", .01, same_ids=True))

        nominal_keys = ["R0081818-NOMINAL", "REF-0075", "REF-006"]
        nominal_series = {key: _series(sources[key], handles[key]) for key in nominal_keys}
        for first, second in combinations(nominal_keys, 2):
            panels.append(_panel_from_series(first, nominal_series[first], second,
                                             nominal_series[second], "nominal_reference_spatial", .05))

        for prefix, kind in (("R0081818-ENDPOINT-LOW", "endpoint_low"),
                             ("R0081818-ENDPOINT-HIGH", "endpoint_high")):
            keys = [prefix, f"R075-ENDPOINT-{kind.split('_')[-1].upper()}-0075",
                    f"R075-ENDPOINT-{kind.split('_')[-1].upper()}-006"]
            series = {key: _series(sources[key], handles[key]) for key in keys}
            for first, second in combinations(keys, 2):
                panels.append(_panel_from_series(first, series[first], second, series[second],
                                                 kind, .05))
        internal = ["R075-INTERNAL-0075", "R075-INTERNAL-006"]
        series = {key: _series(sources[key], handles[key]) for key in internal}
        panels.append(_panel_from_series(internal[0], series[internal[0]], internal[1],
                                         series[internal[1]], "independent_internal_spatial", .05))
        frame_loads = {key: handle.frame_loads for key, handle in handles.items()}
    return {"panels": panels, "frame_loads": frame_loads}


def score() -> dict[str, Any]:
    authorization, manifest, summary = _verify_authorization()
    records = _prepared_records(manifest, summary)
    sources: dict[str, dict[str, Any]] = {}
    bindings: dict[str, str] = {}
    for label, case_id in EXISTING_CASES.items():
        source, bound = old_score._existing_source(label, case_id)
        sources[label] = source
        bindings.update(bound)
    for cell_id, record in records.items():
        source, bound = _new_source(cell_id, record)
        sources[cell_id] = source
        bindings.update(bound)
    result = _audit_and_gate(sources, bindings)
    for name in ("scripts/f3_ref0081818_score.py", "scripts/f3_revision075_score.py",
                 "scripts/f3_nopen_stage_score.py", "scripts/f3_observation_v2.py",
                 "scripts/f3_reference_score.py", "scripts/f3_timestep_evidence.py",
                 "scripts/l1r_q2_mdbc_bridge.py"):
        _bind(bindings, LAB / name)
    historical_report = OUT / "F3-075-REVISION-SCORES-887035e274d17b56f3c0ab4b749ca6988069b42060ee047b116224a8b8f38af6.json"
    if sha256(historical_report) != preparation.OLD_REPORT_SHA256:
        raise ValueError("immutable revision075 historical report changed")
    _bind(bindings, historical_report)
    report = {
        "schema": "f3.revision075.ref0081818.stage_scores.v1",
        "recipe_id": RECIPE,
        "created_at_utc": utc_now(),
        "status": "passed" if all(panel["status"] == "passed" for panel in result["panels"]) else "failed",
        "time_window_s": [0.0, HORIZON],
        "coordinate_frame": "fixed tank computational coordinates",
        "control_domain": [0.9, 1.1],
        "production_resolution_m": 0.0075,
        "reference_resolutions_m": [preparation.DP, 0.0075, 0.006],
        "retained_historical_resolution_m": 0.01,
        "panels": result["panels"],
        "native_frame_loads": result["frame_loads"],
        "evidence_sha256": bindings,
        "historical_failure_report": {
            "path": _relative(historical_report),
            "sha256": preparation.OLD_REPORT_SHA256,
            "status": "failed_immutable",
        },
        "owner_authorization_sha256": sha256(AUTHORIZATION),
        "scope": "full-window three-resolution numerical recipe gate; no material or learning qualification",
    }
    data = (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    report_path = OUT / f"F3-075-REF0081818-SCORES-{digest}.json"
    report_path.write_bytes(data)
    gate = {
        "schema": "f3.revision075.ref0081818.gate.v1",
        "recipe_id": RECIPE,
        "status": report["status"],
        "production_resolution_m": 0.0075,
        "reference_resolutions_m": [preparation.DP, 0.0075, 0.006],
        "retained_historical_resolution_m": 0.01,
        "time_window_s": [0.0, HORIZON],
        "control_domain": [0.9, 1.1],
        "coordinate_frame": "fixed tank computational coordinates",
        "scoring_evidence_path": _relative(report_path),
        "scoring_evidence_sha256": digest,
        "full_goal_complete": False,
        "development_launch_allowed": report["status"] == "passed",
        "material_production_allowed": False,
        "training_launch_allowed": False,
    }
    atomic_json(OUT / "F3-075-REF0081818-GATE.json", gate)
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
