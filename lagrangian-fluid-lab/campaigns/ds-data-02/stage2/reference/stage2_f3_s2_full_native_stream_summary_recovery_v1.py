#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Recover a bounded compact summary from ROOT188's retained full report.

ROOT188's native observer decoded the native Part stream and wrote its large
full report before the v5 compact-summary write exceeded the old 2 MiB cap.
This forward worker consumes that retained JSON report only after the parent
guard reserves the attempt.  It performs one stable bytes read, rebuilds the
v5 summary with a 4 MiB cap, and never opens native Part/BI4/H5 data.

The failed observer receipt/proof remains failure evidence.  The recovered
summary is an operational producer artifact only; it does not turn the failed
observer into a scientific pass and it grants no QI/QN/QE qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V5_PATH = HERE / "stage2_f3_s2_full_native_stream_observer_v5.py"
V3_PATH = HERE / "stage2_f3_s2_full_native_stream_observer_v3.py"
SCHEMA = "ds02.stage2.f3-s2.full-native-stream-observer.recovered-summary.v1"
SUMMARY_SCHEMA = "ds02.stage2.f3-s2.full-native-stream-observer.v5"
PHYSICAL_CASE = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)
SUMMARY_MAX_BYTES = 4 * 1024 * 1024
REPORT_MAX_BYTES = 256 * 1024 * 1024
STAT_JOIN_FIELDS = ("bytes", "mtime_ns", "ctime_ns", "st_ino", "st_dev")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V5 = _load(V5_PATH, "stage2_f3_s2_summary_recovery_v5_dependency")
V3 = _load(V3_PATH, "stage2_f3_s2_summary_recovery_v3_dependency")


def _path(value: Path | str) -> Path:
    # Keep the pre-resolve object long enough for _regular() to reject a
    # symlink replacement.  Resolving first would turn a changed symlink into
    # an apparently ordinary file and defeat the preserved-output join.
    return Path(value).expanduser()


def _regular(path: Path, label: str, *, max_bytes: int | None = None) -> Path:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise ValueError(f"{label} exceeds bounded size {max_bytes}: {path.stat().st_size}")
    return path


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "mode": int(value.st_mode),
    }


def _assert_expected_stat(path: Path, expected: dict[str, Any], label: str) -> dict[str, int]:
    """Join a retained source to the parent's exact pre/post stat record."""
    actual = _stat(path)
    expected_path = expected.get("path")
    if expected_path is not None and Path(str(expected_path)).expanduser().resolve() != _path(path).resolve():
        raise RuntimeError(f"{label} path differs from preserved proof: {path}")
    for field in STAT_JOIN_FIELDS:
        if field not in expected:
            raise RuntimeError(f"{label} is missing preserved stat field {field}")
        try:
            expected_value = int(expected[field])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{label} has non-integer preserved stat field {field}") from exc
        if actual[field] != expected_value:
            raise RuntimeError(
                f"{label} stat mismatch for {field}: expected {expected_value}, actual {actual[field]}"
            )
    return actual


def _receipt_returncode(receipt: dict[str, Any]) -> int | None:
    value = receipt.get("returncode")
    if value is None and isinstance(receipt.get("execution"), dict):
        value = receipt["execution"].get("returncode", receipt["execution"].get("return_code"))
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _require_zero_returncode(receipt: dict[str, Any], label: str) -> None:
    if _receipt_returncode(receipt) != 0:
        raise ValueError(f"{label} does not prove returncode 0")


