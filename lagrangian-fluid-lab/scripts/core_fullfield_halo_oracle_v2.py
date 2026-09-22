#!/usr/bin/env python3
"""Build and verify the refreshed CPU full-field/halo diagnostic bundle.

This is a read-only evidence wrapper around the existing tiny CPU witness.  It
does not train, submit a job, start a solver, use a GPU, or write the Core
registry/ledger.  The v2 bundle separates the three implementation hashes
that matter for the current witness into an explicit source-closure artifact;
the old v1 receipt remains historical evidence and is never overwritten.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_fullfield_halo_oracle import (  # noqa: E402
    SCHEMA_V2,
    _reference,
    run_diagnostic,
    sha256_file,
    verify_receipt,
    write_json,
    write_sha256,
)


RECORD_ID = "core-fullfield-halo-oracle-diagnostic-20260922-v2"
CLOSURE_SCHEMA = "core.fullfield_halo_oracle_source_closure.v1"
CLOSURE_VERSION = "core-fullfield-halo-oracle-source-closure-20260922-v2"
CORE_SOURCE_RELS = (
    "scripts/core_learning.py",
    "scripts/core_models.py",
    "scripts/core_contract.py",
)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def build_source_closure(*, data_root: str | Path) -> dict[str, Any]:
    root = Path(data_root).expanduser().resolve()
    bindings = [_reference(root / relative, root) for relative in CORE_SOURCE_RELS]
    return {
        "schema": CLOSURE_SCHEMA,
        "closure_version": CLOSURE_VERSION,
        "purpose": "Bind the current core_learning/core_models/core_contract implementation used by the v2 live CPU witness.",
        "source_snapshot_policy": "live_cpu_witness_at_refresh",
        "source_bindings": bindings,
        "execution_boundary": {
            "diagnostic_only": True,
            "formal_training": False,
            "registry_written": False,
            "ledger_written": False,
            "solver_started": False,
            "gpu_started": False,
        },
    }


def build_v2_bundle(
    *,
    data_root: str | Path,
    receipt_path: str | Path,
    closure_path: str | Path,
    receipt_sha256_path: str | Path | None = None,
    closure_sha256_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the existing CPU witness and write a fresh v2 receipt/closure."""
    root = Path(data_root).expanduser().resolve()
    receipt = Path(receipt_path).expanduser().resolve()
    closure = Path(closure_path).expanduser().resolve()
    closure_payload = build_source_closure(data_root=root)
    write_json(closure, closure_payload)
    if closure_sha256_path is not None:
        write_sha256(closure_sha256_path, source=closure)

    report = run_diagnostic(data_root=root)
    report["schema"] = SCHEMA_V2
    report["record_id"] = RECORD_ID
    report["source_closure"] = {
        "schema": CLOSURE_SCHEMA,
        "closure_version": CLOSURE_VERSION,
        "path": _relative(closure, root),
        "sha256": sha256_file(closure),
        "source_bindings": closure_payload["source_bindings"],
    }
    report["refresh"] = {
        "kind": "live_cpu_witness_refresh",
        "formal_training": False,
        "registry_written": False,
        "ledger_written": False,
        "gpu_started": False,
        "solver_started": False,
    }
    write_json(receipt, report)
    if receipt_sha256_path is not None:
        write_sha256(receipt_sha256_path, source=receipt)
    return report


