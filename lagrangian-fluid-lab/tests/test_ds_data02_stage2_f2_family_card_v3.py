from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_family_card_v3.py"
MANIFEST = ROOT / "campaigns/ds-data-02/stage2/requests/f2-family-card-v3-root-forward-131-001/f2-family-card-v3-manifest.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_family_card_v3", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def replacement_manifest(tmp_path: Path, key: str, replacement: dict) -> Path:
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["source_refs"] if item["key"] == key)
    replacement_path = tmp_path / f"{key}.json"
    replacement_path.write_text(json.dumps(replacement, ensure_ascii=False), encoding="utf-8")
    entry["path"] = str(replacement_path)
    entry["sha256"] = loaded.sha256_file(replacement_path)
    output = tmp_path / f"manifest-{key}.json"
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return output


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual source-bound V3 manifest is not present")
def test_actual_root126_root129_root131_card_preserves_unknown_boundary():
    loaded = module()
    result = loaded.derive(MANIFEST)
    assert result["schema"] == "ds02.stage2.f2.family-card.v3"
    assert result["status"] == "PREPARED_F2_ADDITIVE_CARD_V3_NATIVE_STREAM_DOMAIN_BOUND_NO_SCIENTIFIC_CREDIT"
    assert result["actual_root126_stream"]["frame_count"] == 401
    assert result["actual_root126_stream"]["native_omission_count"] == 153
    assert result["actual_root126_stream"]["mass_screen"] == "FAIL_OVER_FROZEN_XML_WHOLE_INITIAL_0P003"
    assert result["actual_root131_domain"]["final_unique_position_violators"] == 153
    assert result["actual_root131_domain"]["border_face_events"] == 175
    assert result["task_eligibility"]["QN"] == "UNKNOWN"
    assert result["claim_boundary"]["physical_fate"] == "UNKNOWN"
    assert result["claim_boundary"]["dynamics"] == "UNKNOWN"


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual source-bound V3 manifest is not present")
def test_v3_rejects_root129_count_relabel(tmp_path: Path):
    loaded = module()
    path = next(item["path"] for item in json.loads(MANIFEST.read_text())["source_refs"] if item["key"] == "root129_report")
    sidecar = json.loads(Path(path).read_text())
    sidecar["product"]["native_omission_count"] = 152
    manifest = replacement_manifest(tmp_path, "root129_report", sidecar)
    with pytest.raises(loaded.CardError, match="ROOT129 sidecar does not bind ROOT126 401/153"):
        loaded.derive(manifest)


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual source-bound V3 manifest is not present")
def test_v3_rejects_root131_wrong_root126_proof(tmp_path: Path):
    loaded = module()
    path = next(item["path"] for item in json.loads(MANIFEST.read_text())["source_refs"] if item["key"] == "root131_proof")
    proof = json.loads(Path(path).read_text())
    proof["root126_proof_sha256"] = "0" * 64
    manifest = replacement_manifest(tmp_path, "root131_proof", proof)
    with pytest.raises(loaded.CardError, match="ROOT131 does not bind the actual ROOT126 proof"):
        loaded.derive(manifest)


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual source-bound V3 manifest is not present")
def test_v3_rejects_gpu_source_path_or_hash_drift(tmp_path: Path):
    loaded = module()
    manifest_data = json.loads(MANIFEST.read_text())
    entry = next(item for item in manifest_data["source_refs"] if item["key"] == "gpu_predicate_source")
    entry["sha256"] = "0" * 64
    altered = tmp_path / "manifest-gpu.json"
    altered.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    with pytest.raises(loaded.CardError, match="gpu_predicate_source SHA differs"):
        loaded.derive(altered)
