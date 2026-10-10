from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f6_producer_role_contract_v2.py"
SPEC = importlib.util.spec_from_file_location("f6_producer_role_contract_v2_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
BASE = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
MANIFEST = BASE / "requests/source-prepared276v8-primary-001/f6-initial-support-manifest-v8.json"
PARENT = BASE / "requests/reference-audit-root-forward-276-001.json"
PLAN = BASE / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT306_V4.json"
REGISTRY = BASE / "requests/typed-lifecycle-evidence-registry-v4-after-root306-001.json"
S095 = "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025"
S200 = "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025"


def _build(tmp_path: Path, *, manifest: Path = MANIFEST, parent: Path = PARENT, plan: Path = PLAN) -> dict:
    return MODULE.build_contract_v2(
        manifest, parent, current_plan_path=plan, registry_path=REGISTRY,
        case_ids={S095, S200}, output_path=tmp_path / "contract.json",
    )


def test_real_root276_manifest_and_v4_plan_registry_bind_s095_s200(tmp_path: Path) -> None:
    result = _build(tmp_path)
    assert result["schema"] == MODULE.SCHEMA
    assert result["status"] == "SOURCE_PREPARED_CURRENT_V4_LIFECYCLE_METADATA_ONLY"
    assert result["production_eligible"] is False
    assert result["launch_performed"] is False
    assert result["root276_launch_status"] == "WAIT_ONLY_NOT_LAUNCHED"
    assert set(result["current_v4_lifecycle"]["cases"]) == {S095, S200}
    assert all(item["status"] == MODULE.CURRENT_STATUS for item in result["current_v4_lifecycle"]["cases"].values())
    assert all(item["source_closure"] == MODULE.SOURCE_CLOSURE for item in result["current_v4_lifecycle"]["cases"].values())
    assert all(item["scientific_credit"] == "NONE_PHYSICAL_SAVED_MASK_ONLY" for item in result["current_v4_lifecycle"]["cases"].values())
    assert result["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_real_plan_alias_mutation_is_rejected(tmp_path: Path) -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    row = next(row for row in plan["case_records"] if row["physical_case_id"] == S095)
    row["historical_alias"] = "HISTORICAL_ALIAS_UNRESOLVED"
    bad_plan = tmp_path / "plan-alias.json"
    bad_plan.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.F6ProducerRoleContractV2Error, match="historical_alias"):
        _build(tmp_path, plan=bad_plan)


def test_root276_parent_manifest_path_and_sha_are_strict(tmp_path: Path) -> None:
    parent = json.loads(PARENT.read_text(encoding="utf-8"))
    parent["manifest"]["sha256"] = "0" * 64
    bad_parent = tmp_path / "parent-manifest-mismatch.json"
    bad_parent.write_text(json.dumps(parent, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.F6ProducerRoleContractV2Error, match="parent manifest SHA"):
        _build(tmp_path, parent=bad_parent)


def test_registry_schema_is_not_generic_stage2(tmp_path: Path) -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["schema"] = "ds02.stage2.lifecycle-producer-registry.v1"
    bad_registry = tmp_path / "registry-generic.json"
    bad_registry.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    old = MODULE.REGISTRY_SCHEMA
    try:
        # The builder accepts an explicit registry path; this test also keeps
        # the real v4 input immutable while exercising the exact schema gate.
        with pytest.raises(MODULE.F6ProducerRoleContractV2Error, match="registry schema"):
            MODULE.build_contract_v2(
                MANIFEST, PARENT, current_plan_path=PLAN, registry_path=bad_registry,
                case_ids={S095, S200}, output_path=tmp_path / "bad.json",
            )
    finally:
        assert MODULE.REGISTRY_SCHEMA == old

