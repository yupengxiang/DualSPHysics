#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Compare the two existing F1-S1 DP005 native observer reports.

The parent guard supplies the two terminal proofs, observer JSON reports and
their small RunPARTs files after reservation.  This worker reads no BI4/H5 or
native array payload.  It pairs observations by the actual saved frame id,
reports each run's native timestamp, and never interpolates asynchronous
fields.  The result is a component-space diagnostic; it grants no QI/QN/QE
or spatial/integration/output truth credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

SCHEMA = "ds02.stage2.f1-s1.dp005-native-common-time.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s1.dp005-native-common-time-manifest.v1"
PASS_STATUS = "PASS_F1_DP005_NATIVE_COMMON_FRAME_DIAGNOSTICS_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_F1_DP005_NATIVE_COMMON_FRAME_DIAGNOSTICS"
MAX_JSON = 32 * 1024 * 1024
MAX_CSV = 8 * 1024 * 1024
STAT_FIELDS = ("dev", "ino", "bytes", "mtime_ns", "ctime_ns")
TASK_TOL = {"position_m": 0.01788, "velocity_m_per_s": 0.04538832449, "kinetic_energy_J": 0.30036258}
QUERY_FRAMES = (0, 79, 80, 159, 160, 239, 240, 319, 320)


class AuditFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise AuditFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _sha(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256(); size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block); size += len(block)
    return digest.hexdigest(), size


def _expected_stat(record: dict[str, Any], label: str) -> dict[str, int] | None:
    value = record.get("stat_at_prepare", record.get("stat"))
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AuditFailure(f"{label} stat is not an object")
    missing = [key for key in STAT_FIELDS if key not in value]
    if missing:
        raise AuditFailure(f"{label} stat missing {missing}")
    return {key: int(value[key]) for key in STAT_FIELDS}


