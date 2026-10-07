#!/usr/bin/env python3
"""Prepare a source-bound raw-to-typed-to-label reconstruction attempt.

The lineage and scientific-scan products are evidence about an existing typed
trajectory.  They are not a raw converter receipt.  This entry point keeps
that distinction explicit: ``prepare`` validates the small source closure and
emits a fail-closed plan; it does not open HDF5, invoke CFD, train a model, or
claim labels.  A later parent-guarded worker may consume the plan only after a
real converter, identity/invalid-mask adapter, and label operator are bound.

The plan intentionally records the producer HDF5 SHA as an expected identity
without hashing that file.  A relocated full replay must prove the copied
bytes separately through the v20 overlay/parent guard.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA = "ds02.stage2.raw-to-typed-to-label-reconstruction.v1"
PLAN_SCHEMA = "ds02.stage2.raw-to-typed-to-label-reconstruction-plan.v1"
H5_SUFFIXES = {".h5", ".hdf5"}
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
SMALL_HASH_LIMIT = 16 * 1024 * 1024


class ReconstructionBindingError(ValueError):
    """Raised for a source identity or contract violation."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key not in {"sha256", "plan_sha256"}}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _load(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReconstructionBindingError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReconstructionBindingError(f"JSON object required: {path}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists():
        raise ReconstructionBindingError(f"refusing to overwrite existing destination: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
    except FileExistsError as error:
        raise ReconstructionBindingError(f"refusing to overwrite existing destination: {target}") from error


def _is_h5(path: str) -> bool:
    return Path(path).suffix.lower() in H5_SUFFIXES


def _mapping_records(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten declared path records without following arbitrary JSON paths."""
    records: list[dict[str, Any]] = []

    def add(item: Mapping[str, Any], inherited_role: str | None = None) -> None:
        path = item.get("path") or item.get("original_path")
        if not isinstance(path, str) or not path:
            return
        role = item.get("role") or inherited_role or "untyped_source"
        expected = item.get("sha256") or item.get("content_sha256") or item.get("expected_content_sha256")
        record: dict[str, Any] = {
            "role": str(role),
            "path": path,
            "declared_sha256": expected if isinstance(expected, str) else None,
            "bytes": item.get("bytes"),
            "hash_mode": item.get("hash_mode"),
        }
        records.append(record)

    for key in ("input_files", "source_files"):
        value = request.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    add(item)
    bindings = request.get("source_bindings")
    if isinstance(bindings, Mapping):
        for role, item in bindings.items():
            if isinstance(item, Mapping):
                add(item, str(role))
    trajectory = request.get("trajectory_h5")
    if isinstance(trajectory, Mapping):
        add({**trajectory, "role": trajectory.get("role", "trajectory_h5")}, "trajectory_h5")
    # A nested producer receipt is provenance unless it contains an explicit
    # path/hash role.  Do not recursively walk arbitrary evidence JSON: doing
    # so could silently turn a scientific scan's copied path into a converter.
    for key in ("producer_receipts", "raw_to_typed_contract", "typed_to_label_contract"):
        value = request.get(key)
        if isinstance(value, Mapping):
            for role, item in value.items():
                if isinstance(item, Mapping) and (item.get("path") or item.get("original_path")):
                    add(item, str(role))
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in records:
        unique[(item["role"], item["path"])] = item
    return [unique[key] for key in sorted(unique)]


def _source_status(records: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    checked: list[dict[str, Any]] = []
    violations: list[str] = []
    for raw in records:
        item = dict(raw)
        path = Path(str(item["path"])).expanduser()
        item["resolved_path"] = str(path.resolve())
        item["exists"] = path.is_file()
        if not path.is_file():
            item["status"] = "MISSING"
            violations.append(f"missing source: {path}")
            checked.append(item)
            continue
        stat = path.stat()
        item["actual_bytes"] = stat.st_size
        item["mtime_ns"] = stat.st_mtime_ns
        declared = item.get("declared_sha256")
        if _is_h5(str(path)):
            # Stat is useful for relocation planning, but it is never a
            # content proof.  Parent v20 overlay must verify HDF5 bytes.
            item["status"] = "H5_STAT_ONLY_CONTENT_HASH_DEFERRED"
            item["content_hash_checked"] = False
            if declared:
                item["expected_content_sha256"] = declared
        elif stat.st_size <= SMALL_HASH_LIMIT and declared:
            actual = sha256(path)
            item["actual_sha256"] = actual
            item["content_hash_checked"] = True
            item["status"] = "HASH_MATCH" if actual == declared else "HASH_MISMATCH"
            if actual != declared:
                violations.append(f"source SHA differs: {path}")
        elif declared:
            item["status"] = "CONTENT_HASH_DEFERRED_PARENT_GUARD"
            item["content_hash_checked"] = False
        else:
            item["status"] = "PRESENT_WITHOUT_DECLARED_HASH"
            item["content_hash_checked"] = False
        checked.append(item)
    return checked, violations


def _role_text(item: Mapping[str, Any]) -> str:
    return f"{item.get('role', '')} {item.get('path', '')}".lower()


def _contract_status(request: Mapping[str, Any], records: list[Mapping[str, Any]]) -> dict[str, Any]:
    role_text = [_role_text(item) for item in records]
    raw = [item for item, text in zip(records, role_text)
           if any(token in text for token in ("partout", "runparts", "raw_native", "raw_source"))]
    typed = [item for item, text in zip(records, role_text) if "trajectory_h5" in text or _is_h5(str(item.get("path", "")))]
    scan_evidence = [item for item, text in zip(records, role_text) if "scan" in text or "scientific" in text]
    explicit = request.get("reconstruction_contract")
    contract = explicit if isinstance(explicit, Mapping) else {}
    converter = contract.get("raw_to_typed") if isinstance(contract.get("raw_to_typed"), Mapping) else {}
    adapter = contract.get("typed_to_label") if isinstance(contract.get("typed_to_label"), Mapping) else {}
    converter_receipt = [item for item, text in zip(records, role_text)
                         if any(token in text for token in ("raw_to_typed", "converter_receipt", "typed_producer_receipt"))
                         and "scan" not in text and "scientific" not in text]
    label_receipt = [item for item, text in zip(records, role_text)
                     if any(token in text for token in ("label_operator_receipt", "typed_to_label_receipt"))]
    missing: list[str] = []
    if not raw:
        missing.append("CURRENT-bound native raw anchor (PartOut/RunPARTs or equivalent)")
    if not typed:
        missing.append("typed trajectory producer binding with expected HDF5 SHA")
    if not converter.get("module_path") or not converter.get("module_sha256"):
        missing.append("raw_to_typed converter source and SHA")
    if not converter_receipt and not converter.get("receipt_path"):
        missing.append("raw_to_typed converter execution receipt")
    if not converter.get("schema_contract"):
        missing.append("raw_to_typed field/schema/units contract")
    if not adapter.get("module_path") or not adapter.get("module_sha256"):
        missing.append("typed-to-label identity/invalid-mask adapter source and SHA")
    if not adapter.get("valid_mask_proof"):
        missing.append("typed valid-mask and (Zone,Idp) identity proof")
    if not label_receipt and not adapter.get("receipt_path"):
        missing.append("typed_to_label operator receipt")
    return {
        "raw_anchor_count": len(raw),
        "typed_trajectory_count": len(typed),
        "scientific_scan_evidence_count": len(scan_evidence),
        "scientific_scan_is_not_reconstruction": True,
        "converter_receipt_count": len(converter_receipt),
        "label_receipt_count": len(label_receipt),
        "missing": missing,
        "ready_for_parent_guarded_reconstruction": not missing,
    }


def prepare_plan(request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load(request_file)
    if request.get("model_invoked") is True or request.get("cfd_invoked") is True:
        raise ReconstructionBindingError("model/CFD invocation is forbidden in reconstruction preparation")
    qualification = request.get("qualification")
    if qualification is not None and qualification != UNKNOWN_QUALIFICATION:
        raise ReconstructionBindingError("reconstruction preparation requires QI/QN/QE UNKNOWN")
    records = _mapping_records(request)
    checked, violations = _source_status(records)
    if violations:
        raise ReconstructionBindingError("; ".join(violations))
    contract = _contract_status(request, checked)
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "plan_version": 1,
        "status": "READY_FOR_PARENT_GUARDED_RECONSTRUCTION" if contract["ready_for_parent_guarded_reconstruction"] else "PENDING_SOURCE_RECONSTRUCTION",
        "request": {
            "path": str(request_file),
            "schema": request.get("schema"),
            "request_id": request.get("request_id") or request.get("attempt_id"),
            "sha256": sha256(request_file),
        },
        "source_inventory": checked,
        "contract": contract,
        "raw_to_typed": {
            "invoked": False,
            "status": "NOT_INVOKED",
            "content_sha_proof": "PENDING_RECONSTRUCTION_RECEIPT",
            "scientific_scan_cannot_substitute": True,
        },
        "typed_to_label": {
            "invoked": False,
            "status": "NOT_INVOKED",
            "identity_axis": "(Zone,Idp) exact; no positional reordering",
            "valid_mask_required": True,
            "scientific_scan_cannot_substitute": True,
        },
        "execution_boundary": {
            "hdf5_opened": False,
            "hdf5_content_hashed": False,
            "native_converter_invoked": False,
            "label_operator_invoked": False,
            "model_invoked": False,
            "cfd_invoked": False,
            "parent_stage2guard_required": True,
            "os_open_trace_required_for_relocated_execution": True,
        },
        "required_receipts_before_labels": [
            "raw_to_typed converter receipt with source/raw SHA, schema, units, identity and invalid-mask mapping",
            "typed HDF5 content SHA verified at actual relocated path",
            "typed_to_label operator receipt with exact operator source/config SHA",
            "(Zone,Idp) order/valid-mask cross-check against the CURRENT-bound initial cohort",
            "OS-level openat trace showing no original-path fallback",
        ],
        "qualification": UNKNOWN_QUALIFICATION,
        "development_boundary": "Preparation/evidence only; no scientific label or QI/QN/QE credit",
    }
    plan["plan_sha256"] = canonical_sha(plan)
    _write_new(output_path, plan)
    return plan


def validate_plan(plan_path: Path | str) -> dict[str, Any]:
    plan = _load(plan_path)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ReconstructionBindingError("raw-to-typed-to-label plan schema is required")
    if plan.get("raw_to_typed", {}).get("invoked") or plan.get("typed_to_label", {}).get("invoked"):
        raise ReconstructionBindingError("this preparation validator cannot certify invoked reconstruction")
    if plan.get("qualification") != UNKNOWN_QUALIFICATION:
        raise ReconstructionBindingError("plan qualification must remain UNKNOWN")
    return {
        "schema": "ds02.stage2.raw-to-typed-to-label-reconstruction-validation.v1",
        "status": "VALID_PREPARATION_ONLY",
        "plan_sha256": plan.get("plan_sha256"),
        "reconstruction_invoked": False,
        "qualification": UNKNOWN_QUALIFICATION,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--request", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare_plan(args.request, args.output)
        else:
            result = validate_plan(args.plan)
    except (OSError, ReconstructionBindingError) as error:
        parser.error(str(error))
    print(json.dumps({"status": result["status"], "schema": result["schema"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
