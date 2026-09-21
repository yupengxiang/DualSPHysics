import json
from pathlib import Path

from scripts.core_independent_reproduction import audit_manifest


def test_registered_f3_v2_and_f4_compact_v2_are_portable_without_oracle_claim(tmp_path):
    lab = Path(__file__).resolve().parents[1]
    f3 = lab / "campaigns/core-v1/f3-dataset-v2.json"
    f4 = (lab / "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1"
          / "f4-tallwall120-formal-reader-manifest-v2-compact.json")

    f3_report = audit_manifest(f3, lab, label="F3_v2", verify_assets=False)
    f4_report = audit_manifest(f4, lab, label="F4_compact_v2", verify_assets=False)

    assert f3_report["dataset_schema"] == "core.dataset.v2"
    assert f3_report["case_count"] == 32
    assert f3_report["relative_paths"] is True
    assert f3_report["future_state_inputs"] is False
    assert f4_report["dataset_schema"] == "core.dataset.v2"
    assert f4_report["case_count"] == 32
    assert f4_report["formal_release"] is True
    assert f4_report["future_state_inputs"] is False
    assert all(row["verified"] is False for row in f3_report["input_assets"])


def test_manifest_audit_rejects_absolute_or_parent_asset_paths(tmp_path):
    lab = Path(__file__).resolve().parents[1]
    source = json.loads((lab / "campaigns/core-v1/f3-dataset-v2.json").read_text())
    source["cases"] = [json.loads(json.dumps(source["cases"][0]))]
    source["cases"][0]["known_inputs_ref"]["geometry"]["path"] = "/outside/geometry.npz"
    manifest = tmp_path / "bad.json"
    manifest.write_text(json.dumps(source))

    try:
        audit_manifest(manifest, lab, label="bad", verify_assets=False)
    except ValueError as error:
        assert "portable" in str(error)
    else:
        raise AssertionError("absolute compact asset path was accepted")
