#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Read the guarded ROOT150 full report once and emit a compact F3 sidecar.

The builder for this worker never opens the 14.8 MiB report.  After the
parent has reserved the request this worker checks the proof binding, records
a stable pre-read stat, streams the report once while hashing it, checks the
post-read stat, and parses only the JSON that was just read.  It does not
open BI4, Part, H5, or any native payload.  The output contains saved
endpoints around the registered query times; it performs no interpolation and
does not grant a numerical qualification.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f3-s2.coarse-deferred-json-observer.v1"
REPORT_SCHEMA = "ds02.stage2.f3-s2.full-native-stream-observer.v2"
REPORT_STATUS = "PASS_FULL_NATIVE_STREAM_V2"
PASS_STATUS = "PASS_F3_COARSE_DEFERRED_JSON_COMPACT_V1"
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)
TIME_TOLERANCE_S = 1.0e-10
MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024


def _regular(path: Path, label: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink() or not raw.is_file():
        raise FileNotFoundError(f"{label} is not a regular file: {raw}")
    resolved = raw.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise FileNotFoundError(f"{label} resolved path is not regular: {resolved}")
    return resolved


def _stat_tuple(path: Path) -> tuple[int, int, int, int, int, int]:
    st = path.stat()
    return (int(st.st_size), int(st.st_mtime_ns), int(st.st_ctime_ns), int(st.st_dev), int(st.st_ino), int(st.st_mode))


def _stat_dict(value: tuple[int, int, int, int, int, int]) -> dict[str, int]:
    return {"bytes": value[0], "mtime_ns": value[1], "ctime_ns": value[2], "st_dev": value[3], "st_ino": value[4], "mode": value[5]}


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value.lower()):
        raise ValueError(f"{label} is not a SHA-256")
    return value.lower()


def _read_small_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(path, label)
    before = _stat_tuple(path)
    data = path.read_bytes()
    after = _stat_tuple(path)
    if before != after:
        raise RuntimeError(f"{label} changed during read")
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value, {"path": str(path), "bytes": len(data), "sha256": _sha_bytes(data), "stat_before": _stat_dict(before), "stat_after": _stat_dict(after), "stable_read": True}


