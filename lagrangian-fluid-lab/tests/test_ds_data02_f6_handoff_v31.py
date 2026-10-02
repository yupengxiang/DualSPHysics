import json
from pathlib import Path


SCOPE = Path(__file__).parents[1] / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003/dp025_postprocessing_001"


def test_dp025_native_manifests_cover_complete_solver_windows():
    manifests = sorted((SCOPE / "raw_tree_manifests").glob("*.json"))
    assert {p.stem for p in manifests} == {"simple_free_response_dp025", "wave_no_contact_dp025"}
    for path in manifests:
        value = json.loads(path.read_text())
        assert value["frame_count"] == 241
        assert value["frame_indices"] == list(range(241))
        assert value["file_count"] == 246
        assert value["total_bytes"] > 4_000_000_000
        assert len(value["tree_sha256"]) == 64
        assert len(value["generated_xml_sha256"]) == 64
        assert len(value["generated_bi4_sha256"]) == 64


def test_dp025_requests_are_source_bound_and_gpu_free():
    request_dir = SCOPE / "execution_requests"
    requests = [p for p in request_dir.glob("*.json") if p.name != "request_manifest.json"]
    assert len(requests) == 8
    for path in requests:
        value = json.loads(path.read_text())
        assert value["gpu_launch"] is False
        assert value["solver_launch_forbidden"] is True
        assert value["source_native_tree_manifest_sha256"]
        assert value["input_hashes_at_request"]
        assert value["q_n_status"].startswith("pending")
        if value["cpu_task_kind"] in {"audit", "conversion"}:
            assert value["source_solver_status"]["status"] == "completed"
        if value["cpu_task_kind"] == "labels":
            assert value["source_trajectory_sha256"] == "deferred_until_native_h5_receipt"


def test_wave_postprocessing_uses_domain_repair_native_inputs():
    for suffix in ("floatinginfo", "computeforces", "native_h5"):
        value = json.loads((SCOPE / "execution_requests" / f"wave_no_contact_dp025_{suffix}.json").read_text())
        command_text = " ".join(value["command"])
        generated_xml = value.get("generated_xml", command_text)
        assert "root-domain-x-repair-001/native_inputs" in generated_xml
        assert value["repair_scope"] == "F6_HANDOFF_20261002_RIGID003_DOMAIN_X_REPAIR_001"
