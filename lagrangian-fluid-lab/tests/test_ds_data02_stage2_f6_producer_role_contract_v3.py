from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f6_producer_role_contract_v3.py"
SPEC = importlib.util.spec_from_file_location("f6_producer_role_contract_v3_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
BASE = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
MANIFEST = BASE / "requests/source-prepared276v8-primary-001/f6-initial-support-manifest-v8.json"
PARENT = BASE / "requests/reference-audit-root-forward-276-001.json"
PLAN = BASE / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json"
REGISTRY = BASE / "requests/typed-lifecycle-evidence-registry-v4-after-root307-001.json"
S095 = "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025"
S200 = "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025"


def test_real_root276_manifest_input_tables_and_latest_plan_registry_bind(tmp_path: Path) -> None:
    result = MODULE.build_contract_v3(
        MANIFEST, PARENT, current_plan_path=PLAN, registry_path=REGISTRY,
        case_ids={S095, S200}, output_path=tmp_path / "contract-v3.json",
    )
    assert result["schema"] == MODULE.SCHEMA
    assert result["parent_task"]["manifest_binding"]["input_sha256_bound"] is True
    assert result["parent_task"]["manifest_binding"]["input_record_bound"] is True
    assert result["parent_task"]["manifest_binding"]["root_canonical_bound"] is True
    assert result["current_v4_lifecycle"]["plan"]["path"].endswith("CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json")
    assert set(result["current_v4_lifecycle"]["cases"]) == {S095, S200}
    assert result["production_eligible"] is False
    assert result["launch_performed"] is False


def test_missing_parent_manifest_input_hash_table_is_rejected(tmp_path: Path) -> None:
    parent = json.loads(PARENT.read_text(encoding="utf-8"))
    manifest_key = str(MANIFEST)
    parent["input_sha256"].pop(manifest_key)
    bad = tmp_path / "parent-no-input-hash.json"
    bad.write_text(json.dumps(parent, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.F6ProducerRoleContractV3Error, match="input_sha256"):
        MODULE.build_contract_v3(
            MANIFEST, bad, current_plan_path=PLAN, registry_path=REGISTRY,
            case_ids={S095}, output_path=tmp_path / "bad.json",
        )

