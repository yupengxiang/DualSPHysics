from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_full_goal_rollup_v155_source_binding_audit_v1.py"
MANIFEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "full-goal-rollup-v155-final-code-binding-audit-v1-root-prepared-159-001/"
    / "full-goal-rollup-v155-final-code-binding-audit-v1-manifest.json"
)


def module():
    spec = importlib.util.spec_from_file_location("rollup_v155_binding_audit_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_audit_detects_stale_immutable_v155_worker_binding():
    loaded = module()
    report = loaded.audit(MANIFEST, Path("/tmp/unused-v155-binding-report.json"))
    assert report["status"] == "STALE_OLD_REQUEST_WORKER_BINDING"
    assert report["worker_binding"]["matches"] is False
    assert report["worker_binding"]["forward_request_required"] is True
    assert report["manifest_binding"]["matches"] is True
    assert report["input_audit"]["request_input_count"] == 111
    assert report["input_audit"]["manifest_source_ref_count"] == 110
    assert report["input_audit"]["all_referenced_inputs_are_json_or_python"] is True
    assert report["read_policy"]["h5_opened"] is False


def test_manifest_binds_immutable_old_request_and_current_worker_contract():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["contract"]["old_request_immutable"] is True
    assert manifest["contract"]["all_old_request_input_hashes_rechecked"] is True
    assert manifest["contract"]["new_request_required_on_worker_mismatch"] is True
    assert manifest["expected_current_worker_sha256"] == (
        "3fc9353eb5ce6102f029757bbcfd699773ab7b5b4464514b9013950c1ffe5e79"
    )
