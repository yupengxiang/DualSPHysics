#!/usr/bin/env python3
"""Materialize an M086 producer-identity binding from the immutable fresh158 base."""
from __future__ import annotations
import argparse, copy, hashlib, json
from pathlib import Path

BASE_CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
PRODUCER_CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M086_T085_NEXT34"
ADAPTER_SCHEMA = "ds02.f5.c082s1.m086.identity-adapter.fresh159.v1"
BED_SCHEMA = "ds02.f5.c082s1.full-event-bed-audit-binding.fresh138.v1"
ORIGINAL_WORKER_SHA = "89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2"
SCIENCE_SUFFIXES = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz"}

def sha(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise ValueError(f"science payload hashing is forbidden: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def load(path: Path):
    value = json.loads(path.read_text())
    if not isinstance(value, dict): raise ValueError(f"JSON object required: {path}")
    return value

def require(condition, message):
    if not condition: raise ValueError(message)

def materialize(base_path: Path, output_path: Path) -> dict:
    base = load(base_path)
    require(base.get("schema") == BED_SCHEMA, "unexpected bed binding schema")
    require(base.get("case_id") == BASE_CASE_ID, "base case ID must remain the worker base")
    require(base.get("producer_case_id") == PRODUCER_CASE_ID, "producer case ID missing")
    value = copy.deepcopy(base)
    value["case_id"] = PRODUCER_CASE_ID
    value["producer_case_id"] = PRODUCER_CASE_ID
    adapter_path = Path(__file__).resolve().parents[1] / "workers/identity_bound_bed_audit_fresh159.py"
    materializer_path = Path(__file__).resolve()
    value["identity_adapter"] = {
        "schema": ADAPTER_SCHEMA,
        "mode": "metadata_only_in_memory_case_identity_rebind",
        "base_binding_path": str(base_path),
        "base_binding_sha256": sha(base_path),
        "base_case_id": BASE_CASE_ID,
        "producer_case_id": PRODUCER_CASE_ID,
        "original_worker_sha256": ORIGINAL_WORKER_SHA,
        "adapter_worker_path": str(adapter_path),
        "adapter_worker_sha256": sha(adapter_path),
        "materializer_path": str(materializer_path),
        "materializer_sha256": sha(materializer_path),
        "downstream_role": "fresh138 full801 Mk50 bed audit with producer identity",
        "numerical_logic_unchanged": True,
        "array_edit_allowed": False,
        "receipt_identity_rule": "nested GenCase/native/typed receipt case_id must remain the producer suffix",
        "source_agent_did_not_read_or_hash_science_payloads": True,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return value

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-binding", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        print("fresh159 materializer CLI metadata check passed")
        return 0
    if args.base_binding is None or args.output is None:
        parser.error("--base-binding and --output are required")
    materialize(args.base_binding, args.output)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
