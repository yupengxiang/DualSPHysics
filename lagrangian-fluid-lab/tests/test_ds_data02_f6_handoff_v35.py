import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCOPE = ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003/dp025_postprocessing_005"
SCRIPT = ROOT / "scripts/ds_data02_f6_handoff_20261002_v35.py"
CONVERTER = ROOT / "scripts/ds_data02_f6_native_h5_v35.py"


def test_v35_requests_are_source_bound_and_gpu_free():
    request_dir = SCOPE / "execution_requests"
    requests = [p for p in request_dir.glob("*.json") if p.name != "request_manifest.json"]
    assert len(requests) == 8
    for path in requests:
        value = json.loads(path.read_text())
        assert value["gpu_launch"] is False
        assert value["solver_launch_forbidden"] is True
        assert value["source_native_tree_manifest_sha256"]
        assert value["input_hashes_at_request"]
        assert value["cwd"].endswith("/lagrangian-fluid-lab")
        assert value["q_n_status"].startswith("pending")
        if value["cpu_task_kind"] == "conversion":
            assert value["attempt_id"].endswith("_NATIVE_H5_005")
            assert str(SCRIPT) in value["command"]
            assert str(CONVERTER) in value["input_hashes_at_request"]
        if value["cpu_task_kind"] == "labels":
            assert value["attempt_id"].endswith("_LABELS_005")
            assert value["source_trajectory_sha256"] == "deferred_until_native_h5_receipt"


def test_v35_keeps_domain_repaired_wave_source():
    for suffix in ("floatinginfo", "computeforces", "native_h5"):
        value = json.loads((SCOPE / "execution_requests" / f"wave_no_contact_dp025_{suffix}.json").read_text())
        generated_xml = value.get("generated_xml", " ".join(value["command"]))
        assert "root-domain-x-repair-001/native_inputs" in generated_xml
        assert value["repair_scope"] == "F6_HANDOFF_20261002_RIGID003_DOMAIN_X_REPAIR_001"


def test_v35_converter_preserves_native_exclusions_and_xml_inertia():
    text = CONVERTER.read_text()
    assert "valid\"][frame_idx, slots] = True" in text
    assert "Unexpected particle identity" in text
    assert '"x", "Ixx"' in text
    assert '"y", "Iyy"' in text
    assert '"z", "Izz"' in text
