#!/usr/bin/env python3
"""Bounded, source-closed ROOT279 pair verifier (additive V2).

This module keeps the consumed V1 verifier unchanged while tightening its
admission boundary.  Every metadata file opened by this verifier must be a
regular ``.json`` file no larger than 10 MiB.  Native Part files are only
checked through the already-established SHA/stat records in the ROOT310
snapshot, pair manifest, deferred request, and guarded-result JSON; this
process never opens a native/VTK/HDF5/solver payload.

V2 also requires exact producer statuses, the terminal ROOT277/278
proof->request->receipt joins, and an exact ROOT310 snapshot record in the
pair request's static source closure.  The scientific result remains a
metadata-only diagnostic: no interpolation, neighboring-grid truth, or
QI/QN/QE credit is produced.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_f1_s2_root279_pair_report_verify_v1.py"
GUARDED = HERE / "stage2_f1_s2_root279_pair_native_observer_guarded_v1.py"
V4 = HERE / "stage2_f1_native_selected_observer_guarded_v4.py"
COMMON = HERE / "stage2_f1_s2_root279_common_endpoint_observer_v1.py"

V1_SPEC = importlib.util.spec_from_file_location("stage2_root279_pair_report_v1_for_v2", V1_PATH)
if V1_SPEC is None or V1_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot load frozen V1 verifier: {V1_PATH}")
V1 = importlib.util.module_from_spec(V1_SPEC)
V1_SPEC.loader.exec_module(V1)

JSON_CAP_BYTES = 10 * 1024 * 1024
SCHEMA = "ds02.stage2.f1-s2.root279-pair-report-verifier.v2"
PAIR_STATUS = "PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V3_WITH_PARENT_SNAPSHOT"
REQUEST_STATUS = "READY_FOR_PARENT_V8_F1_S2_ROOT279_PAIR_NATIVE_OBSERVER_V3"
GUARD_SCHEMA = "ds02.stage2.f1-s2.root279-native-observer-guarded.v1"
GUARD_STATUS = "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES"
CHILD_SCHEMA = "ds02.stage2.f1.native-selected-observer.v1"
CHILD_STATUS = GUARD_STATUS
COMMON_MANIFEST_SCHEMA = "ds02.stage2.f1-s2.root279-common-endpoint-manifest.v1"
COMMON_MANIFEST_STATUSES = {
    "PREPARED_ROOT279_COMMON_ENDPOINT_OBSERVER_V1",
    "PREPARED_ROOT279_COMMON_ENDPOINT_OBSERVER_V1_WAITING_RESULT",
}
COMMON_SCHEMA = "ds02.stage2.f1-s2.root279-common-endpoint-observer.v1"
COMMON_OUTPUT_STATUS = "COMPLETE_F1_S2_ROOT279_COMMON_ENDPOINT_DIAGNOSTICS_NO_SCIENTIFIC_Q"
PROOF_SCHEMA = "ds02.stage2.root-actual-external-solver-verification.v1"
PROOF_STATUS_PREFIX = "VERIFIED_ACTUAL_F1_S2_DP020_"
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
SNAPSHOT_STATUS = "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE"
REQUEST_SCHEMA = "ds02.request.v1"
REQUEST_VARIANT = "ds02.stage2.f1-s2.root279-pair-native-observer-request.v3"
QUERY_TIMES = (0.0, 0.25, 0.5)


class VerificationFailure(RuntimeError):
    pass


_V1_READ_JSON = V1._read_json
_V1_VALIDATE_PAIR = V1._validate_pair_manifest
_V1_VERIFY_GUARD = V1._verify_guard_result
_V1_VERIFY_CHILD = V1._verify_child
V1.SMALL_CAP = JSON_CAP_BYTES


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _digest(value: Any, label: str = "SHA-256") -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise VerificationFailure(f"{label} is not a concrete SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise VerificationFailure(f"{label} is not hexadecimal") from exc
    return value.lower()


def _read_json(path: Path, label: str, *, expected: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use the frozen V1 parser with a strict suffix and 10 MiB boundary."""
    path = _absolute(path)
    if path.suffix.lower() != ".json":
        raise VerificationFailure(f"{label} is not a .json metadata file: {path}")
    if path.stat().st_size > JSON_CAP_BYTES:
        raise VerificationFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    # V1's implementation performs the stable read and expected SHA/stat join;
    # the global cap is changed above without changing its source bytes.
    return _V1_READ_JSON(path, label, expected=expected)


