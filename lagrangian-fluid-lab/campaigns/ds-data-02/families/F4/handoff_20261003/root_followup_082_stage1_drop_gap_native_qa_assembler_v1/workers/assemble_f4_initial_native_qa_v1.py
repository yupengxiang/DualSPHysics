#!/usr/bin/env python3
"""Bind Root195 genuine GenCase evidence to the Root196 native QA index.

This is a strict metadata binder.  It does not launch GenCase, copy/rewrite
BI4, decode native arrays, or modify any historical Root195 receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

SCHEMA = "ds02.f4.internal8.initial-native-qa-assembler.v1"
EXPECTED_UPSTREAM_COMMIT = "ae0d8a25"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_once(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{__import__('os').getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_validator(path: Path):
    spec = importlib.util.spec_from_file_location("f4_fresh082_validator", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def failure_payload(args: argparse.Namespace, error: Exception) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "family_id": "F4",
        "scope_id": "root_followup_081_stage1_drop_gap_internal8_source_v1",
        "qa_attempt_id": "root-stage1-f4-internal8-native-initial-qa-196",
        "status": "blocked_evidence_or_contract_failure",
        "error_type": type(error).__name__,
        "error": str(error),
        "gencase_parent_execution_receipt": str(args.gencase_execution_receipt),
        "gencase_aggregate_report": str(args.gencase_report),
        "native_qa_index": str(args.native_qa_index),
        "arrays_read_by_binder": False,
        "bi4_read_by_binder": False,
        "historical_receipts_unchanged": True,
        "production_approval": "none",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-binding", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--source-build-receipt", required=True, type=Path)
    parser.add_argument("--owner-root", required=True, type=Path)
    parser.add_argument("--metadata-root", required=True, type=Path)
    parser.add_argument("--gencase-report", required=True, type=Path)
    parser.add_argument("--gencase-execution-receipt", required=True, type=Path)
    parser.add_argument("--gencase-root", required=True, type=Path)
    parser.add_argument("--native-qa-index", required=True, type=Path)
    parser.add_argument("--validator", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        binding = load_json(args.source_binding)
        if binding.get("upstream_adopted_commit") != EXPECTED_UPSTREAM_COMMIT:
            raise ValueError("fresh081 adopted commit binding changed")
        if binding.get("source_plan") != str(args.plan):
            raise ValueError("source binding plan path differs")
        if binding.get("source_plan_sha256") != sha256(args.plan):
            raise ValueError("source plan hash differs from fresh081 binding")
        if binding.get("source_build_receipt") != str(args.source_build_receipt):
            raise ValueError("source binding receipt path differs")
        if binding.get("source_build_receipt_sha256") != sha256(args.source_build_receipt):
            raise ValueError("source build receipt hash differs from fresh081 binding")
        validator = load_validator(args.validator)
        result = validator.validate(
            plan_path=args.plan,
            source_receipt_path=args.source_build_receipt,
            gencase_report_path=args.gencase_report,
            gencase_execution_receipt_path=args.gencase_execution_receipt,
            gencase_root=args.gencase_root,
            native_qa_index_path=args.native_qa_index,
            owner_root=args.owner_root,
            metadata_root=args.metadata_root,
        )
        result["assembler_schema"] = SCHEMA
        result["assembler_path"] = str(Path(__file__).resolve())
        result["assembler_sha256"] = sha256(Path(__file__).resolve())
        result["validator_path"] = str(args.validator)
        result["validator_sha256"] = sha256(args.validator)
        result["source_binding"] = str(args.source_binding)
        result["source_binding_sha256"] = sha256(args.source_binding)
        result["source_build_receipt"] = str(args.source_build_receipt)
        result["source_build_receipt_sha256"] = sha256(args.source_build_receipt)
        write_once(args.output, result)
        print(json.dumps({"status": result["status"], "scope_id": result["scope_id"], "case_count": len(result["cases"])}, sort_keys=True))
        return 0
    except Exception as error:
        payload = failure_payload(args, error)
        try:
            write_once(args.output, payload)
        except FileExistsError:
            pass
        print(json.dumps(payload, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
