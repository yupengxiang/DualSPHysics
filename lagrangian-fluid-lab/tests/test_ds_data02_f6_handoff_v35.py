import hashlib
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
            # Historical requests retain their actual launch worktree. Verify
            # the integrated copies match those bound bytes without rebasing
            # consumed request paths to this checkout.
            bound_script = next(arg for arg in value["command"] if Path(arg).name == SCRIPT.name)
            assert value["input_hashes_at_request"][bound_script] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
            bound_converter = next(arg for arg in value["input_hashes_at_request"] if Path(arg).name == CONVERTER.name)
            assert value["input_hashes_at_request"][bound_converter] == hashlib.sha256(CONVERTER.read_bytes()).hexdigest()
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


def test_v35_actual_evidence_keeps_qn_pending_and_negative_evidence():
    evidence = json.loads((SCOPE / "actual_h5_labels_spatial_evidence_001.json").read_text())
    assert evidence["qualification_claim"] == "none"
    assert evidence["production_claim"] == "none"
    assert evidence["negative_evidence_preserved"]
    assert evidence["cases"]["simple_free_response"]["h5"]["receipt"]["status"] == "completed"
    assert evidence["cases"]["wave_no_contact"]["labels"]["receipt"]["status"] == "completed"
    for row in evidence["cases"].values():
        assert row["h5"]["aggregate_massbody_kg"] == 128.0
        assert row["h5"]["inertia_tensor_kg_m2"][0][0] > 0.0
        assert row["h5"]["initial_fluid_mass_kg"] == 5120.0
