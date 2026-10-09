#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Compare F3-S2 coarse/middle/fine compact native diagnostics.

ROOT150 is intentionally represented by its small terminal proof only: its
observer product is a legacy 14.8 MB full report and no compact sidecar was
produced.  This worker therefore never opens that report.  ROOT177 and
ROOT178 are consumed through their <=2 MB compact summaries.  The result
retains a strict three-producer/source join, reports middle/fine lifecycle
and saved-bracket diagnostics, and explicitly leaves any three-grid field
error unavailable until a guarded coarse compact sidecar exists.

No Part/BI4, H5, VTK, RunPARTs, or full observer report is opened here.  A
neighbouring grid is never treated as truth, and bracket endpoints are never
interpolated.
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


SCHEMA = "ds02.stage2.f3-s2.compact-spatial-lifecycle-compare.v1"
MANIFEST_SCHEMA = "ds02.stage2.f3-s2.compact-spatial-lifecycle-manifest.v1"
PASS_STATUS = "COMPLETE_F3_S2_COMPACT_SPATIAL_LIFECYCLE_DIAGNOSTICS_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE"
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)
MAX_SUMMARY_BYTES = 4 * 1024 * 1024
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"


class CompareFailure(RuntimeError):
    pass


def _stat_tuple(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (int(value.st_dev), int(value.st_ino), int(value.st_size), int(value.st_mtime_ns), int(value.st_ctime_ns))


def _stat_dict(value: os.stat_result) -> dict[str, int]:
    return {"dev": int(value.st_dev), "ino": int(value.st_ino), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _read_json(path: Path, label: str, *, max_bytes: int = MAX_SUMMARY_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise CompareFailure(f"{label} is not a regular file: {path}")
    before = path.stat()
    if before.st_size > max_bytes:
        raise CompareFailure(f"{label} exceeds bounded JSON limit: {before.st_size}")
    digest = hashlib.sha256(); chunks: list[bytes] = []
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk); chunks.append(chunk)
    after = path.stat()
    if _stat_tuple(before) != _stat_tuple(after):
        raise CompareFailure(f"{label} changed while being read")
    try:
        value = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompareFailure(f"{label} is not JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CompareFailure(f"{label} is not a JSON object")
    return value, {"path": str(path), "bytes": int(after.st_size), "sha256": digest.hexdigest(), "stat": _stat_dict(after), "stable_read": True}


def _bound(record: Any, label: str, *, read_json: bool = True, max_bytes: int = MAX_SUMMARY_BYTES) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise CompareFailure(f"{label} source record is missing")
    path = Path(record["path"])
    if read_json:
        value, actual = _read_json(path, label, max_bytes=max_bytes)
    else:
        path = path.expanduser().absolute()
        if path.is_symlink() or not path.is_file():
            raise CompareFailure(f"{label} is not a regular file")
        stat = path.stat(); value = None
        actual = {"path": str(path), "bytes": int(stat.st_size), "sha256": None, "stat": _stat_dict(stat), "stable_read": False}
    if Path(str(record["path"])).expanduser().absolute() != Path(actual["path"]):
        raise CompareFailure(f"{label} path differs from source record")
    if record.get("sha256") is not None and actual.get("sha256") is not None and str(record["sha256"]).lower() != str(actual["sha256"]).lower():
        raise CompareFailure(f"{label} SHA differs from source record")
    if record.get("bytes") is not None and int(record["bytes"]) != int(actual["bytes"]):
        raise CompareFailure(f"{label} byte count differs from source record")
    bound_stat = record.get("stat")
    if isinstance(bound_stat, dict):
        for key in ("dev", "ino", "bytes", "mtime_ns", "ctime_ns"):
            if key in bound_stat and int(bound_stat[key]) != int(actual["stat"][key]):
                raise CompareFailure(f"{label} {key} differs from source record")
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


def _record_solver_edges(producer: dict[str, Any], label: str) -> dict[str, Any]:
    """Validate actual observer proof/request/receipt and solver proof edges."""
    proof, proof_record = _bound(producer.get("observer_proof"), f"{label} observer proof")
    assert proof is not None
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise CompareFailure(f"{label} observer proof is not an actual terminal proof")
    request, request_record = _bound(producer.get("observer_request"), f"{label} observer request")
    receipt, receipt_record = _bound(producer.get("observer_receipt"), f"{label} observer receipt")
    if proof.get("request") != request_record["path"] or proof.get("request_sha256") != request_record["sha256"]:
        raise CompareFailure(f"{label} observer proof/request join failed")
    if proof.get("receipt") != receipt_record["path"] or proof.get("receipt_sha256") != receipt_record["sha256"]:
        raise CompareFailure(f"{label} observer proof/receipt join failed")
    if isinstance(receipt, dict) and not str(receipt.get("status", "")).lower().startswith(("completed", "complete", "success")):
        raise CompareFailure(f"{label} observer receipt is not completed")
    solver_proof, solver_proof_record = _bound(producer.get("solver_proof"), f"{label} solver proof")
    assert solver_proof is not None
    if solver_proof.get("schema") not in {"ds02.stage2.root-actual-verification.v1", "ds02.stage2.root-actual-external-solver-verification.v1"} or "ACTUAL" not in str(solver_proof.get("status", "")):
        raise CompareFailure(f"{label} solver proof is not actual")
    solver_request, solver_request_record = _bound(producer.get("solver_request"), f"{label} solver request")
    solver_receipt, solver_receipt_record = _bound(producer.get("solver_receipt"), f"{label} solver receipt")
    if solver_proof.get("request") != solver_request_record["path"] or solver_proof.get("request_sha256") != solver_request_record["sha256"]:
        raise CompareFailure(f"{label} solver proof/request join failed")
    if solver_proof.get("receipt") != solver_receipt_record["path"] or solver_proof.get("receipt_sha256") != solver_receipt_record["sha256"]:
        raise CompareFailure(f"{label} solver proof/receipt join failed")
    if isinstance(solver_receipt, dict) and not str(solver_receipt.get("status", "")).lower().startswith(("completed", "complete", "success")):
        raise CompareFailure(f"{label} solver receipt is not completed")
    if isinstance(request, dict) and request.get("physical_case_id") not in {None, PHYSICAL_CASE_ID}:
        raise CompareFailure(f"{label} observer physical case differs")
    return {"observer_proof": proof_record, "observer_request": request_record, "observer_receipt": receipt_record, "solver_proof": solver_proof_record, "solver_request": solver_request_record, "solver_receipt": solver_receipt_record, "observer_proof_value": proof, "solver_proof_value": solver_proof}


def _summary_values(summary: dict[str, Any], label: str) -> dict[str, Any]:
    if summary.get("schema") != "ds02.stage2.f3-s2.full-native-stream-observer.v5" or not str(summary.get("status", "")).startswith("PASS"):
        raise CompareFailure(f"{label} compact summary schema/status is not successful")
    binding = summary.get("case_binding")
    if not isinstance(binding, dict) or binding.get("physical_case_id") not in {None, PHYSICAL_CASE_ID}:
        raise CompareFailure(f"{label} compact summary case binding is missing or differs")
    if int(summary.get("frame_count", -1)) != 836:
        raise CompareFailure(f"{label} compact summary frame count is not 836")
    header = summary.get("native_header_summary")
    if not isinstance(header, dict):
        raise CompareFailure(f"{label} compact summary has no native header summary")
    initial = summary.get("initial_counts"); final = summary.get("final_counts"); lifecycle = summary.get("lifecycle_counts")
    if not isinstance(initial, dict) or not isinstance(final, dict) or not isinstance(lifecycle, dict):
        raise CompareFailure(f"{label} compact count/lifecycle fields are missing")
    selected = summary.get("selected_observations")
    if not isinstance(selected, list) or not selected:
        raise CompareFailure(f"{label} compact selected observations are missing")
    obs_by_frame: dict[int, dict[str, Any]] = {}
    for row in selected:
        if not isinstance(row, dict) or not isinstance(row.get("frame"), int):
            raise CompareFailure(f"{label} compact selected frame is invalid")
        frame = int(row["frame"])
        if frame in obs_by_frame:
            raise CompareFailure(f"{label} compact selected frame repeats")
        fields = row.get("fields")
        if not isinstance(fields, dict):
            raise CompareFailure(f"{label} compact selected fields are missing")
        _vector(fields.get("weighted_centroid_m"), f"{label}.frame{frame}.centroid")
        _vector(fields.get("weighted_velocity_m_per_s"), f"{label}.frame{frame}.velocity")
        _finite(fields.get("kinetic_energy_j"), f"{label}.frame{frame}.kinetic")
        obs_by_frame[frame] = {"frame": frame, "time_s": _finite(row.get("runparts_time_s", row.get("decoded_time_s")), f"{label}.frame{frame}.time"), "fields": {"weighted_centroid_m": fields["weighted_centroid_m"], "weighted_velocity_m_per_s": fields["weighted_velocity_m_per_s"], "kinetic_energy_j": fields["kinetic_energy_j"], "fluid_count": fields.get("fluid_count"), "sample_mass_kg": fields.get("sample_mass_kg"), "native_header": row.get("native_header")}}
    brackets = summary.get("query_brackets")
    if not isinstance(brackets, list):
        raise CompareFailure(f"{label} compact query brackets are missing")
    return {"label": label, "frame_count": int(summary["frame_count"]), "first_saved_time_s": _finite(summary.get("first_saved_time_s"), f"{label}.first_saved_time_s"), "last_saved_time_s": _finite(summary.get("last_saved_time_s"), f"{label}.last_saved_time_s"), "native_header_summary": header, "initial_counts": initial, "final_counts": final, "lifecycle_counts": lifecycle, "query_brackets": brackets, "observations": obs_by_frame, "scientific_qualification": summary.get("scientific_qualification"), "summary_scope": summary.get("summary_scope")}


def _query_diag(grid: dict[str, Any], query_time: float) -> dict[str, Any]:
    brackets = {round(_finite(item.get("query_time_s"), f"{grid['label']}.query"), 12): item for item in grid["query_brackets"] if isinstance(item, dict)}
    item = brackets.get(round(query_time, 12))
    if item is None:
        return {"query_time_s": query_time, "status": "UNKNOWN_QUERY_NOT_PRESENT"}
    lower = int(item.get("lower_frame")); upper = int(item.get("upper_frame"))
    result = {"query_time_s": query_time, "status": item.get("status"), "lower": {"frame": lower, "time_s": _finite(item.get("lower_time_s"), "lower_time_s")}, "upper": {"frame": upper, "time_s": _finite(item.get("upper_time_s"), "upper_time_s")}, "saved_time_gap_s": _finite(item.get("upper_time_s"), "upper_time_s") - _finite(item.get("lower_time_s"), "lower_time_s")}
    if lower in grid["observations"] and upper in grid["observations"]:
        result["lower"]["fields"] = grid["observations"][lower]["fields"]
        result["upper"]["fields"] = grid["observations"][upper]["fields"]
    else:
        result["status"] = "UNKNOWN_BRACKET_FIELDS_NOT_SELECTED"
    return result


def _pair_diag(left: dict[str, Any], right: dict[str, Any], query_time: float) -> dict[str, Any]:
    lq = _query_diag(left, query_time); rq = _query_diag(right, query_time)
    exact_statuses = {"EXACT", "EXACT_OR_LEFT"}
    if lq.get("status") not in exact_statuses or rq.get("status") not in exact_statuses or lq.get("lower", {}).get("time_s") != rq.get("lower", {}).get("time_s"):
        return {"query_time_s": query_time, "status": "UNKNOWN_ASYNC_TIME_ALIGNMENT", "left": lq, "right": rq, "field_difference": "UNKNOWN"}
    fields: dict[str, Any] = {}
    for field in ("weighted_centroid_m", "weighted_velocity_m_per_s"):
        a = lq["lower"]["fields"][field]; b = rq["lower"]["fields"][field]
        fields[field] = [float(b[i]) - float(a[i]) for i in range(3)]
    fields["kinetic_energy_j"] = float(rq["lower"]["fields"]["kinetic_energy_j"]) - float(lq["lower"]["fields"]["kinetic_energy_j"])
    return {"query_time_s": query_time, "status": "OBSERVED_EXACT_COMMON_SAVED_TIME", "left": lq, "right": rq, "field_difference": fields}


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, manifest_record = _read_json(manifest_path, "F3 compact comparison manifest", max_bytes=4 * 1024 * 1024)
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE":
        raise CompareFailure("F3 compact comparison manifest schema/status mismatch")
    producers = manifest.get("producers")
    if not isinstance(producers, list) or {item.get("label") for item in producers if isinstance(item, dict)} != {"coarse", "middle", "fine"}:
        raise CompareFailure("F3 compact comparison requires coarse/middle/fine")
    loaded: dict[str, dict[str, Any]] = {}
    bindings: dict[str, Any] = {}
    for producer in producers:
        label = producer["label"]
        bindings[label] = _record_solver_edges(producer, label)
        if label == "coarse":
            proof = bindings[label]["observer_proof_value"]
            loaded[label] = {"label": label, "frame_count": proof.get("frame_count"), "native_massfluid_kg": proof.get("native_massfluid_kg"), "initial_counts": {"fluid_count": 4320, "fixed_count": 19944}, "final_counts": "UNKNOWN_LEGACY_REPORT_NOT_READ", "lifecycle_counts": "UNKNOWN_LEGACY_REPORT_NOT_READ", "compact_fields": "UNKNOWN_LEGACY_REPORT_NOT_READ", "source_scope": "proof/header metadata only; legacy full report intentionally not opened"}
        else:
            summary, summary_actual = _bound(producer.get("summary"), f"{label} compact summary")
            assert summary is not None
            if producer.get("summary", {}).get("sha256") != summary_actual["sha256"]:
                raise CompareFailure(f"{label} compact summary SHA differs")
            loaded[label] = _summary_values(summary, label)
            loaded[label]["summary_record"] = summary_actual
    queries = manifest.get("query_times_s")
    if queries != list(QUERY_TIMES_S):
        raise CompareFailure("F3 compact query set is not frozen")
    result = {"schema": SCHEMA, "status": PASS_STATUS, "manifest": manifest_record, "producer_bindings": {label: {key: value for key, value in value.items() if not key.endswith("_value")} for label, value in bindings.items()}, "grids": loaded, "queries": {"middle_vs_fine": [_pair_diag(loaded["middle"], loaded["fine"], query) for query in QUERY_TIMES_S], "three_grid_fields": "UNKNOWN_COARSE_COMPACT_SIDECAR_NOT_AVAILABLE"}, "lifecycle_diagnostics": {"semantics": "observed compact event counts only; disappearance is not physical flux/fate", "middle_vs_fine": {"middle": loaded["middle"]["lifecycle_counts"], "fine": loaded["fine"]["lifecycle_counts"]}, "coarse": "UNKNOWN_LEGACY_REPORT_NOT_READ"}, "diagnostic_semantics": {"saved_time_source": "compact observer RunPARTs-derived saved times", "interpolation": "FORBIDDEN", "neighbor_grid_truth": False, "bracket_width_is_error": False, "spatial_error_bound": "UNKNOWN", "integration_error_bound": "UNKNOWN", "output_error_bound": "UNKNOWN", "physical_fate_or_flux": "UNKNOWN"}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}, "read_scope": {"compact_summary_json_only": True, "legacy_coarse_full_report_read": False, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "solver_launch": False, "interpolation": False}}
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
    # Test compact-summary normalization and the intended async refusal using
    # a tiny fixture; no production proof or full report is touched.
    def summary(label: str, t: float) -> dict[str, Any]:
        row = {"frame": 0, "runparts_time_s": t, "fields": {"weighted_centroid_m": [1.0, 2.0, 3.0], "weighted_velocity_m_per_s": [0.0, 0.0, 1.0], "kinetic_energy_j": 1.0, "fluid_count": 2, "sample_mass_kg": 2.0}}
        return {"schema": "ds02.stage2.f3-s2.full-native-stream-observer.v5", "status": "PASS_F3_FULL_NATIVE_STREAM_STRICT_SOURCE_JOIN_WITH_SCHEMA_CORRECT_COMPACT_SUMMARY", "case_binding": {"physical_case_id": PHYSICAL_CASE_ID}, "frame_count": 836, "first_saved_time_s": 0.0, "last_saved_time_s": 8.0, "native_header_summary": {"MassFluid": 1.0, "Dp": 0.01}, "initial_counts": {"fluid_count": 2}, "final_counts": {"fluid_count": 2}, "lifecycle_counts": {"fluid": {"lost": 0, "new": 0, "reappeared": 0}}, "selected_observations": [row], "query_brackets": [{"query_time_s": 0.0, "status": "EXACT", "lower_frame": 0, "upper_frame": 0, "lower_time_s": t, "upper_time_s": t}], "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    a = _summary_values(summary("a", 0.0), "fixture_a"); b = _summary_values(summary("b", 1e-6), "fixture_b")
    assert _pair_diag(a, b, 0.0)["status"] == "UNKNOWN_ASYNC_TIME_ALIGNMENT"
    bad = summary("bad", 0.0); bad["schema"] = "wrong"
    try: _summary_values(bad, "bad")
    except CompareFailure: pass
    else: raise AssertionError("wrong compact schema accepted")
    print("PASS_F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE_V1_SELFTEST")


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
    print(json.dumps({"status": result["status"], "output": str(args.output.absolute())}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
