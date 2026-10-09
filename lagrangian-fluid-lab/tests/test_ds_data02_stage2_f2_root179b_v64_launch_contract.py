"""Source-only contract checks for the ROOT179B V64 primary entry.

The positive case uses the root-prepared candidate request when that shared
source is present.  It invokes the bound V64 metadata validator only; it does
not reserve a ledger, launch a child, or open BI4/HDF5/raw payloads.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_root179b_v64_launch_contract_v1.py"
ROOT_REQUEST = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f2-s1-root145-v64-root179b-primary-prepared-002.json"
)
ROOT_FILE_SHA = "d83e5aaabdf9a8863a10abf654995ea868364ca1d0f171f9b2e676241cf73570"
ROOT_CANONICAL_SHA = "ccddfb549a33eab8178a5f1c859e1dea7938008a300d8c784396586816d7129f"


def _load():
    spec = importlib.util.spec_from_file_location("root179b_v64_contract_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not ROOT_REQUEST.is_file(), reason="root-prepared candidate is not mounted")
def test_root179b_candidate_passes_real_bound_v64_metadata_preflight():
    module = _load()
    plan = module.inspect_request(
        ROOT_REQUEST,
        expected_file_sha=ROOT_FILE_SHA,
        expected_canonical_sha=ROOT_CANONICAL_SHA,
    )

    assert plan["status"] == "READY_FOR_PRIMARY_V64_GUARDED_RUN"
    assert plan["payload_read"] is False
    assert plan["hdf5_or_bi4_content_read"] is False
    assert plan["ledger_mutated"] is False
    assert plan["request"]["file_sha256"] == ROOT_FILE_SHA
    assert plan["request"]["canonical_sha256"] == ROOT_CANONICAL_SHA
    assert plan["parent_entry"]["same_parent_ledger"] is True
    assert plan["parent_entry"]["reservation_id"].endswith("::reservation")
    assert plan["parent_entry"]["charge_id"].endswith("::charge")
    assert plan["child_entry"]["literal_python"] == module.PINNED_VENV
    assert plan["child_entry"]["resolved_python_provenance"] == module.RESOLVED_SYSTEM_PYTHON
    assert "--io-slot-approved" in plan["child_entry"]["command"]
    assert "--run-labels" in plan["child_entry"]["command"]
    assert plan["resources"]["max_wall_seconds"] == 6000.0
    assert plan["resources"]["memory_max_bytes"] == 16 * 1024**3
    assert plan["resources"]["external_reservation_bytes"] == 12 * 1024**3
    assert plan["resources"]["external_min_free_bytes"] == 20 * 1024**3
    assert plan["resources"]["home_receipt_bytes"] >= 1024**2
    assert plan["terminal"]["apply_scope"].startswith("same-parent CPU/storage metadata delta only")
    assert plan["fresh_v65"]["status"] == "DEFERRED_UNTIL_V64_SUCCESS"


@pytest.mark.skipif(not ROOT_REQUEST.is_file(), reason="root-prepared candidate is not mounted")
def test_root179b_candidate_sha_binding_is_strict():
    module = _load()
    with pytest.raises(module.LaunchContractError, match="file SHA"):
        module.inspect_request(ROOT_REQUEST, expected_file_sha="0" * 64)
    with pytest.raises(module.LaunchContractError, match="canonical SHA"):
        module.inspect_request(ROOT_REQUEST, expected_canonical_sha="1" * 64)


def test_command_contract_keeps_literal_venv_distinct_from_resolved_provenance():
    module = _load()
    assert module.PINNED_VENV != module.RESOLVED_SYSTEM_PYTHON
    assert module.PINNED_VENV.endswith("/.venv/bin/python")
    assert module.RESOLVED_SYSTEM_PYTHON == "/usr/bin/python3.10"
