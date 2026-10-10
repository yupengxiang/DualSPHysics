from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f6_producer_role_contract_v4.py"
SPEC = importlib.util.spec_from_file_location("f6_producer_role_contract_v4_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BASE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2")
MANIFEST = BASE / "requests/source-prepared276v8-primary-001/f6-initial-support-manifest-v8.json"
PARENT = BASE / "requests/reference-audit-root-forward-276-001.json"
PLAN = BASE / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json"
REGISTRY = BASE / "requests/typed-lifecycle-evidence-registry-v4-after-root307-001.json"
S095 = "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025"
S200 = "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025"


def test_f6_v4_binds_selected_root_proof_rows(tmp_path: Path) -> None:
    result = MODULE.build_contract_v4(
        MANIFEST, PARENT, current_plan_path=PLAN, registry_path=REGISTRY,
        case_ids={S095, S200}, output_path=tmp_path / "contract-v4.json",
    )
    assert result["schema"] == MODULE.SCHEMA
    assert set(result["current_v4_lifecycle"]["cases"]) == {S095, S200}
    for value in result["current_v4_lifecycle"]["cases"].values():
        assert value["mandatory_selected_proof_closure"]["selected_case_status"] == "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY"
    assert result["production_eligible"] is False


def test_f6_v4_rejects_missing_requested_case(tmp_path: Path) -> None:
    with pytest.raises(MODULE.F6ProducerRoleContractV4Error, match="CURRENT"):
        MODULE.build_contract_v4(
            MANIFEST, PARENT, current_plan_path=PLAN, registry_path=REGISTRY,
            case_ids={"F6_DOES_NOT_EXIST"}, output_path=tmp_path / "bad.json",
        )
