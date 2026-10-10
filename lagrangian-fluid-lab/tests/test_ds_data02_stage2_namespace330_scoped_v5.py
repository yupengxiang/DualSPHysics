from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace330_scoped_v5.py"
SPEC = importlib.util.spec_from_file_location("namespace330_scoped_v5_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
BASE = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT = BASE / "CURRENT336.json"
PLAN = BASE / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json"
REGISTRY = BASE / "requests/typed-lifecycle-evidence-registry-v4-after-root307-001.json"


def test_root307_builds_dynamic_335_plus_alias_cards(tmp_path: Path) -> None:
    built = MODULE.build_namespace330_scoped_v5(
        current_path=CURRENT, plan_path=PLAN, registry_path=REGISTRY,
        output_dir=tmp_path / "v5-output", request_id="namespace330-v5-test-001",
    )
    assert built["coverage"]["actual_saved_mask_cases"] == 335
    assert built["coverage"]["historical_alias_unresolved"] == 1
    assert built["coverage"]["failed_retry_history_entries"] == 8
    loaded = MODULE.load_namespace330_scoped_v5(tmp_path / "v5-output")
    assert loaded["case_count"] == 336
    catalog = json.loads(Path(built["catalog_path"]).read_text(encoding="utf-8"))
    assert catalog["qualification"] == MODULE.UNKNOWN
    assert all(row["claim_boundary"].startswith("saved-mask lifecycle") for row in catalog["cases"])
    alias = [row for row in catalog["cases"] if row["lifecycle"]["status"] == MODULE.ALIAS_STATUS]
    assert len(alias) == 1
    assert alias[0]["lifecycle"]["producer_id"] is None
    retry = next(row for row in catalog["cases"] if row["physical_case_id"] == "F5_COMPACT_RUNUP_RECOVERY_C082S1_M105_T100")
    assert retry["lifecycle"]["producer_id"] == "ROOT327"
    assert retry["lifecycle"]["failed_history_count"] == 1


def test_root307_plan_must_bind_the_pinned_current_catalog(tmp_path: Path) -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    plan["current_catalog"]["sha256"] = "0" * 64
    bad_plan = tmp_path / "bad-plan.json"
    bad_plan.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.Namespace330ScopedV5Error, match="plan CURRENT catalog"):
        MODULE.build_namespace330_scoped_v5(
            current_path=CURRENT, plan_path=bad_plan, registry_path=REGISTRY,
            output_dir=tmp_path / "bad-output",
        )
