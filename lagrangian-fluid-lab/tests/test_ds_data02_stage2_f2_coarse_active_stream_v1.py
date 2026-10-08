from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_active_stream_v1.py"
REQUEST_DIR = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "f2-coarse-active-stream-v1-root-forward-106-001"
)
MANIFEST = REQUEST_DIR / "f2-coarse-active-stream-v1-manifest.json"
REQUEST = REQUEST_DIR / "f2-coarse-active-stream-v1-request.json"
CONTRACT = ROOT / "campaigns/ds-data-02/stage2/contracts/f2-coarse-observation-contract-v1.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_active_stream_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_request_is_one_cpu_bounded_and_explicit_about_raw_frame_cost():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert request["case_id"] == "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
    assert request["cpu_threads"] == request["omp_threads"] == 1
    assert request["max_wall_seconds"] == 10800
    assert request["hdf5_read"] is False
    assert request["solver_launch"] is False
    assert request["gencase_launch"] is False
    assert request["gpu_launch"] is False
    assert request["native_decode"] is True
    assert request["bi4_read"] is True
    assert len(manifest["frames"]) == 401
    assert len(request["deferred_input_files"]) == 408
    assert request["deferred_input_stats"]["frame_count"] == 401
    frame_bytes = request["deferred_input_stats"]["frame_bytes"]
    assert request["estimated_input_read_bytes"] >= 3 * frame_bytes
    assert all(not path.lower().endswith((".h5", ".hdf5")) for path in request["input_files"])
    assert all("/Part_" not in path or not path.endswith(".bi4") for path in request["input_files"])
    assert request["source_binding"]["expected_native_loss_count"] == 153


def test_contract_keeps_frozen_gates_and_unknown_physics():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["frozen_tolerances"]["whole_initial_unknown_mass_fraction_max"] == 0.003
    assert contract["frozen_tolerances"]["mk_region_flux_error_fraction_whole_initial"] == 0.03
    assert contract["frozen_tolerances"]["integration_error_allocation_fraction"] == 0.25
    assert contract["frozen_tolerances"]["output_sampling_error_allocation_fraction"] == 0.25
    assert contract["half_cfl_comparison"]["status"] == "NOT_MEASURED"
    assert contract["native_output_projection"]["status"] == "NOT_MEASURED"
    assert contract["claim_boundary"]["physical_destination"] == "UNKNOWN"
    assert contract["claim_boundary"]["dynamical_impact"] == "UNKNOWN"


def test_lifecycle_counts_missing_runs_and_reentry_once():
    loaded = module()
    lifecycle = {
        10: {
            "first_missing_frame": None,
            "first_missing_time_s": None,
            "last_present_frame": None,
            "last_present_time_s": None,
            "missing_frame_count": 0,
            "consecutive_missing_frame_count": 0,
            "reappeared_after_missing": False,
            "reentry_count": 0,
        }
    }
    initial = {10}
    missing, _ = loaded.update_lifecycle(lifecycle, initial, set(), 0, 0.0, set())
    assert missing == {10}
    assert lifecycle[10]["first_missing_frame"] == 0
    assert lifecycle[10]["consecutive_missing_frame_count"] == 1
    missing, _ = loaded.update_lifecycle(lifecycle, initial, set(), 1, 0.1, missing)
    assert missing == {10}
    assert lifecycle[10]["missing_frame_count"] == 2
    assert lifecycle[10]["consecutive_missing_frame_count"] == 2
    missing, _ = loaded.update_lifecycle(lifecycle, initial, initial, 2, 0.2, missing)
    assert missing == set()
    assert lifecycle[10]["reappeared_after_missing"] is True
    assert lifecycle[10]["reentry_count"] == 1
    assert lifecycle[10]["consecutive_missing_frame_count"] == 0
    missing, _ = loaded.update_lifecycle(lifecycle, initial, initial, 3, 0.3, missing)
    assert missing == set()
    assert lifecycle[10]["reentry_count"] == 1


def test_identity_join_rejects_wrong_case_and_duplicate_id():
    loaded = module()
    with pytest.raises(loaded.StreamObservationError, match="case_key differs"):
        loaded.case_qualified_rows("case-a", [{"case_key": "case-b", "idp": 1}])
    with pytest.raises(loaded.StreamObservationError, match="duplicate"):
        loaded.case_qualified_rows("case-a", [{"idp": 1}, {"idp": 1}])


def test_source_paths_require_solver_request_and_contract(tmp_path: Path):
    loaded = module()
    one = tmp_path / "one.json"
    one.write_text("{}\n", encoding="utf-8")
    ref = {"path": str(one), "bytes": one.stat().st_size, "sha256": loaded.sha256(one)}
    inputs = {key: ref for key in ("native_qa_report", "native_qa_manifest", "native_qa_request", "runparts", "generated_xml", "solver_receipt", "direct_converter", "bi4_dump", "timing_contract")}
    with pytest.raises(loaded.StreamObservationError, match="solver_request"):
        loaded._source_paths({"inputs": inputs})
    inputs["solver_request"] = ref
    assert set(loaded._source_paths({"inputs": inputs})) == set(inputs)


def test_completed_native_qa_request_is_bound_to_its_manifest():
    loaded = module()
    qa_manifest = Path(json.loads(MANIFEST.read_text(encoding="utf-8"))["inputs"]["native_qa_manifest"]["path"])
    qa_request = json.loads(Path(json.loads(MANIFEST.read_text(encoding="utf-8"))["inputs"]["native_qa_request"]["path"]).read_text(encoding="utf-8"))
    loaded._validate_native_request(qa_request, qa_manifest)
    wrong = dict(qa_request)
    wrong["command"] = list(qa_request["command"])
    wrong["command"][wrong["command"].index("--manifest") + 1] = str(qa_manifest) + ".wrong"
    with pytest.raises(loaded.StreamObservationError, match="manifest"):
        loaded._validate_native_request(wrong, qa_manifest)
