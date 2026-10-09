"""ROOT228 V4 immutable manifest/contract and strict overlay tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_root213_portable_typed_executor_v4.py"
ROOT222_BASE = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "STAGE2_F2_ROOT213_PORTABLE_TYPED_PARENT_ROOT222_V2/"
    "f2-s1-root213-root222-portable-typed-parent-root-forward-030-001"
)


def _load():
    spec = importlib.util.spec_from_file_location("root213_executor_v4_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v4_writes_new_manifest_and_contract_without_mutating_v1_pair(tmp_path, monkeypatch):
    module = _load()
    root = tmp_path / "attempt"
    root.mkdir()
    original_manifest = root / "metadata" / "root213-copy-manifest.json"
    original_contract = root / "metadata" / "root213-copy-contract.json"
    original_manifest.parent.mkdir()
    manifest = {
        "schema": "ds02.stage2.root213-copy-manifest.v1",
        "artifacts": [
            {"logical_role": "typed_scorer_v2", "target_relative_path": "runtime/a"},
            {"logical_role": "typed_scorer_v3", "target_relative_path": "runtime/b"},
        ],
        "sha256": "placeholder",
    }
    original_manifest.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    original_contract.write_text("{\"contract\":\"v1\"}\n")
    before_manifest = original_manifest.read_bytes()
    before_contract = original_contract.read_bytes()

    class Table:
        items = [dict(item) for item in manifest["artifacts"]]

    def original_builder(_request, _root, _started):
        return original_manifest, original_contract, {"table": Table(), "manifest": manifest}

    def fake_build_contract(*, manifest_path, relocated_root, output, contract_id):
        value = {
            "schema": "ds02.stage2.root213-copy-contract.v1",
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha(Path(manifest_path)),
            "relocated_root": str(relocated_root),
            "contract_id": contract_id,
        }
        Path(output).write_text(json.dumps(value, sort_keys=True) + "\n")
        return value

    monkeypatch.setattr(module.V3, "_ORIGINAL_MAKE_MANIFEST", original_builder)
    monkeypatch.setattr(module.V3.V2_EXECUTOR.V1.V1, "build_contract", fake_build_contract)
    request = {"attempt_id": "ROOT228-IMMUTABLE-MANIFEST-001"}
    v3_manifest, v3_contract, built = module._make_manifest_v4(request, root, 1.25)

    assert original_manifest.read_bytes() == before_manifest
    assert original_contract.read_bytes() == before_contract
    assert v3_manifest.name == "root213-copy-manifest-v3.json"
    assert v3_contract.name == "root213-copy-contract-v3.json"
    fresh = json.loads(v3_manifest.read_text())
    assert [x["logical_role"] for x in fresh["artifacts"]] == [
        "typed_only_evaluator_v2", "typed_only_evaluator_v3"
    ]
    assert fresh["forward_of"]["manifest_path"] == str(original_manifest)
    contract = json.loads(v3_contract.read_text())
    assert contract["manifest_path"] == str(v3_manifest)
    assert contract["manifest_sha256"] == _sha(v3_manifest)
    assert built["v1_manifest"] == str(original_manifest)
    assert built["v4_manifest"] == str(v3_manifest)


def test_v4_actual_root222_directory_alias_and_unknown_path_rejection(tmp_path):
    """Use the real ROOT222 small contract; deferred payloads stay absent."""
    if not ROOT222_BASE.is_dir():
        pytest.skip("ROOT222 production metadata is not present in this checkout")
    module = _load()
    contract_path = ROOT222_BASE / "portable" / "metadata" / "root213-copy-contract.json"
    if not contract_path.is_file():
        pytest.skip("ROOT222 production metadata contract is not present")
    original = json.loads(contract_path.read_text(encoding="utf-8"))
    staging = tmp_path / "relocated"
    staging.mkdir()
    for role in original["roles"]:
        target = staging / role["target_relative_path"]
        if role.get("deferred_content"):
            continue
        source = ROOT222_BASE / "portable" / role["target_relative_path"]
        assert source.is_file(), role["logical_role"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    staged = dict(original)
    staged["relocated_root"] = str(staging)
    for role in staged["roles"]:
        role["logical_role"] = {
            "typed_scorer_v2": "typed_only_evaluator_v2",
            "typed_scorer_v3": "typed_only_evaluator_v3",
        }.get(role["logical_role"], role["logical_role"])
    staged["sha256"] = module.V2_EXECUTOR.V1.V2._canonical(staged)
    staged_contract = staging / "metadata" / "contract.json"
    staged_contract.parent.mkdir(parents=True, exist_ok=True)
    staged_contract.write_text(json.dumps(staged, sort_keys=True) + "\n")

    module._install_hooks()
    try:
        overlay = staging / "requests" / "root228-v4-overlay.json"
        checked = module.V2_EXECUTOR.V1.V2.build_request_overlay(
            contract_path=staged_contract, request_role="root200_inner_request",
            output=overlay, request_target_relative="requests/rebound-inner.json",
            request_id="ROOT228-V4-METADATA-PROBE")
        value = module.V2_EXECUTOR.V1.V2.validate_request_overlay(overlay)
        inner = value["inner"]
        reports = str(staging / "reports")
        assert inner["v12_forward"]["output_root_rebind_v14"]["path"] == reports
        assert inner["output_root_rebind_provenance"]["new_output_root"] == reports
        assert inner["profile_rebind_provenance"]["proof_output_root"] == reports

        bad = json.loads((staging / "requests" / "rebound-inner.json").read_text())
        bad["unknown_actionable"] = {"path": "/unbound/root228/unknown.json"}
        # The actual overlay builder must reject this unregistered path; it is
        # not a provenance field and cannot be silently waived.
        bad_target = staging / "requests" / "bad-inner.json"
        bad_target.write_text(json.dumps(bad, sort_keys=True) + "\n")
        # Re-run the strict request walk directly so the negative exercises
        # the production V3 path policy without changing the sealed overlay.
        with pytest.raises(module.V2_EXECUTOR.V1.V2.PortableRebindV2Error):
            module.V2_EXECUTOR.V1.V2._verify_request_recursive(
                bad, staging, value["request"].get("nested_actionable_bindings", [])
                if isinstance(value.get("request"), dict) else [])
    finally:
        module._restore_hooks()
