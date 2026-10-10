#!/usr/bin/env python3
"""Run a bounded, source-bound three-sentinel comparison study.

The parent supplies compact native-observer sidecars after reservation.  This
worker compares only fields already decoded by that observer: native headers,
typed role counts, native-MassFluid weighted fluid fields, and actual saved
times.  It never opens BI4, VTK, HDF5, Part files, or solver output.

Three modes enforce a single changed recipe variable:

* ``spatial``: three dp values with source/control/output invariants;
* ``integration``: two CFL values on one grid with an actual dt/clamp trace;
* ``output_sampling``: two output intervals on one grid/CFL recipe.

All differences are diagnostic.  The result grants no QI/QN/QE, does not
interpolate, and does not treat an adjacent grid as truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
SCHEMA = "ds02.stage2.three-sentinel.refstudy-worker.v1"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel.refstudy-manifest.v1"
SIDES_SCHEMA = "ds02.stage2.three-sentinel.observer-sidecar.v1"
TARGETS = {"F2-S2", "F3-S1", "F5-S1"}
DIMENSIONS = {"spatial", "integration", "output_sampling"}
MAX_JSON_BYTES = 10 * 1024 * 1024
TIME_EPS = 1.0e-12
UNKNOWN_Q = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}
RECIPE_KEYS = ("source_def_sha256", "source_xml_sha256", "control_sha256", "forcing_sha256", "physical_case_id")


class RefstudyFailure(RuntimeError):
    pass


def _abs(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"device": int(s.st_dev), "inode": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise RefstudyFailure(f"{label} is not a regular non-symlink JSON file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_JSON_BYTES:
        raise RefstudyFailure(f"{label} exceeds 10 MiB cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise RefstudyFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RefstudyFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RefstudyFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after, "bytes": len(raw)}


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RefstudyFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise RefstudyFailure(f"{label} is not finite")
    return result


def _vec(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise RefstudyFailure(f"{label} is not a three-vector")
    return [_finite(item, f"{label}[{i}]") for i, item in enumerate(value)]


def _same_json(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, separators=(",", ":"), ensure_ascii=False) == json.dumps(b, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _required_recipe(sidecar: dict[str, Any], label: str) -> dict[str, Any]:
    source = sidecar.get("source_contract")
    if not isinstance(source, dict):
        raise RefstudyFailure(f"{label} source_contract is missing")
    for key in RECIPE_KEYS:
        if not isinstance(source.get(key), str) or not source[key]:
            raise RefstudyFailure(f"{label} source_contract.{key} is missing")
    recipe = sidecar.get("recipe")
    if not isinstance(recipe, dict):
        raise RefstudyFailure(f"{label} recipe is missing")
    for key in ("definition_dp_m", "cfl_number", "coef_dt_min", "output_interval_s", "time_max_s"):
        _finite(recipe.get(key), f"{label} recipe.{key}")
    return source


def _read_sidecar(path: Path, expected_sha: str | None, expected_stat: dict[str, Any] | None,
                  label: str, manifest_identity: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    value, record = _read_json(path, label)
    if expected_sha not in (None, "", "UNKNOWN", "PARENT_AFTER_RESERVATION_REQUIRED") and record["sha256"] != expected_sha.lower():
        raise RefstudyFailure(f"{label} SHA differs from manifest")
    if not isinstance(expected_stat, dict):
        raise RefstudyFailure(f"{label} lacks a concrete post-reservation stat")
    for key in ("device", "inode", "bytes", "mtime_ns", "ctime_ns"):
        if key not in expected_stat or int(expected_stat[key]) != int(record["stat"][key]):
            raise RefstudyFailure(f"{label} stat.{key} differs from manifest")
    if value.get("schema") != SIDES_SCHEMA or value.get("status") != "COMPLETE_NATIVE_OBSERVER_FIELDS":
        raise RefstudyFailure(f"{label} is not a completed native observer sidecar")
    if value.get("sentinel_id") != manifest_identity["sentinel_id"] or value.get("physical_case_id") != manifest_identity["physical_case_id"]:
        raise RefstudyFailure(f"{label} physical identity differs from manifest")
    if value.get("scientific_qualification") not in (None, UNKNOWN_Q):
        raise RefstudyFailure(f"{label} grants scientific qualification")
    _required_recipe(value, label)
    native = value.get("native_header")
    roles = value.get("role_counts")
    if not isinstance(native, dict) or not isinstance(roles, dict):
        raise RefstudyFailure(f"{label} lacks native header or role counts")
    for key in ("MassFluid_kg", "MassBound_kg", "Dp_m"):
        _finite(native.get(key), f"{label} native_header.{key}")
    for key in ("fluid", "fixed", "moving", "total"):
        count = roles.get(key)
        if not isinstance(count, int) or count < 0:
            raise RefstudyFailure(f"{label} role_counts.{key} is invalid")
    if roles["fluid"] + roles["fixed"] + roles["moving"] != roles["total"]:
        raise RefstudyFailure(f"{label} role counts do not sum to total")
    if value.get("finite_native_fields") is not True or value.get("xml_mass_is_not_native") is not True:
        raise RefstudyFailure(f"{label} does not establish native finite fields/XML mass separation")
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise RefstudyFailure(f"{label} has no observations")
    times: list[float] = []
    for index, item in enumerate(observations):
        if not isinstance(item, dict):
            raise RefstudyFailure(f"{label} observation {index} is not an object")
        t = _finite(item.get("time_s"), f"{label} observation {index}.time_s")
        if times and t <= times[-1]:
            raise RefstudyFailure(f"{label} saved times are not strictly increasing")
        times.append(t)
        fluid = item.get("fluid_observables")
        if not isinstance(fluid, dict):
            raise RefstudyFailure(f"{label} observation {index} has no native fluid observables")
        _finite(fluid.get("mass_kg"), f"{label} observation {index}.mass_kg")
        _vec(fluid.get("weighted_centroid_m"), f"{label} observation {index}.centroid")
        _vec(fluid.get("weighted_velocity_m_per_s"), f"{label} observation {index}.velocity")
        _finite(fluid.get("kinetic_energy_j"), f"{label} observation {index}.kinetic_energy_j")
    return value, record


def _validate_dt(sidecar: dict[str, Any], label: str) -> dict[str, Any]:
    trace = sidecar.get("dt_trace")
    if not isinstance(trace, dict):
        raise RefstudyFailure(f"{label} requires an actual dt_trace")
    rows = trace.get("dt_rows")
    clamps = trace.get("clamped_count")
    if not isinstance(rows, int) or rows < 1 or not isinstance(clamps, int) or clamps < 0:
        raise RefstudyFailure(f"{label} dt_trace is invalid")
    return {"dt_rows": rows, "clamped_count": clamps,
            "min_dt_s": _finite(trace.get("min_dt_s"), f"{label} min_dt_s"),
            "max_dt_s": _finite(trace.get("max_dt_s"), f"{label} max_dt_s")}


def _validate_saved_times(sidecar: dict[str, Any], label: str) -> list[float]:
    trace = sidecar.get("saved_time_trace")
    if not isinstance(trace, dict) or not isinstance(trace.get("exact_saved_times_s"), list):
        raise RefstudyFailure(f"{label} requires exact saved_time_trace")
    values = [_finite(item, f"{label} exact_saved_times_s") for item in trace["exact_saved_times_s"]]
    if not values or any(b <= a for a, b in zip(values, values[1:])):
        raise RefstudyFailure(f"{label} saved_time_trace is not strictly increasing")
    if trace.get("saved_rows") != len(values):
        raise RefstudyFailure(f"{label} saved_time_trace row count mismatch")
    return values


def _recipe_pair(sidecars: list[dict[str, Any]], dimension: str) -> None:
    recipes = [item["recipe"] for item in sidecars]
    sources = [item["source_contract"] for item in sidecars]
    if not all(_same_json(sources[0], source) for source in sources[1:]):
        raise RefstudyFailure("source contract differs across the comparison")
    if dimension == "spatial":
        if len({str(item.get("grid_label")) for item in sidecars}) != 3:
            raise RefstudyFailure("spatial study requires three distinct grid labels")
        invariant = ("cfl_number", "coef_dt_min", "output_interval_s", "time_max_s")
        if any(not _same_json(recipes[0].get(key), recipe.get(key)) for recipe in recipes[1:] for key in invariant):
            raise RefstudyFailure("spatial study changes CFL/output/time control")
        if len({_finite(recipe["definition_dp_m"], "dp") for recipe in recipes}) != 3:
            raise RefstudyFailure("spatial study requires three distinct dp values")
    elif dimension == "integration":
        if len(sidecars) != 2:
            raise RefstudyFailure("integration study requires two records")
        invariant = ("definition_dp_m", "coef_dt_min", "output_interval_s", "time_max_s")
        if any(not _same_json(recipes[0].get(key), recipe.get(key)) for recipe in recipes[1:] for key in invariant):
            raise RefstudyFailure("integration study changes more than CFL")
        if _same_json(recipes[0].get("cfl_number"), recipes[1].get("cfl_number")):
            raise RefstudyFailure("integration study does not change CFL")
    elif dimension == "output_sampling":
        if len(sidecars) != 2:
            raise RefstudyFailure("output study requires two records")
        invariant = ("definition_dp_m", "cfl_number", "coef_dt_min", "time_max_s")
        if any(not _same_json(recipes[0].get(key), recipe.get(key)) for recipe in recipes[1:] for key in invariant):
            raise RefstudyFailure("output study changes more than output interval")
        if _same_json(recipes[0].get("output_interval_s"), recipes[1].get("output_interval_s")):
            raise RefstudyFailure("output study does not change output interval")


def _obs_map(sidecar: dict[str, Any]) -> dict[float, dict[str, Any]]:
    result: dict[float, dict[str, Any]] = {}
    for item in sidecar["observations"]:
        t = _finite(item["time_s"], "observation time")
        if t in result:
            raise RefstudyFailure(f"duplicate observation time {t}")
        result[t] = item
    return result


def _common_times(left: dict[float, dict[str, Any]], right: dict[float, dict[str, Any]]) -> list[tuple[float, float, float]]:
    rows: list[tuple[float, float, float]] = []
    for a in sorted(left):
        matches = [b for b in right if abs(a - b) <= TIME_EPS]
        if len(matches) == 1:
            rows.append((a, matches[0], abs(a - matches[0])))
    return rows


def _delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    lf, rf = left["fluid_observables"], right["fluid_observables"]
    lp, rp = _vec(lf["weighted_centroid_m"], "left centroid"), _vec(rf["weighted_centroid_m"], "right centroid")
    lv, rv = _vec(lf["weighted_velocity_m_per_s"], "left velocity"), _vec(rf["weighted_velocity_m_per_s"], "right velocity")
    dp = [a - b for a, b in zip(lp, rp)]
    dv = [a - b for a, b in zip(lv, rv)]
    return {"position_delta_m": dp, "position_l2_m": math.sqrt(sum(x * x for x in dp)),
            "velocity_delta_m_per_s": dv, "velocity_l2_m_per_s": math.sqrt(sum(x * x for x in dv)),
            "kinetic_energy_delta_j": _finite(lf["kinetic_energy_j"], "left KE") - _finite(rf["kinetic_energy_j"], "right KE"),
            "mass_delta_kg": _finite(lf["mass_kg"], "left mass") - _finite(rf["mass_kg"], "right mass")}


def run(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest, manifest_record = _read_json(manifest_path, "refstudy manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_PARENT_GUARDED_REFSTUDY":
        raise RefstudyFailure("manifest schema/status is not a guarded refstudy manifest")
    sid, dimension, physical = manifest.get("sentinel_id"), manifest.get("dimension"), manifest.get("physical_case_id")
    if sid not in TARGETS or dimension not in DIMENSIONS or not isinstance(physical, str):
        raise RefstudyFailure("manifest identity/dimension is invalid")
    scope = manifest.get("scientific_scope")
    if not isinstance(scope, dict) or scope.get("scientific_qualification") != UNKNOWN_Q or scope.get("interpolation") is not False or scope.get("neighbor_grid_truth") is not False:
        raise RefstudyFailure("manifest scientific scope is not explicitly no-Q/no-interpolation")
    records = manifest.get("observer_records")
    if not isinstance(records, list):
        raise RefstudyFailure("manifest has no observer records")
    expected_count = 3 if dimension == "spatial" else 2
    if len(records) != expected_count:
        raise RefstudyFailure(f"{dimension} requires {expected_count} observer records")
    identity = {"sentinel_id": sid, "physical_case_id": physical}
    sidecars: list[dict[str, Any]] = []
    sidecar_guards: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise RefstudyFailure(f"observer record {index} is malformed")
        expected_sha = record.get("sha256")
        if expected_sha in (None, "", "PARENT_AFTER_RESERVATION_REQUIRED", "UNKNOWN"):
            raise RefstudyFailure("refstudy cannot run until every deferred observer has a concrete post-reservation SHA")
        sidecar, guard = _read_sidecar(Path(record["path"]), str(expected_sha), record.get("stat"), f"observer {index}", identity)
        sidecars.append(sidecar); sidecar_guards.append(guard)
    _recipe_pair(sidecars, dimension)
    traces: list[dict[str, Any]] = []
    if dimension == "integration":
        traces = [_validate_dt(sidecar, f"observer {i}") for i, sidecar in enumerate(sidecars)]
    if dimension == "output_sampling":
        for i, sidecar in enumerate(sidecars):
            _validate_saved_times(sidecar, f"observer {i}")
    maps = [_obs_map(sidecar) for sidecar in sidecars]
    common = list(maps[0])
    for other in maps[1:]:
        common = [t for t in common if any(abs(t - candidate) <= TIME_EPS for candidate in other)]
    comparisons: list[dict[str, Any]] = []
    if dimension == "spatial":
        baseline = maps[0]
        for time in sorted(common):
            row = {"time_s": time, "comparisons": []}
            for index in range(1, len(maps)):
                match = next(candidate for candidate in maps[index] if abs(time - candidate) <= TIME_EPS)
                row["comparisons"].append({"right_time_s": match, "time_delta_s": match - time,
                                            "delta": _delta(baseline[time], maps[index][match])})
            comparisons.append(row)
    else:
        for time in sorted(common):
            match = next(candidate for candidate in maps[1] if abs(time - candidate) <= TIME_EPS)
            comparisons.append({"left_time_s": time, "right_time_s": match, "time_delta_s": match - time,
                                "delta": _delta(maps[0][time], maps[1][match])})
    status = "COMPLETE_REFSTUDY_DIAGNOSTIC_NO_Q" if comparisons else "COMPLETE_REFSTUDY_NO_EXACT_COMMON_SAVED_TIMES_NO_Q"
    result = {
        "schema": SCHEMA, "status": status, "sentinel_id": sid, "dimension": dimension,
        "physical_case_id": physical, "manifest": manifest_record, "observer_sources": sidecar_guards,
        "recipe_contract": manifest.get("recipe_contract"),
        "actual_common_saved_times_s": [row.get("time_s", row.get("left_time_s")) for row in comparisons],
        "comparison_count": len(comparisons), "comparisons": comparisons,
        "missing_time_scope": [{"sidecar_index": i, "times_s": sorted(set(_obs_map(sidecar)) - set(common))} for i, sidecar in enumerate(sidecars)],
        "dt_traces": traces,
        "interpretation": {"spatial": "diagnostic only; no adjacent-grid truth", "integration": "diagnostic CFL delta; no integration error bound", "output_sampling": "diagnostic saved-row delta; no output error bound", "time_alignment": "exact common saved times only; no interpolation", "event_time": "UNKNOWN"},
        "scientific_qualification": dict(UNKNOWN_Q),
        "read_scope": {"observer_json_only": True, "production_bi4": False, "production_vtk": False, "production_hdf5": False, "solver_launch": False, "gencase_launch": False},
    }
    output_path = _abs(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise RefstudyFailure(f"refusing to overwrite output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def _sidecar(root: Path, sid: str, grid: str, cfl: float, output: float, t: list[float]) -> Path:
    path = root / f"{grid}-{cfl}-{output}.json"
    observations = []
    for index, time in enumerate(t):
        observations.append({"frame_id": index, "time_s": time, "fluid_observables": {"mass_kg": 1.0, "weighted_centroid_m": [float(index), 0.0, 0.5], "weighted_velocity_m_per_s": [1.0, 0.0, 0.0], "kinetic_energy_j": 0.5}})
    # The fixture deliberately uses three distinct spatial definitions.  The
    # production worker must obtain these values from the actual observer
    # header/recipe; it must not infer a grid from a label.
    dp_by_grid = {"coarse": 0.01, "medium": 0.0075, "fine": 0.0048}
    value = {"schema": SIDES_SCHEMA, "status": "COMPLETE_NATIVE_OBSERVER_FIELDS", "sentinel_id": sid, "physical_case_id": "TEST_CASE", "grid_label": grid, "source_contract": {"source_def_sha256": "a" * 64, "source_xml_sha256": "b" * 64, "control_sha256": "c" * 64, "forcing_sha256": "d" * 64, "physical_case_id": "TEST_CASE"}, "recipe": {"definition_dp_m": dp_by_grid.get(grid, 0.01), "cfl_number": cfl, "coef_dt_min": 0.05, "output_interval_s": output, "time_max_s": 1.0}, "native_header": {"MassFluid_kg": 1.0, "MassBound_kg": 1.0, "Dp_m": dp_by_grid.get(grid, 0.01)}, "role_counts": {"fluid": 1, "fixed": 1, "moving": 0, "total": 2}, "finite_native_fields": True, "xml_mass_is_not_native": True, "observations": observations, "dt_trace": {"dt_rows": 2, "clamped_count": 0, "min_dt_s": 0.001, "max_dt_s": 0.002}, "saved_time_trace": {"saved_rows": len(t), "exact_saved_times_s": t}, "scientific_qualification": dict(UNKNOWN_Q)}
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fixture_manifest(root: Path, dimension: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    sid = "F3-S1"
    if dimension == "spatial":
        paths = [_sidecar(root, sid, grid, 0.05, 0.01, [0.0, 0.5]) for grid in ("coarse", "medium", "fine")]
    elif dimension == "integration":
        paths = [_sidecar(root, sid, "medium", cfl, 0.01, [0.0, 0.5]) for cfl in (0.05, 0.025)]
    else:
        paths = [_sidecar(root, sid, "medium", 0.05, out, [0.0, out]) for out in (0.01, 0.005)]
    records = [{"label": str(index), "path": str(path), "sha256": _sha(path.read_bytes()), "stat": _stat(path), "status": "PARENT_AFTER_RESERVATION_BOUND"} for index, path in enumerate(paths)]
    value = {"schema": MANIFEST_SCHEMA, "status": "READY_FOR_PARENT_GUARDED_REFSTUDY", "sentinel_id": sid, "dimension": dimension, "physical_case_id": "TEST_CASE", "observer_records": records, "scientific_scope": {"scientific_qualification": dict(UNKNOWN_Q), "interpolation": False, "neighbor_grid_truth": False}, "recipe_contract": {"dimension": dimension, "allowed_variable": {"spatial": "definition_dp_m", "integration": "cfl_number", "output_sampling": "output_interval_s"}[dimension]}}
    path = root / "manifest.json"; path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"); return path


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="three-sentinel-refstudy-") as td:
        root = Path(td)
        for dimension in DIMENSIONS:
            manifest = _fixture_manifest(root / dimension, dimension)
            output = root / f"{dimension}.report.json"
            result = run(manifest, output)
            assert result["status"].startswith("COMPLETE_REFSTUDY")
            assert result["scientific_qualification"] == UNKNOWN_Q
        bad = json.loads((_fixture_manifest(root / "bad", "integration")).read_text())
        bad["observer_records"][1]["sha256"] = "0" * 64
        bad_path = root / "bad-manifest.json"; bad_path.write_text(json.dumps(bad))
        try:
            run(bad_path, root / "bad-report.json")
        except RefstudyFailure:
            pass
        else:
            raise AssertionError("tampered observer SHA was accepted")
    print("PASS_THREE_SENTINEL_REFSTUDY_WORKER_V1_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test(); return 0
    if not args.run or args.manifest is None or args.output is None:
        parser.error("--run, --manifest and --output are required unless --self-test is used")
    try:
        result = run(args.manifest, args.output)
    except (RefstudyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_REFSTUDY_V1: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "dimension": result["dimension"], "comparison_count": result["comparison_count"], "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
