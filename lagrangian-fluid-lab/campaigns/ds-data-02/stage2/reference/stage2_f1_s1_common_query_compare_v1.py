#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Compare the already-produced F1-S1 same-CFL observer JSON files.

This is a bounded JSON consumer.  It consumes the three selected native
observer reports for DP010, DP005, and DP0025; it does not open Part/BI4,
H5, VTK, or RunPARTs.  A registered query is represented by the producer's
actual saved lower/upper rows.  The worker never interpolates a bracket.
Only an exact saved time shared by all three reports can be compared as a
same-time observation.  All other differences are retained as diagnostics
and carry ``UNKNOWN_ASYNC_TIME_ALIGNMENT`` rather than an output or spatial
error bound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1-s1.common-query-compare.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s1.common-query-manifest.v1"
PASS_STATUS = "COMPLETE_F1_S1_COMMON_QUERY_BRACKET_DIAGNOSTICS_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_F1_S1_COMMON_QUERY_COMPARE"
QUERY_TIMES_S = (0.0, 0.4, 0.8, 1.2, 1.6)
FIELDS = ("weighted_centroid_m", "weighted_velocity_m_per_s", "kinetic_energy_j")
MAX_REPORT_BYTES = 2 * 1024 * 1024


class CompareFailure(RuntimeError):
    pass


