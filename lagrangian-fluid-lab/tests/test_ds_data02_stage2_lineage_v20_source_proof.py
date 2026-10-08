from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_lineage_v20_source_proof.py"
SPEC = importlib.util.spec_from_file_location("lineage_v20_source_proof_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


CURRENT = ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"
AUDIT_DIR = ROOT / "campaigns/ds-data-02/stage2/lineage/v19-source-closure"
F7_REQUEST = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/f7-nvme-counterpart-v4/f7-s2-same-cfl-nvme-request-v4-001.json"
OBSERVER_PROFILE = ROOT / "campaigns/ds-data-02/stage2/replay/v15/f2-s1-observer-profile-v15-001.json"


def test_v20_rebinds_all_current_rows_and_seven_cards_without_large_reads(tmp_path: Path) -> None:
    result = MODULE.build(CURRENT, AUDIT_DIR, tmp_path / "proof", f7_request=F7_REQUEST,
                          observer_profile=OBSERVER_PROFILE)
    report = json.loads(Path(result["report"]).read_text())
    assert report["current_binding"]["case_count"] == 336
    assert report["current_binding"]["sha256"] == MODULE.file_sha256(CURRENT)
    assert set(report["family_cards"]) == {f"F{i}" for i in range(1, 8)}
    assert report["read_scope"]["hdf5_opened"] is False
    assert report["read_scope"]["bi4_opened"] is False
    assert report["qualification"] == MODULE.UNKNOWN
    assert report["f7_dense_request"]["native_save_interval_s"] == 0.01
    assert report["f7_dense_request"]["scientific_credit"] == "NONE_CROPPED_TIMEOUT"
    assert report["observer_profile"]["current_sha256"] == report["current_binding"]["sha256"]
    assert report["observer_profile"]["frozen_before_reference"] is True
    assert report["observer_profile"]["qualification"] == MODULE.UNKNOWN
    for family in report["family_cards"]:
        card = json.loads((tmp_path / "proof" / f"{family}-family-card-v20-source-proof.json").read_text())
        assert card["source_link_count"] == 48
        assert card["raw_anchor_policy"]["split_safe"] is False
        assert card["qualification"] == MODULE.UNKNOWN


def test_v20_rejects_a_card_that_claims_split_safe(tmp_path: Path) -> None:
    source = AUDIT_DIR / "F1-family-card-v19-development.json"
    original = json.loads(source.read_text())
    original["development_split"]["split_safe"] = True
    # The audit still points at the immutable original, so the mutation is
    # exercised through the same canonical check rather than by overwriting a
    # consumed card.
    mutated_audit = tmp_path / "audit"
    mutated_audit.mkdir()
    for path in AUDIT_DIR.glob("*.json"):
        target = mutated_audit / path.name
        target.write_text(path.read_text())
    mutated_card = mutated_audit / source.name
    mutated_card.write_text(json.dumps(original, indent=2, sort_keys=True) + "\n")
    audit_path = mutated_audit / "CURRENT336-effective-lineage-audit-v19-source-closure.json"
    audit = json.loads(audit_path.read_text())
    audit["family_cards"]["F1"]["sha256"] = original["sha256"]
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    with pytest.raises(MODULE.SourceProofError, match="embedded SHA|split safety"):
        MODULE.build(CURRENT, mutated_audit, tmp_path / "out")
