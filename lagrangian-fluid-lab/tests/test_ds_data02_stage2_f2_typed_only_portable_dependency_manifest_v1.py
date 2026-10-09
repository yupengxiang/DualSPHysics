"""Metadata-only portability audit tests for the consumed F2 typed product."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_portable_dependency_manifest_v1.py"
RESULT = Path(
    "/var/tmp/ds02-stage2/F2/STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_20261009/"
    "products/v16-reconstructed-label-result-v2.json"
)


def _load():
    spec = importlib.util.spec_from_file_location("f2_portable_dependency_manifest_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not RESULT.is_file(), reason="ROOT179C typed result is not mounted")
def test_real_manifest_binds_evidence_and_defers_payload(tmp_path: Path):
    audit = _load()
    output = tmp_path / "typed-only-portable-manifest.json"
    manifest = audit.build_manifest(output=output)
    checked = audit.validate_manifest(output)
    assert checked["status"] == "PORTABLE_DEPENDENCY_MANIFEST_VALIDATED"
    assert checked["payload_read"] is False
    assert checked["large_payload_content_read"] is False
    assert manifest["runtime_import_closure"]["external_import_roots"] == ["h5py", "numpy"]
    loading = manifest["portable_loading_entry"]
    assert loading["entrypoint_target_relative_path"].startswith("runtime/")
    assert loading["request_target_relative_path"].startswith("evidence/")
    assert loading["source_fallback"] == "REJECT"
    assert loading["argv0_policy"] == "literal_shared_venv_only"
    assert loading["standalone_python_claim"] is False
    assert loading["no_model"] is True
    assert loading["model_invoked"] is False
    assert loading["payload_read_phase"] == "parent_after_reservation_pre_post_stat_and_SHA_gate"
    assert {gap["id"] for gap in manifest["identified_portability_gaps"]} == {
        "G1_RESULT_REBIND", "G2_V15_REBIND", "G3_CANONICAL_SIBLING_NAMES",
        "G4_EXTERNAL_ABI", "G5_CURRENT_ALIAS", "G6_DEFERRED_CONTENT",
    }
    deferred = {item["logical_role"]: item for item in manifest["artifacts"]
                if item["source_kind"] in {"deferred_result_json", "deferred_typed_h5", "source_provenance_deferred_h5"}}
    assert deferred["root179c_typed_result_deferred"]["content_read_by_manifest"] is False
    assert deferred["root179c_typed_h5_deferred"]["content_read_by_manifest"] is False
    for item in manifest["artifacts"]:
        assert item["source_stat_is_target_claim"] is False


def test_fixture_rejects_actionable_original_path_but_keeps_provenance():
    audit = _load()
    original = "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/runtime/module.py"
    audit.validate_actionable_mapping({"provenance": {"path": original}}, original_roots=("/home/jade/.codex",))
    with pytest.raises(audit.ManifestError, match="actionable original absolute path"):
        audit.validate_actionable_mapping({"execution": {"path": original}}, original_roots=("/home/jade/.codex",))


@pytest.mark.skipif(not RESULT.is_file(), reason="ROOT179C typed result is not mounted")
def test_manifest_rejects_tampered_canonical_sha_without_payload_read(tmp_path: Path):
    audit = _load()
    output = tmp_path / "typed-only-portable-manifest.json"
    audit.build_manifest(output=output)
    value = json.loads(output.read_text(encoding="utf-8"))
    value["path_policy"]["original_absolute_path_fallback"] = "ALLOW"
    output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(audit.ManifestError, match="canonical SHA"):
        audit.validate_manifest(output)
