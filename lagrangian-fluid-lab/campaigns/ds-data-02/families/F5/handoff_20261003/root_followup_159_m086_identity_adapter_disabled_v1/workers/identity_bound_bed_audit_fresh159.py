#!/usr/bin/env python3
"""Metadata-only M086 identity adapter around the unchanged fresh138 bed worker.

The producer's nested GenCase/native/typed receipts use the suffixed case ID
``F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M086_T085_NEXT34`` while the
reusable fresh138 worker has the base C082S1 case constant. This adapter validates
that distinction from JSON/XML metadata, creates an in-memory case-ID rebinding,
and invokes the original worker. It never changes the numerical audit code,
thresholds, geometry, arrays, or consumed binding.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any

BINDING_SCHEMA = "ds02.f5.c082s1.full-event-bed-audit-binding.fresh138.v1"
ADAPTER_SCHEMA = "ds02.f5.c082s1.m086.identity-adapter.fresh159.v1"
BASE_CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
PRODUCER_CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M086_T085_NEXT34"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M086_T085"
CANONICAL_SHA = "89a891b45dae3220aaa64f9b8764645cece3164633fb45fc57c0ad8f51c734f3"
SOURCE_PLAN_SHA = "85d0e0af79ae69aeb83d88a21c4b277e321169167145c74e215d3d246704cb70"
LEGACY_SHA = "ff41cd47740e7d7532982b004ef761ec97feb4b72cbfc77bcd7b3666df0d72c1"
ORIGINAL_WORKER = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_138_stage1_f5_remaining10_full801_downstream_disabled_v1/workers/bed_audit_full801_fresh138.py")
ORIGINAL_WORKER_SHA = "89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2"
SCIENCE_SUFFIXES = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz"}

def _sha(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise ValueError(f"science payload hash forbidden by adapter metadata phase: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)

DOWNSTREAM_BINDING_FIELDS = {"xmf_manifest", "xmf_manifest_sha256", "xdmf", "xdmf_sha256", "xmf_receipt", "xmf_receipt_sha256"}

def _identity_stripped(binding: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(binding)
    value.pop("case_id", None)
    value.pop("producer_case_id", None)
    value.pop("identity_adapter", None)
    for key in DOWNSTREAM_BINDING_FIELDS:
        value.pop(key, None)
    return value

def _validate_downstream_refs(binding: dict[str, Any]) -> None:
    for path_key, hash_key in (("xmf_manifest", "xmf_manifest_sha256"), ("xdmf", "xdmf_sha256"), ("xmf_receipt", "xmf_receipt_sha256")):
        raw_path = binding.get(path_key)
        raw_hash = binding.get(hash_key)
        if raw_path is None:
            _require(raw_hash is None, f"{path_key} hash without path")
            continue
        path = Path(str(raw_path))
        _require(path.is_file() and path.suffix.lower() not in SCIENCE_SUFFIXES, f"{path_key} metadata path missing or science payload")
        _require(isinstance(raw_hash, str) and _sha(path) == raw_hash, f"{path_key} metadata SHA mismatch")

def validate_base_binding(base: dict[str, Any]) -> None:
    _require(base.get("schema") == BINDING_SCHEMA, "fresh138 binding schema mismatch")
    _require(base.get("case_id") == BASE_CASE_ID, "fresh158 base case identity mismatch")
    _require(base.get("producer_case_id") == PRODUCER_CASE_ID, "producer case identity missing")
    _require(base.get("physical_case_id") == PHYSICAL_CASE_ID, "physical case identity mismatch")
    _require(base.get("physical_condition_sha256") == CANONICAL_SHA, "canonical physical scope mismatch")
    _require(base.get("source_plan_physical_condition_sha256") == SOURCE_PLAN_SHA, "source definition scope mismatch")
    _require(base.get("source_h5_physical_condition_sha256") == LEGACY_SHA, "legacy H5 scope mismatch")
    semantics = base.get("physical_condition_hash_semantics", {})
    _require(semantics.get("canonical_owner_sha256") == CANONICAL_SHA, "canonical semantic binding mismatch")
    _require(semantics.get("source_h5_sha256") == LEGACY_SHA, "legacy semantic binding mismatch")
    _require(semantics.get("source_h5_scope_schema") == "legacy-owner-scope.v0", "legacy scope schema mismatch")
    _require(semantics.get("source_h5_scope_status") == "legacy_incomplete; no cross-resolution physical claim", "legacy scope status changed")
    _require(base.get("native_bed_marker_mk") == 50 and base.get("source_bed_marker_mkbound") == 40, "Mk50/mkbound40 mapping changed")

def adapt_binding(binding_path: Path) -> dict[str, Any]:
    """Validate a materialized identity binding and return the in-memory worker binding."""
    binding = _load(binding_path)
    _require(binding.get("identity_adapter", {}).get("schema") == ADAPTER_SCHEMA, "identity adapter metadata missing")
    adapter = binding["identity_adapter"]
    base_path = Path(str(adapter["base_binding_path"]))
    _require(base_path.is_file(), "base binding missing")
    _require(_sha(base_path) == adapter.get("base_binding_sha256"), "base binding SHA mismatch")
    base = _load(base_path)
    validate_base_binding(base)
    _require(binding.get("case_id") == PRODUCER_CASE_ID, "materialized worker case is not producer identity")
    _require(binding.get("producer_case_id") == PRODUCER_CASE_ID, "materialized producer identity changed")
    _require(binding.get("physical_case_id") == PHYSICAL_CASE_ID, "materialized physical identity changed")
    _validate_downstream_refs(binding)
    _require(_identity_stripped(binding) == _identity_stripped(base), "identity adapter changed non-identity binding fields")
    _require(adapter.get("base_case_id") == BASE_CASE_ID and adapter.get("producer_case_id") == PRODUCER_CASE_ID, "adapter identity contract mismatch")
    _require(adapter.get("original_worker_sha256") == ORIGINAL_WORKER_SHA, "original fresh138 worker SHA mismatch")
    _require(adapter.get("numerical_logic_unchanged") is True and adapter.get("array_edit_allowed") is False, "adapter mutation policy changed")
    return binding

def _toy_check() -> None:
    base = {
        "schema": BINDING_SCHEMA,
        "case_id": BASE_CASE_ID,
        "producer_case_id": PRODUCER_CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "physical_condition_sha256": CANONICAL_SHA,
        "source_plan_physical_condition_sha256": SOURCE_PLAN_SHA,
        "source_h5_physical_condition_sha256": LEGACY_SHA,
        "physical_condition_hash_semantics": {
            "canonical_owner_sha256": CANONICAL_SHA,
            "source_h5_sha256": LEGACY_SHA,
            "source_h5_scope_schema": "legacy-owner-scope.v0",
            "source_h5_scope_status": "legacy_incomplete; no cross-resolution physical claim",
        },
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "sentinel": "unchanged",
    }
    validate_base_binding(base)
    derived = copy.deepcopy(base)
    derived["case_id"] = PRODUCER_CASE_ID
    derived["identity_adapter"] = {
        "schema": ADAPTER_SCHEMA,
        "base_binding_path": "toy-base.json",
        "base_binding_sha256": "toy",
        "base_case_id": BASE_CASE_ID,
        "producer_case_id": PRODUCER_CASE_ID,
        "original_worker_sha256": ORIGINAL_WORKER_SHA,
        "numerical_logic_unchanged": True,
        "array_edit_allowed": False,
    }
    # The toy's path/SHA is intentionally tested by the materializer/validator separately;
    # these checks cover the mismatch boundary without opening scientific data.
    _require(derived["case_id"] == PRODUCER_CASE_ID and derived["sentinel"] == "unchanged", "toy accepted identity")
    for field, value in (("case_id", "wrong"), ("physical_condition_sha256", "f" * 64), ("producer_case_id", BASE_CASE_ID)):
        bad = copy.deepcopy(base); bad[field] = value
        try:
            validate_base_binding(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"toy mismatch was accepted: {field}")
    print("fresh159 identity metadata toy checks passed")

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--trajectory-h5", type=Path)
    parser.add_argument("--xdmf", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.check:
        _toy_check()
        return 0
    required = (args.binding, args.trajectory_h5, args.xdmf, args.output_dir)
    if any(value is None for value in required):
        parser.error("--binding, --trajectory-h5, --xdmf, and --output-dir are required")
    binding = adapt_binding(args.binding)
    spec = importlib.util.spec_from_file_location("fresh138_original_bed_audit", ORIGINAL_WORKER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load original fresh138 worker")
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    with tempfile.TemporaryDirectory(prefix="f5-m086-identity-adapter-") as temp_dir:
        temp_binding = Path(temp_dir) / "identity-bound-binding.json"
        temp_binding.write_text(json.dumps(binding, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return int(original.main([
            "--binding", str(temp_binding),
            "--trajectory-h5", str(args.trajectory_h5),
            "--xdmf", str(args.xdmf),
            "--output-dir", str(args.output_dir),
        ]))

if __name__ == "__main__":
    raise SystemExit(main())
