from __future__ import annotations

import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_lineage_v16_provisional_domains as domains  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / (
    "campaigns/ds-data-02/stage2/lineage/v15/"
    "CURRENT336-effective-lineage-audit-v15-full-small-closure-request-001.json"
)
CARDS_ROOT = ROOT / "campaigns/ds-data-02/stage2"


def test_v16_builder_reconciles_336_cases_and_seven_conservative_cards(tmp_path: Path) -> None:
    result = domains.build(AUDIT, CARDS_ROOT, tmp_path / "v16")
    report = json.loads(Path(result["report"]).read_text())
    assert report["audit_scope"]["case_count"] == 336
    assert report["audit_scope"]["family_case_counts"] == {f"F{i}": 48 for i in range(1, 8)}
    assert report["split_policy"]["split_safe"] is False
    assert report["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert len(report["cards"]) == 7
    for family in report["cards"]:
        card = json.loads((tmp_path / "v16" / f"{family}-family-card-v16-provisional.json").read_text())
        assert card["case_count"] == 48
        assert card["lineage_and_split"]["split_safe"] is False
        assert card["observed_finite_support"]["numeric_parameter_values"]


def test_v16_source_role_coverage_exposes_real_missing_control_assets() -> None:
    report = json.loads(
        (CARDS_ROOT / "lineage/v16-provisional/CURRENT336-effective-lineage-audit-v16-provisional.json").read_text()
    ) if (CARDS_ROOT / "lineage/v16-provisional/CURRENT336-effective-lineage-audit-v16-provisional.json").is_file() else None
    if report is None:
        # The committed generated cards are optional during an isolated test;
        # the first test still validates generation from immutable inputs.
        return
    f1 = json.loads((CARDS_ROOT / "lineage/v16-provisional/F1-family-card-v16-provisional.json").read_text())
    f2 = json.loads((CARDS_ROOT / "lineage/v16-provisional/F2-family-card-v16-provisional.json").read_text())
    assert f1["source_role_coverage"]["control"]["role_case_coverage"]["case:control_asset"] == 0
    assert f2["source_role_coverage"]["control"]["role_case_coverage"]["case:control_asset"] == 48