# All V1 helper calls resolve _read_json through the V1 module globals.
V1._read_json = _read_json


def _strict_validate_pair(pair: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    value, paths = _V1_VALIDATE_PAIR(pair)
    if value.get("status") != PAIR_STATUS:
        raise VerificationFailure("ROOT279 pair status is not the completed V3-with-snapshot status")
    return value, paths


def _strict_verify_guard(guard: dict[str, Any], snapshot: dict[str, dict[str, Any]], pair_paths: set[str]) -> None:
    _V1_VERIFY_GUARD(guard, snapshot, pair_paths)
    if guard.get("schema") != GUARD_SCHEMA:
        raise VerificationFailure("ROOT279 guard schema is not the exact V1 guarded schema")
    if guard.get("status") != GUARD_STATUS:
        raise VerificationFailure("ROOT279 guard status is not the exact guarded PASS status")


def _strict_verify_child(child: dict[str, Any]) -> None:
    _V1_VERIFY_CHILD(child)
    if child.get("schema") != CHILD_SCHEMA or child.get("status") != CHILD_STATUS:
        raise VerificationFailure("ROOT279 child schema/status is not the exact guarded observer result")


V1._validate_pair_manifest = _strict_validate_pair
V1._verify_guard_result = _strict_verify_guard
V1._verify_child = _strict_verify_child


def _stat_record(value: Path) -> dict[str, int]:
    stat = value.stat()
    return {"device": int(stat.st_dev), "inode": int(stat.st_ino), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns)}


def _same_path(left: Any, right: Path) -> bool:
    return isinstance(left, str) and str(_absolute(Path(left))) == str(_absolute(right))


def _input_record(request: dict[str, Any], path: Path, label: str) -> dict[str, Any]:
    records = request.get("input_records")
    hashes = request.get("input_sha256")
    if not isinstance(records, dict) or not isinstance(hashes, dict):
        raise VerificationFailure("ROOT279 request lacks input_records/input_sha256")
    key = str(_absolute(path))
    record = records.get(key)
    if not isinstance(record, dict):
        # The request builder uses absolute paths.  The fallback only accepts
        # a unique equivalent path; it never accepts a label or basename.
        matches = [item for item in records.items() if isinstance(item[0], str) and _same_path(item[0], path)]
        if len(matches) != 1:
            raise VerificationFailure(f"{label} is absent from exact request input_records")
        key, record = matches[0]
    if key not in hashes or _digest(hashes[key], f"{label} input SHA") != _digest(record.get("sha256"), f"{label} record SHA"):
        raise VerificationFailure(f"{label} input_records/input_sha256 join failed")
    return record


def _bound_json_record(path: Path, record: dict[str, Any], label: str) -> dict[str, Any]:
    value, actual = _read_json(path, label, expected=record)
    return value


