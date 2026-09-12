import json
from pathlib import Path

import pytest

from scripts import f3_revision075_launch_gate as gate


def _copies(tmp_path):
    manifest = tmp_path / "manifest.json"
    summary = tmp_path / "summary.json"
    limits = tmp_path / "limits.json"
    manifest.write_bytes(gate.MANIFEST.read_bytes())
    summary.write_bytes(gate.SUMMARY.read_bytes())
    limits.write_bytes(gate.LIMITS.read_bytes())
    return manifest, summary, limits


def _authorization(tmp_path, manifest, summary, **overrides):
    payload = {
        "schema": gate.SCHEMA,
        "status": "approved",
        "owner_reply": "owner approved revision075",
        "recipe_id": gate.RECIPE,
        "existing_evidence": sorted(gate.REQUIRED_EXISTING_EVIDENCE),
        "manifest_sha256": gate.sha256(manifest),
        "preparation_summary_sha256": gate.sha256(summary),
        "limits": {"qualification": 80, "cpu_core_hours": 896, "gpu_hours": 64},
    }
    payload.update(overrides)
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(payload))
    return path


def test_missing_authorization_fails_closed(tmp_path):
    _, _, limits = _copies(tmp_path)
    with pytest.raises((ValueError, PermissionError)):
        gate.verify_authorization(tmp_path / "missing.json", limits)


def test_pending_authorization_is_not_approval(tmp_path):
    manifest, summary, limits = _copies(tmp_path)
    path = _authorization(tmp_path, manifest, summary, status="pending_owner_decision")
    with pytest.raises(PermissionError, match="approved revision authorization"):
        gate.verify_authorization(path, limits)


def test_hash_mismatch_fails_closed(tmp_path):
    manifest, summary, limits = _copies(tmp_path)
    path = _authorization(tmp_path, manifest, summary, manifest_sha256="0" * 64)
    with pytest.raises(PermissionError, match="different revision manifest"):
        gate.verify_authorization(path, limits)


def test_approved_record_cannot_bypass_unupdated_limits(tmp_path):
    manifest, summary, limits = _copies(tmp_path)
    current = json.loads(limits.read_text())
    current["limits"].update({"qualification": 72, "cpu_core_hours": 768})
    limits.write_text(json.dumps(current))
    path = _authorization(tmp_path, manifest, summary)
    with pytest.raises(PermissionError, match="not been updated"):
        gate.verify_authorization(path, limits)


def test_matching_authorization_and_limits_pass(tmp_path):
    manifest, summary, limits = _copies(tmp_path)
    current = json.loads(limits.read_text())
    current["limits"].update({"qualification": 80, "cpu_core_hours": 896, "gpu_hours": 64})
    limits.write_text(json.dumps(current))
    path = _authorization(tmp_path, manifest, summary)
    result = gate.verify_authorization(path, limits)
    assert result["authorization"]["recipe_id"] == gate.RECIPE
    assert result["active_limits"]["qualification"] == 80
