#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""ROOT240 additive compact F3-S2 three-grid diagnostic.

The coarse producer is ROOT247's bounded compact JSON product; middle and
fine are the existing V5 compact summaries.  This worker joins each compact
product to both its observer and solver proof/request/receipt chains.  It
never opens a Part/BI4/H5/VTK file or a legacy full report.  Saved brackets
are retained as observations.  No interpolation, neighbouring-grid truth,
or scientific qualification is produced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

SCHEMA = "ds02.stage2.f3-s2.compact-spatial-lifecycle-compare.v2"
MANIFEST_SCHEMA = "ds02.stage2.f3-s2.compact-spatial-lifecycle-manifest.v2"
PASS_STATUS = "COMPLETE_F3_S2_COMPACT_SPATIAL_LIFECYCLE_DIAGNOSTICS_V2_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE_V2"
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)
MAX_JSON_BYTES = 4 * 1024 * 1024
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"


class CompareFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _read_json(path: Path, label: str, limit: int = MAX_JSON_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise CompareFailure(f"{label} is not a regular file")
    before = _stat(path)
    if before["bytes"] > limit:
        raise CompareFailure(f"{label} exceeds bounded JSON limit: {before['bytes']}")
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            chunks.append(chunk)
    after = _stat(path)
    if before != after:
        raise CompareFailure(f"{label} changed while being read")
    try:
        value = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompareFailure(f"{label} is not JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CompareFailure(f"{label} is not a JSON object")
    return value, {"path": str(path), "sha256": digest.hexdigest(), "bytes": after["bytes"],
                   "stat": after, "stable_read": True}


def _bound(record: Any, label: str, limit: int = MAX_JSON_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise CompareFailure(f"{label} source record is missing")
    value, actual = _read_json(Path(record["path"]), label, limit)
    if Path(record["path"]).expanduser().absolute() != Path(actual["path"]):
        raise CompareFailure(f"{label} path differs from binding")
    if record.get("sha256") and str(record["sha256"]).lower() != actual["sha256"]:
        raise CompareFailure(f"{label} SHA differs from binding")
    if record.get("bytes") is not None and int(record["bytes"]) != actual["bytes"]:
        raise CompareFailure(f"{label} byte count differs from binding")
    if isinstance(record.get("stat"), dict):
        for key in ("dev", "ino", "bytes", "mtime_ns", "ctime_ns"):
            if key in record["stat"] and int(record["stat"][key]) != actual["stat"][key]:
                raise CompareFailure(f"{label} {key} differs from binding")
    return value, actual


def _num(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise CompareFailure(f"{label} is boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CompareFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise CompareFailure(f"{label} is not finite")
    return result


def _vec(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise CompareFailure(f"{label} is not a three-vector")
    return [_num(v, f"{label}[{i}]") for i, v in enumerate(value)]


def _record_edges(producer: dict[str, Any], label: str) -> dict[str, Any]:
    proof, proof_r = _bound(producer.get("observer_proof"), f"{label} observer proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise CompareFailure(f"{label} observer proof is not actual")
    obs_req, obs_req_r = _bound(producer.get("observer_request"), f"{label} observer request")
    obs_rec, obs_rec_r = _bound(producer.get("observer_receipt"), f"{label} observer receipt")
    if proof.get("request") != obs_req_r["path"] or proof.get("request_sha256") != obs_req_r["sha256"]:
        raise CompareFailure(f"{label} observer proof/request join failed")
    if proof.get("receipt") != obs_rec_r["path"] or proof.get("receipt_sha256") != obs_rec_r["sha256"]:
        raise CompareFailure(f"{label} observer proof/receipt join failed")
    if not str(obs_rec.get("status", "")).lower().startswith(("complete", "success")):
        raise CompareFailure(f"{label} observer receipt is not complete")
    solver_proof, solver_proof_r = _bound(producer.get("solver_proof"), f"{label} solver proof")
    if solver_proof.get("schema") not in {"ds02.stage2.root-actual-verification.v1", "ds02.stage2.root-actual-external-solver-verification.v1"} or "ACTUAL" not in str(solver_proof.get("status", "")):
        raise CompareFailure(f"{label} solver proof is not actual")
    solver_req, solver_req_r = _bound(producer.get("solver_request"), f"{label} solver request")
    solver_rec, solver_rec_r = _bound(producer.get("solver_receipt"), f"{label} solver receipt")
    if solver_proof.get("request") != solver_req_r["path"] or solver_proof.get("request_sha256") != solver_req_r["sha256"]:
        raise CompareFailure(f"{label} solver proof/request join failed")
    if solver_proof.get("receipt") != solver_rec_r["path"] or solver_proof.get("receipt_sha256") != solver_rec_r["sha256"]:
        raise CompareFailure(f"{label} solver proof/receipt join failed")
    if not str(solver_rec.get("status", "")).lower().startswith(("complete", "success")):
        raise CompareFailure(f"{label} solver receipt is not complete")
    if obs_req.get("physical_case_id") not in {None, PHYSICAL_CASE_ID}:
        raise CompareFailure(f"{label} observer physical case differs")
    return {"observer_proof": proof_r, "observer_request": obs_req_r, "observer_receipt": obs_rec_r,
            "solver_proof": solver_proof_r, "solver_request": solver_req_r, "solver_receipt": solver_rec_r,
            "observer_proof_value": proof, "solver_proof_value": solver_proof}


def _summary_link(proof: dict[str, Any], record: dict[str, Any], label: str) -> None:
    """Require the proof's compact output edge to point to this exact file."""
    path = record["path"]
    sha = record["sha256"]
    found = False
    for key in ("summary", "report", "observer_report", "compact_report", "output", "child_report"):
        value = proof.get(key)
        if isinstance(value, str):
            found = found or value == path
            if value == path:
                bound_sha = proof.get(f"{key}_sha256") or proof.get("report_sha256") or proof.get("summary_sha256")
                if bound_sha and str(bound_sha).lower() != sha:
                    raise CompareFailure(f"{label} proof/{key} SHA mismatch")
        elif isinstance(value, dict) and value.get("path") == path:
            found = True
            if value.get("sha256") and str(value["sha256"]).lower() != sha:
                raise CompareFailure(f"{label} proof/{key} SHA mismatch")
    if not found:
        raise CompareFailure(f"{label} compact summary is not linked by observer proof")


def _fields(row: dict[str, Any], label: str) -> dict[str, Any]:
    fields = row.get("fields")
    if not isinstance(fields, dict):
        raise CompareFailure(f"{label} fields are missing")
    centroid = fields.get("weighted_centroid_m")
    velocity = fields.get("weighted_velocity_m_per_s")
    energy = fields.get("kinetic_energy_j")
    return {"weighted_centroid_m": _vec(centroid, f"{label}.centroid"),
            "weighted_velocity_m_per_s": _vec(velocity, f"{label}.velocity"),
            "kinetic_energy_j": _num(energy, f"{label}.kinetic_energy_j"),
            "fluid_count": fields.get("fluid_count"), "sample_mass_kg": fields.get("sample_mass_kg"),
            "native_header": row.get("native_header")}


def _normalize_coarse(summary: dict[str, Any], label: str) -> dict[str, Any]:
    if summary.get("schema") != "ds02.stage2.f3-s2.coarse-deferred-json-observer.v2" or not str(summary.get("status", "")).startswith("PASS"):
        raise CompareFailure(f"{label} coarse compact schema/status mismatch")
    window = summary.get("window")
    queries = summary.get("queries")
    if not isinstance(window, dict) or not isinstance(queries, list) or len(queries) != 5:
        raise CompareFailure(f"{label} coarse compact window/queries missing")
    obs: dict[int, dict[str, Any]] = {}
    brackets: list[dict[str, Any]] = []
    for q in queries:
        if not isinstance(q, dict):
            raise CompareFailure(f"{label} coarse query invalid")
        qt = _num(q.get("query_time_s"), f"{label}.query_time_s")
        endpoints = q.get("endpoints")
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            raise CompareFailure(f"{label} coarse query endpoints missing")
        lower = next((x for x in endpoints if isinstance(x, dict) and x.get("side") == "lower"), None)
        upper = next((x for x in endpoints if isinstance(x, dict) and x.get("side") == "upper"), None)
        if not isinstance(lower, dict) or not isinstance(upper, dict):
            raise CompareFailure(f"{label} coarse endpoint sides missing")
        for side, endpoint in (("lower", lower), ("upper", upper)):
            frame = endpoint.get("frame")
            if not isinstance(frame, int):
                raise CompareFailure(f"{label} coarse {side} frame invalid")
            row = {"frame": frame, "runparts_time_s": endpoint.get("time_s"), "fields": endpoint.get("fields"), "native_header": {"MassFluid": endpoint.get("native_massfluid_kg")}}
            obs.setdefault(frame, {"frame": frame, "time_s": _num(endpoint.get("time_s"), f"{label}.{side}.time_s"), "fields": _fields(row, f"{label}.{side}")})
        brackets.append({"query_time_s": qt, "status": q.get("status"), "lower_frame": lower["frame"], "upper_frame": upper["frame"], "lower_time_s": _num(lower.get("time_s"), "lower_time_s"), "upper_time_s": _num(upper.get("time_s"), "upper_time_s"), "bracket_width_s": _num(q.get("bracket_width_s", float(upper["time_s"]) - float(lower["time_s"])), "bracket_width_s"), "interpolation_performed": False})
    return {"label": label, "schema": summary["schema"], "frame_count": int(window.get("frame_count", -1)), "first_saved_time_s": _num(window.get("first_saved_time_s"), f"{label}.first_saved_time_s"), "last_saved_time_s": _num(window.get("last_saved_time_s"), f"{label}.last_saved_time_s"), "native_header_summary": {"MassFluid_values_kg": window.get("native_massfluid_values_kg")}, "initial_counts": window.get("initial_fields"), "final_counts": window.get("final_fields"), "lifecycle_counts": summary.get("lifecycle"), "observations": obs, "query_brackets": brackets, "summary_scope": summary.get("scope"), "native_massfluid_kg": (window.get("native_massfluid_values_kg") or [None])[0]}


def _normalize_v5(summary: dict[str, Any], label: str) -> dict[str, Any]:
    if summary.get("schema") != "ds02.stage2.f3-s2.full-native-stream-observer.v5" or not str(summary.get("status", "")).startswith("PASS"):
        raise CompareFailure(f"{label} V5 compact schema/status mismatch")
    if summary.get("case_binding", {}).get("physical_case_id") not in {None, PHYSICAL_CASE_ID}:
        raise CompareFailure(f"{label} physical case differs")
    if int(summary.get("frame_count", -1)) != 836:
        raise CompareFailure(f"{label} frame count differs")
    observations: dict[int, dict[str, Any]] = {}
    for row in summary.get("selected_observations", []):
        if not isinstance(row, dict) or not isinstance(row.get("frame"), int):
            raise CompareFailure(f"{label} selected observation invalid")
        frame = int(row["frame"])
        if frame in observations:
            raise CompareFailure(f"{label} selected frame repeated")
        observations[frame] = {"frame": frame, "time_s": _num(row.get("runparts_time_s", row.get("decoded_time_s")), f"{label}.frame{frame}.time"), "fields": _fields(row, f"{label}.frame{frame}")}
    brackets = summary.get("query_brackets")
    if not isinstance(brackets, list):
        raise CompareFailure(f"{label} query brackets missing")
    return {"label": label, "schema": summary["schema"], "frame_count": int(summary["frame_count"]), "first_saved_time_s": _num(summary.get("first_saved_time_s"), f"{label}.first_saved_time_s"), "last_saved_time_s": _num(summary.get("last_saved_time_s"), f"{label}.last_saved_time_s"), "native_header_summary": summary.get("native_header_summary"), "initial_counts": summary.get("initial_counts"), "final_counts": summary.get("final_counts"), "lifecycle_counts": summary.get("lifecycle_counts"), "observations": observations, "query_brackets": brackets, "summary_scope": summary.get("summary_scope")}


def _query(grid: dict[str, Any], query_time: float) -> dict[str, Any]:
    candidates = [x for x in grid.get("query_brackets", []) if isinstance(x, dict) and abs(_num(x.get("query_time_s"), "query") - query_time) < 1e-12]
    if len(candidates) != 1:
        return {"query_time_s": query_time, "status": "UNKNOWN_QUERY_NOT_PRESENT"}
    q = candidates[0]
    lower, upper = int(q["lower_frame"]), int(q["upper_frame"])
    result = {"query_time_s": query_time, "status": q.get("status"), "lower": {"frame": lower, "time_s": _num(q.get("lower_time_s"), "lower_time_s")}, "upper": {"frame": upper, "time_s": _num(q.get("upper_time_s"), "upper_time_s")}, "bracket_width_s": _num(q.get("bracket_width_s", float(q["upper_time_s"]) - float(q["lower_time_s"])), "bracket_width_s")}
    if lower in grid["observations"]:
        result["lower"]["fields"] = grid["observations"][lower]["fields"]
    if upper in grid["observations"]:
        result["upper"]["fields"] = grid["observations"][upper]["fields"]
    if "fields" not in result["lower"] or "fields" not in result["upper"]:
        result["status"] = "UNKNOWN_BRACKET_FIELDS_NOT_SELECTED"
    return result


def _pair(left: dict[str, Any], right: dict[str, Any], query_time: float) -> dict[str, Any]:
    lq, rq = _query(left, query_time), _query(right, query_time)
    # Compare only readings already saved at the same native time.  A bracket
    # never licenses interpolation or a numerical error estimate.
    if lq.get("status") not in {"EXACT", "EXACT_OR_LEFT"} or rq.get("status") not in {"EXACT", "EXACT_OR_LEFT"}:
        return {"query_time_s": query_time, "status": "UNKNOWN_ASYNC_TIME_ALIGNMENT", "left": lq, "right": rq, "field_difference": "UNKNOWN"}
    if lq["lower"]["time_s"] != rq["lower"]["time_s"]:
        return {"query_time_s": query_time, "status": "UNKNOWN_ASYNC_TIME_ALIGNMENT", "left": lq, "right": rq, "field_difference": "UNKNOWN"}
    a, b = lq["lower"]["fields"], rq["lower"]["fields"]
    return {"query_time_s": query_time, "status": "OBSERVED_EXACT_COMMON_SAVED_TIME", "left": lq, "right": rq, "field_difference": {"weighted_centroid_m": [b["weighted_centroid_m"][i] - a["weighted_centroid_m"][i] for i in range(3)], "weighted_velocity_m_per_s": [b["weighted_velocity_m_per_s"][i] - a["weighted_velocity_m_per_s"][i] for i in range(3)], "kinetic_energy_j": b["kinetic_energy_j"] - a["kinetic_energy_j"]}}


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, manifest_record = _read_json(manifest_path, "F3 V2 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE_V2":
        raise CompareFailure("manifest schema/status mismatch")
    producers = manifest.get("producers")
    if not isinstance(producers, list) or {p.get("label") for p in producers if isinstance(p, dict)} != {"coarse", "middle", "fine"}:
        raise CompareFailure("manifest must contain coarse, middle, fine")
    if manifest.get("query_times_s") != list(QUERY_TIMES_S):
        raise CompareFailure("query set is not frozen")
    grids: dict[str, dict[str, Any]] = {}
    bindings: dict[str, Any] = {}
    for p in producers:
        label = p["label"]
        bindings[label] = _record_edges(p, label)
        summary, summary_record = _bound(p.get("summary"), f"{label} compact summary")
        _summary_link(bindings[label]["observer_proof_value"], summary_record, label)
        if label == "coarse":
            grids[label] = _normalize_coarse(summary, label)
        else:
            grids[label] = _normalize_v5(summary, label)
        grids[label]["summary_record"] = summary_record
        bindings[label].pop("observer_proof_value", None); bindings[label].pop("solver_proof_value", None)
    result = {"schema": SCHEMA, "status": PASS_STATUS, "manifest": manifest_record, "producer_bindings": bindings, "grids": grids, "queries_s": list(QUERY_TIMES_S), "pairwise_observed_differences": {"coarse_vs_middle": [_pair(grids["coarse"], grids["middle"], t) for t in QUERY_TIMES_S], "coarse_vs_fine": [_pair(grids["coarse"], grids["fine"], t) for t in QUERY_TIMES_S], "middle_vs_fine": [_pair(grids["middle"], grids["fine"], t) for t in QUERY_TIMES_S]}, "lifecycle_diagnostics": {"semantics": "compact selected-frame lifecycle only; disappearance is not physical flux/fate", "physical_fate_or_flux": "UNKNOWN"}, "diagnostic_semantics": {"saved_time_source": "producer RunPARTs-derived saved times retained by compact products", "interpolation": "FORBIDDEN", "bracket_width_is_field_error": False, "neighbor_grid_truth": False, "event_time": "UNKNOWN", "spatial_error_bound": "UNKNOWN", "integration_error_bound": "UNKNOWN", "output_error_bound": "UNKNOWN"}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}, "read_scope": {"compact_json_only": True, "max_compact_bytes": MAX_JSON_BYTES, "full_report_read": False, "legacy_report_read": False, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "solver_launch": False, "interpolation": False}}
    _write_once(output, result)
    return result


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise CompareFailure(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _self_test() -> None:
    def v5(t: float) -> dict[str, Any]:
        row = {"frame": 0, "runparts_time_s": t, "fields": {"weighted_centroid_m": [1, 2, 3], "weighted_velocity_m_per_s": [0, 0, 1], "kinetic_energy_j": 1}}
        return {"schema": "ds02.stage2.f3-s2.full-native-stream-observer.v5", "status": "PASS_TEST", "case_binding": {"physical_case_id": PHYSICAL_CASE_ID}, "frame_count": 836, "first_saved_time_s": 0, "last_saved_time_s": 8, "native_header_summary": {}, "initial_counts": {}, "final_counts": {}, "lifecycle_counts": {}, "selected_observations": [row], "query_brackets": [{"query_time_s": 0, "status": "EXACT_OR_LEFT", "lower_frame": 0, "upper_frame": 0, "lower_time_s": t, "upper_time_s": t}]}
    def coarse(t: float) -> dict[str, Any]:
        row = {"side": "lower", "frame": 0, "time_s": t, "native_massfluid_kg": .1, "fields": {"weighted_centroid_m": [1, 2, 3], "weighted_velocity_m_per_s": [0, 0, 1], "kinetic_energy_j": 1}}
        row2 = dict(row); row2["side"] = "upper"
        return {"schema": "ds02.stage2.f3-s2.coarse-deferred-json-observer.v2", "status": "PASS_TEST", "window": {"frame_count": 836, "first_saved_time_s": 0, "last_saved_time_s": 8, "native_massfluid_values_kg": [.1], "initial_fields": {}, "final_fields": {}}, "queries": [{"query_time_s": q, "status": "EXACT", "lower_time_s": t, "upper_time_s": t, "bracket_width_s": 0, "endpoints": [dict(row, frame=int(q)), dict(row2, frame=int(q))]} for q in (0, 2, 4, 6, 8)], "lifecycle": {}}
    a, b = _normalize_coarse(coarse(0), "a"), _normalize_v5(v5(1e-6), "b")
    assert _pair(a, b, 0)["status"] == "UNKNOWN_ASYNC_TIME_ALIGNMENT"
    bad = v5(0); bad["schema"] = "wrong"
    try: _normalize_v5(bad, "bad")
    except CompareFailure: pass
    else: raise AssertionError("bad schema accepted")
    print("PASS_F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE_V2_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path); parser.add_argument("--output", type=Path); parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test(); return 0
    if args.manifest is None or args.output is None:
        parser.error("--manifest and --output are required unless --self-test is used")
    try:
        result = run(args.manifest, args.output)
    except Exception as exc:
        print(f"{FAIL_STATUS}: {exc}"); return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().absolute())}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
