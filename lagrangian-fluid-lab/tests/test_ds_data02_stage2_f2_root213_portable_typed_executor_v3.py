"""ROOT228 directory-alias closure tests for executor V3."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_root213_portable_typed_executor_v3.py"
ROOT222_BASE = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "STAGE2_F2_ROOT213_PORTABLE_TYPED_PARENT_ROOT222_V2/"
    "f2-s1-root213-root222-portable-typed-parent-root-forward-030-001"
)


def _load():
    spec = importlib.util.spec_from_file_location("root213_executor_v3_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_v14_directory_alias_requires_schema_and_predicate():
    module = _load()
    value = {
        "v12_forward": {"output_root_rebind_v14": {
            "path": "/old/current",
            "new_output_root": "/old/current",
            "old_v13_output_root": "/old/v13",
            "proof_output_only": True,
            "schema": module.V14_OUTPUT_SCHEMA,
        }},
        "output_root_rebind_provenance": {
            "new_output_root": "/old/current", "old_output_root": "/old/v13"
        },
        "profile_rebind_provenance": {"proof_output_root": "/old/current"},
    }
    info = module._prepare_alias_info(value)
    assert info["aliases"][("v12_forward", "output_root_rebind_v14")]["source"] == "/old/current"
    assert info["manual"][("profile_rebind_provenance", "proof_output_root")]["source"] == "/old/current"
    bad = json.loads(json.dumps(value))
    bad["v12_forward"]["output_root_rebind_v14"]["schema"] = "wrong"
    with pytest.raises(module.Root213ExecutorV3Error):
        module._prepare_alias_info(bad)


def test_actual_root222_inner_builds_overlay_with_closed_directory_alias(tmp_path: Path):
    """Run the real V2 overlay builder on ROOT222's small copied metadata.

    Only non-deferred roles are copied to the temporary staging root.  The
    deferred V16/H5/raw roles remain absent, so this exercises the complete
    metadata path rewrite without reading any production payload.
    """
    contract_path = ROOT222_BASE / "portable" / "metadata" / "root213-copy-contract.json"
    if not contract_path.is_file():
        pytest.skip("ROOT222 production metadata is not present in this checkout")
    module = _load()
    original = json.loads(contract_path.read_text(encoding="utf-8"))
    staging = tmp_path / "relocated"
    staging.mkdir()
    for role in original["roles"]:
        target = staging / role["target_relative_path"]
        if role.get("deferred_content"):
            continue
        source_target = ROOT222_BASE / "portable" / role["target_relative_path"]
        assert source_target.is_file(), role["logical_role"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_target, target)
    staged_contract = dict(original)
    staged_contract["relocated_root"] = str(staging)
    # ROOT222 was produced before the alias-name forward fix.  Recreate the
    # V3 fresh-contract normalization in this metadata-only staging copy;
    # source bytes and target paths remain identical.
    for role in staged_contract["roles"]:
        role["logical_role"] = {
            "typed_scorer_v2": "typed_only_evaluator_v2",
            "typed_scorer_v3": "typed_only_evaluator_v3",
        }.get(role["logical_role"], role["logical_role"])
    staged_contract["sha256"] = module.V2_EXECUTOR.V1.V2._canonical(staged_contract)
    contract = staging / "metadata" / "contract.json"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(json.dumps(staged_contract, sort_keys=True) + "\n", encoding="utf-8")
    overlay = staging / "requests" / "root228-v3-overlay.json"
    module._install_hooks()
    try:
        module.V2_EXECUTOR.V1.V2.build_request_overlay(
            contract_path=contract, request_role="root200_inner_request",
            output=overlay, request_target_relative="requests/rebound-inner.json",
            request_id="ROOT228-METADATA-PROBE")
        checked = module.V2_EXECUTOR.V1.V2.validate_request_overlay(overlay)
    finally:
        module._restore_hooks()
    inner = checked["inner"]
    assert inner["v12_forward"]["output_root_rebind_v14"]["path"] == str(staging / "reports")
    assert inner["output_root_rebind_provenance"]["new_output_root"] == str(staging / "reports")
    assert inner["profile_rebind_provenance"]["proof_output_root"] == str(staging / "reports")
    assert inner["source_metadata_provenance"]["path"].startswith(str(staging))
    assert all(not (isinstance(v, str) and "ROOT200_V14_PROFILE_OUTPUT_ROOT" in v)
               for v in inner["v12_forward"]["output_root_rebind_v14"].values())
