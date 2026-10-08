from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_s1_native_source_closure_118_v1.py"
MANIFEST = ROOT / "campaigns/ds-data-02/stage2/requests/f2-s1-native-source-closure-118-v1/f2-s1-native-source-closure-118-v1-manifest.json"
SINGLE = Path("/var/tmp/ds02-stage2/f2-s1-native-source-adapter-v3-local-check.json")
SPEC = importlib.util.spec_from_file_location("f2_s1_native_source_closure_118_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _binding(path: Path) -> dict[str, object]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def _fixture_manifest(tmp_path: Path) -> Path:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    receipt = tmp_path / "singleton-receipt.json"
    receipt.write_text(json.dumps({
        "schema": "ds02.execution-receipt.v1", "status": "completed", "returncode": 0,
        "output_root": "/var/tmp/ds02-stage2", "request": {"status": "completed"},
    }, sort_keys=True), encoding="utf-8")
    data["bindings"]["single_report"] = _binding(SINGLE)
    data["bindings"]["single_receipt"] = _binding(receipt)
    out = tmp_path / "manifest.json"
    out.write_text(json.dumps(data), encoding="utf-8")
    return out


def test_actual_117_plus_singleton_closes_118_without_h5(tmp_path: Path) -> None:
    result = MODULE.collect(_fixture_manifest(tmp_path), tmp_path / "closure.json")
    assert result["status"] == "PASS_ACTUAL_118_CASE_SOURCE_CLOSED_WITH_PRIOR_GAP_SPECTRUM_PRESERVED"
    assert result["case_counts"] == {
        "requested": 118, "native_identity_source_closed": 118,
        "source_binding_rejected": 0, "source_incomplete_active": 0,
        "prior_v2_source_incomplete": 1,
    }
    assert result["native_id_count"] == 1328
    assert result["prior_gap"]["case_key"] == "F2/scan-F2-S1-001"
    assert result["read_policy"]["h5_opened"] is False
    assert result["claim_boundary"]["physical_fate"] == "UNKNOWN_NOT_PROVEN; numerical exclusion is not legal spill or physical outflow"


def test_unrelated_singleton_report_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "wrong.json"
    data = json.loads(SINGLE.read_text(encoding="utf-8"))
    data["native_identity"]["id_count"] = 4
    path.write_text(json.dumps(data), encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"status": "completed", "returncode": 0, "output_root": str(tmp_path)}), encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["bindings"]["single_report"] = _binding(path)
    manifest["bindings"]["single_receipt"] = _binding(receipt)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(MODULE.ClosureError, match="singleton native identity differs"):
        MODULE.collect(manifest_path, tmp_path / "out.json")


def test_current_alias_sha_mismatch_is_rejected(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["bindings"]["current_root_alias"]["sha256"] = "0" * 64
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(MODULE.ClosureError, match="root CURRENT336 alias digest differs"):
        MODULE.collect(manifest_path, tmp_path / "out.json")
