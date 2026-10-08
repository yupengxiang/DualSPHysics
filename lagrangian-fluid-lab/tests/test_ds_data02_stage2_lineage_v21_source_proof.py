from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_lineage_v21_source_proof.py"
SPEC = importlib.util.spec_from_file_location("lineage_v21_source_proof_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

V20_DIR = ROOT / "campaigns/ds-data-02/stage2/lineage/v20-source-proof-002"
SCIENTIFIC = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
    "SCIENTIFIC_AUDIT_VERIFICATION_023.json"
)
IMPACT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
    "ALL118_IMPACT_V8_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
)


def test_v21_binds_actual_proofs_and_preserves_conservative_cards(tmp_path: Path) -> None:
    result = MODULE.build(
        ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json",
        V20_DIR,
        tmp_path / "proof",
        scientific_audit=SCIENTIFIC,
        impact_proof=IMPACT,
    )
    report_path = Path(result["report"])
    report = json.loads(report_path.read_text())
    assert report["schema"] == "ds02.stage2.current336-source-proof.v21"
    assert report["qualification"] == MODULE.UNKNOWN
    assert report["split_policy"]["split_safe"] is False
    assert report["evidence_bindings"]["scientific_audit_v23"]["distinct_completed_cases"] == 336
    assert report["evidence_bindings"]["impact_v8_all118"]["coverage"]["full_source_case_count"] == 118
    assert report["read_scope"]["hdf5_opened"] is False
    assert set(report["family_cards"]) == set(MODULE.FAMILIES)
    assert report["sha256"] == MODULE.canonical_sha(report)
    for family in MODULE.FAMILIES:
        card_path = Path(result["cards"][family])
        card = json.loads(card_path.read_text())
        assert card["qualification"] == MODULE.UNKNOWN
        assert card["actual_evidence_scope"]["scientific_audit_v23"]["case_count"] == 48
        assert card["raw_anchor_policy"]["split_safe"] is False
        assert card["sha256"] == MODULE.canonical_sha(card)


def test_v21_rejects_a_completion_or_raw_read_claim(tmp_path: Path) -> None:
    bad_scientific = tmp_path / "bad-scientific.json"
    value = json.loads(SCIENTIFIC.read_text())
    value["goal_complete"] = True
    bad_scientific.write_text(json.dumps(value))
    with pytest.raises(MODULE.SourceProofV21Error, match="completion claim"):
        MODULE.build(
            ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json",
            V20_DIR,
            tmp_path / "proof",
            scientific_audit=bad_scientific,
            impact_proof=IMPACT,
        )
