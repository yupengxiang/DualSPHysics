import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_six_family_index_is_source_bound_metadata_only():
    path = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/family-bundles-v1/six-family-native-raw-anchor-index-v1-001.json"
    value = json.loads(path.read_text())
    assert value["schema"] == "ds02.stage2.family-native-raw-anchor-index.v1"
    assert value["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert [item["family_id"] for item in value["families"]] == ["F1", "F3", "F4", "F5", "F6", "F7"]
    assert all(item["actual_or_pending"] == "PLANNED_REQUEST; NO_NATIVE_EXECUTION_CREDIT" for item in value["families"])
    for item in value["families"]:
        bundle = json.loads(Path(item["bundle"]["path"]).read_text())
        assert bundle["source_closure"]["complete_stat_only"] is True
        assert bundle["raw_anchor"]["expected_raw_tree_sha256"] is None
        assert bundle["execution"]["raw_bi4_read"] is True
        assert bundle["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}

