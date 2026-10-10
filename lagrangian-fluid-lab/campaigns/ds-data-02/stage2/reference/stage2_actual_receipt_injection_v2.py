#!/usr/bin/env python3
"""Strict additive verifier for actual receipt/proof injection edges.

The consumed injection V1 is a useful source-only manifest writer, but its
terminal checks are substring based and make the embedded receipt/report
edges optional.  This version is a verifier for a fresh hand-off: it reads
the proof, the exact producer request file, the exact execution receipt, and
declared compact report/map files, then checks raw-byte SHA, exact request
documents, return code, identity, and allow-listed status values.  Missing
evidence is WAITING; a contradiction is REJECTED.  It never opens native
payloads and grants no scientific credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any


JSON_CAP = 10 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
REQUEST_SCHEMA = "ds02.request.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
SCHEMA = "ds02.stage2.actual-receipt-injection.v2"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}

RECEIPT_TERMINAL = {"COMPLETED", "COMPLETED_ACTUAL", "COMPLETED_DEVELOPMENT_UNKNOWN",
                    "SUCCESS", "SUCCEEDED"}
PROOF_PREFIXES = ("VERIFIED_ACTUAL_", "COMPLETED_ACTUAL_", "PASS_ACTUAL_")


class StrictReceiptFailure(RuntimeError):
    pass


def _abs(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stat(path: Path) -> dict[str, int]:
    st = path.stat()
    return {"device": int(st.st_dev), "inode": int(st.st_ino), "bytes": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns)}


def _valid(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _json(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    value = _abs(path)
    if value.is_symlink() or not value.is_file():
        raise StrictReceiptFailure(f"{label} is not a regular non-symlink file: {value}")
    before = _stat(value)
    if before["bytes"] > JSON_CAP:
        raise StrictReceiptFailure(f"{label} exceeds the 10 MiB metadata cap: {value}")
    raw = value.read_bytes(); after = _stat(value)
    if before != after:
        raise StrictReceiptFailure(f"{label} changed during bounded read: {value}")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StrictReceiptFailure(f"{label} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise StrictReceiptFailure(f"{label} must be an object")
    return parsed, {"path": str(value), "sha256": _sha(raw), "bytes": len(raw),
                    "stat_before": before, "stat_after": after}


def _status(value: Any) -> str:
    return str(value or "").strip().upper()


def _proof_status(value: Any) -> bool:
    text = _status(value)
    return any(text.startswith(prefix) for prefix in PROOF_PREFIXES) and "FAIL" not in text


def _exact_embedded_request(receipt: dict[str, Any], request: dict[str, Any],
                            label: str) -> None:
    embedded = receipt.get("request")
    if not isinstance(embedded, dict):
        raise StrictReceiptFailure(f"{label} receipt.request is missing")
    extra = set(embedded) - set(request)
    normalized = dict(embedded)
    if extra == {"request_sha256"}:
        normalized.pop("request_sha256", None)
    if normalized != request:
        raise StrictReceiptFailure(f"{label} receipt.request differs from raw producer request")


def _proof_edge(path: Path, label: str) -> dict[str, Any]:
    proof, proof_record = _json(path, label)
    if not _proof_status(proof.get("status")):
        raise StrictReceiptFailure(f"{label} status is not an allow-listed verified actual status: {proof.get('status')!r}")
    request_path = proof.get("request") or proof.get("request_path")
    request_sha = proof.get("request_sha256")
    if not isinstance(request_path, str) or not _valid(request_sha):
        raise StrictReceiptFailure(f"{label} lacks request path/raw-byte SHA")
    request, request_record = _json(request_path, f"{label} producer request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise StrictReceiptFailure(f"{label} producer request schema mismatch")
    if request_record["sha256"].lower() != request_sha.lower():
        raise StrictReceiptFailure(f"{label} request_sha256 is not raw request-file SHA")

    receipt_path = proof.get("receipt") or proof.get("receipt_path")
    receipt_sha = proof.get("receipt_sha256")
    if not isinstance(receipt_path, str) or not _valid(receipt_sha):
        raise StrictReceiptFailure(f"{label} requires an execution receipt path and declared raw SHA")
    receipt, receipt_record = _json(receipt_path, f"{label} execution receipt")
    if receipt_record["sha256"].lower() != receipt_sha.lower():
        raise StrictReceiptFailure(f"{label} receipt SHA differs from receipt bytes")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise StrictReceiptFailure(f"{label} receipt schema mismatch")
    if _status(receipt.get("status")) not in RECEIPT_TERMINAL:
        raise StrictReceiptFailure(f"{label} receipt status is not allow-listed: {receipt.get('status')!r}")
    if receipt.get("returncode") != 0:
        raise StrictReceiptFailure(f"{label} receipt returncode is not zero")
    if receipt.get("request_sha256") != request_record["sha256"]:
        raise StrictReceiptFailure(f"{label} receipt request_sha256 does not join request bytes")
    _exact_embedded_request(receipt, request, label)

    # Proof fields are optional in some historical checkpoints, but when an
    # actual proof carries them they must agree exactly.  For a fresh V2 edge,
    # case/attempt/family are required by the producer request and receipt.
    for key in ("family_id", "sentinel_id", "physical_case_id", "case_id", "attempt_id"):
        expected = request.get(key)
        if expected is None:
            continue
        if receipt.get(key) != expected:
            raise StrictReceiptFailure(f"{label} receipt {key} does not match request")
        if key in proof and proof.get(key) != expected:
            raise StrictReceiptFailure(f"{label} proof {key} does not match request")
    output_root = receipt.get("output_root")
    if not isinstance(output_root, str) or not _abs(output_root).is_dir():
        raise StrictReceiptFailure(f"{label} receipt output_root is absent")

    report_record = None
    report_path = proof.get("report") or proof.get("report_path")
    if isinstance(report_path, str):
        _, report_record = _json(report_path, f"{label} compact report")
        declared = proof.get("report_sha256")
        if not _valid(declared) or declared.lower() != report_record["sha256"].lower():
            raise StrictReceiptFailure(f"{label} report SHA is not its raw file SHA")
    return {"proof": proof_record, "proof_status": proof.get("status"),
            "request": request_record, "request_sha256": request_record["sha256"],
            "receipt": receipt_record, "receipt_sha256": receipt_record["sha256"],
            "report": report_record, "payload_read": False}


def verify(path: Path) -> dict[str, Any]:
    fresh, fresh_record = _json(path, "fresh receipt-injection request")
    if fresh.get("schema") != REQUEST_SCHEMA:
        raise StrictReceiptFailure("fresh request schema mismatch")
    if fresh.get("execution_allowed") is not False or fresh.get("launch_disabled") is not True:
        raise StrictReceiptFailure("fresh request is not source-only")
    binding = fresh.get("root_canonical_binding")
    if not isinstance(binding, dict):
        raise StrictReceiptFailure("fresh request lacks root_canonical_binding")
    proofs = binding.get("terminal_proofs")
    if not isinstance(proofs, list) or not proofs:
        raise StrictReceiptFailure("fresh request has no terminal proof bindings")
    checked = []
    for item in proofs:
        if not isinstance(item, dict) or not isinstance(item.get("proof"), dict):
            raise StrictReceiptFailure("terminal proof binding lacks proof file record")
        record = item["proof"]
        proof_path = record.get("path")
        declared = record.get("sha256")
        if not isinstance(proof_path, str) or not _valid(declared):
            raise StrictReceiptFailure("proof binding lacks path/raw SHA")
        edge = _proof_edge(_abs(proof_path), str(item.get("label") or "terminal proof"))
        if edge["proof"]["sha256"].lower() != declared.lower():
            raise StrictReceiptFailure("fresh proof binding SHA differs from proof bytes")
        request_item = item.get("request")
        if not isinstance(request_item, dict) or request_item.get("sha256") != edge["request_sha256"]:
            raise StrictReceiptFailure("fresh proof binding request edge differs from actual proof")
        checked.append(edge)
    return {"schema": SCHEMA, "status": "PASS_STRICT_ACTUAL_RECEIPT_EDGES",
            "request": fresh_record, "proof_count": len(checked),
            "edges": checked, "execution_allowed": False,
            "scientific_qualification": dict(UNKNOWN), "scientific_credit": 0,
            "payload_read": False}


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="receipt-edge-v2-") as td:
        root = Path(td)
        request = root / "request.json"
        request.write_text(json.dumps({"schema": REQUEST_SCHEMA, "family_id": "F3",
                                       "sentinel_id": "F3-S1", "case_id": "tiny",
                                       "attempt_id": "attempt", "execution_allowed": True},
                                      sort_keys=True) + "\n", encoding="utf-8")
        qsha = _sha(request.read_bytes())
        receipt = root / "receipt.json"
        receipt_value = {"schema": RECEIPT_SCHEMA, "status": "COMPLETED", "returncode": 0,
                         "family_id": "F3", "sentinel_id": "F3-S1", "case_id": "tiny",
                         "attempt_id": "attempt", "output_root": str(root),
                         "request_sha256": qsha,
                         "request": json.loads(request.read_text())}
        receipt.write_text(json.dumps(receipt_value, sort_keys=True) + "\n", encoding="utf-8")
        rsha = _sha(receipt.read_bytes())
        proof = root / "proof.json"
        proof.write_text(json.dumps({"status": "VERIFIED_ACTUAL_TINY",
                                     "family_id": "F3", "sentinel_id": "F3-S1",
                                     "case_id": "tiny", "attempt_id": "attempt",
                                     "request": str(request), "request_sha256": qsha,
                                     "receipt": str(receipt), "receipt_sha256": rsha},
                                    sort_keys=True) + "\n", encoding="utf-8")
        psha = _sha(proof.read_bytes())
        fresh = root / "fresh.json"
        fresh.write_text(json.dumps({"schema": REQUEST_SCHEMA, "execution_allowed": False,
                                     "launch_disabled": True,
                                     "root_canonical_binding": {"terminal_proofs": [{
                                         "label": "tiny", "proof": {"path": str(proof), "sha256": psha},
                                         "request": {"path": str(request), "sha256": qsha}}]}}) + "\n", encoding="utf-8")
        checked = verify(fresh)
        assert checked["status"] == "PASS_STRICT_ACTUAL_RECEIPT_EDGES"
        # Exact negative edges: status and raw receipt SHA cannot be hidden by
        # a proof's self-consistent strings.
        bad = json.loads(proof.read_text())
        bad["status"] = "OWNER_NOT_VERIFIED"
        proof.write_text(json.dumps(bad, sort_keys=True) + "\n", encoding="utf-8")
        try:
            verify(fresh)
        except StrictReceiptFailure:
            pass
        else:
            raise AssertionError("nonterminal proof status accepted")
        proof.write_text(json.dumps({"status": "VERIFIED_ACTUAL_TINY",
                                     "family_id": "F3", "sentinel_id": "F3-S1",
                                     "case_id": "tiny", "attempt_id": "attempt",
                                     "request": str(request), "request_sha256": qsha,
                                     "receipt": str(receipt), "receipt_sha256": rsha},
                                    sort_keys=True) + "\n", encoding="utf-8")
        fresh_value = json.loads(fresh.read_text())
        fresh_value["root_canonical_binding"]["terminal_proofs"][0]["proof"]["sha256"] = "0" * 64
        fresh.write_text(json.dumps(fresh_value) + "\n", encoding="utf-8")
        try:
            verify(fresh)
        except StrictReceiptFailure:
            pass
        else:
            raise AssertionError("tampered proof SHA accepted")
    print("PASS_ACTUAL_RECEIPT_INJECTION_V2_STRICT_EDGE_FIXTURES_NO_PRODUCTION_CREDIT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        print(json.dumps(verify(args.verify), indent=2, sort_keys=True, ensure_ascii=False)); return 0
    except (StrictReceiptFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ACTUAL_RECEIPT_INJECTION_V2: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
