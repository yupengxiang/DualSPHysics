#!/usr/bin/env python3
"""Metadata-only preflight for the real direct converter owner scope.

This imports the checked-in integration converter and calls only
``_physical_condition_scope``.  It never opens BI4, H5, CSV, XMF, or solver
outputs and never calls ``convert_direct``.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def load_real_converter(path: Path):
    spec = importlib.util.spec_from_file_location("ds02_real_direct_convert", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import converter source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", type=Path, required=True)
    parser.add_argument("--converter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    owner = load_json(args.owner)
    if "physical_binding" in owner:
        raise ValueError("fresh095 must exercise the real legacy-owner scope; physical_binding is forbidden")
    module = load_real_converter(args.converter)
    scope = module._physical_condition_scope(owner)
    scope_hash = module.canonical_hash(scope)
    canonical_hash = owner["physical_condition_sha256"]
    source_plan_hash = owner["source_plan_physical_condition_sha256"]
    if scope.get("schema") != "legacy-owner-scope.v0":
        raise ValueError(f"unexpected scope schema: {scope.get('schema')!r}")
    if scope.get("semantic_binding_status") != "legacy_incomplete; no cross-resolution physical claim":
        raise ValueError("unexpected legacy scope semantic status")
    if scope_hash in {canonical_hash, source_plan_hash}:
        raise ValueError("legacy scope hash was collapsed into another physical identity")
    if owner.get("legacy_scope_sha256") != scope_hash:
        raise ValueError("owner legacy_scope_sha256 does not match the real converter function")
    forbidden = {
        "dp_m", "resolution", "particle_count", "particle_counts", "expected_particles",
        "save_interval_s", "solver_timestep_s", "time_out_s",
    }
    seen_forbidden: list[str] = []

    def walk(value: Any, path: str = "scope") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in forbidden:
                    seen_forbidden.append(f"{path}.{key}")
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(scope)
    if seen_forbidden:
        raise ValueError(f"resolution-dependent fields entered the physical scope: {seen_forbidden}")
    result = {
        "schema": "ds02.f5.c082s1.direct-converter-scope-preflight.fresh095.v1",
        "status": "passed",
        "owner_metadata": str(args.owner.resolve()),
        "owner_metadata_sha256": sha256_file(args.owner),
        "converter_source": str(args.converter.resolve()),
        "converter_source_sha256": sha256_file(args.converter),
        "function_used": "ds_data02_direct_convert._physical_condition_scope",
        "scope": scope,
        "scope_sha256": scope_hash,
        "canonical_owner_sha256": canonical_hash,
        "source_plan_sha256": source_plan_hash,
        "hashes_are_distinct": {
            "legacy_vs_canonical": scope_hash != canonical_hash,
            "legacy_vs_source_plan": scope_hash != source_plan_hash,
            "canonical_vs_source_plan": canonical_hash != source_plan_hash,
        },
        "semantic_binding_status": scope["semantic_binding_status"],
        "resolution_dependent_fields_excluded_from_scope": True,
        "science_arrays_read": False,
        "science_arrays_hashed": False,
        "actual_conversion_run": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "passed", "scope_sha256": scope_hash}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
