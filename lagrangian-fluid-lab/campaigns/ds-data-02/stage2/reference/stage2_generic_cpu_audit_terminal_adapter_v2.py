#!/usr/bin/env python3
"""Read-only terminal adapter for the generic CPU-audit request schema.

The v8 runner accepts ``ds02.stage2.generic-cpu-audit-request.v2`` for a
small source audit, while the historical terminal fee reconciler only accepts
``ds02.request.v1``.  This adapter deliberately does not translate or rewrite
the consumed request.  It validates the original request, receipt, systemd
CPU evidence, runtime/source closure, and ledger charge, and emits a new
read-only reconciliation record for the parent process.

It never appends to the resource ledger and never reads native payloads.  The
input files are restricted to small source/metadata files; a future guarded
worker must be used for any native payload.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Sequence


ADAPTER_SCHEMA = "ds02.stage2.generic-cpu-audit-terminal-adapter.v2"
REQUEST_SCHEMA = "ds02.stage2.generic-cpu-audit-request.v2"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
EVIDENCE_SCHEMA = "ds02.stage2.systemd-cpu-evidence.v1"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
MAX_INPUT_BYTES = 16 * 1024 * 1024
HEX64 = set("0123456789abcdef")
FORBIDDEN_PAYLOAD_SUFFIXES = (".bi4", ".h5", ".hdf5", ".vtk", ".vtu")


class AdapterFailure(RuntimeError):
    """A binding or accounting assertion failed."""


def _fail(message: str) -> None:
    raise AdapterFailure(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path, *, max_bytes: int) -> tuple[str, os.stat_result, int]:
    """Hash one small regular file and return hash, stable stat, and bytes."""
    _require(path.exists(), f"missing file: {path}")
    before = path.stat()
    _require(stat.S_ISREG(before.st_mode), f"not a regular file: {path}")
    _require(not path.is_symlink(), f"symlink is not an immutable input: {path}")
    _require(before.st_size <= max_bytes, f"file exceeds bounded adapter read: {path}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            _require(size <= max_bytes, f"file grew past bounded adapter read: {path}")
            digest.update(chunk)
    after = path.stat()
    _require(_stat_signature(before) == _stat_signature(after), f"file changed while read: {path}")
    _require(size == before.st_size, f"file size changed while read: {path}")
    return digest.hexdigest(), after, size


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
        int(value.st_mode),
        int(value.st_nlink),
    )


def _load_json(path_value: str | Path, *, max_bytes: int) -> tuple[Dict[str, Any], str, os.stat_result, int]:
    path = Path(path_value)
    digest, info, size = _sha_file(path, max_bytes=max_bytes)
    # Parse the bytes whose stable stat was just checked.  This second
    # bounded read closes the small metadata race between hashing and JSON
    # decoding; it never applies to deferred native payloads.
    payload = path.read_bytes()
    after = path.stat()
    _require(_stat_signature(info) == _stat_signature(after), f"JSON changed after hash: {path}")
    _require(_sha_bytes(payload) == digest, f"JSON bytes changed after hash: {path}")
    try:
        value = json.loads(payload.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - message is part of guard output
        _fail(f"invalid JSON {path}: {exc}")
    _require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value, digest, info, size


def _as_path(value: Any, label: str) -> Path:
    _require(isinstance(value, str) and value and os.path.isabs(value), f"{label} must be absolute")
    return Path(value)


def _exactly(value: Any, expected: Any, label: str) -> None:
    _require(value == expected, f"{label} mismatch")


def _sha_hex(value: Any, label: str) -> str:
    _require(isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX64, f"{label} is not SHA-256")
    return value.lower()


def _positive_int(value: Any, label: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool) and value > 0, f"{label} must be positive integer")
    return value


def _finite_number(value: Any, label: str) -> float:
    _require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{label} must be numeric")
    number = float(value)
    _require(math.isfinite(number) and number >= 0, f"{label} must be finite and nonnegative")
    return number


def _identity(request: Mapping[str, Any]) -> Dict[str, str]:
    fields = ("family_id", "case_id", "attempt_id")
    result: Dict[str, str] = {}
    for field in fields:
        value = request.get(field)
        _require(isinstance(value, str) and value, f"request identity missing {field}")
        result[field] = value
    return result


def _identity_from_receipt(value: Mapping[str, Any]) -> Dict[str, str]:
    return {field: value.get(field) for field in ("family_id", "case_id", "attempt_id")}


def _find_runtime_input(request: Mapping[str, Any], input_hashes: Mapping[str, Any]) -> tuple[Path, str]:
    candidates = []
    for raw in request["input_files"]:
        path = Path(raw)
        name = path.name
        if name in {"ds_data02_runtime_v8.py", "ds_data02_runtime_v6.py", "ds_data02_runtime_v2.py"}:
            candidates.append(path)
    _require(candidates, "generic audit must bind a runtime source")
    selected_version = request.get("shared_runtime_version")
    if isinstance(selected_version, str) and selected_version in {"v2", "v6", "v8"}:
        selected_name = f"ds_data02_runtime_{selected_version}.py"
        selected = [path for path in candidates if path.name == selected_name]
        _require(len(selected) == 1, f"requested runtime {selected_version} is not uniquely bound")
        runtime = selected[0]
    else:
        _require(len(candidates) == 1, "generic audit without shared_runtime_version must bind exactly one runtime source")
        runtime = candidates[0]
    expected = _sha_hex(input_hashes.get(str(runtime)), f"runtime hash {runtime}")
    return runtime, expected


def _validate_literal_invocation(request: Mapping[str, Any], input_hashes: Mapping[str, Any]) -> Dict[str, Any]:
    invocation = request.get("literal_venv_invocation")
    if invocation is None:
        return {"present": False}
    _require(isinstance(invocation, dict), "literal_venv_invocation must be an object")
    literal = _as_path(invocation.get("path"), "literal_venv_invocation.path")
    _require(invocation.get("argv0_literal") is True, "literal venv argv0 must be explicitly preserved")
    command = request.get("command")
    _require(isinstance(command, list) and command and command[0] == str(literal), "command argv0 is not the literal venv path")
    # The project venv's literal argv0 is commonly a symlink (for example
    # ``bin/python -> python3``).  Preserve that argv0, but bind the resolved
    # regular executable bytes explicitly below.
    _require(literal.exists(), "literal venv executable is unavailable")
    resolved = literal.resolve()
    resolved_sha, _, _ = _sha_file(resolved, max_bytes=MAX_INPUT_BYTES)
    _exactly(resolved_sha, _sha_hex(invocation.get("resolved_target_sha256"), "resolved target SHA"), "resolved target SHA")
    pyvenv = invocation.get("pyvenv_cfg")
    _require(isinstance(pyvenv, dict), "literal venv pyvenv_cfg missing")
    cfg = _as_path(pyvenv.get("path"), "pyvenv_cfg.path")
    cfg_sha, _, cfg_size = _sha_file(cfg, max_bytes=MAX_INPUT_BYTES)
    _exactly(cfg_sha, _sha_hex(pyvenv.get("sha256"), "pyvenv.cfg SHA"), "pyvenv.cfg SHA")
    _exactly(cfg_size, int(pyvenv.get("bytes")), "pyvenv.cfg byte count")
    # The q may bind the resolved executable and cfg under input_files.  If it
    # does, their hashes must agree; absence is allowed for older generic q's.
    for path, digest in ((resolved, resolved_sha), (cfg, cfg_sha)):
        bound = input_hashes.get(str(path))
        if bound is not None:
            _exactly(_sha_hex(bound, f"literal closure hash {path}"), digest, f"literal closure hash {path}")
    return {
        "present": True,
        "literal_path": str(literal),
        "resolved_path": str(resolved),
        "resolved_sha256": resolved_sha,
        "pyvenv_cfg_path": str(cfg),
        "pyvenv_cfg_sha256": cfg_sha,
    }


def _validate_request_inputs(request: Mapping[str, Any]) -> Dict[str, Any]:
    _exactly(request.get("schema"), REQUEST_SCHEMA, "request schema")
    _exactly(request.get("kind"), "cpu", "request kind")
    _exactly(request.get("cpu_task_kind"), "audit", "request cpu_task_kind")
    _identity(request)
    resources = request.get("resources")
    _require(isinstance(resources, dict), "request resources missing")
    raw_threads = resources.get("cpu_threads", resources.get("cpu_cores", request.get("cpu_threads")))
    threads = _positive_int(raw_threads, "request CPU thread count")
    wall = _finite_number(resources.get("max_wall_seconds"), "resources.max_wall_seconds")
    raw_memory = resources.get("memory_max_bytes", request.get("max_memory_bytes"))
    memory = _positive_int(raw_memory, "request memory_max_bytes")
    for key in ("scratch_max_bytes", "home_storage_max_bytes", "external_storage_max_bytes", "log_max_bytes"):
        if key in resources:
            _positive_int(resources[key], f"resources.{key}")
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    _require(isinstance(files, list) and files and all(isinstance(p, str) for p in files), "request input_files invalid")
    _require(len(files) == len(set(files)), "request input_files contains duplicates")
    _require(isinstance(hashes, dict) and set(files) == set(hashes), "request input_files/input_sha256 sets differ")
    _require(len(files) <= 128, "generic audit input closure is unexpectedly large")
    seen: Dict[str, Dict[str, Any]] = {}
    for raw in files:
        path = _as_path(raw, "request input file")
        _require(path.suffix.lower() not in FORBIDDEN_PAYLOAD_SUFFIXES, f"native payload cannot be generic CPU input: {path}")
        expected = _sha_hex(hashes[raw], f"input SHA {raw}")
        actual, info, size = _sha_file(path, max_bytes=MAX_INPUT_BYTES)
        _exactly(actual, expected, f"input SHA {raw}")
        seen[raw] = {"sha256": actual, "bytes": size, "stat": _stat_signature(info)}
    runtime, runtime_sha = _find_runtime_input(request, hashes)
    literal = _validate_literal_invocation(request, hashes)
    command = request.get("command")
    _require(isinstance(command, list) and command and all(isinstance(x, str) for x in command), "request command invalid")
    return {
        "family_id": request["family_id"],
        "case_id": request["case_id"],
        "attempt_id": request["attempt_id"],
        "input_count": len(files),
        "input_bytes": sum(v["bytes"] for v in seen.values()),
        "runtime_source": str(runtime),
        "runtime_sha256": runtime_sha,
        "literal_venv": literal,
        "cpu_threads": threads,
        "max_wall_seconds": wall,
        "memory_max_bytes": memory,
    }


def _validate_receipt(
    request: Mapping[str, Any],
    request_path: Path,
    request_sha: str,
    receipt: Mapping[str, Any],
    receipt_path: Path,
    receipt_sha: str,
    input_sha256: Mapping[str, str],
) -> Dict[str, Any]:
    _exactly(receipt.get("schema"), RECEIPT_SCHEMA, "receipt schema")
    _exactly(receipt.get("request"), request, "receipt embedded request")
    _exactly(receipt.get("request_sha256"), request_sha, "receipt request SHA")
    _exactly(receipt.get("status"), "completed", "receipt status")
    _exactly(receipt.get("returncode"), 0, "receipt returncode")
    _exactly(receipt.get("input_hashes_at_launch"), input_sha256, "receipt launch input hashes")
    _exactly(receipt.get("input_hashes_after_run"), input_sha256, "receipt after-run input hashes")
    runner = _as_path(receipt.get("runner_source"), "receipt runner_source")
    runner_sha, _, _ = _sha_file(runner, max_bytes=MAX_INPUT_BYTES)
    _exactly(runner_sha, _sha_hex(receipt.get("runner_sha256"), "receipt runner SHA"), "receipt runner SHA")
    _require(str(runner) in input_sha256, "receipt runner source is outside request input closure")
    _exactly(runner_sha, _sha_hex(input_sha256[str(runner)], "bound runner SHA"), "bound runner SHA")
    preflight = receipt.get("source_preflight")
    _require(isinstance(preflight, dict), "receipt source_preflight missing")
    _exactly(preflight.get("status"), "PASS_AFTER_RESERVATION", "receipt source preflight status")
    _exactly(preflight.get("reservation_registered_before_content_hash"), True, "reservation ordering")
    _exactly(preflight.get("content_read_started_after_reservation"), True, "content-read ordering")
    storage = receipt.get("terminal_storage_guard")
    _require(isinstance(storage, dict), "receipt terminal storage guard missing")
    _exactly(storage.get("status"), "passed", "terminal storage guard")
    _positive_int(storage.get("reservation_bytes"), "terminal storage reservation")
    _require(isinstance(storage.get("actual_bytes"), int) and storage["actual_bytes"] >= 0, "terminal storage actual bytes")
    _exactly(storage.get("excess_bytes"), 0, "terminal storage excess")
    cpu = _finite_number(receipt.get("cpu_core_seconds"), "receipt cpu_core_seconds")
    return {
        "path": str(receipt_path),
        "sha256": receipt_sha,
        "request_sha256": request_sha,
        "status": receipt["status"],
        "returncode": receipt["returncode"],
        "cpu_core_seconds": cpu,
        "output_root": receipt.get("output_root"),
        "runner_source": str(runner),
        "runner_sha256": runner_sha,
        "storage": copy.deepcopy(storage),
        "qualification": copy.deepcopy(receipt.get("qualification")),
    }


def _validate_evidence(
    request: Mapping[str, Any],
    request_path: Path,
    request_sha: str,
    receipt_path: Path,
    receipt_sha: str,
    evidence: Mapping[str, Any],
    evidence_path: Path,
    evidence_sha: str,
) -> Dict[str, Any]:
    _exactly(evidence.get("schema"), EVIDENCE_SCHEMA, "CPU evidence schema")
    _exactly(evidence.get("request"), str(request_path), "CPU evidence request path")
    _exactly(evidence.get("request_sha256"), request_sha, "CPU evidence request SHA")
    _exactly(evidence.get("receipt"), str(receipt_path), "CPU evidence receipt path")
    _exactly(evidence.get("receipt_sha256"), receipt_sha, "CPU evidence receipt SHA")
    _exactly(evidence.get("identity"), _identity(request), "CPU evidence identity")
    charge_id = evidence.get("charge_id")
    _require(isinstance(charge_id, str) and charge_id, "CPU evidence charge_id missing")
    cpu_ns = evidence.get("CPUUsageNSec", evidence.get("cpu_usage_nsec"))
    _require(isinstance(cpu_ns, int) and not isinstance(cpu_ns, bool) and cpu_ns >= 0, "CPUUsageNSec invalid")
    props = evidence.get("systemd_properties")
    _require(isinstance(props, dict), "systemd properties missing")
    _exactly(str(props.get("Result")), "success", "systemd Result")
    _exactly(str(props.get("ExecMainStatus")), "0", "systemd ExecMainStatus")
    _exactly(str(props.get("SubState")), "exited", "systemd SubState")
    _require(isinstance(props.get("MemoryMax"), (str, int)), "systemd MemoryMax missing")
    memory_max = int(props["MemoryMax"])
    resources = request["resources"]
    expected_memory = resources.get("memory_max_bytes", request.get("max_memory_bytes"))
    _exactly(memory_max, int(expected_memory), "systemd MemoryMax")
    _exactly(evidence.get("terminal"), True, "CPU evidence terminal flag")
    return {
        "path": str(evidence_path),
        "sha256": evidence_sha,
        "charge_id": charge_id,
        "cpu_usage_nsec": cpu_ns,
        "cpu_core_seconds": cpu_ns / 1_000_000_000.0,
        "systemd_unit": props.get("Id"),
        "memory_max_bytes": memory_max,
        "result": props.get("Result"),
        "exec_main_status": props.get("ExecMainStatus"),
    }


def _validate_ledger(
    ledger: Mapping[str, Any],
    evidence: Mapping[str, Any],
    receipt_cpu: float,
) -> Dict[str, Any]:
    charges = ledger.get("charges")
    _require(isinstance(charges, list), "resource ledger charges missing")
    matches = [
        item for item in charges
        if isinstance(item, dict)
        and item.get("charge_id", item.get("id")) == evidence["charge_id"]
    ]
    _require(len(matches) == 1, "resource ledger must contain exactly one matching charge")
    charge = matches[0]
    _exactly(charge.get("status"), "completed", "ledger charge status")
    if "terminal_status" in charge:
        _exactly(charge.get("terminal_status"), "completed", "ledger terminal status")
    charge_cpu = _finite_number(charge.get("cpu_core_seconds"), "ledger cpu_core_seconds")
    _require(abs(charge_cpu - receipt_cpu) <= 1e-9, "ledger CPU does not equal receipt CPU")
    return {
        "charge_id": charge.get("charge_id", charge.get("id")),
        "status": charge["status"],
        "terminal_status": charge.get("terminal_status", charge["status"]),
        "cpu_core_seconds": charge_cpu,
        "charge_record_sha256": _sha_bytes(_canonical(charge)),
    }


def inspect(
    request_path_value: str,
    receipt_path_value: str,
    evidence_path_value: str,
    ledger_path_value: str,
) -> Dict[str, Any]:
    request_path = Path(request_path_value)
    receipt_path = Path(receipt_path_value)
    evidence_path = Path(evidence_path_value)
    ledger_path = Path(ledger_path_value)
    request, request_sha, request_stat, request_bytes = _load_json(request_path, max_bytes=MAX_JSON_BYTES)
    receipt, receipt_sha, receipt_stat, receipt_bytes = _load_json(receipt_path, max_bytes=MAX_JSON_BYTES)
    evidence, evidence_sha, evidence_stat, evidence_bytes = _load_json(evidence_path, max_bytes=MAX_EVIDENCE_BYTES)
    ledger, ledger_sha, ledger_stat, ledger_bytes = _load_json(ledger_path, max_bytes=MAX_JSON_BYTES)
    request_info = _validate_request_inputs(request)
    receipt_info = _validate_receipt(
        request,
        request_path,
        request_sha,
        receipt,
        receipt_path,
        receipt_sha,
        request["input_sha256"],
    )
    evidence_info = _validate_evidence(
        request,
        request_path,
        request_sha,
        receipt_path,
        receipt_sha,
        evidence,
        evidence_path,
        evidence_sha,
    )
    ledger_info = _validate_ledger(ledger, evidence, receipt_info["cpu_core_seconds"])
    evidence_cpu = evidence_info["cpu_core_seconds"]
    delta = evidence_cpu - receipt_info["cpu_core_seconds"]
    _require(delta >= -1e-9, "systemd CPU evidence is below receipt CPU")
    _exactly(evidence_info["charge_id"], ledger_info["charge_id"], "evidence/ledger charge identity")
    return {
        "schema": ADAPTER_SCHEMA,
        "status": "READY_FOR_TERMINAL_CPU_RECONCILIATION" if delta > 1e-9 else "NO_CPU_DELTA_REQUIRED",
        "request_schema": REQUEST_SCHEMA,
        "request": {"path": str(request_path), "sha256": request_sha, "bytes": request_bytes, "stat": _stat_signature(request_stat)},
        "receipt": receipt_info,
        "cpu_evidence": evidence_info,
        "ledger": {"path": str(ledger_path), "sha256": ledger_sha, "bytes": ledger_bytes, "stat": _stat_signature(ledger_stat), **ledger_info},
        "identity": _identity(request),
        "source_binding": request_info,
        "cpu": {
            "receipt_core_seconds": receipt_info["cpu_core_seconds"],
            "systemd_core_seconds": evidence_cpu,
            "terminal_delta_core_seconds": max(0.0, delta),
            "systemd_cpu_nsec": evidence_info["cpu_usage_nsec"],
        },
        "memory": {"requested_max_bytes": request_info["memory_max_bytes"], "systemd_max_bytes": evidence_info["memory_max_bytes"]},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "fee_action": "MAIN_PROCESS_ONLY",
        "reservation_created": False,
        "ledger_mutation": False,
        "original_request_unchanged": True,
        "native_payload_read": False,
        "report_read_scope": "request/receipt/evidence/ledger and bounded small input closure only",
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _require(not path.exists(), f"refusing to overwrite output: {path}")
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp.write_bytes(_canonical(value) + b"\n")
    os.replace(temp, path)


def _fixture_request(root: Path) -> tuple[Path, Path, Path, Path]:
    source = root / "ds_data02_runtime_v8.py"
    worker = root / "worker.py"
    source.write_text("# fixture runtime\n", encoding="utf-8")
    worker.write_text("# fixture worker\n", encoding="utf-8")
    input_files = [str(source), str(worker)]
    input_hashes = {path: _sha_file(Path(path), max_bytes=MAX_INPUT_BYTES)[0] for path in input_files}
    request = {
        "schema": REQUEST_SCHEMA,
        "status": "PREPARED_NOT_RUN_SOURCE_ONLY",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "fixture-request",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "case_id": "fixture-case",
        "attempt_id": "fixture-attempt",
        "command": ["/bin/echo", "fixture"],
        "resources": {
            "cpu_threads": 1,
            "max_wall_seconds": 10,
            "memory_max_bytes": 1024 * 1024,
            "scratch_max_bytes": 1024 * 1024,
            "home_storage_max_bytes": 1024 * 1024,
            "external_storage_max_bytes": 1024 * 1024,
            "log_max_bytes": 1024,
        },
        "input_files": input_files,
        "input_sha256": input_hashes,
    }
    request_path = root / "request.json"
    _write_json(request_path, request)
    request_sha = _sha_file(request_path, max_bytes=MAX_JSON_BYTES)[0]
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "request": request,
        "request_sha256": request_sha,
        "input_hashes_at_launch": input_hashes,
        "input_hashes_after_run": input_hashes,
        "runner_source": str(source),
        "runner_sha256": input_hashes[str(source)],
        "status": "completed",
        "returncode": 0,
        "cpu_core_seconds": 1.0,
        "terminal_storage_guard": {"status": "passed", "reservation_bytes": 1024, "actual_bytes": 1, "excess_bytes": 0},
        "source_preflight": {"status": "PASS_AFTER_RESERVATION", "reservation_registered_before_content_hash": True, "content_read_started_after_reservation": True},
        "output_root": str(root / "output"),
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    receipt_path = root / "receipt.json"
    _write_json(receipt_path, receipt)
    receipt_sha = _sha_file(receipt_path, max_bytes=MAX_JSON_BYTES)[0]
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "request": str(request_path),
        "request_sha256": request_sha,
        "receipt": str(receipt_path),
        "receipt_sha256": receipt_sha,
        "identity": {"family_id": "F1", "case_id": "fixture-case", "attempt_id": "fixture-attempt"},
        "charge_id": "fixture-charge",
        "CPUUsageNSec": 1_100_000_000,
        "systemd_properties": {"Result": "success", "ExecMainStatus": "0", "SubState": "exited", "MemoryMax": str(1024 * 1024), "Id": "fixture.service"},
        "terminal": True,
    }
    evidence_path = root / "evidence.json"
    _write_json(evidence_path, evidence)
    ledger = {"charges": [{"charge_id": "fixture-charge", "status": "completed", "terminal_status": "completed", "cpu_core_seconds": 1.0}]}
    ledger_path = root / "ledger.json"
    _write_json(ledger_path, ledger)
    return request_path, receipt_path, evidence_path, ledger_path


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="generic-cpu-audit-v2-") as temp:
        root = Path(temp)
        request, receipt, evidence, ledger = _fixture_request(root)
        before = ledger.read_bytes()
        report = inspect(str(request), str(receipt), str(evidence), str(ledger))
        _exactly(report["status"], "READY_FOR_TERMINAL_CPU_RECONCILIATION", "fixture adapter status")
        _exactly(report["ledger_mutation"], False, "fixture ledger mutation")
        _exactly(ledger.read_bytes(), before, "fixture ledger unchanged")

        original = json.loads(request.read_text())
        bad = copy.deepcopy(original)
        bad["schema"] = "ds02.request.v1"
        request.write_bytes(_canonical(bad) + b"\n")
        try:
            inspect(str(request), str(receipt), str(evidence), str(ledger))
        except AdapterFailure:
            pass
        else:  # pragma: no cover - guard must reject this mutation
            raise AssertionError("schema mutation was accepted")
        request.write_bytes(_canonical(original) + b"\n")

        original_evidence = json.loads(evidence.read_text())
        bad_evidence = copy.deepcopy(original_evidence)
        bad_evidence["systemd_properties"]["MemoryMax"] = str(2 * 1024 * 1024)
        evidence.write_bytes(_canonical(bad_evidence) + b"\n")
        try:
            inspect(str(request), str(receipt), str(evidence), str(ledger))
        except AdapterFailure:
            pass
        else:  # pragma: no cover
            raise AssertionError("memory mutation was accepted")
        evidence.write_bytes(_canonical(original_evidence) + b"\n")
        # Receipt SHA and identity are separate joins; exercise both rather
        # than relying on the schema and memory checks above.
        original_receipt = json.loads(receipt.read_text())
        bad_receipt = copy.deepcopy(original_receipt)
        bad_receipt["request_sha256"] = "0" * 64
        receipt.write_bytes(_canonical(bad_receipt) + b"\n")
        try:
            inspect(str(request), str(receipt), str(evidence), str(ledger))
        except AdapterFailure:
            pass
        else:  # pragma: no cover
            raise AssertionError("receipt request SHA mutation was accepted")
        receipt.write_bytes(_canonical(original_receipt) + b"\n")

        bad_identity = copy.deepcopy(original_evidence)
        bad_identity["identity"]["case_id"] = "wrong-case"
        evidence.write_bytes(_canonical(bad_identity) + b"\n")
        try:
            inspect(str(request), str(receipt), str(evidence), str(ledger))
        except AdapterFailure:
            pass
        else:  # pragma: no cover
            raise AssertionError("evidence identity mutation was accepted")
    print("PASS_GENERIC_CPU_AUDIT_TERMINAL_ADAPTER_V2_SELFTEST")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run bounded positive and negative fixtures")
    sub = parser.add_subparsers(dest="command")
    inspect_parser = sub.add_parser("inspect", help="validate one completed generic CPU audit read-only")
    inspect_parser.add_argument("--request", required=True)
    inspect_parser.add_argument("--receipt", required=True)
    inspect_parser.add_argument("--evidence", required=True)
    inspect_parser.add_argument("--ledger", required=True)
    inspect_parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.command != "inspect":
            parser.error("choose inspect or --self-test")
        report = inspect(args.request, args.receipt, args.evidence, args.ledger)
        _write_json(Path(args.output), report)
        print(json.dumps({"status": report["status"], "output": args.output, "ledger_mutation": False}, sort_keys=True))
        return 0
    except (AdapterFailure, OSError, ValueError, KeyError) as exc:
        print(f"GENERIC_CPU_AUDIT_TERMINAL_ADAPTER_V2_FAILED: {exc}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