def _read_json_stable(
    path: Path,
    label: str,
    *,
    max_bytes: int = REPORT_MAX_BYTES,
    expected_stat: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(path, label, max_bytes=max_bytes)
    before = _stat(path)
    if expected_stat is not None:
        _assert_expected_stat(path, expected_stat, f"{label} pre-read preserved join")
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            chunks.append(block)
    after = _stat(path)
    if before != after:
        raise RuntimeError(f"{label} changed during one guarded read: {path}")
    if expected_stat is not None:
        _assert_expected_stat(path, expected_stat, f"{label} post-read preserved join")
    try:
        value = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return {
        "path": str(path),
        "bytes": before["bytes"],
        "sha256": digest.hexdigest(),
        "stat_before": before,
        "stat_after": after,
        "stable_read": True,
        "label": label,
        "content_scope": "one guarded full-report JSON read; no native/H5 payload",
    }, value


def _record_json(path: Path, label: str, *, max_bytes: int = 32 * 1024 * 1024) -> tuple[dict[str, Any], dict[str, Any]]:
    return _read_json_stable(path, label, max_bytes=max_bytes)


def _atomic_json(path: Path, value: dict[str, Any], *, max_bytes: int = SUMMARY_MAX_BYTES) -> dict[str, Any]:
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable recovery summary: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if temporary.stat().st_size > max_bytes:
            raise ValueError(f"recovered compact summary exceeds {max_bytes} bytes: {temporary.stat().st_size}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    record, _ = _read_json_stable(path, "recovered compact summary", max_bytes=max_bytes)
    return record


def _read_request(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return _record_json(path, "underlying ROOT174 solver request", max_bytes=8 * 1024 * 1024)


def _validate_failed_observer(
    request_path: Path,
    receipt_path: Path,
    proof_path: Path,
    retained_report_path: Path,
) -> dict[str, Any]:
    request_record, request = _record_json(request_path, "ROOT188 observer request", max_bytes=8 * 1024 * 1024)
    receipt_record, receipt = _record_json(receipt_path, "ROOT188 failed observer receipt", max_bytes=32 * 1024 * 1024)
    proof_record, proof = _record_json(proof_path, "ROOT188 failed observer proof", max_bytes=32 * 1024 * 1024)
    if request.get("physical_case_id") not in {PHYSICAL_CASE, None}:
        raise ValueError("ROOT188 observer request physical case differs")
    receipt_status = str(receipt.get("status", "")).lower()
    if not (receipt_status.startswith("failed") or receipt_status in {"error", "aborted"}):
        raise ValueError(f"ROOT188 receipt is not preserved failure evidence: {receipt.get('status')!r}")
    returncode = _receipt_returncode(receipt)
    if returncode is None or returncode == 0:
        raise ValueError("ROOT188 failed observer receipt lacks nonzero returncode")
    # ds02 execution receipts keep the immutable request-file join at the
    # receipt top level.  ``request`` is the expanded runtime payload and has
    # no path/SHA pair, so never treat it as the request file itself.
    if receipt.get("request_sha256") != request_record["sha256"]:
        raise ValueError("ROOT188 failed receipt request SHA differs")
    receipt_request = receipt.get("request")
    if isinstance(receipt_request, dict):
        if receipt_request.get("physical_case_id") not in {PHYSICAL_CASE, None}:
            raise ValueError("ROOT188 failed receipt expanded physical case differs")
        if receipt_request.get("case_id") not in {None, "F3_S2_MIDDLE_HALF_OUTPUT_FULL_NATIVE_ROOT188_V2"}:
            raise ValueError("ROOT188 failed receipt expanded case differs")
    if proof.get("schema") not in {"ds02.stage2.root-actual-verification.v1", "ds02.stage2.root-actual-external-solver-verification.v1"}:
        raise ValueError("ROOT188 failure proof schema is not a root proof")
    proof_status = str(proof.get("status", "")).upper()
    if "FAIL" not in proof_status and "ERROR" not in proof_status and "ABORT" not in proof_status:
        raise ValueError("ROOT188 proof must preserve failure, not claim producer success")
    if Path(str(proof.get("request", ""))).expanduser().resolve() != Path(request_record["path"]):
        raise ValueError("ROOT188 failure proof request path differs")
    if proof.get("request_sha256") != request_record["sha256"]:
        raise ValueError("ROOT188 failure proof request SHA differs")
    if Path(str(proof.get("receipt", ""))).expanduser().resolve() != Path(receipt_record["path"]):
        raise ValueError("ROOT188 failure proof receipt path differs")
    if proof.get("receipt_sha256") != receipt_record["sha256"]:
        raise ValueError("ROOT188 failure proof receipt SHA differs")
    retained = proof.get("preserved_outputs_stat_only")
    if not isinstance(retained, list):
        raise ValueError("ROOT188 failure proof lacks preserved_outputs_stat_only")
    normalized_report = _regular(retained_report_path, "retained ROOT188 full observer report")
    matching = [
        entry
        for entry in retained
        if isinstance(entry, dict)
        and entry.get("path") is not None
        and Path(str(entry["path"])).expanduser().resolve() == normalized_report
    ]
    if len(matching) != 1:
        raise ValueError("ROOT188 failure proof does not bind exactly one retained full report path")
    retained_stat = matching[0]
    _assert_expected_stat(normalized_report, retained_stat, "ROOT188 retained full report pre-read")
    return {
        "request": request_record,
        "receipt": receipt_record,
        "proof": proof_record,
        "proof_value": proof,
        "retained_report_stat": retained_stat,
    }


def _validate_solver(
    request_path: Path,
    receipt_path: Path,
    proof_path: Path,
) -> dict[str, Any]:
    request_record, request = _record_json(request_path, "ROOT174 solver request", max_bytes=8 * 1024 * 1024)
    receipt_record, receipt = _record_json(receipt_path, "ROOT174 solver receipt", max_bytes=32 * 1024 * 1024)
    proof_record, proof = _record_json(proof_path, "ROOT174 solver proof", max_bytes=32 * 1024 * 1024)
    if request.get("physical_case_id") not in {PHYSICAL_CASE, None}:
        raise ValueError("ROOT174 solver request physical case differs")
    if proof.get("schema") not in {"ds02.stage2.root-actual-verification.v1", "ds02.stage2.root-actual-external-solver-verification.v1"}:
        raise ValueError("ROOT174 solver proof schema is not a root proof")
    if "ACTUAL" not in str(proof.get("status", "")) and not str(proof.get("status", "")).startswith("VERIFIED"):
        raise ValueError("ROOT174 solver proof is not actual")
    if Path(str(proof.get("request", ""))).expanduser().resolve() != Path(request_record["path"]):
        raise ValueError("ROOT174 solver proof request path differs")
    if proof.get("request_sha256") != request_record["sha256"]:
        raise ValueError("ROOT174 solver proof request SHA differs")
    if Path(str(proof.get("receipt", ""))).expanduser().resolve() != Path(receipt_record["path"]):
        raise ValueError("ROOT174 solver proof receipt path differs")
    if proof.get("receipt_sha256") != receipt_record["sha256"]:
        raise ValueError("ROOT174 solver proof receipt SHA differs")
    status = str(receipt.get("status", "")).lower()
    if not status.startswith(("completed", "complete", "success")):
        raise ValueError("ROOT174 solver receipt is not completed")
    _require_zero_returncode(receipt, "ROOT174 solver receipt")
    return {"request": request_record, "receipt": receipt_record, "proof": proof_record}


def _validate_report(value: dict[str, Any], report_record: dict[str, Any], solver_request_record: dict[str, Any]) -> None:
    if value.get("schema") != "ds02.stage2.f3-s2.full-native-stream-observer.v3":
        raise ValueError(f"retained report schema is not the consumed v3 full report: {value.get('schema')!r}")
    if not str(value.get("status", "")).startswith("PASS"):
        raise ValueError("retained full report does not contain a successful decoded report")
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("retained full report lacks observations")
    strict = value.get("strict_source_binding")
    if not isinstance(strict, dict) or strict.get("terminal_request_sha256") != solver_request_record["sha256"]:
        raise ValueError("retained full report is not bound to ROOT174 solver request")
    scope = value.get("scope")
    if not isinstance(scope, dict) or scope.get("full_native_window") is not True:
        raise ValueError("retained full report is not full-window")
    times = value.get("time_window")
    brackets = times.get("query_brackets") if isinstance(times, dict) else None
    if not isinstance(brackets, list):
        raise ValueError("retained full report lacks query brackets")
    available = {float(item.get("query_time_s")) for item in brackets if isinstance(item, dict) and isinstance(item.get("query_time_s"), (int, float))}
    missing = [time for time in QUERY_TIMES_S if time not in available]
    if missing:
        raise ValueError(f"retained full report lacks fixed query times: {missing}")


def recover(args: argparse.Namespace) -> dict[str, Any]:
    failed = _validate_failed_observer(
        args.observer_request,
        args.failed_observer_receipt,
        args.failed_observer_proof,
        args.full_report,
    )
    solver = _validate_solver(args.solver_request, args.solver_receipt, args.solver_proof)
    report_record, report = _read_json_stable(
        args.full_report,
        "retained ROOT188 full observer report",
        expected_stat=failed["retained_report_stat"],
    )
    _validate_report(report, report_record, solver["request"])
    request_binding = V5._request_binding(args.solver_request)
    summary = V5._compact_summary(report, args.full_report, request_binding)
    summary["status"] = "PASS_F3_FULL_NATIVE_STREAM_RECOVERED_COMPACT_SUMMARY_FROM_RETAINED_REPORT"
    summary["full_report"] = report_record
    summary["recovery_provenance"] = {
        "schema": SCHEMA,
        "source_failure_preserved": True,
        "failed_observer_request": failed["request"],
        "failed_observer_receipt": failed["receipt"],
        "failed_observer_proof": failed["proof"],
        "underlying_solver_request": solver["request"],
        "underlying_solver_receipt": solver["receipt"],
        "underlying_solver_proof": solver["proof"],
        "retained_full_report": report_record,
        "retained_full_report_preserved_stat_join": failed["retained_report_stat"],
        "full_report_read_passes": 1,
        "native_payload_read_by_recovery": False,
        "hdf5_read_by_recovery": False,
        "summary_limit_bytes": SUMMARY_MAX_BYTES,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "recovered operational compact summary only; original observer failure and all scientific gates remain explicit"},
    }
    summary_record = _atomic_json(args.summary_output, summary)
    return {"status": summary["status"], "summary": summary_record, "retained_full_report": report_record, "source_failure_preserved": True, "native_payload_read": False}


def _fixture_report(frame_count: int = 1680) -> dict[str, Any]:
    observations = []
    frame_records = []
    for frame in range(frame_count):
        digest = f"{frame:064x}"[-64:]
        observations.append({
            "frame": frame,
            "runparts_time_s": frame * 0.005,
            "decoded_time_s": frame * 0.005,
            "native_header": {"Dp": {"value": 0.006}, "MassFluid": {"value": 0.003375}, "MassBound": {"value": 0.001}},
            "fluid_observable_using_native_header_mass": {"fluid_count": 10, "sample_mass_kg": 0.03375, "weighted_centroid_m": [0.0, 0.0, 0.0], "weighted_velocity_m_per_s": [0.0, 0.0, 0.0], "kinetic_energy_j": 0.0, "mass_semantics": "native MassFluid"},
            "identity": {"particle_count": 12},
            "identity_lifecycle": {"appeared_idp": [0, 1] if frame == 0 else [], "disappeared_idp": [], "particle_count": 12},
            "field_digest_sha256": digest,
        })
        frame_records.append({"frame": frame, "pre_decode": {"path": f"/tmp/Part_{frame:05d}.bi4", "bytes": 12, "sha256": digest, "stat_before": {"bytes": 12}, "stat_after": {"bytes": 12}, "stat_consistency": "PASS"}, "post_decode": {"path": f"/tmp/Part_{frame:05d}.bi4", "bytes": 12, "sha256": digest, "stat_before": {"bytes": 12}, "stat_after": {"bytes": 12}, "stat_consistency": "PASS"}})
    return {
        "schema": "ds02.stage2.f3-s2.full-native-stream-observer.v3",
        "status": "PASS_FIXTURE",
        "scope": {"full_native_window": True, "frame_count": frame_count},
        "strict_source_binding": {"terminal_request_sha256": "a" * 64},
        "time_window": {"first_saved_time_s": 0.0, "last_saved_time_s": (frame_count - 1) * 0.005, "query_brackets": [{"query_time_s": time, "status": "BRACKETED", "lower_frame": min(frame_count - 1, int(time / 0.005)), "upper_frame": min(frame_count - 1, int(time / 0.005) + 1), "lower_time_s": time, "upper_time_s": time + 0.005} for time in QUERY_TIMES_S]},
        "observations": observations,
        "id_lifecycle": {"records": [{"idp": 0, "first_frame": 0, "last_frame": frame_count - 1, "classification": {"xml_kind": "fluid"}, "first_missing_frame": None}, {"idp": 1, "first_frame": 0, "last_frame": frame_count - 1, "classification": {"xml_kind": "fixed"}, "first_missing_frame": None}]},
        "source": {"particle_range_semantics": {"blocks": [{"kind": "fluid", "begin": 0, "count": 10}, {"kind": "fixed", "begin": 10, "count": 2}]}, "full_window_frame_records": frame_records},
        "native_header_summary": {"massfluid_kg": 0.003375},
    }


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="root196-recovery-") as temp:
        root = Path(temp)
        fixture = _fixture_report(1680)
        fixture["strict_source_binding"]["terminal_request_sha256"] = "b" * 64
        summary = V5._compact_summary(fixture, root / "retained-full.json", {"request_record": {"sha256": "b" * 64}, "physical_case_id": PHYSICAL_CASE})
        encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        if summary["frame_count"] != 1680 or summary["selected_observation_count"] > 12 or len(encoded) >= SUMMARY_MAX_BYTES:
            raise AssertionError(f"1680-frame bounded summary fixture failed: {len(encoded)} bytes")
        oversized = root / "overflow.json"
        try:
            _atomic_json(oversized, {"payload": "x" * (SUMMARY_MAX_BYTES + 1)})
        except ValueError:
            overflow_rejected = not oversized.exists()
        else:
            overflow_rejected = False
        if not overflow_rejected:
            raise AssertionError("summary overflow was not rejected atomically")
        invalid = root / "invalid.json"
        invalid.write_text("{not-json", encoding="utf-8")
        try:
            _read_json_stable(invalid, "invalid fixture")
        except ValueError:
            exception_rejected = True
        else:
            exception_rejected = False
        if not exception_rejected:
            raise AssertionError("invalid JSON exception fixture was accepted")
        stat_source = root / "stat-source.json"
        stat_source.write_text("{}", encoding="utf-8")
        expected_stat = _stat(stat_source)
        _read_json_stable(stat_source, "stat fixture", expected_stat=expected_stat)
        stat_source.write_text('{"changed":true}', encoding="utf-8")
        try:
            _assert_expected_stat(stat_source, expected_stat, "stat-change negative")
        except RuntimeError:
            stat_change_rejected = True
        else:
            stat_change_rejected = False
        if not stat_change_rejected:
            raise AssertionError("stat-change replacement was accepted")
        replaced = root / "replacement.json"
        replaced.write_text("{}", encoding="utf-8")
        replacement_stat = _stat(replaced)
        replacement = root / "replacement-new.json"
        replacement.write_text('{"replacement":true}', encoding="utf-8")
        os.replace(replacement, replaced)
        try:
            _assert_expected_stat(replaced, replacement_stat, "source-replacement negative")
        except RuntimeError:
            source_replacement_rejected = True
        else:
            source_replacement_rejected = False
        if not source_replacement_rejected:
            raise AssertionError("source replacement was accepted")
        _require_zero_returncode({"returncode": 0}, "zero returncode fixture")
        try:
            _require_zero_returncode({"returncode": 1}, "nonzero returncode fixture")
        except ValueError:
            solver_nonzero_rejected = True
        else:
            solver_nonzero_rejected = False
        if not solver_nonzero_rejected:
            raise AssertionError("nonzero solver returncode was accepted")
        return {"status": "PASS", "schema": SCHEMA, "frames": 1680, "summary_bytes": len(encoded), "overflow_rejected": overflow_rejected, "exception_rejected": exception_rejected, "stat_change_rejected": stat_change_rejected, "source_replacement_rejected": source_replacement_rejected, "solver_nonzero_rejected": solver_nonzero_rejected, "native_payload_read": False, "hdf5_read": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--observer-request", type=Path)
    parser.add_argument("--failed-observer-receipt", type=Path)
    parser.add_argument("--failed-observer-proof", type=Path)
    parser.add_argument("--full-report", type=Path)
    parser.add_argument("--solver-request", type=Path)
    parser.add_argument("--solver-receipt", type=Path)
    parser.add_argument("--solver-proof", type=Path)
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        try:
            print(json.dumps(self_test(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        except Exception as exc:
            print(f"ROOT196 self-test failed: {exc}", file=sys.stderr)
            return 2
    required = (args.observer_request, args.failed_observer_receipt, args.failed_observer_proof, args.full_report, args.solver_request, args.solver_receipt, args.solver_proof, args.summary_output)
    if any(item is None for item in required):
        parser.error("all ROOT188 failure, retained-report, and ROOT174 solver arguments are required")
    try:
        result = recover(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ROOT196 recovery refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "summary": result["summary"], "retained_full_report": result["retained_full_report"], "source_failure_preserved": True, "native_payload_read": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