def _strict_terminal_binding(request: dict[str, Any], mode: str) -> dict[str, Any]:
    binding = request.get("source_binding")
    if not isinstance(binding, dict):
        raise VerificationFailure("ROOT279 request has no source_binding")
    terminal = binding.get(f"root277_terminal" if mode == "same_cfl" else "root278_terminal")
    if not isinstance(terminal, dict):
        raise VerificationFailure(f"ROOT279 request lacks {mode} terminal binding")
    proof_path = terminal.get("proof")
    request_path = terminal.get("request")
    request_sha = terminal.get("request_sha256")
    receipt_ref = terminal.get("receipt")
    if not all(isinstance(item, str) for item in (proof_path, request_path, request_sha)) or not isinstance(receipt_ref, dict):
        raise VerificationFailure(f"{mode} terminal binding lacks proof/request/receipt records")
    proof_path_p = _absolute(Path(proof_path))
    receipt_path = receipt_ref.get("path")
    receipt_sha = receipt_ref.get("sha256")
    if not isinstance(receipt_path, str):
        raise VerificationFailure(f"{mode} terminal receipt lacks path")
    receipt_path_p = _absolute(Path(receipt_path))
    proof_sha = _digest(terminal.get("proof_sha256"), f"{mode} proof binding")
    receipt_sha = _digest(receipt_sha, f"{mode} receipt binding")

    # The proof and receipt are JSON metadata, so the 10 MiB cap applies to
    # both.  No native/solver payload is opened here.
    proof, proof_actual = _read_json(proof_path_p, f"{mode} terminal proof")
    receipt, receipt_actual = _read_json(receipt_path_p, f"{mode} terminal receipt")
    if proof_actual["sha256"] != proof_sha or receipt_actual["sha256"] != receipt_sha:
        raise VerificationFailure(f"{mode} terminal proof/receipt SHA changed")
    if proof.get("schema") != PROOF_SCHEMA or not str(proof.get("status", "")).startswith(PROOF_STATUS_PREFIX):
        raise VerificationFailure(f"{mode} terminal proof schema/status is not an actual ROOT277/278 proof")
    if proof.get("request") != str(_absolute(Path(request_path))) or _digest(proof.get("request_sha256"), f"{mode} proof request SHA") != _digest(request_sha, f"{mode} bound request SHA"):
        raise VerificationFailure(f"{mode} proof does not identify its exact producer request")
    if proof.get("receipt") != str(receipt_path_p) or _digest(proof.get("receipt_sha256"), f"{mode} proof receipt SHA") != receipt_sha:
        raise VerificationFailure(f"{mode} proof does not identify its exact receipt")
    receipt_request = receipt.get("request")
    if not isinstance(receipt_request, dict) or receipt_request.get("path") != str(_absolute(Path(request_path))) or _digest(receipt_request.get("sha256"), f"{mode} receipt request SHA") != _digest(request_sha, f"{mode} bound request SHA"):
        raise VerificationFailure(f"{mode} receipt/request identity is not exact")
    if not isinstance(receipt.get("attempt_id"), str) or not receipt.get("attempt_id"):
        raise VerificationFailure(f"{mode} receipt has no concrete attempt identity")
    execution = receipt.get("execution")
    if not isinstance(execution, dict) or execution.get("returncode") != 0:
        raise VerificationFailure(f"{mode} receipt does not explicitly report execution returncode 0")
    if not str(receipt.get("status", "")).startswith("COMPLETED_"):
        raise VerificationFailure(f"{mode} receipt is not terminal completed status")
    return {"mode": mode, "proof": proof_actual, "receipt": receipt_actual}


def _strict_request_bindings(request_path: Path, request: dict[str, Any], pair_manifest_path: Path,
                             snapshot_path: Path) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA or request.get("variant_schema") != REQUEST_VARIANT:
        raise VerificationFailure("ROOT279 request schema/variant is not the exact V3 contract")
    if request.get("status") != REQUEST_STATUS:
        raise VerificationFailure("ROOT279 request is not the ready-for-parent V3 status")
    if request.get("execution_allowed") is not False or request.get("launch_disabled") is not False:
        raise VerificationFailure("ROOT279 request permits execution")
    manifest_ref = request.get("manifest")
    if not isinstance(manifest_ref, dict) or not _same_path(manifest_ref.get("path"), pair_manifest_path):
        raise VerificationFailure("ROOT279 request manifest does not point to the actual pair manifest")
    if _digest(manifest_ref.get("sha256"), "ROOT279 manifest binding") != _digest(request.get("input_sha256", {}).get(str(_absolute(pair_manifest_path))), "ROOT279 manifest input SHA"):
        raise VerificationFailure("ROOT279 request manifest SHA is not joined to input_sha256")
    # ROOT310 is a deferred producer, but its completed JSON wrapper is a
    # static metadata input in the ready request.  This is the cross-boundary
    # that prevents a different snapshot from being substituted at verify time.
    snapshot_record = _input_record(request, snapshot_path, "ROOT310 snapshot")
    snap_value = _bound_json_record(snapshot_path, snapshot_record, "ROOT310 snapshot input")
    if snap_value.get("schema") != SNAPSHOT_SCHEMA or snap_value.get("status") != SNAPSHOT_STATUS:
        raise VerificationFailure("ROOT310 snapshot input is not the exact completed v2 snapshot")
    source_binding = request.get("source_binding")
    if not isinstance(source_binding, dict) or source_binding.get("queries_s") != list(QUERY_TIMES) or source_binding.get("interpolation") != "FORBIDDEN":
        raise VerificationFailure("ROOT279 request source binding does not freeze query policy")
    # If the additive builder supplies an explicit binding, check it; the
    # actual V3 builder currently carries the same closure through input_files.
    explicit_snapshot = source_binding.get("root310_snapshot")
    if explicit_snapshot is not None:
        if not isinstance(explicit_snapshot, dict) or not _same_path(explicit_snapshot.get("path"), snapshot_path):
            raise VerificationFailure("explicit ROOT310 snapshot binding points elsewhere")
        if _digest(explicit_snapshot.get("sha256"), "explicit ROOT310 snapshot SHA") != _digest(snapshot_record.get("sha256"), "ROOT310 input SHA"):
            raise VerificationFailure("explicit ROOT310 snapshot SHA differs from request input SHA")
    terminal = {mode: _strict_terminal_binding(request, mode) for mode in ("same_cfl", "half_cfl")}
    # Proofs and receipts must also be represented in the exact static source
    # closure.  Their JSON contents were already checked above.
    for mode in terminal.values():
        _input_record(request, Path(mode["proof"]["path"]), "terminal proof")
        _input_record(request, Path(mode["receipt"]["path"]), "terminal receipt")
    return {"snapshot": {"path": str(_absolute(snapshot_path)), "sha256": _digest(snapshot_record.get("sha256"), "ROOT310 input SHA")}, "terminal": terminal}


