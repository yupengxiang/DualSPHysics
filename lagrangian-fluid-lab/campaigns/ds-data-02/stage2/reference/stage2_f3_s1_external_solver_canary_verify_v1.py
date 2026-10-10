#!/usr/bin/env python3
"""Independent gate for the F3-S1 canary and its post-solver observer.

The verifier is intentionally separate from the request builder.  It checks
raw request-file SHA joins, producer receipt identity, literal-venv/source
closure, reservation/resource fields, and the native-observer hand-off.  It
does not read generated BI4/VTK/Part payloads.  A compact observer summary is
diagnostic only: QI/QN/QE remain UNKNOWN and saved-time brackets are never
turned into interpolated values.

``--self-test`` runs a genuine manufactured subprocess chain with the literal
stage2 venv: a tiny runtime-shaped producer receipt, a tiny observer producer,
and this verifier/scorer.  The fixture is explicitly marked manufactured and
grants no production credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
MATERIALIZER = HERE / "stage2_f3_s1_external_solver_canary_materialize.py"
OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
SCHEMA = "ds02.stage2.external-solver-request.v5"
VARIANT = "ds02.stage2.f3-s1.external-solver-canary.v1"
JSON_CAP = 10 * 1024 * 1024
HEX64 = set("0123456789abcdef")
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class VerifyFailure(RuntimeError):
    pass


def _abs(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and not (set(value.lower()) - HEX64)


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise VerifyFailure(f"{label} exceeds 10 MiB cap: {path}")
    raw = path.read_bytes(); after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise VerifyFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} must be an object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after}, raw


def _record_stat(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    source = value.get("stat_after") or value.get("stat_at_prepare") or value.get("stat") or {}
    if not isinstance(source, dict):
        return {}
    aliases = {"device": ("device", "st_dev"), "inode": ("inode", "st_ino"),
               "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",)}
    result: dict[str, int] = {}
    for dest, names in aliases.items():
        for name in names:
            if name in source:
                result[dest] = int(source[name]); break
    return result


def _check_path_record(value: Any, label: str, *, payload: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise VerifyFailure(f"{label} lacks a path record")
    path = _abs(Path(value["path"]))
    if not path.is_file() or path.is_symlink():
        raise VerifyFailure(f"{label} is not a regular file: {path}")
    actual = _stat(path)
    expected = _record_stat(value)
    for key, val in expected.items():
        if actual[key] != val:
            raise VerifyFailure(f"{label} {key} differs from its bound stat")
    if _valid_sha(value.get("sha256")) and not payload:
        raw = path.read_bytes()
        if _sha(raw).lower() != str(value["sha256"]).lower():
            raise VerifyFailure(f"{label} SHA differs from its bound metadata")
    elif _valid_sha(value.get("sha256")) and payload:
        # Payload bytes are deliberately not opened in this verifier.  The
        # parent must establish this SHA after reservation and repeat it after
        # the child; current stat is still checked above.
        pass
    return {"path": str(path), "sha256": value.get("sha256"), "stat": actual}


def _assert_request(request: dict[str, Any], request_path: Path) -> dict[str, Any]:
    if request.get("schema") != SCHEMA or request.get("variant_schema") != VARIANT:
        raise VerifyFailure("request schema/variant is not F3-S1 external-v5")
    if request.get("status") != "READY_FOR_PARENT_GUARD":
        raise VerifyFailure(f"request status is not READY_FOR_PARENT_GUARD: {request.get('status')!r}")
    if (request.get("family_id"), request.get("sentinel_id")) != ("F3", "F3-S1"):
        raise VerifyFailure("request family/sentinel identity mismatch")
    if request.get("launch_allowed") is not True or request.get("production_eligible") is not True:
        raise VerifyFailure("request is not parent-launch eligible")
    if request.get("cfd_invoked") is not False or request.get("model_invoked") is not False:
        raise VerifyFailure("request claims a pre-build solver/model invocation")
    if request.get("qualification") != UNKNOWN:
        raise VerifyFailure("scientific qualification was promoted by the canary request")
    if request.get("gpu_uuid") not in (None, "PARENT_AFTER_INVENTORY"):
        raise VerifyFailure("canary request hardcodes a GPU UUID outside the parent lease")
    raw = _abs(request_path).read_bytes()
    raw_sha = _sha(raw)
    closure = request.get("runtime_binding")
    if not isinstance(closure, dict) or closure.get("argv0_literal") != str(VENV):
        raise VerifyFailure("runtime closure does not preserve literal venv argv0")
    if request.get("input_files") != sorted(request.get("input_files", [])):
        raise VerifyFailure("input_files is not sorted")
    input_files = request.get("input_files")
    input_sha = request.get("input_sha256")
    if not isinstance(input_files, list) or not isinstance(input_sha, dict) or not set(input_sha) <= set(input_files):
        raise VerifyFailure("input SHA closure is malformed")
    for path, value in input_sha.items():
        if not _valid_sha(value):
            raise VerifyFailure(f"input SHA is not concrete: {path}")
    deferred = request.get("deferred_input_records")
    if not isinstance(deferred, list) or not deferred:
        raise VerifyFailure("deferred parent payload records are missing")
    for item in deferred:
        if not isinstance(item, dict) or item.get("path") not in input_files:
            raise VerifyFailure("deferred record is not a declared input")
        if not _valid_sha(item.get("sha256")):
            raise VerifyFailure("deferred record has no concrete parent SHA")
        _check_path_record(item, f"deferred {item.get('path')}", payload=True)
    command = request.get("command")
    if not isinstance(command, list) or not command or command[0] != str(MATERIALIZER):
        raise VerifyFailure("request command does not invoke the F3-S1 materializer")
    if any(isinstance(arg, str) and arg.startswith("/usr/bin/python") for arg in command):
        raise VerifyFailure("request command substitutes system Python for the literal wrapper")
    observer = request.get("observer_producer")
    if not isinstance(observer, dict) or observer.get("status") != "WAITING_PARENT_SOLVER_TERMINAL_OBSERVER_BIND":
        raise VerifyFailure("native observer hand-off is missing or prematurely runnable")
    template = observer.get("command_template")
    if not isinstance(template, list) or not template or template[0] != str(VENV):
        raise VerifyFailure("observer command does not preserve literal venv argv0")
    if observer.get("native_mass_basis") != "native_header_only; XML mass fallback forbidden":
        raise VerifyFailure("observer mass contract permits an XML fallback")
    decoder = observer.get("decoder")
    if not isinstance(decoder, dict) or decoder.get("tool_role") != "project_native_adapter" or decoder.get("official_tool_claim") is not False:
        raise VerifyFailure("bi4_dump adapter/library distinction is missing")
    authority = observer.get("decoder_authority")
    if not isinstance(authority, dict) or authority.get("adapter_is_not_official_tool") is not True:
        raise VerifyFailure("JBinaryData authority is not explicitly separated from the adapter")
    resources = request.get("parent_resource_binding")
    if not isinstance(resources, dict) or int(resources.get("cpu_seconds", 0)) <= 0 or int(resources.get("gpu_seconds", 0)) <= 0:
        raise VerifyFailure("parent CPU/GPU resource reservation is missing")
    if int(resources.get("max_memory_bytes", 0)) < 4 * 1024**3:
        raise VerifyFailure("parent memory reservation is too small for the canary")
    if not bool(resources.get("cancellation")):
        raise VerifyFailure("parent cancellation/fee-close protocol is missing")
    return {"request_raw_sha256": raw_sha, "request_path": str(_abs(request_path)),
            "deferred_count": len(deferred), "observer_status": observer["status"]}


def verify_request(request_path: Path) -> dict[str, Any]:
    request, record, _ = _read_json(request_path, "F3-S1 canary request")
    result = _assert_request(request, request_path)
    result["request_record"] = record
    return result


def verify_terminal(request_path: Path, receipt_path: Path) -> dict[str, Any]:
    request, _, request_raw = _read_json(request_path, "F3-S1 canary request")
    base = _assert_request(request, request_path)
    receipt, receipt_record, _ = _read_json(receipt_path, "F3-S1 external-v5 receipt")
    status = str(receipt.get("status") or receipt.get("state") or "").upper()
    if "COMPLETED" not in status and "SUCCESS" not in status:
        raise VerifyFailure(f"external-v5 receipt is not terminal-completed: {status}")
    if "FAIL" in status:
        raise VerifyFailure("external-v5 receipt is a failed terminal")
    rc = receipt.get("returncode")
    if rc is None:
        rc = (receipt.get("execution") or {}).get("returncode")
    if rc != 0:
        raise VerifyFailure("external-v5 receipt returncode is not zero")
    req_sha = receipt.get("request_sha256")
    if not _valid_sha(req_sha) or req_sha.lower() != _sha(request_raw).lower():
        raise VerifyFailure("external-v5 receipt does not bind the request file bytes")
    if isinstance(receipt.get("request"), dict) and receipt["request"] != request:
        raise VerifyFailure("external-v5 receipt.request is not the exact request document")
    if receipt.get("family_id") not in (None, "F3") or receipt.get("sentinel_id") not in (None, "F3-S1"):
        raise VerifyFailure("external-v5 receipt family/sentinel mismatch")
    root = receipt.get("output_root") or (receipt.get("execution") or {}).get("output_root")
    if not isinstance(root, str):
        raise VerifyFailure("external-v5 receipt lacks output_root")
    if receipt.get("fee_status") not in (None, "CLOSED", "CLOSED_IDEMPOTENT", "COMPLETED"):
        raise VerifyFailure("external-v5 fee closure is not explicit")
    return {**base, "terminal_receipt": receipt_record, "terminal_status": status,
            "returncode": 0, "output_root": str(_abs(Path(root))),
            "scientific_qualification": dict(UNKNOWN), "credit": 0}


def verify_observer(request_path: Path, observer_path: Path, solver_receipt_sha: str | None = None) -> dict[str, Any]:
    request, _, _ = _read_json(request_path, "F3-S1 canary request")
    base = _assert_request(request, request_path)
    report, report_record, _ = _read_json(observer_path, "F3-S1 native observer summary")
    status = str(report.get("status", "")).upper()
    if "COMPLETED" not in status and "DIAGNOSTIC" not in status:
        raise VerifyFailure("observer summary is not terminal diagnostic output")
    if report.get("interpolation_used") is not False:
        raise VerifyFailure("observer summary does not prove no interpolation")
    if report.get("native_mass_basis") != "native_header_only; XML mass fallback forbidden":
        raise VerifyFailure("observer summary mass basis is not native-only")
    if report.get("qualification") != UNKNOWN:
        raise VerifyFailure("observer summary promoted scientific Q")
    if solver_receipt_sha is not None and report.get("source_solver_receipt_sha256") != solver_receipt_sha:
        raise VerifyFailure("observer summary source solver receipt does not join")
    return {**base, "observer_summary": report_record, "observer_status": status,
            "scientific_qualification": dict(UNKNOWN), "credit": 0}


def _fixture_chain() -> dict[str, Any]:
    """Run a real literal-venv producer -> observer -> verifier fixture."""
    with tempfile.TemporaryDirectory(prefix="f3-s1-canary-chain-") as td:
        root = Path(td)
        request_path = root / "request.json"
        deferred_payload = root / "deferred-input.bin"
        deferred_payload.write_bytes(b"manufactured-parent-payload")
        deferred_stat = _stat(deferred_payload)
        deferred_sha = _sha(deferred_payload.read_bytes())
        request = {
            "schema": SCHEMA, "variant_schema": VARIANT, "status": "READY_FOR_PARENT_GUARD",
            "family_id": "F3", "sentinel_id": "F3-S1", "case_id": "fixture-case",
            "attempt_id": "fixture-attempt", "launch_allowed": True, "production_eligible": True,
            "cfd_invoked": False, "model_invoked": False, "qualification": dict(UNKNOWN),
            "gpu_uuid": None, "input_files": [str(deferred_payload)],
            "input_sha256": {str(deferred_payload): deferred_sha},
            "deferred_input_records": [{"path": str(deferred_payload), "sha256": deferred_sha,
                                        "stat_before": deferred_stat, "stat_after": deferred_stat}],
            "runtime_binding": {"argv0_literal": str(VENV)},
            "command": [str(MATERIALIZER)],
            "observer_producer": {"status": "WAITING_PARENT_SOLVER_TERMINAL_OBSERVER_BIND",
                                  "command_template": [str(VENV)],
                                  "native_mass_basis": "native_header_only; XML mass fallback forbidden",
                                  "decoder": {"tool_role": "project_native_adapter", "official_tool_claim": False},
                                  "decoder_authority": {"adapter_is_not_official_tool": True}},
            "parent_resource_binding": {"cpu_seconds": 1, "gpu_seconds": 1,
                                        "max_memory_bytes": 4 * 1024**3, "cancellation": "fixture"},
            "manufactured_only": True,
        }
        producer = root / "producer.py"
        producer.write_text("""#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python\nimport hashlib,json,sys\nq=open(sys.argv[1],'rb').read(); qv=json.loads(q)\njson.dump({'schema':'ds02.execution-receipt.v1','status':'COMPLETED_DEVELOPMENT_UNKNOWN','returncode':0,'request_sha256':hashlib.sha256(q).hexdigest(),'request':qv,'family_id':'F3','sentinel_id':'F3-S1','output_root':sys.argv[3],'fee_status':'CLOSED'},open(sys.argv[2],'w'))\n""", encoding="utf-8")
        observer = root / "observer.py"
        observer.write_text("""#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python\nimport json,sys\njson.dump({'status':'COMPLETED_NATIVE_OBSERVER_DIAGNOSTIC','native_mass_basis':'native_header_only; XML mass fallback forbidden','interpolation_used':False,'qualification':{'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN'},'source_solver_receipt_sha256':sys.argv[2]},open(sys.argv[1],'w'))\n""", encoding="utf-8")
        for path in (producer, observer): path.chmod(0o755)
        request_path.write_text(json.dumps(request, sort_keys=True) + "\n", encoding="utf-8")
        receipt_path = root / "receipt.json"; output_root = root / "attempt"; output_root.mkdir()
        completed = subprocess.run([str(VENV), str(producer), str(request_path), str(receipt_path), str(output_root)], check=False)
        if completed.returncode != 0: raise AssertionError("fixture producer subprocess failed")
        req_result = verify_request(request_path)
        receipt, _, _ = _read_json(receipt_path, "fixture receipt")
        observer_path = root / "observer.json"
        subprocess.run([str(VENV), str(observer), str(observer_path), str(receipt["request_sha256"])], check=True)
        obs_result = verify_observer(request_path, observer_path, receipt["request_sha256"])
        # The negative path must reject an altered raw request SHA, not merely
        # a missing field.
        bad = json.loads(receipt_path.read_text()); bad["request_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(bad), encoding="utf-8")
        try:
            verify_terminal(request_path, receipt_path)
        except VerifyFailure:
            rejected = True
        else:
            rejected = False
        if not rejected: raise AssertionError("tampered fixture receipt was accepted")
        return {"status": "PASS_MANUFACTURED_LITERAL_VENV_CHAIN", "producer_rc": 0,
                "request": req_result, "observer": obs_result, "tamper_rejected": rejected,
                "production_credit": 0, "native_payload_read": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--verify-request", type=Path)
    modes.add_argument("--verify-terminal", nargs=2, metavar=("REQUEST", "RECEIPT"))
    modes.add_argument("--verify-observer", nargs=2, metavar=("REQUEST", "SUMMARY"))
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            print(json.dumps(_fixture_chain(), indent=2, sort_keys=True)); return 0
        if args.verify_request:
            print(json.dumps(verify_request(args.verify_request), indent=2, sort_keys=True)); return 0
        if args.verify_terminal:
            print(json.dumps(verify_terminal(Path(args.verify_terminal[0]), Path(args.verify_terminal[1])), indent=2, sort_keys=True)); return 0
        if args.verify_observer:
            print(json.dumps(verify_observer(Path(args.verify_observer[0]), Path(args.verify_observer[1])), indent=2, sort_keys=True)); return 0
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F3_S1_EXTERNAL_SOLVER_CANARY_VERIFY_V1: {exc}", file=sys.stderr); return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
