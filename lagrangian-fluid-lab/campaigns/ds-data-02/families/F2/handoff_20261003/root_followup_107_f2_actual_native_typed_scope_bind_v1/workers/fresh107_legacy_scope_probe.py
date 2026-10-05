#!/usr/bin/env python3
"""Metadata-only probe of ds_data02_direct_convert._physical_condition_scope.

The integration LAB venv is required because the host Python has an h5py/numpy
ABI mismatch. The probe imports the converter under a private module name and
calls only _physical_condition_scope(owner) and canonical_hash(scope). It never
opens BI4, H5, CSV, DAT, VTK, Run.out, or a native output tree.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def import_converter(path: Path) -> Any:
    name = "ds02_f2_fresh107_scope_probe_private"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner-manifest", required=True)
    ap.add_argument("--converter", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    manifest = load(Path(args.owner_manifest).resolve())
    converter_path = Path(args.converter).resolve()
    converter = import_converter(converter_path)
    rows = []
    errors = []
    for item in manifest.get("owners", []):
        owner_path = Path(item["path"]).resolve()
        owner = load(owner_path)
        scope = converter._physical_condition_scope(owner)
        scope_sha = converter.canonical_hash(scope)
        expected = item.get("expected_legacy_scope_sha256")
        case_errors = []
        if scope.get("schema") != "legacy-owner-scope.v0":
            case_errors.append("scope schema is not legacy-owner-scope.v0")
        if scope.get("semantic_binding_status") != "legacy_incomplete; no cross-resolution physical claim":
            case_errors.append("legacy semantic status changed")
        if expected is not None and scope_sha != expected:
            case_errors.append(f"scope hash mismatch: expected {expected}, got {scope_sha}")
        if owner.get("canonical_physical_binding_sha256") is not None:
            case_errors.append("owner canonical scope was prefilled")
        rows.append({
            "case_id": item["case_id"],
            "owner": str(owner_path),
            "scope": scope,
            "prospective_legacy_scope_sha256": scope_sha,
            "actual_converter_physical_condition_sha256": None,
            "canonical_physical_binding_sha256": None,
            "canonical_grant": False,
            "status": "pass" if not case_errors else "fail",
            "errors": case_errors,
        })
        errors.extend(f"{item['case_id']}: {e}" for e in case_errors)
    result = {
        "schema": "ds02.f2.stage1.fresh107.legacy-scope-probe.v1",
        "status": "pass" if len(rows) == 16 and not errors else "fail",
        "converter": str(converter_path),
        "probe_calls": ["_physical_condition_scope(owner)", "canonical_hash(scope)"],
        "private_sys_modules_name": "ds02_f2_fresh107_scope_probe_private",
        "scientific_inputs_opened": [],
        "actual_conversion_executed": False,
        "canonical_scope_granted": False,
        "owners": rows,
        "errors": errors,
    }
    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "case_count": len(rows), "errors": errors}, sort_keys=True))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
