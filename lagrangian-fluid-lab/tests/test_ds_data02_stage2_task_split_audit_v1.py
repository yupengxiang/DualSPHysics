from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_task_split_audit_v1.py"
spec = importlib.util.spec_from_file_location("task_split_audit_v1", SCRIPT)
assert spec and spec.loader
AUDIT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(AUDIT)


def test_f1_anchor_validator_keeps_reference_and_portable_claims_separate(tmp_path: Path) -> None:
    payload = {
        "schema": "ds02.stage2.f1-full161-raw-reconstruction-independent.v1",
        "status": "PASS_ACTUAL_FULL_RAW_RECONSTRUCTION_BYTE_IDENTICAL_CURRENT_TYPED",
        "root_original_reference_h5_reread": False,
        "root_native_raw_reread": False,
        "all_typed_fields_and_entire_file_byte_identity_verified": True,
        "portable_trial_completed": False,
    }
    path = tmp_path / "f1-proof.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    record = {"evidence_id": "f1", "kind": "f1_raw_to_typed_proof", "path": str(path), "sha256": AUDIT.sha256_file(path)}
    normalized = AUDIT._validate_evidence_record(record, "d" * 64, 336)
    assert normalized["kind"] == "f1_raw_to_typed_proof"


def test_task_role_map_excludes_partial_components() -> None:
    base = {"components": [
        {"component_id": "a", "members": [{"family_id": "F1", "physical_case_id": "A"}, {"family_id": "F1", "physical_case_id": "B"}]},
        {"component_id": "b", "members": [{"family_id": "F2", "physical_case_id": "C"}]},
    ]}
    roles, partial, eligible = AUDIT._role_map(base, {("F1", "A"), ("F2", "C")})
    assert partial == {("F1", "A")}
    assert eligible == {"b"}
    assert roles == {"b": "development_train"}


@pytest.mark.skipif(
    not Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v19-source-closure/CURRENT336-effective-lineage-audit-v19-source-closure.json").is_file(),
    reason="primary v19 lineage is not mounted",
)
def test_actual_task_products_resolve_without_h5_reads(tmp_path: Path) -> None:
    current = ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"
    lineage = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v19-source-closure/CURRENT336-effective-lineage-audit-v19-source-closure.json")
    index = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v22-source-proof/SEVEN_FAMILY_SOURCE_ACCESS_INDEX_V22.json")
    manifest = ROOT / "campaigns/ds-data-02/stage2/requests/current336-task-split-evidence-v1.json"
    result = AUDIT.audit(current, lineage, index, manifest)
    by_task = {row["task_id"]: row for row in result["tasks"]}
    assert result["diagnostics"]["h5_bi4_trajectory_opened"] is False
    assert by_task["metadata_lineage_audit"]["eligible_case_count"] == 336
    assert by_task["native_cause_mass_censoring"]["eligible_case_count"] == 118
    assert by_task["raw_to_typed_identity"]["eligible_case_count"] == 1
    assert by_task["label_source_role_diagnostics"]["role_case_counts"] == {
        "development_train": 1, "development_validation": 1, "development_test": 1,
    }
    assert all(
        case["global_promotion_status_unchanged"] == "UNRESOLVED_EXCLUDED"
        for task in result["tasks"] for case in task["cases"]
    )