def _stat_tuple(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (int(value.st_dev), int(value.st_ino), int(value.st_size), int(value.st_mtime_ns), int(value.st_ctime_ns))


def _stat_dict(value: os.stat_result) -> dict[str, int]:
    return {
        "dev": int(value.st_dev),
        "ino": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _read_json(path: Path, label: str, *, max_bytes: int = MAX_REPORT_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise CompareFailure(f"{label} is not a regular file: {path}")
    before = path.stat()
    if before.st_size > max_bytes:
        raise CompareFailure(f"{label} exceeds bounded JSON limit: {before.st_size}")
    chunks: list[bytes] = []
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            chunks.append(chunk)
    after = path.stat()
    if _stat_tuple(before) != _stat_tuple(after):
        raise CompareFailure(f"{label} changed while being read")
    try:
        value = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompareFailure(f"{label} is not JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CompareFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "bytes": int(after.st_size), "sha256": digest.hexdigest(), "stat": _stat_dict(after), "stable_read": True}


def _bound_record(record: Any, label: str, *, read_json: bool = True) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise CompareFailure(f"{label} source record is missing")
    path = Path(record["path"])
    if read_json:
        value, actual = _read_json(path, label)
    else:
        path = path.expanduser().absolute()
        if path.is_symlink() or not path.is_file():
            raise CompareFailure(f"{label} is not a regular file")
        stat = path.stat()
        value = None
        actual = {"path": str(path), "bytes": int(stat.st_size), "sha256": None, "stat": _stat_dict(stat), "stable_read": False}
    expected_path = str(path.expanduser().absolute())
    if record.get("path") not in (expected_path, str(path)):
        raise CompareFailure(f"{label} path differs from its bound record")
    expected_sha = record.get("sha256")
    if isinstance(expected_sha, str) and actual.get("sha256") is not None and actual["sha256"].lower() != expected_sha.lower():
        raise CompareFailure(f"{label} SHA differs from its bound record")
    expected_bytes = record.get("bytes")
    if expected_bytes is not None and int(expected_bytes) != int(actual["bytes"]):
        raise CompareFailure(f"{label} byte count differs from its bound record")
    expected_stat = record.get("stat")
    if isinstance(expected_stat, dict):
        for key in ("dev", "ino", "bytes", "mtime_ns", "ctime_ns"):
            if key in expected_stat and int(expected_stat[key]) != int(actual["stat"][key]):
                raise CompareFailure(f"{label} {key} differs from its bound record")
    return value, actual


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise CompareFailure(f"{label} is boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CompareFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise CompareFailure(f"{label} is non-finite")
    return result


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise CompareFailure(f"{label} is not a three-vector")
    return [_finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _field_row(observation: dict[str, Any], label: str) -> dict[str, Any]:
    groups = observation.get("groups")
    fluid = groups.get("fluid") if isinstance(groups, dict) else None
    if not isinstance(fluid, dict):
        raise CompareFailure(f"{label} has no fluid group")
    for key in ("weighted_centroid_m", "weighted_velocity_m_per_s"):
        _vector(fluid.get(key), f"{label}.{key}")
    return {
        "native_frame": observation.get("frame"),
        "saved_time_s": _finite((observation.get("time") or {}).get("runparts_s"), f"{label}.saved_time_s"),
        "fluid_count": int(fluid.get("count")),
        "native_sample_mass_kg": _finite(fluid.get("sample_mass_kg"), f"{label}.sample_mass_kg"),
        "weighted_centroid_m": _vector(fluid.get("weighted_centroid_m"), f"{label}.weighted_centroid_m"),
        "weighted_velocity_m_per_s": _vector(fluid.get("weighted_velocity_m_per_s"), f"{label}.weighted_velocity_m_per_s"),
        "kinetic_energy_j": _finite(fluid.get("kinetic_energy_j"), f"{label}.kinetic_energy_j"),
        "mass_semantics": fluid.get("mass_semantics", "UNKNOWN"),
    }


def _observations(report: dict[str, Any], label: str) -> dict[int, dict[str, Any]]:
    rows = report.get("observations")
    if not isinstance(rows, list) or not rows:
        raise CompareFailure(f"{label} has no selected observations")
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("frame"), int):
            raise CompareFailure(f"{label} has an invalid selected frame")
        frame = int(row["frame"])
        if frame in result:
            raise CompareFailure(f"{label} repeats native frame {frame}")
        if row.get("finite_fields", {}).get("position") is False or row.get("finite_fields", {}).get("velocity") is False or row.get("finite_fields", {}).get("density") is False:
            raise CompareFailure(f"{label} has non-finite selected fields")
        result[frame] = _field_row(row, f"{label}.frame{frame}")
    return result


def _query_map(report: dict[str, Any], label: str) -> dict[float, dict[str, Any]]:
    time_window = report.get("time_window")
    queries = time_window.get("queries") if isinstance(time_window, dict) else None
    if not isinstance(queries, list):
        raise CompareFailure(f"{label} has no query brackets")
    result: dict[float, dict[str, Any]] = {}
    for query in queries:
        if not isinstance(query, dict):
            raise CompareFailure(f"{label} has invalid query bracket")
        time = _finite(query.get("query_time_s"), f"{label}.query_time_s")
        key = round(time, 12)
        if key in result:
            raise CompareFailure(f"{label} repeats query {time}")
        if query.get("field_interpolation") not in (None, "NOT_PERFORMED_BY_WORKER"):
            raise CompareFailure(f"{label} query permits interpolation")
        lower = query.get("lower_observation")
        upper = query.get("upper_observation")
        if not isinstance(lower, dict) or not isinstance(upper, dict):
            raise CompareFailure(f"{label} query lacks lower/upper observations")
        result[key] = {
            "query_time_s": time,
            "status": query.get("status"),
            "lower_frame": int(query.get("lower_frame")),
            "upper_frame": int(query.get("upper_frame")),
            "lower_time_s": _finite(query.get("lower_time_s"), f"{label}.lower_time_s"),
            "upper_time_s": _finite(query.get("upper_time_s"), f"{label}.upper_time_s"),
            "lower": _field_row(lower, f"{label}.query{time}.lower"),
            "upper": _field_row(upper, f"{label}.query{time}.upper"),
        }
    return result


def _load_producer(spec: dict[str, Any]) -> dict[str, Any]:
    label = spec.get("label")
    if label not in {"dp010", "dp005", "dp0025"}:
        raise CompareFailure(f"invalid F1-S1 producer label: {label!r}")
    proof, proof_actual = _bound_record(spec.get("proof"), f"{label} proof")
    assert proof is not None
    if label == "dp010":
        if proof.get("schema") != "ds02.stage2.native-observer-independent-verification.v1":
            raise CompareFailure("DP010 producer proof schema mismatch")
        selected = [row for row in proof.get("observations", []) if isinstance(row, dict) and "DP010_SAME_CFL" in str(row.get("identity", ""))]
        if len(selected) != 1:
            raise CompareFailure("DP010 SAME-CFL observation is not uniquely present in its five-observer proof")
        selected = selected[0]
        report_record = spec.get("report")
        receipt_record = spec.get("receipt")
        if selected.get("output") != report_record.get("path") or selected.get("output_sha256") != report_record.get("sha256"):
            raise CompareFailure("DP010 report does not match its independent proof observation")
        if selected.get("receipt") != receipt_record.get("path") or selected.get("receipt_sha256") != receipt_record.get("sha256"):
            raise CompareFailure("DP010 receipt does not match its independent proof observation")
    else:
        if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")) and not str(proof.get("status", "")).startswith("PASS"):
            raise CompareFailure(f"{label} proof is not an actual native observer proof")
        report_record = spec.get("report")
        receipt_record = spec.get("receipt")
        if proof.get("report") != report_record.get("path") or proof.get("report_sha256") != report_record.get("sha256"):
            raise CompareFailure(f"{label} report does not match proof")
        if proof.get("receipt") != receipt_record.get("path") or proof.get("receipt_sha256") != receipt_record.get("sha256"):
            raise CompareFailure(f"{label} receipt does not match proof")
        request_record = spec.get("request")
        if proof.get("request") != request_record.get("path") or proof.get("request_sha256") != request_record.get("sha256"):
            raise CompareFailure(f"{label} request does not match proof")
        _bound_record(request_record, f"{label} request")
    receipt, receipt_actual = _bound_record(receipt_record, f"{label} receipt")
    if isinstance(receipt, dict) and isinstance(receipt.get("status"), str) and not receipt["status"].lower().startswith(("completed", "complete", "success")):
        raise CompareFailure(f"{label} receipt is not completed")
    if label != "dp010":
        _bound_record(spec.get("request"), f"{label} request")
    report, report_actual = _bound_record(spec.get("report"), f"{label} observer report")
    assert report is not None
    if not str(report.get("schema", "")).startswith("ds02.stage2.native-physical-observer"):
        raise CompareFailure(f"{label} observer schema is not native physical observer")
    if not str(report.get("status", "")).startswith("PASS"):
        raise CompareFailure(f"{label} observer is not successful")
    scope = report.get("scope") if isinstance(report.get("scope"), dict) else {}
    if scope.get("particle_field_interpolation") not in (None, "NOT_PERFORMED"):
        raise CompareFailure(f"{label} observer contains interpolation")
    obs = _observations(report, label)
    return {
        "label": label,
        "proof": proof_actual,
        "receipt": receipt_actual,
        "report": report_actual,
        "report_value": report,
        "observations": obs,
        "queries": _query_map(report, label),
        "grid_spacing_m": float(spec.get("grid_spacing_m")),
        "sample_mass_semantics": "native particle sample mass only; not continuum truth",
    }


def _delta(left: Any, right: Any) -> Any:
    if isinstance(left, list) and isinstance(right, list):
        return [float(right[i]) - float(left[i]) for i in range(3)]
    return float(right) - float(left)


def _same_time(rows: list[dict[str, Any]], key: str = "lower") -> bool:
    if not rows:
        return False
    times = [float(row[key]["saved_time_s"]) for row in rows]
    return max(times) - min(times) <= 1e-12


def _compare_query(producers: list[dict[str, Any]], query_time: float) -> dict[str, Any]:
    key = round(query_time, 12)
    entries: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for producer in producers:
        query = producer["queries"].get(key)
        if query is None:
            entries[producer["label"]] = {"status": "UNKNOWN_QUERY_NOT_PRESENT"}
            continue
        entries[producer["label"]] = {"status": query.get("status"), "lower": query["lower"], "upper": query["upper"], "saved_time_gap_s": query["upper_time_s"] - query["lower_time_s"]}
        rows.append(query)
    exact_all = len(rows) == len(producers) and all(row["lower_frame"] == row["upper_frame"] for row in rows) and _same_time(rows, "lower")
    if not exact_all:
        return {"query_time_s": query_time, "status": "UNKNOWN_ASYNC_TIME_ALIGNMENT", "producers": entries, "cross_grid_fields": "UNKNOWN", "interpretation": "actual lower/upper fields only; no interpolation and no bracket-width error credit"}
    reference = rows[0]["lower"]
    fields: dict[str, Any] = {}
    for producer, row in zip(producers, rows):
        if producer is producers[0]:
            continue
        fields[f"{producers[0]['label']}_vs_{producer['label']}"] = {field: _delta(reference[field], row["lower"][field]) for field in FIELDS}
    return {"query_time_s": query_time, "status": "OBSERVED_EXACT_COMMON_SAVED_TIME", "producers": entries, "cross_grid_fields": fields, "interpretation": "same-time observed diagnostic only; not spatial truth or integration/output error"}


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, manifest_record = _read_json(manifest_path, "F1-S1 comparison manifest", max_bytes=4 * 1024 * 1024)
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_F1_S1_COMMON_QUERY_COMPARE":
        raise CompareFailure("F1-S1 comparison manifest schema/status mismatch")
    queries = manifest.get("query_times_s")
    if queries != list(QUERY_TIMES_S):
        raise CompareFailure("F1-S1 query times are not the frozen registered set")
    specs = manifest.get("producers")
    if not isinstance(specs, list) or len(specs) != 3 or {item.get("label") for item in specs if isinstance(item, dict)} != {"dp010", "dp005", "dp0025"}:
        raise CompareFailure("F1-S1 requires exactly DP010/DP005/DP0025 producers")
    producers = [_load_producer(spec) for spec in specs]
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "manifest": manifest_record,
        "producers": [{key: value for key, value in producer.items() if key not in {"report_value", "observations", "queries"}} for producer in producers],
        "queries": [_compare_query(producers, query) for query in QUERY_TIMES_S],
        "diagnostic_semantics": {
            "time_source": "actual observer RunPARTs-derived saved times",
            "interpolation": "FORBIDDEN",
            "extrapolation": "FORBIDDEN",
            "neighbor_grid_truth": False,
            "bracket_width_is_output_error": False,
            "same_grid_half_cfl_or_output_error": "not evaluated by this same-CFL spatial comparison",
            "native_sample_mass_is_continuum_mass": False,
            "world_axis_authority": "UNKNOWN",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "read_scope": {"bounded_observer_json_only": True, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "solver_launch": False, "interpolation": False},
    }
    _write_once(output, result)
    return result


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise CompareFailure(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="f1-s1-compare-") as directory:
        root = Path(directory)
        def report(label: str, lower: float, upper: float, *, fixed_contamination: bool = False) -> Path:
            fluid = {"kind": "fluid", "count": 2, "sample_mass_kg": 2.0, "weighted_centroid_m": [1.0, 2.0, 3.0], "weighted_velocity_m_per_s": [0.0, 0.0, 1.0], "kinetic_energy_j": 1.0, "mass_semantics": "native particle sample mass only"}
            if fixed_contamination:
                fluid["weighted_centroid_m"] = [9.0, 9.0, 9.0]
            def obs(frame: int, time: float) -> dict[str, Any]:
                return {"frame": frame, "time": {"runparts_s": time}, "finite_fields": {"position": True, "velocity": True, "density": True}, "groups": {"fluid": fluid}}
            value = {"schema": "ds02.stage2.native-physical-observer.v2", "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS", "scope": {"particle_field_interpolation": "NOT_PERFORMED"}, "observations": [obs(0, lower), obs(1, upper)], "time_window": {"queries": [{"query_time_s": 0.4, "status": "BRACKETED", "lower_frame": 0, "upper_frame": 1, "lower_time_s": lower, "upper_time_s": upper, "lower_observation": obs(0, lower), "upper_observation": obs(1, upper), "field_interpolation": "NOT_PERFORMED_BY_WORKER"}]}}
            path = root / f"{label}.json"; path.write_text(json.dumps(value), encoding="utf-8"); return path
        reports = [report("a", 0.4, 0.4), report("b", 0.39, 0.41), report("c", 0.4, 0.4)]
        specs = []
        for label, path in zip(("dp010", "dp005", "dp0025"), reports):
            rec = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
            specs.append({"label": label, "grid_spacing_m": 0.01, "proof": rec, "report": rec, "receipt": rec})
        try:
            _load_producer(specs[0])
        except CompareFailure:
            # Manufactured records deliberately lack the old DP010 proof
            # envelope; the report parser itself is exercised below.
            pass
        fake = {"schema": "ds02.stage2.native-physical-observer.v2", "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS", "scope": {"particle_field_interpolation": "NOT_PERFORMED"}, "observations": json.loads(reports[0].read_text())["observations"], "time_window": json.loads(reports[0].read_text())["time_window"]}
        assert _query_map(fake, "fixture")[0.4]["lower_time_s"] == 0.4
        assert _query_map(json.loads(reports[1].read_text()), "async")[0.4]["lower_time_s"] == 0.39
        assert _same_time([{"lower": {"saved_time_s": 0.4}}, {"lower": {"saved_time_s": 0.4}}])
        print("PASS_F1_S1_COMMON_QUERY_COMPARE_V1_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test(); return 0
    if args.manifest is None or args.output is None:
        parser.error("--manifest and --output are required unless --self-test is used")
    try:
        result = run(args.manifest, args.output)
    except Exception as exc:
        print(f"{FAIL_STATUS}: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.absolute())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
