from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f6_handoff_20261002_v21.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_handoff_20261002_v21", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
F6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F6)


def test_partvtkout_requests_cover_all_six_solver_cases() -> None:
    manifest = F6.read_json(F6.POST_ROOT / "request_manifest.json")
    requests = [F6.read_json(Path(row["path"])) for row in manifest["requests"]]
    assert len(requests) == 6
    assert {(row["mechanism_id"], row["resolution_id"]) for row in requests} == {
        ("simple_free_response", "coarse"),
        ("simple_free_response", "medium"),
        ("simple_free_response", "fine"),
        ("wave_no_contact", "coarse"),
        ("wave_no_contact", "medium"),
        ("wave_no_contact", "fine"),
    }
    for row in requests:
        assert row["cpu_task_kind"] == "audit"
        assert row["gpu_launch"] is False
        assert "PartVTKOut_linux64" in row["command"][0]
        assert "-saveresume" in row["command"]
        assert all(Path(path).is_file() for path in row["input_files"])
        assert row["q_n_status"] == "pending_native_exclusion_reconciliation"


def test_labels_bind_enriched_h5_and_reuse_sidecar_keeps_medium01_lineage() -> None:
    labels = F6.read_json(F6.POST_ROOT / "labels_004_evidence.json")
    assert len(labels["requests"]) == 2
    for row in labels["requests"]:
        request = F6.read_json(Path(row["path"]))
        assert request["source_trajectory"].endswith("_NATIVE_H5_004/trajectory.h5")
        assert request["source_trajectory_sha256"] != "deferred"
        assert request["gpu_launch"] is False
    reuse = F6.read_json(F6.POST_ROOT / "medium_native_reuse_sidecar_001.json")
    assert reuse["native_array_equivalence"]["case_count_increment"] is False
    assert reuse["qualification_claim"] == "none"
    assert "actual medium01 paths and hashes" in reuse["reuse_boundary"]