def _read_report_once(path: Path, expected_sha: str, expected_bytes: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read and hash the deferred report in one pass, with stable stats."""

    path = _regular(path, "deferred full report")
    before = _stat_tuple(path)
    if before[0] != expected_bytes:
        raise ValueError(f"deferred report byte count differs before read: {before[0]} != {expected_bytes}")
    if before[0] > MAX_REPORT_BYTES:
        raise ValueError(f"deferred report exceeds worker cap: {before[0]}")
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            chunks.append(block)
    after = _stat_tuple(path)
    actual_sha = digest.hexdigest()
    if before != after:
        raise RuntimeError("deferred full report changed while being read")
    if actual_sha != _hex(expected_sha, "expected deferred report SHA"):
        raise ValueError("deferred full report SHA does not match ROOT150 proof")
    data = b"".join(chunks)
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("deferred report is not a JSON object")
    return value, {
        "path": str(path),
        "bytes": len(data),
        "sha256": actual_sha,
        "stat_before": _stat_dict(before),
        "stat_after": _stat_dict(after),
        "stable_read": True,
        "content_read_passes": 1,
        "read_scope": "ROOT150 full JSON only; no native Part/BI4/H5 payload",
    }


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} is not finite numeric data")
    return float(value)


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} is not a 3-vector")
    return [_finite(item, f"{label}[{i}]") for i, item in enumerate(value)]


def _time(observation: dict[str, Any], label: str) -> float:
    if "runparts_time_s" in observation:
        return _finite(observation["runparts_time_s"], f"{label} time")
    if isinstance(observation.get("time"), dict):
        for key in ("runparts_s", "decoded_s"):
            if key in observation["time"]:
                return _finite(observation["time"][key], f"{label} time")
    if "decoded_time_s" in observation:
        return _finite(observation["decoded_time_s"], f"{label} time")
    raise ValueError(f"{label} has no saved time")


def _mass_header(observation: dict[str, Any], label: str) -> float:
    header = observation.get("native_header")
    if not isinstance(header, dict) or not isinstance(header.get("MassFluid"), dict):
        raise ValueError(f"{label} has no native MassFluid header")
    return _finite(header["MassFluid"].get("value"), f"{label} MassFluid")


def _fields(observation: dict[str, Any], label: str) -> dict[str, Any]:
    value = observation.get("fluid_observable_using_native_header_mass")
    if not isinstance(value, dict):
        raise ValueError(f"{label} has no native-mass fluid observable")
    count = value.get("fluid_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError(f"{label} fluid count is invalid")
    return {
        "weighted_centroid_m": _vector(value.get("weighted_centroid_m"), f"{label} centroid"),
        "weighted_velocity_m_per_s": _vector(value.get("weighted_velocity_m_per_s"), f"{label} velocity"),
        "kinetic_energy_j": _finite(value.get("kinetic_energy_j"), f"{label} kinetic energy"),
        "fluid_count": count,
        "sample_mass_kg": _finite(value.get("sample_mass_kg"), f"{label} sample mass"),
        "mass_semantics": str(value.get("mass_semantics", "UNKNOWN")),
    }


def _normalise_observation(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"observation {index} is not an object")
    frame = value.get("frame")
    if not isinstance(frame, int) or isinstance(frame, bool) or frame < 0:
        raise ValueError(f"observation {index} frame is invalid")
    return {
        "frame": frame,
        "time_s": _time(value, f"observation {index}"),
        "native_massfluid_kg": _mass_header(value, f"observation {index}"),
        "fields": _fields(value, f"observation {index}"),
        "identity": value.get("identity") if isinstance(value.get("identity"), dict) else None,
    }


def _compact_identity(value: Any) -> dict[str, Any]:
    """Keep lifecycle/count metadata without copying per-particle records."""

    if not isinstance(value, dict):
        return {"status": "UNKNOWN_NO_ID_LIFECYCLE_OBJECT"}
    out: dict[str, Any] = {"available": True}
    for key, item in value.items():
        key_text = str(key)
        if isinstance(item, (str, bool, int, float)) and not isinstance(item, float) or (isinstance(item, float) and math.isfinite(item)):
            if isinstance(item, (int, float)) and abs(float(item)) > 1.0e12:
                continue
            out[key_text] = item
        elif isinstance(item, dict):
            nested = {str(k): v for k, v in item.items() if str(k).lower().endswith(("count", "counts", "total", "unknown", "lost", "reappear", "new")) and isinstance(v, (int, float, bool, str))}
            if nested:
                out[key_text] = nested
        elif isinstance(item, list):
            out[f"{key_text}_length"] = len(item)
            out[f"{key_text}_per_id_records_omitted"] = True
    return out


def _query_endpoint(observations: list[dict[str, Any]], query: float) -> dict[str, Any]:
    times = [item["time_s"] for item in observations]
    if query < times[0] or query > times[-1]:
        return {"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW", "interpolation_performed": False}
    right = bisect.bisect_left(times, query)
    if right == 0:
        left = right = 0
        status = "EXACT" if abs(times[0] - query) <= TIME_TOLERANCE_S else "LEFT_OF_FIRST_SAVED_FRAME"
    elif right == len(times):
        left = right = len(times) - 1
        status = "EXACT" if abs(times[-1] - query) <= TIME_TOLERANCE_S else "RIGHT_OF_LAST_SAVED_FRAME"
    elif abs(times[right] - query) <= TIME_TOLERANCE_S:
        left = right
        status = "EXACT"
    else:
        left, status = right - 1, "BRACKETED"
    sides = []
    for side, index in (("lower", left), ("upper", right)):
        item = observations[index]
        sides.append({"side": side, **item})
    return {
        "query_time_s": query,
        "status": status,
        "lower_index": left,
        "upper_index": right,
        "lower_time_s": times[left],
        "upper_time_s": times[right],
        "bracket_width_s": times[right] - times[left],
        "endpoints": sides,
        "interpolation_performed": False,
        "error_bound": "UNKNOWN_NOT_ESTIMATED",
        "truth_credit": False,
    }


def _proof_binding(proof_path: Path, report_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    proof, proof_record = _read_small_json(proof_path, "ROOT150 verification proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError("ROOT150 proof is not an actual verification")
    expected_report = _regular(Path(str(proof.get("report", ""))), "ROOT150 proof report")
    report_path = _regular(report_path, "deferred report")
    if expected_report != report_path:
        raise ValueError("deferred report path differs from ROOT150 proof")
    report_sha = _hex(proof.get("report_sha256"), "ROOT150 proof report SHA")
    report_bytes = int(proof.get("report_bytes", -1))
    if report_bytes <= 0:
        raise ValueError("ROOT150 proof report byte count is missing")
    request_path = _regular(Path(str(proof.get("request", ""))), "ROOT150 request")
    receipt_path = _regular(Path(str(proof.get("receipt", ""))), "ROOT150 receipt")
    request, request_record = _read_small_json(request_path, "ROOT150 request")
    receipt, receipt_record = _read_small_json(receipt_path, "ROOT150 receipt")
    if request_record["sha256"] != _hex(proof.get("request_sha256"), "ROOT150 request SHA"):
        raise ValueError("ROOT150 request SHA differs from proof")
    if receipt_record["sha256"] != _hex(proof.get("receipt_sha256"), "ROOT150 receipt SHA"):
        raise ValueError("ROOT150 receipt SHA differs from proof")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed_development_unknown"}:
        raise ValueError("ROOT150 receipt is not terminal completed")
    if request.get("physical_case_id") not in (None, "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"):
        raise ValueError("ROOT150 request physical case differs")
    return proof, {"proof": proof_record, "request": request_record, "receipt": receipt_record}, {"report_sha256": report_sha, "report_bytes": report_bytes, "path": str(report_path), "content_read_by_builder": False}


def build_compact(report: dict[str, Any], source_record: dict[str, Any], queries: list[float]) -> dict[str, Any]:
    if report.get("schema") != REPORT_SCHEMA or report.get("status") != REPORT_STATUS:
        raise ValueError("ROOT150 report schema/status is not the expected full-stream report")
    scope = report.get("scope") if isinstance(report.get("scope"), dict) else {}
    if scope.get("particle_field_interpolation") not in (None, "NOT_PERFORMED"):
        raise ValueError("report declares particle interpolation")
    raw_observations = report.get("observations")
    if not isinstance(raw_observations, list) or not raw_observations:
        raise ValueError("ROOT150 report has no observations")
    observations = [_normalise_observation(item, index) for index, item in enumerate(raw_observations)]
    observations.sort(key=lambda item: (item["time_s"], item["frame"]))
    if len({item["frame"] for item in observations}) != len(observations):
        raise ValueError("ROOT150 report has duplicate frame IDs")
    if any(b["time_s"] <= a["time_s"] for a, b in zip(observations, observations[1:])):
        raise ValueError("ROOT150 report saved times are not strictly increasing")
    masses = sorted({item["native_massfluid_kg"] for item in observations})
    lifecycle = _compact_identity(report.get("id_lifecycle", report.get("lifecycle")))
    first, final = observations[0], observations[-1]
    queries_out = [_query_endpoint(observations, float(query)) for query in queries]
    return {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": report.get("physical_case_id", "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"),
        "source": {
            "producer": "ROOT150",
            "report": source_record,
            "proof_status": "ACTUAL_ROOT150_FULL836_NATIVE_STREAM",
            "native_payloads_read_by_this_worker": False,
            "full_report_read_after_parent_reservation": True,
            "full_report_content_read_passes": 1,
        },
        "window": {
            "frame_count": len(observations),
            "first_frame": first["frame"],
            "first_saved_time_s": first["time_s"],
            "last_frame": final["frame"],
            "last_saved_time_s": final["time_s"],
            "native_massfluid_values_kg": masses,
            "initial_fields": first["fields"],
            "final_fields": final["fields"],
        },
        "lifecycle": lifecycle,
        "queries": queries_out,
        "qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "compact actual saved endpoints are available; asynchronous alignment, integration/output error, and neighbouring-grid truth are not identified",
        },
        "scope": {
            "saved_endpoint_only": True,
            "time_interpolation": False,
            "particle_field_interpolation": False,
            "adjacent_grid_truth": False,
            "error_bounds": "UNKNOWN_NOT_ESTIMATED",
        },
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > MAX_OUTPUT_BYTES:
        raise ValueError(f"compact output exceeds cap: {len(data)}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run(report_path: Path, proof_path: Path, output: Path, queries: list[float]) -> dict[str, Any]:
    proof, binding, deferred = _proof_binding(proof_path, report_path)
    report, report_record = _read_report_once(report_path, deferred["report_sha256"], deferred["report_bytes"])
    source_record = {**deferred, **report_record, "proof": binding["proof"], "request": binding["request"], "receipt": binding["receipt"]}
    result = build_compact(report, source_record, queries)
    _atomic_json(output, result)
    return result


def _fixture() -> tuple[Path, Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="ds02-root243-fixture-"))
    report = root / "report.json"
    request = root / "request.json"
    receipt = root / "receipt.json"
    observation = {
        "frame": 0,
        "runparts_time_s": 0.0,
        "native_header": {"MassFluid": {"value": 0.5}},
        "fluid_observable_using_native_header_mass": {
            "weighted_centroid_m": [1.0, 2.0, 3.0],
            "weighted_velocity_m_per_s": [0.1, 0.2, 0.3],
            "kinetic_energy_j": 0.07,
            "fluid_count": 2,
            "sample_mass_kg": 1.0,
            "mass_semantics": "native_header",
        },
        "identity": {"fluid_count": 2},
    }
    report.write_text(json.dumps({"schema": REPORT_SCHEMA, "status": REPORT_STATUS, "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT", "scope": {"particle_field_interpolation": "NOT_PERFORMED"}, "observations": [observation]}, indent=2) + "\n", encoding="utf-8")
    request.write_text(json.dumps({"schema": "ds02.request.v1", "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"}) + "\n", encoding="utf-8")
    receipt.write_text(json.dumps({"status": "completed"}) + "\n", encoding="utf-8")
    def rec(path: Path) -> str:
        return _sha_bytes(path.read_bytes())
    proof = root / "proof.json"
    proof.write_text(json.dumps({"schema": "ds02.stage2.root-actual-verification.v1", "status": "VERIFIED_ACTUAL_FIXTURE", "report": str(report), "report_sha256": rec(report), "report_bytes": report.stat().st_size, "request": str(request), "request_sha256": rec(request), "receipt": str(receipt), "receipt_sha256": rec(receipt)}) + "\n", encoding="utf-8")
    return report, proof, root / "compact.json"


def self_test() -> dict[str, Any]:
    report, proof, output = _fixture()
    result = run(report, proof, output, [0.0])
    if result["queries"][0]["status"] != "EXACT" or result["source"]["full_report_content_read_passes"] != 1:
        raise AssertionError("ROOT243 compact fixture did not produce an exact endpoint")
    wrong = json.loads(proof.read_text(encoding="utf-8"))
    wrong["report_sha256"] = "0" * 64
    bad = proof.with_name("bad-proof.json")
    bad.write_text(json.dumps(wrong) + "\n", encoding="utf-8")
    try:
        run(report, bad, output.with_name("bad-output.json"), [0.0])
    except ValueError:
        pass
    else:
        raise AssertionError("wrong proof SHA was accepted")
    report.write_text(report.read_text(encoding="utf-8") + " ", encoding="utf-8")
    try:
        run(report, proof, output.with_name("changed-output.json"), [0.0])
    except ValueError:
        pass
    else:
        raise AssertionError("changed deferred report was accepted")
    return {"status": "PASS", "schema": SCHEMA, "fixture": "actual CLI worker path exercised by run()", "wrong_sha_rejected": True, "changed_source_rejected": True, "native_payload_read": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--proof", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--query-times", nargs="*", type=float, default=list(QUERY_TIMES_S))
    args = parser.parse_args(argv)
    if args.self_test:
        print(json.dumps(self_test(), sort_keys=True))
        return 0
    if args.report is None or args.proof is None or args.output is None:
        parser.error("--report, --proof, and --output are required")
    result = run(args.report, args.proof, args.output, args.query_times)
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().resolve()), "report_sha256": result["source"]["sha256"], "frame_count": result["window"]["frame_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
