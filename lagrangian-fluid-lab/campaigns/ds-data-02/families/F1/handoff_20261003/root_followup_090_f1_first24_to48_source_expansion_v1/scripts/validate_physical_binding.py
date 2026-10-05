#!/usr/bin/env python3
"""Call the real direct-converter physical scope helper on owner JSON only."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json
from pathlib import Path

SCIENCE = {".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".npy", ".npz", ".dat"}

def sha(path: Path) -> str:
    if path.suffix.lower() in SCIENCE:
        raise RuntimeError(f"scientific payload forbidden: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--converter", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    spec = importlib.util.spec_from_file_location("ds_data02_direct_convert_metadata_only", a.converter)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    rows = []
    for owner_path in sorted((a.package / "owners").glob("*.owner.json")):
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        scope = module._physical_condition_scope(owner)
        rows.append({
            "case_id": owner["case_id"],
            "owner": str(owner_path),
            "owner_sha256": sha(owner_path),
            "physical_condition_sha256": owner["physical_condition_sha256"],
            "canonical_physical_binding_sha256": canonical(owner["physical_binding"]),
            "scope_schema": scope.get("schema", "ds-data-02.physical-binding.v1"),
            "scope_sha256": canonical(scope),
            "scope": scope,
            "status": "metadata_only_preflight_passed",
        })
    if len(rows) != 24:
        raise RuntimeError(f"expected 24 owners, found {len(rows)}")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps({
        "schema": "ds02.f1.fresh090.converter-physical-scope-preflight.v1",
        "converter": str(a.converter),
        "converter_sha256": sha(a.converter),
        "rows": rows,
        "arrays_read": False,
        "jobs_launched": False,
        "status": "metadata_only_preflight_passed",
    }, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "metadata_only_preflight_passed", "cases": len(rows)}))

if __name__ == "__main__":
    main()
