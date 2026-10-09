from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_family_card_v2.py"
MANIFEST = ROOT / "campaigns/ds-data-02/stage2/requests/f2-family-card-v2-root-forward-114-001/f2-family-card-v2-manifest.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_family_card_v2", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _manifest_with_replacement(tmp_path: Path, key: str, replacement: dict) -> Path:
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source = next(item for item in manifest["source_refs"] if item["key"] == key)
    replacement_path = tmp_path / f"{key}.json"
    replacement_path.write_text(json.dumps(replacement, ensure_ascii=False), encoding="utf-8")
    source["path"] = str(replacement_path)
    source["sha256"] = loaded.sha256_file(replacement_path)
    output = tmp_path / f"manifest-{key}.json"
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return output


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual source-bound V2 request is not present")
def test_actual_root056_to_root070_identity_transition_is_closed():
    loaded = module()
    result = loaded.derive(MANIFEST)
    transition = result["native_identity_closure"]["transition"]
    supplement = result["native_identity_closure"]["f2_s1_supplement"]
    assert result["schema"] == "ds02.stage2.f2.family-card.v2"
    assert result["status"] == "PREPARED_F2_ADDITIVE_CARD_V2_IDENTITY_CLOSED_NO_STREAM_CREDIT"
    assert transition == {
        "historical_root056_rows": 1325,
        "supplemented_root070_rows": 1328,
        "supplement_rows": 3,
        "transition_is_set_difference": True,
        "source_closure_is_not_physical_fate": True,
        "converter_initial_filter": "UNKNOWN outside explicit selected producer metadata",
    }
    assert supplement["added_idp"] == [397194, 403829, 404024]
    assert supplement["physical_fate"] == "UNKNOWN_NOT_PROVEN"
    assert result["task_eligibility"]["QN"] == "UNKNOWN"
    assert result["root111_stream"]["execution_credit"] == "NONE_UNTIL_COMPLETED_RECEIPT"


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual source-bound V2 request is not present")
def test_v2_rejects_root070_row_count_loss(tmp_path: Path):
    supplemented_path = next(
        item["path"] for item in json.loads(MANIFEST.read_text(encoding="utf-8"))["source_refs"]
        if item["key"] == "supplemented_identity_rows"
    )
    supplemented = json.loads(Path(supplemented_path).read_text(encoding="utf-8"))
    supplemented["native_identity_records"] = supplemented["native_identity_records"][:-1]
    manifest = _manifest_with_replacement(tmp_path, "supplemented_identity_rows", supplemented)
    loaded = module()
    with pytest.raises(loaded.CardError, match="exactly 1328 identity rows"):
        loaded.derive(manifest)


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual source-bound V2 request is not present")
def test_v2_rejects_historical_1325_product_relabelled_as_closed(tmp_path: Path):
    historical_path = next(
        item["path"] for item in json.loads(MANIFEST.read_text(encoding="utf-8"))["source_refs"]
        if item["key"] == "historical_identity_audit"
    )
    historical = json.loads(Path(historical_path).read_text(encoding="utf-8"))
    historical["native_id_count"] = 1328
    manifest = _manifest_with_replacement(tmp_path, "historical_identity_audit", historical)
    loaded = module()
    with pytest.raises(loaded.CardError, match="immutable 1325-ID"):
        loaded.derive(manifest)


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual source-bound V2 request is not present")
def test_v2_rejects_wrong_f2_s1_supplement_id(tmp_path: Path):
    supplemented_path = next(
        item["path"] for item in json.loads(MANIFEST.read_text(encoding="utf-8"))["source_refs"]
        if item["key"] == "supplemented_identity_rows"
    )
    supplemented = json.loads(Path(supplemented_path).read_text(encoding="utf-8"))
    for row in supplemented["native_identity_records"]:
        if row["case_key"] == "F2/scan-F2-S1-001" and row["idp"] == 397194:
            row["idp"] = 999999
            break
    manifest = _manifest_with_replacement(tmp_path, "supplemented_identity_rows", supplemented)
    loaded = module()
    with pytest.raises(loaded.CardError, match="exact three F2-S1 IDs"):
        loaded.derive(manifest)


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual source-bound V2 request is not present")
def test_v2_rejects_uncompleted_supplement_receipt(tmp_path: Path):
    receipt_path = next(
        item["path"] for item in json.loads(MANIFEST.read_text(encoding="utf-8"))["source_refs"]
        if item["key"] == "supplemented_identity_receipt"
    )
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    receipt["status"] = "failed"
    manifest = _manifest_with_replacement(tmp_path, "supplemented_identity_receipt", receipt)
    loaded = module()
    with pytest.raises(loaded.CardError, match="supplemented native identity receipt is not completed"):
        loaded.derive(manifest)