def _closure_mismatches(
    payload: Mapping[str, Any], *, data_root: Path, closure_path: Path
) -> tuple[list[str], dict[str, bool]]:
    mismatches: list[str] = []
    closure_ref = payload.get("source_closure")
    if not isinstance(closure_ref, Mapping):
        return ["source_closure"], {"closure_present": False}
    if closure_ref.get("path") != _relative(closure_path, data_root):
        mismatches.append("source_closure.path")
    observed_closure_hash = sha256_file(closure_path) if closure_path.is_file() else None
    if observed_closure_hash != closure_ref.get("sha256"):
        mismatches.append("source_closure.sha256")
    try:
        closure = json.loads(closure_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return mismatches + ["source_closure.content"], {
            "closure_present": False,
            "closure_hash_matches": observed_closure_hash == closure_ref.get("sha256"),
        }
    if closure.get("schema") != CLOSURE_SCHEMA:
        mismatches.append("source_closure.schema")
    if closure.get("closure_version") != CLOSURE_VERSION:
        mismatches.append("source_closure.closure_version")
    bindings = closure.get("source_bindings")
    if not isinstance(bindings, list) or len(bindings) != len(CORE_SOURCE_RELS):
        mismatches.append("source_closure.source_bindings")
        bindings = []
    expected_paths = list(CORE_SOURCE_RELS)
    observed_paths = [item.get("path") for item in bindings if isinstance(item, Mapping)]
    if observed_paths != expected_paths:
        mismatches.append("source_closure.source_paths")
    for binding in bindings:
        if not isinstance(binding, Mapping):
            mismatches.append("source_closure.<invalid-binding>")
            continue
        path_value = binding.get("path")
        if not isinstance(path_value, str):
            mismatches.append("source_closure.<missing-path>")
            continue
        path = (data_root / path_value).resolve()
        observed = sha256_file(path) if path.is_file() else None
        if observed != binding.get("sha256"):
            mismatches.append(path_value)
    if closure_ref.get("source_bindings") != bindings:
        mismatches.append("source_closure.receipt_bindings")
    return mismatches, {
        "closure_present": True,
        "closure_hash_matches": observed_closure_hash == closure_ref.get("sha256"),
        "closure_schema": closure.get("schema") == CLOSURE_SCHEMA,
        "closure_version": closure.get("closure_version") == CLOSURE_VERSION,
        "closure_source_hashes_match": not any(
            item in mismatches for item in expected_paths
        ),
        "receipt_bindings_match": closure_ref.get("source_bindings") == bindings,
    }


def verify_v2_receipt(
    receipt_path: str | Path, *, data_root: str | Path, closure_path: str | Path | None = None
) -> dict[str, Any]:
    root = Path(data_root).expanduser().resolve()
    receipt = Path(receipt_path).expanduser().resolve()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    closure_ref = payload.get("source_closure", {})
    default_closure = root / closure_ref.get("path", "") if isinstance(closure_ref, Mapping) else root
    closure = Path(closure_path).expanduser().resolve() if closure_path else default_closure.resolve()
    base = verify_receipt(payload, data_root=root)
    closure_mismatches, closure_checks = _closure_mismatches(
        payload, data_root=root, closure_path=closure
    )
    flags = {
        "diagnostic_only": payload.get("diagnostic_only") is True,
        "formal_training": payload.get("formal_training") is False,
        "registry_written": payload.get("execution_constraints", {}).get("registry_written") is False,
        "ledger_written": payload.get("execution_constraints", {}).get("ledger_written") is False,
        "gpu_started": payload.get("execution_constraints", {}).get("gpu_started") is False,
        "solver_started": payload.get("execution_constraints", {}).get("solver_started") is False,
    }
    checks = {
        "base_receipt": base["ok"],
        "schema_v2": payload.get("schema") == SCHEMA_V2,
        "record_id": payload.get("record_id") == RECORD_ID,
        "all_diagnostic_checks_pass": all(payload.get("checks", {}).values()),
        **flags,
        **closure_checks,
    }
    return {
        "ok": all(checks.values()) and not closure_mismatches,
        "checks": checks,
        "mismatch_paths": base["mismatch_paths"] + closure_mismatches,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--closure", type=Path, required=True)
    parser.add_argument("--receipt-sha256", type=Path)
    parser.add_argument("--closure-sha256", type=Path)
    parser.add_argument("--verify", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.verify:
        result = verify_v2_receipt(args.receipt, data_root=args.data_root, closure_path=args.closure)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1
    report = build_v2_bundle(
        data_root=args.data_root,
        receipt_path=args.receipt,
        closure_path=args.closure,
        receipt_sha256_path=args.receipt_sha256,
        closure_sha256_path=args.closure_sha256,
    )
    print(json.dumps({"status": report["status"], "record_id": report["record_id"]}, sort_keys=True))
    return 0 if report["status"] == "diagnostic_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