def _stable_json(record: dict[str, Any], label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(Path(str(record.get("path", ""))), label)
    before = _stat(path)
    if before["bytes"] > MAX_JSON:
        raise AuditFailure(f"{label} exceeds bounded JSON limit")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    after = _stat(path)
    if before != after or digest != hashlib.sha256(raw).hexdigest():
        raise AuditFailure(f"{label} changed during read")
    expected = record.get("known_sha256") or record.get("sha256")
    if expected and str(expected).lower() != digest:
        raise AuditFailure(f"{label} SHA differs from bound source")
    stat_expected = _expected_stat(record, label)
    if stat_expected is not None and stat_expected != after:
        raise AuditFailure(f"{label} stat differs from bound source")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{label} is not JSON") from exc
    if not isinstance(value, dict):
        raise AuditFailure(f"{label} is not a JSON object")
    return value, {"path": str(path), "sha256": digest, "bytes": len(raw), "stat": after,
                   "stable_read": True, "content_scope": "bounded_json_metadata"}


def _stable_text(record: dict[str, Any], label: str) -> dict[str, Any]:
    path = _regular(Path(str(record.get("path", ""))), label)
    before = _stat(path)
    if before["bytes"] > MAX_CSV:
        raise AuditFailure(f"{label} exceeds bounded CSV limit")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest(); after = _stat(path)
    if before != after:
        raise AuditFailure(f"{label} changed during read")
    expected = record.get("known_sha256") or record.get("sha256")
    if expected and str(expected).lower() != digest:
        raise AuditFailure(f"{label} SHA differs from bound source")
    stat_expected = _expected_stat(record, label)
    if stat_expected is not None and stat_expected != after:
        raise AuditFailure(f"{label} stat differs from bound source")
    return {"path": str(path), "sha256": digest, "bytes": len(raw), "stat": after,
            "stable_read": True, "content_scope": "bounded_RunPARTs_metadata"}


def _same_path(left: Any, right: str) -> bool:
    return isinstance(left, str) and Path(left).expanduser().absolute() == Path(right).expanduser().absolute()


def _finite(value: Any, label: str) -> float:
    try: number = float(value)
    except (TypeError, ValueError) as exc: raise AuditFailure(f"{label} is not numeric") from exc
    if not math.isfinite(number): raise AuditFailure(f"{label} is non-finite")
    return number


def _vec(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise AuditFailure(f"{label} is not a three-vector")
    return [_finite(item, f"{label}[{i}]") for i, item in enumerate(value)]


def _proof_join(proof: dict[str, Any], proof_record: dict[str, Any], case: dict[str, Any], label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise AuditFailure(f"{label} is not an actual verification proof")
    if proof.get("request") != case["request"]["path"] or str(proof.get("request_sha256", "")).lower() != case["request"]["known_sha256"]:
        raise AuditFailure(f"{label} proof/request join failed")
    if proof.get("receipt") != case["receipt"]["path"] or str(proof.get("receipt_sha256", "")).lower() != case["receipt"]["known_sha256"]:
        raise AuditFailure(f"{label} proof/receipt join failed")
    if proof.get("report") != case["report"]["path"] or str(proof.get("report_sha256", "")).lower() != case["report"]["known_sha256"]:
        raise AuditFailure(f"{label} proof/report join failed")
    snapshot = proof.get("snapshot_proof")
    if not isinstance(snapshot, str) or not _same_path(snapshot, case["snapshot_proof"]["path"]):
        raise AuditFailure(f"{label} snapshot proof path mismatch")
    return proof, proof_record


def _verify_request_receipt(request: dict[str, Any], receipt: dict[str, Any], case: dict[str, Any], label: str) -> dict[str, Any]:
    if receipt.get("status") not in ("completed", "COMPLETED", "success"):
        raise AuditFailure(f"{label} receipt is not completed")
    execution = receipt.get("execution") if isinstance(receipt.get("execution"), dict) else {}
    code = execution.get("returncode", receipt.get("returncode"))
    if code not in (None, 0):
        raise AuditFailure(f"{label} receipt returncode is {code}")
    # Receipts embed the complete request object and carry its canonical
    # digest at the receipt top level; they do not normally repeat a request
    # filesystem path inside that embedded object. Validate both forms when
    # present, plus identity fields, so a similarly named producer cannot be
    # substituted.
    embedded = receipt.get("request")
    if not isinstance(embedded, dict):
        raise AuditFailure(f"{label} receipt has no request identity")
    expected_sha = str(case["request"]["known_sha256"]).lower()
    receipt_request_sha = str(receipt.get("request_sha256", "")).lower()
    if receipt_request_sha != expected_sha:
        raise AuditFailure(f"{label} receipt/request SHA mismatch")
    embedded_path = embedded.get("path")
    if embedded_path is not None and not _same_path(embedded_path, case["request"]["path"]):
        raise AuditFailure(f"{label} receipt/request path mismatch")
    embedded_sha = embedded.get("sha256")
    if embedded_sha is not None and str(embedded_sha).lower() != expected_sha:
        raise AuditFailure(f"{label} embedded request SHA mismatch")
    for key in ("schema", "family_id", "sentinel_id", "physical_case_id", "case_id", "attempt_id"):
        if key in request and embedded.get(key) != request.get(key):
            raise AuditFailure(f"{label} receipt/request {key} mismatch")
    if request.get("case_id") != case.get("producer_case_id"):
        raise AuditFailure(f"{label} producer case identity mismatch")
    if request.get("physical_case_id") != case.get("physical_case_id"):
        raise AuditFailure(f"{label} physical case identity mismatch")
    return {"status": "PASS_TERMINAL_PRODUCER_JOIN", "returncode": code,
            "request_path": case["request"]["path"], "request_sha256": receipt_request_sha,
            "case_id": request.get("case_id"), "physical_case_id": request.get("physical_case_id"),
            "receipt_output_root": receipt.get("output_root")}


def _check_report(report: dict[str, Any], case: dict[str, Any], label: str) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    if report.get("schema") != "ds02.stage2.native-physical-observer.v2" or report.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise AuditFailure(f"{label} observer report status/schema mismatch")
    source = report.get("source") if isinstance(report.get("source"), dict) else {}
    for key in ("raw_root", "runparts", "generated_xml"):
        if key not in source:
            raise AuditFailure(f"{label} report source missing {key}")
    expected = case["expected_source"]
    if str(Path(source["raw_root"]).absolute()) != str(Path(expected["raw_root"]).absolute()):
        raise AuditFailure(f"{label} raw_root identity mismatch")
    if not _same_path(source["runparts"].get("path"), expected["runparts"]):
        raise AuditFailure(f"{label} RunPARTs identity mismatch")
    if not _same_path(source["generated_xml"].get("path"), expected["generated_xml"]):
        raise AuditFailure(f"{label} generated XML identity mismatch")
    observations = report.get("observations")
    if not isinstance(observations, list): raise AuditFailure(f"{label} observations missing")
    by_frame: dict[int, dict[str, Any]] = {}
    for observation in observations:
        if not isinstance(observation, dict): raise AuditFailure(f"{label} malformed observation")
        frame = int(observation.get("frame", -1))
        if frame in by_frame: raise AuditFailure(f"{label} duplicate frame {frame}")
        if frame not in QUERY_FRAMES: raise AuditFailure(f"{label} unexpected selected frame {frame}")
        if observation.get("identity", {}).get("id_unique") is not True: raise AuditFailure(f"{label} frame {frame} IDs are not unique")
        finite = observation.get("finite_fields", {})
        if any(finite.get(key) is not True for key in ("position", "velocity", "density")):
            raise AuditFailure(f"{label} frame {frame} has non-finite fields")
        fluid = observation.get("groups", {}).get("fluid")
        if not isinstance(fluid, dict) or fluid.get("mass_semantics") != "native_particle_sample_mass_only":
            raise AuditFailure(f"{label} frame {frame} is missing native fluid group semantics")
        for key in ("count", "sample_mass_kg", "weighted_centroid_m", "weighted_velocity_m_per_s", "kinetic_energy_j"):
            if key not in fluid: raise AuditFailure(f"{label} frame {frame} missing fluid {key}")
        _vec(fluid["weighted_centroid_m"], f"{label} frame {frame} weighted centroid")
        _vec(fluid["weighted_velocity_m_per_s"], f"{label} frame {frame} weighted velocity")
        _finite(fluid["sample_mass_kg"], f"{label} frame {frame} mass")
        _finite(fluid["kinetic_energy_j"], f"{label} frame {frame} KE")
        by_frame[frame] = observation
    if set(by_frame) != set(QUERY_FRAMES):
        raise AuditFailure(f"{label} selected frame set differs from frozen nine-frame contract")
    return by_frame, {"source": source, "selected_frames": sorted(by_frame), "report_status": report.get("status")}


def _fields(observation: dict[str, Any]) -> dict[str, Any]:
    fluid = observation["groups"]["fluid"]
    return {"frame": int(observation["frame"]),
            "time_s": _finite(observation["time"]["decoded_s"], "decoded time"),
            "runparts_time_s": _finite(observation["time"]["runparts_s"], "RunPARTs time"),
            "fluid_count": int(fluid["count"]),
            "native_sample_mass_kg": _finite(fluid["sample_mass_kg"], "sample mass"),
            "weighted_centroid_m": _vec(fluid["weighted_centroid_m"], "weighted centroid"),
            "weighted_velocity_m_per_s": _vec(fluid["weighted_velocity_m_per_s"], "weighted velocity"),
            "kinetic_energy_J": _finite(fluid["kinetic_energy_j"], "kinetic energy"),
            "field_interpolation": "NOT_PERFORMED_BY_OBSERVER"}


def _diff(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    dc = [abs(a - b) for a, b in zip(left["weighted_centroid_m"], right["weighted_centroid_m"])]
    dv = [abs(a - b) for a, b in zip(left["weighted_velocity_m_per_s"], right["weighted_velocity_m_per_s"])]
    dm = abs(left["native_sample_mass_kg"] - right["native_sample_mass_kg"])
    dke = abs(left["kinetic_energy_J"] - right["kinetic_energy_J"])
    return {"centroid_abs_component_m": dc, "centroid_norm_m": math.sqrt(sum(v * v for v in dc)),
            "velocity_abs_component_m_per_s": dv, "velocity_norm_m_per_s": math.sqrt(sum(v * v for v in dv)),
            "native_sample_mass_abs_kg": dm, "kinetic_energy_abs_J": dke,
            "frozen_quarter_budget": {"position_m": TASK_TOL["position_m"] / 4.0, "velocity_m_per_s": TASK_TOL["velocity_m_per_s"] / 4.0, "kinetic_energy_J": TASK_TOL["kinetic_energy_J"] / 4.0},
            "within_quarter_budget_diagnostic": {"position_m": math.sqrt(sum(v * v for v in dc)) <= TASK_TOL["position_m"] / 4.0,
                                                   "velocity_m_per_s": math.sqrt(sum(v * v for v in dv)) <= TASK_TOL["velocity_m_per_s"] / 4.0,
                                                   "kinetic_energy_J": dke <= TASK_TOL["kinetic_energy_J"] / 4.0}}


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink(): raise AuditFailure(f"refusing overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally: temporary.unlink(missing_ok=True)


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, manifest_record = _stable_json({"path": str(manifest_path)}, "DP005 common-time manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_F1_DP005_NATIVE_COMMON_TIME":
        raise AuditFailure("manifest schema/status mismatch")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 2: raise AuditFailure("manifest must contain same and half cases")
    loaded: dict[str, dict[str, Any]] = {}
    source_records: dict[str, Any] = {manifest_record["path"]: manifest_record}
    for case in cases:
        label = str(case.get("label")); variant = str(case.get("variant"))
        proof, proof_rec = _stable_json(case["proof"], f"{label} proof")
        _proof_join(proof, proof_rec, case, label)
        snapshot, snapshot_rec = _stable_json(case["snapshot_proof"], f"{label} source snapshot proof")
        if snapshot.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(snapshot.get("status", "")):
            raise AuditFailure(f"{label} source snapshot proof is not an actual verification proof")
        request, request_rec = _stable_json(case["request"], f"{label} request")
        receipt, receipt_rec = _stable_json(case["receipt"], f"{label} receipt")
        producer_join = _verify_request_receipt(request, receipt, case, label)
        report, report_rec = _stable_json(case["report"], f"{label} observer report")
        frames, source = _check_report(report, case, label)
        runparts_rec = _stable_text(case["runparts"], f"{label} RunPARTs")
        source_records.update({r["path"]: r for r in (proof_rec, snapshot_rec, request_rec, receipt_rec, report_rec, runparts_rec)})
        loaded[variant] = {"label": label, "variant": variant, "proof": proof_rec, "request": request_rec,
                           "receipt": receipt_rec, "report": report_rec, "snapshot_proof": snapshot_rec, "runparts": runparts_rec,
                           "producer_join": producer_join, "frames": frames, "source": source}
    if set(loaded) != {"same_cfl", "half_cfl"}: raise AuditFailure("expected same_cfl and half_cfl variants")
    same = loaded["same_cfl"]["frames"]; half = loaded["half_cfl"]["frames"]
    paired = []
    for frame in QUERY_FRAMES:
        left = _fields(same[frame]); right = _fields(half[frame])
        delta_t = abs(left["time_s"] - right["time_s"])
        paired.append({"frame": frame, "same_cfl": left, "half_cfl": right,
                       "saved_time_delta_s": delta_t,
                       "time_status": "EXACT_COMMON_SAVED_TIME" if delta_t == 0.0 else "ASYNC_SAVED_TIME_NO_EXACT_COMMON_TIME",
                       "field_difference": _diff(left, right),
                       "interpolation": False, "spatial_truth": False})
    result = {"schema": SCHEMA, "status": PASS_STATUS, "manifest": manifest_record,
              "variants": {key: {k: value for k, value in item.items() if k not in {"frames", "source"}} for key, item in loaded.items()},
              "paired_common_native_frames": paired,
              "common_frame_ids": list(QUERY_FRAMES),
              "task_contract": {"position_tolerance_m": TASK_TOL["position_m"], "velocity_tolerance_m_per_s": TASK_TOL["velocity_m_per_s"], "kinetic_energy_tolerance_J": TASK_TOL["kinetic_energy_J"], "quarter_budget_is_diagnostic_only": True},
              "semantics": {"native_fields": "decoded observer weighted fluid aggregates and native particle sample mass only", "same_half_control_difference": "CFL only as source/receipt audit; this worker does not establish solver controls", "component_space": True, "event_time": "UNKNOWN", "output_error": "UNKNOWN", "integration_error": "UNKNOWN", "neighbor_grid_truth": False, "interpolation": False},
              "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
              "read_scope": {"proof_json": True, "request_json": True, "receipt_json": True, "observer_report_json": True, "runparts_csv": True, "native_bi4": False, "hdf5": False, "vtk": False, "solver_launch": False},
              "source_records": source_records}
    _write_once(output, result)
    return result


def _self_test() -> None:
    with __import__("tempfile").TemporaryDirectory(prefix="f1-dp005-common-") as directory:
        root = Path(directory); path = root / "tiny.json"
        def obs(frame: int, time_s: float, x: float) -> dict[str, Any]:
            return {"frame": frame, "time": {"decoded_s": time_s, "runparts_s": time_s}, "identity": {"id_unique": True}, "finite_fields": {"position": True, "velocity": True, "density": True}, "groups": {"fluid": {"count": 2, "mass_semantics": "native_particle_sample_mass_only", "sample_mass_kg": 1.0, "weighted_centroid_m": [x, 0.0, 0.0], "weighted_velocity_m_per_s": [0.0, 0.0, 0.0], "kinetic_energy_j": 0.0}}}
        value = {"schema": "ds02.stage2.native-physical-observer.v2", "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS", "source": {"raw_root": "/raw", "runparts": {"path": "/run.csv"}, "generated_xml": {"path": "/x.xml"}}, "observations": [obs(frame, float(frame), float(frame)) for frame in QUERY_FRAMES]}
        path.write_text(json.dumps(value), encoding="utf-8")
        report, rec = _stable_json({"path": str(path)}, "fixture")
        assert report["status"].startswith("PASS_") and rec["bytes"] > 0
        fixture_case = {"expected_source": {"raw_root": "/raw", "runparts": "/run.csv", "generated_xml": "/x.xml"}}
        frames, _ = _check_report(report, fixture_case, "fixture")
        assert sorted(frames) == list(QUERY_FRAMES)
        request = {"schema": "ds02.request.v1", "family_id": "F1", "sentinel_id": "F1-S1",
                   "physical_case_id": "PHYSICAL", "case_id": "PRODUCER", "attempt_id": "attempt"}
        receipt = {"status": "completed", "returncode": 0, "request_sha256": "a" * 64, "request": request}
        request_case = {"request": {"path": "/source-request.json", "known_sha256": "a" * 64},
                        "producer_case_id": "PRODUCER", "physical_case_id": "PHYSICAL"}
        assert _verify_request_receipt(request, receipt, request_case, "fixture")["status"].startswith("PASS_")
        assert _diff(_fields(report["observations"][0]), _fields(report["observations"][0]))["centroid_norm_m"] == 0.0
    print("PASS_F1_DP005_NATIVE_COMMON_TIME_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--manifest", type=Path); parser.add_argument("--output", type=Path); parser.add_argument("--self-test", action="store_true"); args = parser.parse_args()
    if args.self_test: _self_test(); return 0
    if args.manifest is None or args.output is None: parser.error("--manifest and --output are required unless --self-test")
    try: result = run(args.manifest, args.output)
    except Exception as exc: print(f"{FAIL_STATUS}: {exc}"); return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.absolute()), "frames": len(result["paired_common_native_frames"])}, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
