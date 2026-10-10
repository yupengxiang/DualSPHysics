from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace330_scoped_v6.py"
SPEC = importlib.util.spec_from_file_location("namespace330_scoped_v6_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
BASE = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT = BASE / "CURRENT336.json"
PLAN = BASE / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json"
REGISTRY = BASE / "requests/typed-lifecycle-evidence-registry-v4-after-root307-001.json"


def test_v6_excludes_unresolved_alias_from_canonical_cards(tmp_path: Path) -> None:
    built = MODULE.build_namespace330_scoped_v6(
        current_path=CURRENT, plan_path=PLAN, registry_path=REGISTRY,
        output_dir=tmp_path / "v6-output",
    )
    assert built["coverage"]["canonical_current_saved_mask_cases"] == 335
    assert built["coverage"]["historical_alias_unresolved"] == 1
    loaded = MODULE.load_namespace330_scoped_v6(tmp_path / "v6-output")
    assert loaded["canonical_case_count"] == 335
    assert loaded["historical_alias_count"] == 1

    catalog = json.loads(Path(built["catalog_path"]).read_text(encoding="utf-8"))
    aliases = [row for row in catalog["cases"] if row["canonical_case_id"] is None]
    assert len(aliases) == 1
    alias = aliases[0]
    assert alias["identity"]["identity_credit"] is False
    assert alias["identity"]["historical_reference_case_id"] == alias["physical_case_id"]
    assert alias["lifecycle"]["status"] == MODULE.ALIAS_STATUS

    cards = catalog["cards"]
    assert len(cards["F2"]["canonical_case_ids"]) == 47
    assert cards["F2"]["historical_reference_case_ids"] == [alias["physical_case_id"]]
    for family in ("F1", "F3", "F4", "F5", "F6", "F7"):
        assert len(cards[family]["canonical_case_ids"]) == 48
        assert cards[family]["historical_reference_case_ids"] == []


def test_v6_loader_rejects_alias_reintroduced_as_canonical(tmp_path: Path) -> None:
    built = MODULE.build_namespace330_scoped_v6(
        current_path=CURRENT, plan_path=PLAN, registry_path=REGISTRY,
        output_dir=tmp_path / "v6-output",
    )
    catalog_path = Path(built["catalog_path"])
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    alias = next(row for row in catalog["cases"] if row["canonical_case_id"] is None)
    alias["canonical_case_id"] = alias["physical_case_id"]
    alias["identity"]["canonical_case_id"] = alias["physical_case_id"]
    catalog["sha256"] = MODULE.canonical_sha(catalog)
    catalog_path.write_text(json.dumps(catalog, sort_keys=True), encoding="utf-8")
    with pytest.raises(MODULE.Namespace330ScopedV6Error, match="canonical/alias cardinality"):
        MODULE.load_namespace330_scoped_v6(tmp_path / "v6-output")
