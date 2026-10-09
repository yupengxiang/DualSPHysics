from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f1_s1_existing_observer_bracket_comparison_v1.py"
MANIFEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "f1-s1-existing-observer-bracket-comparison-v1-root-prepared-163-001/"
    / "f1-s1-existing-observer-bracket-comparison-v1-manifest.json"
)


def module():
    spec = importlib.util.spec_from_file_location("f1_observer_bracket_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_existing_f1_observers_have_one_exact_and_four_saved_bracket_queries():
    loaded = module()
    report = loaded.derive(MANIFEST)
    assert report["status"] == "F1_SELECTED_OBSERVER_BRACKETS_COMPARED_NO_INTERPOLATION"
    assert report["common_registered_queries_s"] == [0.0, 0.4, 0.8, 1.2, 1.6]
    for label in report["variants"]:
        rows = report["bracket_summary"][label]
        assert len(rows) == 5
        assert rows[0]["status"] == "EXACT_OR_LEFT"
        assert all(row["status"] == "BRACKETED" for row in rows[1:])
        assert all(row["interpolation_performed"] is False for row in rows)


def test_saved_endpoint_deltas_are_explicitly_not_error_credit():
    loaded = module()
    report = loaded.derive(MANIFEST)
    pair = report["raw_endpoint_comparisons"]["dp005_same_vs_half"]
    assert len(pair["queries"]) == 5
    assert "raw_delta" in pair["queries"][1]["metric_deltas"]["lower"]["centroid_m"]
    assert report["interpretation"]["saved_endpoint_deltas_are_not_integration_error"] is True
    assert report["interpretation"]["no_continuous_time_interpolation"] is True
    assert report["qualification"]["integration_error"] == "UNKNOWN"


def test_manifest_binds_only_json_producer_reports():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["contract"]["json_only"] is True
    assert manifest["contract"]["no_native_payload_inputs"] is True
    assert manifest["contract"]["no_interpolation"] is True
    assert len(manifest["source_refs"]) == 10
    assert all(Path(ref["path"]).suffix == ".json" for ref in manifest["source_refs"])
