#!/usr/bin/env python3
"""Derive Root095-compatible F1 production requests from actual Root094 JSON.

This is a metadata-only adapter.  It reads the two existing Root094 request
JSON documents and the referenced GenCase receipt JSON bytes, then writes
requests that differ only in the runtime receipt contract:

* ``gencase_receipt`` becomes the receipt path string;
* ``gencase_receipt_sha256`` is added with the binding SHA-256.

No solver, runner, authorizer, GenCase, PartVTK, BI4, CSV, H5, or array reader
is imported or invoked.  The mutable approval registry is not read or changed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE_ROOT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    """lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"""
    "root_stage1_f1_two_interior_actual_visual_production_094"
)
DEFAULT_OUTPUT_ROOT = HERE / "requests"
DEFAULT_AUDIT = HERE / "F1_ROOT095_RUNTIME_REQUEST_CONTRACT_AUDIT.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

CASE_REQUESTS = {
    "F1_STAGE1_ECC_H130_DP010": "ecc/request.json",
    "F1_STAGE1_DUAL_H260_DP020": "dual/request.json",
}
RUNTIME_REQUIRED_FIELDS = (
    "family_id",
    "case_id",
    "attempt_id",
    "kind",
    "command",
    "cwd",
    "max_wall_seconds",
    "cpu_threads",
    "estimated_storage_bytes",
    "input_files",
    "worktree_root",
)
RUNTIME_PRODUCTION_FIELDS = (
    "estimated_peak_gpu_mib",
    "gencase_receipt",
)
STAGE1_FIELDS = (
    "visual_stage_profile",
    "visual_stage_adapter_path",
    "scope_id",
)
STAGE1_RECEIPT_FIELDS = ("gencase_receipt_sha256",)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"request must be a JSON object: {path}")
    return value


def type_name(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def required_field_report(request: Mapping[str, Any]) -> dict[str, Any]:
    missing_runtime = [key for key in RUNTIME_REQUIRED_FIELDS if key not in request]
    missing_production = [key for key in RUNTIME_PRODUCTION_FIELDS if key not in request]
    missing_stage1 = [key for key in STAGE1_FIELDS if key not in request]
    missing_stage1_receipt = [key for key in STAGE1_RECEIPT_FIELDS if key not in request]
    type_errors: list[dict[str, str]] = []
    expected_types = {
        "family_id": "string",
        "case_id": "string",
        "attempt_id": "string",
        "kind": "string",
        "command": "array",
        "cwd": "string",
        "max_wall_seconds": "int",
        "cpu_threads": "int",
        "estimated_storage_bytes": "int",
        "input_files": "array",
        "worktree_root": "string",
        "estimated_peak_gpu_mib": "int",
        "gencase_receipt": "string",
        "gencase_receipt_sha256": "string",
        "visual_stage_profile": "string",
        "visual_stage_adapter_path": "string",
        "scope_id": "string",
    }
    for key, expected in expected_types.items():
        if key not in request:
            continue
        actual = type_name(request[key])
        if actual != expected:
            type_errors.append({"field": key, "expected": expected, "observed": actual})
    if isinstance(request.get("command"), list) and not all(isinstance(item, str) for item in request["command"]):
        type_errors.append({"field": "command[]", "expected": "string", "observed": "non-string element"})
    if isinstance(request.get("input_files"), list) and not all(isinstance(item, str) for item in request["input_files"]):
        type_errors.append({"field": "input_files[]", "expected": "string", "observed": "non-string element"})
    return {
        "missing_runtime_required_fields": missing_runtime,
        "missing_runtime_production_fields": missing_production,
        "missing_stage1_fields": missing_stage1,
        "missing_stage1_receipt_fields": missing_stage1_receipt,
        "type_errors": type_errors,
    }


def normalize_request(request: Mapping[str, Any], source_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    before = copy.deepcopy(dict(request))
    binding = request.get("gencase_receipt")
    if not isinstance(binding, Mapping):
        raise ValueError(f"{source_path}: gencase_receipt must be the Root094 binding object")
    receipt_raw_path = binding.get("path")
    declared_sha = binding.get("sha256")
    if not isinstance(receipt_raw_path, str) or not receipt_raw_path:
        raise ValueError(f"{source_path}: gencase_receipt.path is required")
    if not isinstance(declared_sha, str) or not SHA256_RE.fullmatch(declared_sha):
        raise ValueError(f"{source_path}: gencase_receipt.sha256 must be lowercase SHA-256")
    receipt_path = Path(receipt_raw_path).resolve()
    if not receipt_path.is_file():
        raise FileNotFoundError(f"{source_path}: missing actual GenCase receipt: {receipt_path}")
    actual_sha = sha256_file(receipt_path)
    if actual_sha != declared_sha:
        raise ValueError(f"{source_path}: GenCase receipt SHA differs from Root094 binding")

    derived = copy.deepcopy(dict(request))
    derived["gencase_receipt"] = str(receipt_path)
    derived["gencase_receipt_sha256"] = declared_sha
    changed = [key for key in sorted(set(before) | set(derived)) if before.get(key) != derived.get(key)]
    if changed != ["gencase_receipt", "gencase_receipt_sha256"]:
        raise AssertionError(f"unexpected request mutation in {source_path}: {changed}")
    if derived.get("input_files") != before.get("input_files"):
        raise AssertionError(f"input_files changed in {source_path}")
    if derived.get("input_sha256") != before.get("input_sha256"):
        raise AssertionError(f"input_sha256 changed in {source_path}")
    input_hash = None
    input_hashes = before.get("input_sha256")
    if isinstance(input_hashes, Mapping):
        input_hash = input_hashes.get(str(receipt_path))
    if input_hash != declared_sha:
        raise ValueError(f"{source_path}: input_sha256 does not bind the GenCase receipt")

    before_contract = required_field_report(before)
    after_contract = required_field_report(derived)
    report = {
        "source_request": str(source_path.resolve()),
        "source_request_sha256": sha256_file(source_path),
        "case_id": derived.get("case_id"),
        "attempt_id": derived.get("attempt_id"),
        "before_gencase_receipt": {
            "type": type_name(before.get("gencase_receipt")),
            "binding_path": receipt_raw_path,
            "binding_sha256": declared_sha,
        },
        "after_gencase_receipt": {
            "type": type_name(derived.get("gencase_receipt")),
            "path": derived["gencase_receipt"],
            "sha256": derived["gencase_receipt_sha256"],
        },
        "actual_receipt_sha256_matches_binding": actual_sha == declared_sha,
        "changed_fields": changed,
        "all_other_fields_semantically_unchanged": all(
            before.get(key) == derived.get(key)
            for key in set(before) | set(derived)
            if key not in {"gencase_receipt", "gencase_receipt_sha256"}
        ),
        "input_files_unchanged": before.get("input_files") == derived.get("input_files"),
        "input_sha256_unchanged": before.get("input_sha256") == derived.get("input_sha256"),
        "root094_contract": before_contract,
        "root095_contract": after_contract,
        "runtime_contract_result": "pass" if not any(after_contract.values()) else "fail",
    }
    return derived, report


def build(*, source_root: Path, output_root: Path, audit_path: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    case_reports: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    source_contract_bindings: dict[str, list[dict[str, str]]] = {}
    for case_id, relative in CASE_REQUESTS.items():
        source_path = (source_root / relative).resolve()
        request = load_json(source_path)
        input_hashes = request.get("input_sha256", {})
        if isinstance(input_hashes, Mapping):
            for raw_path, declared_hash in input_hashes.items():
                basename = Path(str(raw_path)).name
                if basename in {
                    "ds_data02_runtime_v2.py",
                    "ds_data02_strict_dispatch_v1.py",
                    "ds_data02_stage1_dispatch_f1.py",
                    "ds_data02_stage1_production_f1.py",
                }:
                    source_contract_bindings.setdefault(basename, []).append(
                        {"path": str(raw_path), "sha256": str(declared_hash)}
                    )
        if request.get("case_id") != case_id:
            raise ValueError(f"case identity mismatch: expected {case_id}, got {request.get('case_id')}")
        derived, report = normalize_request(request, source_path)
        output_path = output_root / f"{case_id}_root095_compatible.json"
        output_path.write_text(json.dumps(derived, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report["derived_request"] = str(output_path.resolve())
        report["derived_request_sha256"] = sha256_file(output_path)
        case_reports.append(report)
        outputs.append({"case_id": case_id, "path": str(output_path.resolve()), "sha256": sha256_file(output_path)})
    audit = {
        "schema": "ds02.f1.root095-runtime-request-contract-audit.v1",
        "status": "metadata_only_pass",
        "source_scope": "Root094 actual request JSON; no registry or request source mutation",
        "helper": str((HERE / "build_root095_runtime_request_adapter.py").resolve()),
        "source_root": str(source_root.resolve()),
        "output_root": str(output_root.resolve()),
        "source_contract_bindings": {
            name: [
                {"path": path, "sha256": digest}
                for path, digest in sorted({
                    (item["path"], item["sha256"]) for item in items
                })
            ]
            for name, items in sorted(source_contract_bindings.items())
        },
        "runtime_contract": {
            "required_fields": list(RUNTIME_REQUIRED_FIELDS),
            "production_fields": list(RUNTIME_PRODUCTION_FIELDS),
            "stage1_fields": list(STAGE1_FIELDS),
            "stage1_receipt_fields": list(STAGE1_RECEIPT_FIELDS),
            "validator_behavior": "runtime_v2.validate_request calls Path(request['gencase_receipt']) and sha256(request['gencase_receipt']); therefore it requires a string path",
            "stage1_behavior": "Stage1 build_request normalizes a binding to gencase_receipt string plus gencase_receipt_sha256; authorizer compares both against the frozen actual binding",
            "preserved_fields": "command, cwd, recipe, event window, attempt_id, input_files, input_sha256, worktree_root, approval/profile fields remain semantically exact",
        },
        "root094_failure": {
            "field": "gencase_receipt",
            "observed_type": "object",
            "runtime_expected_type": "string path",
            "secondary_missing_field": "gencase_receipt_sha256",
            "failure_location": "ds_data02_runtime_v2.validate_request before solver launch",
        },
        "transform": {
            "changed_fields_exactly": ["gencase_receipt", "gencase_receipt_sha256"],
            "reads_receipt_json_for_sha_only": True,
            "launches_numeric_work": False,
            "reads_particle_arrays": False,
            "modifies_shared_registry": False,
        },
        "cases": case_reports,
        "derived_requests": outputs,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args()
    audit = build(source_root=args.source_root, output_root=args.output_root, audit_path=args.audit)
    print(json.dumps({"status": audit["status"], "derived_requests": audit["derived_requests"], "audit": str(args.audit.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
