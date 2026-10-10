#!/usr/bin/env python3
"""Inject terminal evidence into a fresh source request without launching it.

ROOT279 and the three-sentinel GenCase products have different producers, but
the safe hand-off is the same: bind each proof to the exact producer request
file bytes, receipt bytes, and (when present) compact report bytes.  This
additive utility creates a new source request carrying those joins.  It keeps
``execution_allowed=false`` and ``launch_disabled=true``; root must perform a
separate runtime-v8 normalization, GPU/resource admission, and fee-owning
launch.  No native/VTK/BI4/Part payload is opened.

The utility is intentionally generic so ROOT310 plus ROOT277/278 and a later
ROOT345 product map can be injected into one fresh ROOT279 hand-off without
changing the consumed ROOT279 source package or any historical receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


JSON_CAP = 10 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
SCHEMA = "ds02.stage2.actual-receipt-injection.v1"
REQUEST_SCHEMA = "ds02.request.v1"


class InjectionFailure(RuntimeError):
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


def _valid(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise InjectionFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise InjectionFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes(); after = _stat(path)
    if before != after:
        raise InjectionFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InjectionFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise InjectionFailure(f"{label} must be an object")
    return value, {"path": str(path), "sha256": _sha(raw), "bytes": len(raw),
                   "stat_before": before, "stat_after": after}, raw


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise InjectionFailure(f"refusing to overwrite fresh request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _terminal_status(value: Any) -> bool:
    text = str(value or "").upper()
    return ("VERIFIED_ACTUAL" in text or "COMPLETED" in text or "SUCCESS" in text) and "FAIL" not in text


def _proof(path: Path, label: str) -> dict[str, Any]:
    proof, proof_record, _ = _json(path, label)
    if not _terminal_status(proof.get("status")):
        raise InjectionFailure(f"{label} is not a terminal verified proof: {proof.get('status')!r}")
    request_path_text = proof.get("request") or proof.get("request_path")
    request_sha = proof.get("request_sha256")
    if not isinstance(request_path_text, str) or not _valid(request_sha):
        raise InjectionFailure(f"{label} lacks request path/SHA join")
    request, request_record, request_raw = _json(Path(request_path_text), f"{label} producer request")
    if request_record["sha256"].lower() != str(request_sha).lower():
        raise InjectionFailure(f"{label} request SHA is not the raw file-byte SHA")
    receipt_record = None
    receipt_path_text = proof.get("receipt") or proof.get("receipt_path")
    if isinstance(receipt_path_text, str):
        receipt, receipt_record, _ = _json(Path(receipt_path_text), f"{label} execution receipt")
        status = str(receipt.get("status") or receipt.get("state") or "").upper()
        if "COMPLETED" not in status and "SUCCESS" not in status:
            raise InjectionFailure(f"{label} receipt is not terminal-completed")
        returncode = receipt.get("returncode")
        if returncode is None:
            returncode = (receipt.get("execution") or {}).get("returncode")
        if returncode != 0:
            raise InjectionFailure(f"{label} receipt returncode is not zero")
        got = receipt.get("request_sha256") or (receipt.get("request") or {}).get("request_sha256")
        if _valid(got) and got.lower() != request_record["sha256"].lower():
            raise InjectionFailure(f"{label} receipt request SHA does not join its producer file")
        declared_receipt_sha = proof.get("receipt_sha256")
        if declared_receipt_sha is not None and (not _valid(declared_receipt_sha) or declared_receipt_sha.lower() != receipt_record["sha256"].lower()):
            raise InjectionFailure(f"{label} proof receipt SHA differs from receipt bytes")
    report_record = None
    report_path_text = proof.get("report") or proof.get("report_path")
    if isinstance(report_path_text, str):
        _, report_record, _ = _json(Path(report_path_text), f"{label} compact report")
        declared = proof.get("report_sha256")
        if declared is not None and (not _valid(declared) or declared.lower() != report_record["sha256"].lower()):
            raise InjectionFailure(f"{label} proof report SHA differs from report bytes")
    return {"label": label, "proof": proof_record, "proof_status": proof.get("status"),
            "request": request_record, "request_sha256": request_record["sha256"],
            "receipt": receipt_record, "report": report_record,
            "producer_request_identity": {"path": request_record["path"], "raw_sha256": request_record["sha256"]},
            "payload_read": False}


def _product_map(path: Path) -> dict[str, Any]:
    value, record, _ = _json(path, "ROOT345 actual product map")
    if not str(value.get("schema", "")).startswith("ds02.stage2.three-sentinel.owner-grid-gencase-product-map"):
        raise InjectionFailure("ROOT345 product map schema mismatch")
    if not _terminal_status(value.get("status")):
        raise InjectionFailure("ROOT345 product map is not terminal-completed")
    rows = value.get("products", value.get("cases"))
    if not isinstance(rows, list) or not rows:
        raise InjectionFailure("ROOT345 product map has no product rows")
    terminal_rows = [row for row in rows if isinstance(row, dict) and _terminal_status(row.get("status"))]
    if len(terminal_rows) != len(rows):
        raise InjectionFailure("ROOT345 product map contains nonterminal rows")
    return {"record": record, "status": value.get("status"), "row_count": len(rows),
            "schema": value.get("schema"), "payload_read": False}


def inject(source_request: Path, output: Path, proofs: list[tuple[str, Path]],
           product_map: Path | None = None, support_reports: list[Path] | None = None) -> dict[str, Any]:
    source, source_record, _ = _json(source_request, "source request")
    if source.get("schema") != REQUEST_SCHEMA:
        raise InjectionFailure("source request must use ds02.request.v1")
    if source.get("execution_allowed") is not False or source.get("launch_disabled") is False:
        raise InjectionFailure("source request is already executable; use a fresh source-only input")
    bindings = [_proof(path, label) for label, path in proofs]
    if not bindings:
        raise InjectionFailure("at least one terminal proof binding is required")
    map_binding = _product_map(product_map) if product_map else None
    supports = []
    for index, path in enumerate(support_reports or []):
        report, record, _ = _json(path, f"initial-QA report {index + 1}")
        if not _terminal_status(report.get("status")):
            raise InjectionFailure(f"initial-QA report {path} is not terminal")
        if report.get("scientific_qualification", {}).get("QI") not in (None, "UNKNOWN"):
            raise InjectionFailure("initial-QA report promotes QI unexpectedly")
        supports.append({"record": record, "status": report.get("status"), "scientific_credit": 0})
    fresh = json.loads(json.dumps(source))
    fresh["schema"] = REQUEST_SCHEMA
    fresh["status"] = "WAITING_PARENT_ROOT_NORMALIZATION_ACTUAL_RECEIPTS_BOUND"
    fresh["execution_allowed"] = False
    fresh["launch_disabled"] = True
    fresh["production_eligible"] = False
    fresh["actual_receipts_injected"] = True
    fresh["root_canonical_binding"] = {
        "source_request": source_record,
        "source_request_sha256_basis": "RAW_REQUEST_FILE_BYTES",
        "terminal_proofs": bindings,
        "root345_product_map": map_binding,
        "initial_support_reports": supports,
        "consumer_must_rebind_actual_root_forward_request": True,
        "consumer_must_not_select_latest_by_basename": True,
    }
    fresh["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
    fresh["source_only_transition"] = {
        "old_execution_allowed": False, "new_execution_allowed": False,
        "parent_runtime_required": True, "payload_read_by_injector": False,
        "gpu_lease_owned_by_root": True, "fee_close_owned_by_root": True,
    }
    _write_once(output, fresh)
    output_sha = _sha(_abs(output).read_bytes())
    return {"status": "PASS_ACTUAL_RECEIPTS_BOUND_SOURCE_REQUEST", "output": str(_abs(output)),
            "output_raw_sha256": output_sha, "terminal_proof_count": len(bindings),
            "product_map_bound": map_binding is not None, "support_report_count": len(supports),
            "execution_allowed": False, "production_launch": False, "scientific_credit": 0}


def verify(path: Path) -> dict[str, Any]:
    value, record, _ = _json(path, "fresh injected request")
    if value.get("schema") != REQUEST_SCHEMA or value.get("execution_allowed") is not False or value.get("launch_disabled") is not True:
        raise InjectionFailure("fresh request is not source-only")
    binding = value.get("root_canonical_binding")
    if not isinstance(binding, dict):
        raise InjectionFailure("fresh request lacks root_canonical_binding")
    source = binding.get("source_request")
    if not isinstance(source, dict):
        raise InjectionFailure("fresh request lacks source request record")
    source_path = _abs(Path(str(source.get("path", ""))))
    source_value, source_record, _ = _json(source_path, "bound source request")
    if source_record["sha256"] != source.get("sha256"):
        raise InjectionFailure("source request record SHA changed")
    if source_value.get("execution_allowed") is not False:
        raise InjectionFailure("bound source request is not source-only")
    proofs = binding.get("terminal_proofs")
    if not isinstance(proofs, list) or not proofs:
        raise InjectionFailure("fresh request has no terminal proof bindings")
    for item in proofs:
        request = item.get("request") if isinstance(item, dict) else None
        if not isinstance(request, dict) or request.get("sha256") != item.get("request_sha256"):
            raise InjectionFailure("terminal proof/request raw SHA closure is incomplete")
    return {"status": "PASS_SOURCE_INJECTION_CLOSED", "request": record,
            "terminal_proof_count": len(proofs), "execution_allowed": False,
            "scientific_credit": 0}


def _self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="actual-receipt-injection-") as td:
        root = Path(td)
        producer_request = root / "producer-request.json"
        producer_request.write_text(json.dumps({"schema": REQUEST_SCHEMA, "execution_allowed": True, "case_id": "tiny"}, sort_keys=True) + "\n", encoding="utf-8")
        q_raw = producer_request.read_bytes(); q_sha = _sha(q_raw)
        receipt = root / "receipt.json"
        receipt.write_text(json.dumps({"schema": "ds02.execution-receipt.v1", "status": "COMPLETED", "returncode": 0, "request_sha256": q_sha}) + "\n", encoding="utf-8")
        proof = root / "proof.json"
        proof.write_text(json.dumps({"status": "VERIFIED_ACTUAL_TINY", "request": str(producer_request),
                                     "request_sha256": q_sha, "receipt": str(receipt),
                                     "receipt_sha256": _sha(receipt.read_bytes())}) + "\n", encoding="utf-8")
        source = root / "source.json"
        source.write_text(json.dumps({"schema": REQUEST_SCHEMA, "execution_allowed": False,
                                      "launch_disabled": True, "input_files": []}) + "\n", encoding="utf-8")
        out = root / "fresh.json"
        result = inject(source, out, [("tiny", proof)])
        checked = verify(out)
        tampered = json.loads(out.read_text()); tampered["root_canonical_binding"]["terminal_proofs"][0]["request"]["sha256"] = "0" * 64
        out.write_text(json.dumps(tampered), encoding="utf-8")
        try: verify(out)
        except InjectionFailure: rejected = True
        else: rejected = False
        if not rejected: raise AssertionError("tampered receipt injection accepted")
        return {"status": "PASS_MANUFACTURED_RECEIPT_INJECTION", "result": result,
                "checked": checked, "tamper_rejected": rejected, "production_credit": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--inject", action="store_true")
    modes.add_argument("--verify", type=Path)
    parser.add_argument("--source-request", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--proof", action="append", default=[], metavar="LABEL=PATH")
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--support-report", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            print(json.dumps(_self_test(), indent=2, sort_keys=True)); return 0
        if args.verify:
            print(json.dumps(verify(args.verify), indent=2, sort_keys=True)); return 0
        if args.source_request is None or args.output is None:
            parser.error("--inject requires --source-request and --output")
        pairs = []
        for value in args.proof:
            if "=" not in value: parser.error("--proof must be LABEL=PATH")
            label, path = value.split("=", 1); pairs.append((label, Path(path)))
        print(json.dumps(inject(args.source_request, args.output, pairs, args.product_map,
                                [Path(x) for x in args.support_report]), indent=2, sort_keys=True)); return 0
    except (InjectionFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ACTUAL_RECEIPT_INJECTION_V1: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
