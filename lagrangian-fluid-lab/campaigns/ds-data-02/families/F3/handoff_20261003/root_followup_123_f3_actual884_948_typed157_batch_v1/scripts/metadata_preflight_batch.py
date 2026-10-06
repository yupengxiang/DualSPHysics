#!/usr/bin/env python3
"""Recompute fresh123 converter scope from owner JSON only.

Run with the integration venv. Importing the converter is limited to its
metadata helpers; this script never opens BI4/H5/CSV/DAT/VTK/solver data.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

FORBIDDEN = {".bi4", ".ibi4", ".obi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz", ".raw"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def import_converter(path: Path):
    module_name = "_fresh123_metadata_only_converter"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import converter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    index_path = package / "metadata" / "candidate-index.json"
    index = read_json(index_path)
    rows = index["selected_cases"]
    if not rows:
        raise RuntimeError("candidate index is empty")
    first_preflight = read_json(Path(rows[0]["preflight_path"]))
    converter_path = Path(first_preflight["converter"]["path"]).resolve()
    converter_digest = sha256(converter_path)
    converter = import_converter(converter_path)
    results = []
    for row in rows:
        owner_path = Path(row["owner_path"]).resolve()
        preflight_path = Path(row["preflight_path"]).resolve()
        owner = read_json(owner_path)
        preflight = read_json(preflight_path)
        binding = owner.get("physical_binding")
        if not isinstance(binding, dict) or binding.get("schema") != "ds-data-02.physical-binding.v1":
            raise RuntimeError(f"{row['case_id']}: explicit physical_binding.v1 missing")
        scope = converter._physical_condition_scope(owner)
        scope_digest = converter.canonical_hash(scope)
        if scope_digest != preflight["scope_sha256"]:
            raise RuntimeError(f"{row['case_id']}: scope digest mismatch")
        if scope_digest != row["physical_condition_sha256"]:
            raise RuntimeError(f"{row['case_id']}: candidate scope digest mismatch")
        if preflight["converter"]["sha256"] != converter_digest:
            raise RuntimeError(f"{row['case_id']}: converter bytes changed")
        if any(Path(str(value)).suffix.lower() in FORBIDDEN for value in owner.get("producer_attested_inputs", {}).get("counts", {}).values() if isinstance(value, str)):
            raise RuntimeError(f"{row['case_id']}: forbidden payload-like count metadata")
        results.append({
            "case_id": row["case_id"],
            "owner_path": str(owner_path),
            "owner_sha256": sha256(owner_path),
            "preflight_path": str(preflight_path),
            "preflight_sha256": sha256(preflight_path),
            "physical_binding_schema": binding["schema"],
            "scope_sha256": scope_digest,
            "converter_path": str(converter_path),
            "converter_sha256": converter_digest,
            "status": "pass_metadata_only",
            "payload_opened_or_hashed": False,
        })
    output = args.output or package / "metadata" / "fresh123-preflight-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "schema": "ds02.stage1.f3.fresh123.preflight-report.v1",
        "package": str(package),
        "selected_count": len(results),
        "results": results,
        "payload_opened_or_hashed": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "selected_count": len(results), "report": str(output.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
