from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_namespace330_v4_actual_verify_v2.py"
SPEC = importlib.util.spec_from_file_location("namespace330_verify_v2_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


PRODUCT = (
    ROOT
    / "campaigns"
    / "ds-data-02"
    / "stage2"
    / "lineage"
    / "v27-namespace330-v4-root299-actual263-001"
)
def _catalog_bound_plan() -> Path:
    catalog = json.loads(
        (PRODUCT / "namespace330-scoped-v4-catalog.json").read_text(encoding="utf-8")
    )
    ref = next(item for item in catalog["source_inputs"]
               if item.get("role") == "typed_lifecycle_registry")
    return Path(ref["path"])


ROOT299_PLAN = _catalog_bound_plan() if PRODUCT.is_dir() else Path("/missing/root299-plan")
ROOT300_PLAN = ROOT299_PLAN.with_name("CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT300_V4.json")


@pytest.mark.skipif(not PRODUCT.is_dir() or not ROOT299_PLAN.is_file(), reason="metadata product is not present")
def test_dynamic_verifier_joins_real_plan_registry_and_native_rows():
    report = MODULE.verify_namespace330_v4_dynamic(PRODUCT)
    plan = json.loads(ROOT299_PLAN.read_text(encoding="utf-8"))

    assert report["status"] == "VERIFIED_METADATA_ONLY_DYNAMIC_COVERAGE"
    assert report["coverage"] == plan["coverage"]
    assert report["case_count_checked"] == report["coverage"]["current_cases"]
    assert report["native"]["proof_file_rows"] == report["native"]["catalog_matching_case_rows"]
    assert report["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert report["read_scope"]["payload_opened"] is False
    assert report["read_scope"]["trajectory_h5_opened"] is False


@pytest.mark.skipif(not PRODUCT.is_dir() or not ROOT300_PLAN.is_file(), reason="metadata product/next plan is not present")
def test_verifier_rejects_unbound_plan_override():
    with pytest.raises(MODULE.Namespace330V4DynamicVerificationError, match="not the path bound"):
        MODULE.verify_namespace330_v4_dynamic(PRODUCT, plan_path=ROOT300_PLAN)
