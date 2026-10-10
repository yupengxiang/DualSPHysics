from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_canonical65_raw_to_typed_phase_v1.py"
SPEC = importlib.util.spec_from_file_location("canonical65_phase_v1_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
CURRENT = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json"
CATALOG = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v35-namespace330-v6-root307-actual335-physical-policy-primary-001/namespace330-scoped-v6-root307-catalog.json"
PHYSICAL = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v27-effective-condition-directory-root307-001/EFFECTIVE_PHYSICAL_UNION_INDEX_V27.json"
PROOF = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/TYPED_LIFECYCLE_BATCH_F2_ACTUAL_ROOT_VERIFICATION_206.json"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")


def _build(tmp_path: Path) -> dict:
    return MODULE.build_phase(
        current_path=CURRENT, catalog_path=CATALOG, physical_index_path=PHYSICAL,
        proof_path=PROOF, repo_root=PRIMARY, decoder_path=DECODER,
        output_dir=tmp_path / "phase", attempt_id="test-canonical65-phase",
    )


def test_actual_row65_phase_is_parent_ready_but_not_worker_ready(tmp_path: Path) -> None:
    result = _build(tmp_path)
    assert result["status"] == "READY_FOR_PARENT_PHASE_GUARD"
    assert result["worker_ready"] is False
    assert result["launch_allowed"] is False
    request_path = Path(result["request"]["path"])
    request = json.loads(request_path.read_text())
    assert MODULE.validate_phase(request_path)["status"] == "VALIDATED_PARENT_PHASE_GUARD_REQUIRED"
    assert request["case_identity"]["current_case_index"] == 65
    assert request["case_identity"]["physical_case_id"] == MODULE.CANONICAL_ID
    assert request["raw_binding"]["expected_raw_tree_sha256"] == MODULE.PENDING
    assert len(request["raw_binding"]["frames"]) == 401
    assert len(request["typed_output_contract"]["expected_times_s"]) == 401
    assert request["cohort"]["expected_initial_fluid_count"] == 21114
    assert request["initial_mass_denominator"]["denominator_kg"] == pytest.approx(21.114001002861187)
    assert request["next_phase"] == "typed_to_label_from_actual_raw_to_typed_receipt"
    assert request["evidence_scope"]["scientific_credit"] == "NONE"
    assert request["source_fallback"] == "REJECT"


def test_phase_rejects_false_ready_before_parent_content_hash(tmp_path: Path) -> None:
    result = _build(tmp_path)
    request_path = Path(result["request"]["path"])
    request = json.loads(request_path.read_text())
    request["status"] = "READY_FOR_PARENT_GUARD"
    bad = tmp_path / "false-ready.json"
    bad.write_text(json.dumps(request), encoding="utf-8")
    with pytest.raises(MODULE.PhaseError, match="parent-content pending"):
        MODULE.validate_phase(bad)


def test_canonical_selector_rejects_historical_row78_alias() -> None:
    rows = [{"physical_case_id": f"case-{index}", "family_id": "F2"} for index in range(336)]
    rows[65] = {"physical_case_id": MODULE.CANONICAL_ID, "family_id": "F2"}
    rows[78] = {"physical_case_id": MODULE.HISTORICAL_ALIAS_ID, "family_id": "F2"}
    current = {"schema": "ds02.stage2.current336.v1", "cases": rows}
    with pytest.raises(MODULE.PLANNER.AnchorError, match="historical unresolved"):
        MODULE.PLANNER.select_canonical(current, index=78)