def verify(common_manifest_path: Path, common_output_path: Path, pair_manifest_path: Path,
           pair_request_path: Path, snapshot_path: Path, guard_result_path: Path,
           child_report_path: Path, verification_output: Path | None = None) -> dict[str, Any]:
    # Exact statuses are checked before delegating to V1.  V1 remains the
    # detailed structural checker and is never modified on disk.
    common_manifest, _ = _read_json(common_manifest_path, "ROOT279 common manifest")
    if common_manifest.get("schema") != COMMON_MANIFEST_SCHEMA or common_manifest.get("status") not in COMMON_MANIFEST_STATUSES:
        raise VerificationFailure("ROOT279 common manifest schema/status is not exact")
    common_output, _ = _read_json(common_output_path, "ROOT279 common output")
    if common_output.get("schema") != COMMON_SCHEMA or common_output.get("status") != COMMON_OUTPUT_STATUS:
        raise VerificationFailure("ROOT279 common output schema/status is not exact")
    pair, _ = _read_json(pair_manifest_path, "ROOT279 pair manifest")
    if pair.get("status") != PAIR_STATUS:
        raise VerificationFailure("ROOT279 pair manifest has no completed parent snapshot status")
    request, _ = _read_json(pair_request_path, "ROOT279 pair request")
    bindings = _strict_request_bindings(pair_request_path, request, pair_manifest_path, snapshot_path)
    guard, _ = _read_json(guard_result_path, "ROOT279 guarded result")
    if guard.get("schema") != GUARD_SCHEMA or guard.get("status") != GUARD_STATUS:
        raise VerificationFailure("ROOT279 guard schema/status is not exact")
    child, _ = _read_json(child_report_path, "ROOT279 child report")
    if child.get("schema") != CHILD_SCHEMA or child.get("status") != CHILD_STATUS:
        raise VerificationFailure("ROOT279 child schema/status is not exact")

    result_v1 = V1.verify(common_manifest_path, common_output_path, pair_manifest_path,
                          pair_request_path, snapshot_path, guard_result_path,
                          child_report_path, None)
    result = dict(result_v1)
    result["schema"] = SCHEMA
    result["status"] = "VERIFIED_ROOT279_PAIR_REPORT_METADATA_ONLY_V2"
    result["v2_contract"] = {
        "json_suffix_required": True,
        "json_metadata_cap_bytes": JSON_CAP_BYTES,
        "exact_guard_schema": GUARD_SCHEMA,
        "exact_guard_status": GUARD_STATUS,
        "root310_snapshot_schema": SNAPSHOT_SCHEMA,
        "root310_snapshot_status": SNAPSHOT_STATUS,
        "terminal_receipt_returncode": 0,
        "native_payload_read": False,
    }
    result["strict_bindings"] = bindings
    if verification_output is not None:
        output = _absolute(verification_output)
        if output.suffix.lower() != ".json":
            raise VerificationFailure("verification output must be a .json file")
        if output.exists() or output.is_symlink():
            raise VerificationFailure(f"refusing overwrite: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _record(path: Path) -> dict[str, Any]:
    path = _absolute(path)
    stat = path.stat()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "stat": {"device": stat.st_dev, "inode": stat.st_ino, "bytes": stat.st_size,
                     "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns}}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _genuine_fixture(root: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
    """Run the real guarded wrapper and common endpoint on tiny manufactured files.

    The verifier input JSON is assembled around the guard's actual output and
    the common observer's actual output; no final report is handwritten as a
    substitute for either process.
    """
    v4_spec = importlib.util.spec_from_file_location("stage2_root279_v4_fixture", V4)
    if v4_spec is None or v4_spec.loader is None:
        raise RuntimeError("cannot load V4 fixture")
    v4 = importlib.util.module_from_spec(v4_spec); v4_spec.loader.exec_module(v4)
    common_spec = importlib.util.spec_from_file_location("stage2_root279_common_fixture", COMMON)
    if common_spec is None or common_spec.loader is None:
        raise RuntimeError("cannot load common observer fixture")
    common = importlib.util.module_from_spec(common_spec); common_spec.loader.exec_module(common)
    v4.EXPECTED_DEFERRED_COUNT = 10
    with_root = root / "chain"; with_root.mkdir(parents=True)
    # Common fixture supplies a valid child observer JSON and calibration
    # manifest.  Its guard/source files are only tiny manufactured metadata.
    (with_root / "common").mkdir(parents=True, exist_ok=True)
    common_manifest_path, _ = common._fixture_manifest(with_root / "common")
    common_manifest = json.loads(common_manifest_path.read_text(encoding="utf-8"))
    common_child = with_root / "common" / "child.json"
    child_worker = with_root / "child-worker.py"
    child_worker.write_text(
        "import argparse,json,pathlib,shutil\n"
        "p=argparse.ArgumentParser(); p.add_argument('--manifest'); p.add_argument('--attempt-root'); p.add_argument('--output'); a=p.parse_args()\n"
        f"pathlib.Path(a.output).parent.mkdir(parents=True, exist_ok=True); shutil.copyfile({str(common_child)!r}, a.output)\n",
        encoding="utf-8")
    child_worker.chmod(0o755)
    guard_manifest, _ = v4._fixture_manifest(with_root / "guard")
    attempt = with_root / "attempt"
    guard_output = attempt / "observer" / "guard.json"
    command = [sys.executable, str(GUARDED), "--run", "--manifest", str(guard_manifest),
               "--attempt-root", str(attempt), "--output", str(guard_output),
               "--v1-worker", str(child_worker), "--python", sys.executable,
               "--cwd", str(with_root), "--timeout-seconds", "20"]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if completed.returncode != 0 or not guard_output.is_file():
        raise AssertionError(f"real ROOT279 guard fixture failed: rc={completed.returncode}; stdout={completed.stdout}; stderr={completed.stderr}")
    guard = json.loads(guard_output.read_text(encoding="utf-8"))
    child_output = attempt / "observer" / ".v1-result.json"
    if not child_output.is_file():
        raise AssertionError("real ROOT279 guard did not produce a child output")
    guard_records = guard.get("source_integrity", {}).get("pre")
    if not isinstance(guard_records, list) or len(guard_records) != 10:
        raise AssertionError("real guard did not expose ten source records")
    paths = [str(_absolute(Path(item["path"]))) for item in guard_records]
    # Build pair/snapshot records from the actual guard source records.
    selected = []
    for frame, item in enumerate(guard_records):
        stat = item["stat"]
        selected.append({"path": paths[frame], "frame": frame, "sha256": item["sha256"], "bytes": stat["bytes"],
                         "stat_before": {"bytes": stat["bytes"], "mtime_ns": stat["mtime_ns"], "ctime_ns": stat["ctime_ns"], "st_dev": stat["device"], "st_ino": stat["inode"]},
                         "stat_after": {"bytes": stat["bytes"], "mtime_ns": stat["mtime_ns"], "ctime_ns": stat["ctime_ns"], "st_dev": stat["device"], "st_ino": stat["inode"]},
                         "stat_consistency": "PASS_PRE_POST_IDENTICAL"})
    immutable = [{"frame": item["frame"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]} for item in selected]
    digest = hashlib.sha256(json.dumps(immutable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    snapshot = {"schema": SNAPSHOT_SCHEMA, "status": SNAPSHOT_STATUS,
                "worker_scope": {"bi4_decode": False, "solver_launch": False},
                "requests": [{"selected_native_files": selected[:5]}, {"selected_native_files": selected[5:]}],
                "immutable_source_sha_list": immutable, "source_sha_list_digest": digest,
                "selected_native_total_bytes": sum(item["bytes"] for item in selected)}
    snapshot_path = with_root / "snapshot.json"; _write_json(snapshot_path, snapshot)
    pair_cases = []
    for mode, subset in zip(("same_cfl", "half_cfl"), (selected[:5], selected[5:])):
        pair_cases.append({"label": mode, "selected_native_frame_metadata": [
            {"path": item["path"], "frame": item["frame"], "known_sha256": item["sha256"],
             "stat_at_prepare": {"device": item["stat_after"]["st_dev"], "inode": item["stat_after"]["st_ino"], "bytes": item["bytes"], "mtime_ns": item["stat_after"]["mtime_ns"], "ctime_ns": item["stat_after"]["ctime_ns"]}}
            for item in subset]})
    pair_path = with_root / "pair.json"
    _write_json(pair_path, {"schema": "ds02.stage2.f1.native-selected-observer-manifest.v2", "status": PAIR_STATUS, "cases": pair_cases})
    # Terminal proof/receipt metadata are tiny and are joined exactly as the
    # real ROOT277/278 source request does.  They do not represent a solver.
    static_paths: list[Path] = []
    terminal_bindings: dict[str, Any] = {}
    for mode in ("same_cfl", "half_cfl"):
        producer_request = with_root / f"{mode}-producer-request.json"
        _write_json(producer_request, {"schema": "ds02.request.v1", "family_id": "F1", "case_id": f"fixture-{mode}", "attempt_id": f"fixture/{mode}"})
        request_record = _record(producer_request)
        receipt_path = with_root / f"{mode}-receipt.json"
        receipt = {"schema": "ds02.execution.receipt.v1", "status": "COMPLETED_DEVELOPMENT_UNKNOWN",
                   "request": {"path": str(producer_request), "sha256": request_record["sha256"]},
                   "attempt_id": f"F1/fixture-{mode}/fixture", "execution": {"returncode": 0}}
        _write_json(receipt_path, receipt); receipt_record = _record(receipt_path)
        proof_path = with_root / f"{mode}-proof.json"
        proof = {"schema": PROOF_SCHEMA, "status": f"VERIFIED_ACTUAL_F1_S2_DP020_{mode.upper()}_NO_Q",
                 "request": str(producer_request), "request_sha256": request_record["sha256"],
                 "receipt": str(receipt_path), "receipt_sha256": receipt_record["sha256"]}
        _write_json(proof_path, proof); proof_record = _record(proof_path)
        terminal_bindings[mode] = {"proof": str(proof_path), "proof_sha256": proof_record["sha256"],
                                   "receipt": receipt_record, "request": str(producer_request), "request_sha256": request_record["sha256"]}
        static_paths.extend((producer_request, receipt_path, proof_path))
    snapshot_record = _record(snapshot_path); pair_record = _record(pair_path)
    static_paths.extend((snapshot_path, pair_path, guard_output, child_output))
    # Use all common observer source records as static metadata.  The actual
    # endpoint runner will validate/read only these JSON files.
    joined_manifest = json.loads(json.dumps(common_manifest))
    joined_manifest["status"] = "PREPARED_ROOT279_COMMON_ENDPOINT_OBSERVER_V1"
    joined_manifest["sources"]["root279_guard_result"] = _record(guard_output)
    joined_manifest["sources"]["root279_child_report"] = _record(child_output)
    joined_manifest["sources"]["root279_manifest"] = pair_record
    joined_manifest_path = with_root / "common-manifest.json"; _write_json(joined_manifest_path, joined_manifest)
    endpoint_output = with_root / "common-output.json"
    # This is the actual common endpoint worker, with source paths updated to
    # the real guard/child outputs from the subprocess above.
    endpoint_result = common.run(joined_manifest_path, endpoint_output)
    if endpoint_result.get("status") != COMMON_OUTPUT_STATUS:
        raise AssertionError(f"actual common endpoint fixture failed: {endpoint_result}")
    static_paths.extend((joined_manifest_path, endpoint_output))
    input_records = {_record(path)["path"]: _record(path) for path in static_paths}
    # A request record for the pair itself is added after content is assembled;
    # it is intentionally not self-referenced in input_records.
    request_path = with_root / "pair-request.json"
    input_files = sorted(input_records)
    request = {"schema": REQUEST_SCHEMA, "variant_schema": REQUEST_VARIANT, "status": REQUEST_STATUS,
               "execution_allowed": False, "launch_disabled": False, "input_files": input_files,
               "input_records": input_records, "input_sha256": {path: rec["sha256"] for path, rec in input_records.items()},
               "manifest": pair_record, "deferred_input_records": [
                   {"path": item["path"], "frame": item["frame"], "known_sha256": item["sha256"],
                    "stat_at_prepare": {"device": item["stat_after"]["st_dev"], "inode": item["stat_after"]["st_ino"], "bytes": item["bytes"], "mtime_ns": item["stat_after"]["mtime_ns"], "ctime_ns": item["stat_after"]["ctime_ns"]}}
                   for item in selected],
               "source_binding": {"queries_s": list(QUERY_TIMES), "interpolation": "FORBIDDEN",
                                  "root277_terminal": terminal_bindings["same_cfl"], "root278_terminal": terminal_bindings["half_cfl"],
                                  "root310_snapshot": snapshot_record},
               "native_payload_read": False, "solver_started": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}}
    _write_json(request_path, request)
    return (joined_manifest_path, endpoint_output, pair_path, request_path, snapshot_path, guard_output, child_output)


def genuine_fixture() -> None:
    with tempfile.TemporaryDirectory(prefix="root279-v2-genuine-chain-") as directory:
        paths = _genuine_fixture(Path(directory))
        result = verify(*paths)
        if result.get("status") != "VERIFIED_ROOT279_PAIR_REPORT_METADATA_ONLY_V2":
            raise AssertionError("V2 verifier did not accept the actual guard→endpoint chain")
        # Exact guard status/schema negative.
        guard = json.loads(paths[5].read_text(encoding="utf-8")); guard["status"] = "PASS_UNTRUSTED"
        bad_guard = Path(directory) / "bad-guard.json"; _write_json(bad_guard, guard)
        try:
            verify(paths[0], paths[1], paths[2], paths[3], paths[4], bad_guard, paths[6])
        except VerificationFailure:
            pass
        else:
            raise AssertionError("non-exact guard status was accepted")
        # Strict suffix negative: the same bounded JSON under .txt is not a
        # metadata file accepted by this verifier.
        bad_output = Path(directory) / "endpoint-result.txt"; shutil.copyfile(paths[1], bad_output)
        try:
            verify(paths[0], bad_output, paths[2], paths[3], paths[4], paths[5], paths[6])
        except VerificationFailure:
            pass
        else:
            raise AssertionError("non-JSON common output was accepted")
        # Receipt/snapshot cross-bound negative: alter the explicit snapshot
        # record without changing the actual ROOT310 JSON.
        request = json.loads(paths[3].read_text(encoding="utf-8")); request["source_binding"]["root310_snapshot"]["sha256"] = "0" * 64
        bad_request = Path(directory) / "bad-request.json"; _write_json(bad_request, request)
        try:
            verify(paths[0], paths[1], paths[2], bad_request, paths[4], paths[5], paths[6])
        except VerificationFailure:
            pass
        else:
            raise AssertionError("tampered ROOT310 snapshot binding was accepted")
        oversize = Path(directory) / "oversize.json"
        oversize.write_bytes(b"{" + b" " * JSON_CAP_BYTES + b"}")
        try:
            _read_json(oversize, "oversize metadata")
        except VerificationFailure:
            pass
        else:
            raise AssertionError("metadata larger than 10 MiB was accepted")
    print("PASS_ROOT279_V2_GENUINE_GUARDED_ENDPOINT_VERIFIER_CHAIN")


def self_test() -> None:
    # The genuine fixture is the meaningful test: it launches only the actual
    # bounded guard and common observer against manufactured tiny files.
    genuine_fixture()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--genuine-fixture", action="store_true")
    mode.add_argument("--verify", action="store_true")
    for name in ("common-manifest", "common-output", "pair-manifest", "pair-request", "snapshot", "guard-result", "child-report", "verification-output"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args(argv)
    if args.self_test or args.genuine_fixture:
        try:
            genuine_fixture()
        except Exception as exc:
            print(f"FAILED_ROOT279_V2_GENUINE_CHAIN: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        return 0
    required = (args.common_manifest, args.common_output, args.pair_manifest, args.pair_request, args.snapshot, args.guard_result, args.child_report)
    if any(item is None for item in required):
        parser.error("--verify requires all seven source/report paths")
    try:
        result = verify(*required, args.verification_output)
    except (VerificationFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_V2_PAIR_REPORT_VERIFIER: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "selected_native_count": result["selected_native_count"], "scientific_credit": 0, "json_cap_bytes": JSON_CAP_BYTES}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
