import copy
import hashlib
import json

import numpy as np
import pytest

from scripts.core_cross_host_canary_compare import compare_reports, main


def _sha(label):
    return hashlib.sha256(label.encode()).hexdigest()


def _digest(label, *, dtype="float32", shape=(2, 4), base=1.0):
    return {
        "sha256": _sha(label),
        "dtype": dtype,
        "shape": list(shape),
        "finite": True,
        "min": float(base),
        "max": float(base + 1.0),
        "mean": float(base + 0.5),
        "rms": float(base + 0.6),
        "max_abs": float(abs(base + 1.0)),
    }


def _state(label, time_s):
    return {
        "time_s": time_s,
        "position": _digest(label + ":position", dtype="float64", shape=(2, 3)),
        "velocity": _digest(label + ":velocity", dtype="float64", shape=(2, 3), base=0.0),
    }


def _trace(label):
    return {
        "cpu": {
            "features": _digest(label + ":features", shape=(2, 23)),
            "neighbors": _digest(label + ":neighbors", dtype="int64", shape=(2, 4)),
            "neighbor_diagnostics": {
                "field_particle_count": 2,
                "max_neighbors": 4,
                "neighbor_radius_over_h": 2.0,
                "neighbor_truncation_fraction": 0.0,
            },
            "active_neighbor_count": {"min": 2, "max": 4, "mean": 3.0},
        },
        "normalized_features": _digest(label + ":normalized_features", shape=(2, 23)),
        "chunks": [{
            "start": 0,
            "stop": 2,
            "encoder": _digest(label + ":encoder", shape=(2, 64)),
            "layers": [
                {
                    "layer": 0,
                    "destination": "one_hop",
                    "destination_count": 2,
                    "source_count": 2,
                    "valid_neighbor_entries": 8,
                    "aggregate": _digest(label + ":aggregate0", shape=(2, 64)),
                },
                {
                    "layer": 1,
                    "destination": "centers",
                    "destination_count": 2,
                    "source_count": 2,
                    "valid_neighbor_entries": 8,
                    "aggregate": _digest(label + ":aggregate1", shape=(2, 64)),
                },
            ],
            "normalized_output": _digest(label + ":normalized_output", shape=(2, 6)),
            "output": _digest(label + ":output", dtype="float64", shape=(2, 6)),
        }],
    }


def _report():
    case_id = "F3_fixture"
    checkpoint = _sha("checkpoint")
    manifest = _sha("manifest")
    models = _sha("models")
    known_inputs = _sha("known-inputs")
    module_hash = _sha("core-models")
    report = {
        "schema": "core.cross_host_canary.v1",
        "status": "complete",
        "case_id": case_id,
        "model_kind": "graph_residual",
        "maximum_steps": 2,
        "expected_frames": 3,
        "completed_steps": 2,
        "chunk_size": 256,
        "autonomous": True,
        "future_state_inputs": False,
        "comparison_protocol": {
            "schema": "core.cross_host_comparison.v1",
            "identity_time_mass_valid": "exact",
            "position_absolute_tolerance_m": 1e-5,
            "velocity_absolute_tolerance_mps": 1e-4,
            "relative_tolerance": 1e-4,
            "tolerances_frozen": True,
        },
        "bundle": {
            "identity": {
                "expected": {"manifest": manifest, "checkpoint": checkpoint, "core_models": models},
                "observed": {
                    "manifest": {"path": "/left/dataset.json", "sha256": manifest},
                    "checkpoint": {"path": "/left/checkpoint.pt", "sha256": checkpoint},
                    "core_models": {"path": "/left/core_models.py", "sha256": models},
                },
            },
        },
        "case": {
            "physical_case_id": case_id,
            "lineage_group_id": _sha("lineage"),
            "family": "F3",
            "split": "validation",
            "hdf5": "input.h5",
            "hdf5_sha256_declared": _sha("hdf5"),
            "known_inputs_sha256": known_inputs,
        },
        "environment": {
            "python": "3.12.13 | packaged by conda-forge",
            "python_executable": "/host/bin/python",
            "torch_version": "2.12.1+cu132",
            "torch_cuda_version": "13.2",
            "requested_device": "cuda",
            "cublas_workspace_config": ":4096:8",
            "cuda_launch_blocking": None,
            "deterministic_requested": True,
            "deterministic_algorithms_enabled": True,
            "deterministic_warn_only": False,
            "cudnn_deterministic": True,
            "cudnn_benchmark": False,
            "torch_tf32_cudnn": True,
            "torch_tf32_matmul": False,
            "driver_query": {
                "available": True,
                "stdout": "595.91.07, NVIDIA fixture, GPU-fixture",
            },
            "modules_before_model": [
                {"module": "scripts.core_models", "path": "/host/core_models.py", "sha256": module_hash},
            ],
            "modules_after_inputs": [
                {"module": "scripts.f3_control", "path": "/host/f3_control.py", "sha256": _sha("f3")},
            ],
            "hostname": "fixture-host",
            "cuda_visible_devices": "GPU-fixture",
            "cuda": {
                "device_name": "fixture-gpu",
                "device_capability": [9, 0],
                "total_memory_bytes": 1,
                "multi_processor_count": 1,
            },
        },
        "initial_state": _state("initial", 0.0),
        "steps": [],
        "read_log": [[case_id, 0]],
        "events": ["environment_captured_before_model_construction"],
    }
    for step in range(2):
        report["steps"].append({
            "step": step,
            "frame": step + 1,
            "dt_s": 0.1,
            "state_before": _state(f"before:{step}", step * 0.1),
            "trace": _trace(f"trace:{step}"),
            "prediction": {
                "displacement": _digest(f"prediction:{step}:position", dtype="float64", shape=(2, 3)),
                "delta_velocity": _digest(f"prediction:{step}:velocity", dtype="float64", shape=(2, 3)),
            },
            "state_after": _state(f"after:{step}", (step + 1) * 0.1),
        })
    return report


def _write_pair(tmp_path, left, right):
    left_path, right_path = tmp_path / "left.json", tmp_path / "right.json"
    left_path.write_text(json.dumps(left))
    right_path.write_text(json.dumps(right))
    return left_path, right_path


def _array_spec(value, role):
    array = np.ascontiguousarray(np.asarray(value))
    return {
        "role": role,
        "sha256": hashlib.sha256(array.view(np.uint8)).hexdigest(),
        "dtype": str(array.dtype),
        "shape": list(array.shape),
        "nbytes": int(array.nbytes),
        "finite": bool(array.dtype.kind not in "fc" or np.isfinite(array).all()),
    }


def _write_element_sidecar(tmp_path, report, name, *, state_position_delta=0.0, layer1_message_delta=0.0):
    arrays = {
        "frame_time_s": np.array([0.0, 0.1, 0.2], dtype=np.float64),
        "state_position": np.zeros((3, 2, 3), dtype=np.float64),
        "state_velocity": np.zeros((3, 2, 3), dtype=np.float64),
        "particle_id": np.array([10, 11], dtype=np.int64),
        "particle_zone": np.array([0, 0], dtype=np.int64),
        "mass": np.ones(2, dtype=np.float64),
        "valid": np.ones(2, dtype=bool),
    }
    arrays["state_position"][2, 0, 0] += state_position_delta
    steps = []
    for step in range(2):
        prefix = f"s{step}"
        arrays.update({
            f"{prefix}_normalized_features": np.zeros((2, 3), dtype=np.float32),
            f"{prefix}_encoder_node_index": np.array([0, 1], dtype=np.int64),
            f"{prefix}_encoder": np.zeros((2, 4), dtype=np.float32),
            f"{prefix}_centers": np.array([0, 1], dtype=np.int64),
            f"{prefix}_head_input": np.zeros((2, 4), dtype=np.float32),
            f"{prefix}_head_raw": np.zeros((2, 6), dtype=np.float32),
            f"{prefix}_head_normalized": np.zeros((2, 6), dtype=np.float32),
            f"{prefix}_head_target_space": np.zeros((2, 6), dtype=np.float32),
            f"{prefix}_prior": np.zeros((2, 6), dtype=np.float32),
            f"{prefix}_prediction_with_prior": np.zeros((2, 6), dtype=np.float64),
        })
        transition_arrays = {
            "trace.normalized_features": f"{prefix}_normalized_features",
            "trace.encoder.node_index": f"{prefix}_encoder_node_index",
            "trace.encoder.values": f"{prefix}_encoder",
            "trace.centers": f"{prefix}_centers",
            "trace.head.input": f"{prefix}_head_input",
            "trace.head.raw_output": f"{prefix}_head_raw",
            "trace.head.normalized_output": f"{prefix}_head_normalized",
            "trace.head.target_space": f"{prefix}_head_target_space",
            "trace.prior": f"{prefix}_prior",
            "trace.prediction_with_prior": f"{prefix}_prediction_with_prior",
        }
        layer_records = []
        for layer in (0, 1):
            lp = f"{prefix}_l{layer}"
            raw = np.zeros((3, 4), dtype=np.float32)
            if layer == 1:
                raw += layer1_message_delta
            arrays.update({
                f"{lp}_destination": np.array([0, 1], dtype=np.int64),
                f"{lp}_source": np.array([0, 1, 2], dtype=np.int64),
                f"{lp}_destination_position": np.array([0, 1], dtype=np.int64),
                f"{lp}_neighbor": np.array([[1, 2], [0, -1]], dtype=np.int64),
                f"{lp}_valid": np.array([[True, True], [True, False]], dtype=bool),
                f"{lp}_source_position": np.array([[1, 2], [0, -1]], dtype=np.int64),
                f"{lp}_edge_destination": np.array([0, 0, 1], dtype=np.int64),
                f"{lp}_edge_neighbor": np.array([1, 2, 0], dtype=np.int64),
                f"{lp}_edge_slot": np.array([0, 1, 0], dtype=np.int64),
                f"{lp}_edge_input": np.zeros((3, 5), dtype=np.float32),
                f"{lp}_message": raw,
                f"{lp}_aggregate": np.zeros((2, 4), dtype=np.float32),
                f"{lp}_updated": np.zeros((2, 4), dtype=np.float32),
            })
            layer_arrays = {
                "node.destination_index": f"{lp}_destination",
                "node.source_index": f"{lp}_source",
                "node.destination_position": f"{lp}_destination_position",
                "edge.neighbor_index": f"{lp}_neighbor",
                "edge.valid_mask": f"{lp}_valid",
                "edge.source_position": f"{lp}_source_position",
                "edge.destination_index_valid": f"{lp}_edge_destination",
                "edge.neighbor_index_valid": f"{lp}_edge_neighbor",
                "edge.slot_index_valid": f"{lp}_edge_slot",
                "edge.input_valid_edges": f"{lp}_edge_input",
                "message.raw_valid_edges": f"{lp}_message",
                "aggregate.values": f"{lp}_aggregate",
                "update.updated_node_embedding": f"{lp}_updated",
            }
            layer_records.append({"layer": layer, "destination": "one_hop" if layer == 0 else "centers", "arrays": layer_arrays})
        steps.append({"step": step, "frame": step + 1, "dt_s": 0.1, "first_chunk": {"start": 0, "stop": 2},
                      "arrays": transition_arrays, "layers": layer_records})

    arrays_path = tmp_path / f"{name}.npz"
    with arrays_path.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    metadata = {
        "schema": "core.cross_host_canary.element_trace.v1",
        "canary_schema": "core.cross_host_canary.v1",
        "status": "complete",
        "case_id": report["case_id"],
        "model_kind": report["model_kind"],
        "maximum_steps": report["maximum_steps"],
        "expected_frames": report["expected_frames"],
        "chunk_size": report["chunk_size"],
        "bundle": copy.deepcopy(report["bundle"]),
        "case": copy.deepcopy(report["case"]),
        "capture_transparency": {
            "schema": "core.cross_host_canary.capture_transparency.v1",
            "step": 0,
            "frame": 1,
            "original_model_forward_vs_capture_forward": {
                "exact_equal": True,
                "max_abs_error": 0.0,
            },
        },
        "array_store": {
            "path": arrays_path.name,
            "format": "npz",
            "compressed": True,
            "allow_pickle": False,
            "sha256": hashlib.sha256(arrays_path.read_bytes()).hexdigest(),
            "arrays": {key: _array_spec(value, key) for key, value in arrays.items()},
        },
        "state_arrays": {
            "frame_time_s": "frame_time_s", "position": "state_position", "velocity": "state_velocity",
            "particle_id": "particle_id", "particle_zone": "particle_zone", "mass": "mass", "valid": "valid",
        },
        "steps": steps,
    }
    metadata_path = tmp_path / f"{name}.json"
    metadata_path.write_text(json.dumps(metadata))
    return metadata_path


def test_identical_small_fixture_is_exactly_comparable(tmp_path):
    left = _report()
    right = copy.deepcopy(left)
    left_path, right_path = _write_pair(tmp_path, left, right)

    result = compare_reports(left_path, right_path)

    assert result["passed"]
    assert result["decision"] == "exact_match"
    assert result["trace_exact_match"]
    assert result["numerical_tolerance_status"] == "satisfied_by_exact_digest_equality"
    assert result["first_difference"] is None
    for step in result["steps"]:
        assert step["position_velocity_differences"]["state_after_position"]["max_elementwise_abs_error"] == 0.0


def test_digest_mismatch_reports_first_layer_without_fabricating_max_error(tmp_path):
    left = _report()
    right = copy.deepcopy(left)
    aggregate = right["steps"][0]["trace"]["chunks"][0]["layers"][1]["aggregate"]
    aggregate["sha256"] = _sha("different-layer-aggregate")
    aggregate["max"] += 0.25
    left_path, right_path = _write_pair(tmp_path, left, right)

    result = compare_reports(left_path, right_path)

    assert not result["passed"]
    assert result["decision"] == "digest_difference_requires_element_output"
    assert result["first_trace_difference"]["path"] == "steps[0].trace.chunks[0].layers[1].aggregate"
    assert result["steps"][0]["trace"]["first_mismatch"]["path"].endswith("layers[1].aggregate")
    assert result["steps"][0]["trace"]["first_mismatch"]["evidence"]["max_elementwise_abs_error"] is None
    assert result["steps"][0]["position_velocity_differences"]["state_after_position"]["exact_equal"]
    assert result["measurement_limits"]["not_computable_from_current_report"]


def test_first_difference_follows_forward_order_before_later_head_output(tmp_path):
    left = _report()
    right = copy.deepcopy(left)
    chunk = right["steps"][0]["trace"]["chunks"][0]
    chunk["normalized_output"]["sha256"] = _sha("later-head-output")
    chunk["normalized_output"]["mean"] += 0.25
    chunk["layers"][0]["aggregate"]["sha256"] = _sha("earlier-aggregate")
    chunk["layers"][0]["aggregate"]["mean"] += 0.1
    left_path, right_path = _write_pair(tmp_path, left, right)

    result = compare_reports(left_path, right_path)

    assert result["first_trace_difference"]["path"] == "steps[0].trace.chunks[0].layers[0].aggregate"
    assert result["steps"][0]["trace"]["mismatch_counts"]["aggregate"] == 1


def test_position_velocity_step_difference_exposes_summary_delta_only(tmp_path):
    left = _report()
    right = copy.deepcopy(left)
    state = right["steps"][1]["state_after"]["position"]
    state["sha256"] = _sha("different-position")
    state["mean"] += 0.01
    left_path, right_path = _write_pair(tmp_path, left, right)

    result = compare_reports(left_path, right_path)

    assert result["decision"] == "digest_difference_requires_element_output"
    difference = result["steps"][1]["position_velocity_differences"]["state_after_position"]
    assert not difference["exact_equal"]
    assert difference["max_elementwise_abs_error"] is None
    assert difference["summary_delta_right_minus_left"]["mean"] == pytest.approx(0.01)
    assert result["first_trace_difference"]["frame"] == 2


def test_identity_and_environment_mismatches_are_not_hidden_by_equal_digests(tmp_path):
    left = _report()
    right = copy.deepcopy(left)
    right["case"]["known_inputs_sha256"] = _sha("future-or-wrong-known-inputs")
    right["environment"]["torch_version"] = "2.11.0+cu128"
    left_path, right_path = _write_pair(tmp_path, left, right)

    result = compare_reports(left_path, right_path)

    assert not result["passed"]
    assert result["decision"] == "identity_mismatch"
    assert "case:known_inputs_sha256" in result["identity"]["mismatches"]
    assert "software:torch_version" in result["environment"]["mismatches"]
    assert result["trace_exact_match"]


def test_cli_writes_report_and_returns_success_for_exact_fixture(tmp_path):
    left_path, right_path = _write_pair(tmp_path, _report(), _report())
    output = tmp_path / "comparison.json"

    assert main(["--left", str(left_path), "--right", str(right_path), "--output", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["schema"] == "core.cross_host_canary_comparison.v1"


def test_element_trace_calculates_real_error_and_reports_first_message_stage(tmp_path):
    left = _report()
    right = copy.deepcopy(left)
    left_path, right_path = _write_pair(tmp_path, left, right)
    left_trace = _write_element_sidecar(tmp_path, left, "element-left")
    right_trace = _write_element_sidecar(
        tmp_path, right, "element-right", state_position_delta=2.0e-5, layer1_message_delta=0.25
    )

    result = compare_reports(left_path, right_path, left_trace, right_trace)

    assert not result["passed"]
    assert result["decision"] == "elementwise_tolerance_violation"
    assert result["element_trace"]["tolerance_status"] == "violated_registered_tolerance"
    assert result["element_trace"]["state"]["max_position_abs_error_m"] == pytest.approx(2.0e-5)
    assert result["element_trace"]["first_difference"]["path"] == "steps[0].layer[1].message.raw_valid_edges"
    assert result["element_trace"]["steps"][0]["first_difference"]["max_abs_error"] == pytest.approx(0.25)


def test_element_trace_within_tolerance_is_not_labeled_digest_failure(tmp_path):
    left = _report()
    right = copy.deepcopy(left)
    left_path, right_path = _write_pair(tmp_path, left, right)
    left_trace = _write_element_sidecar(tmp_path, left, "element-left-ok")
    right_trace = _write_element_sidecar(
        tmp_path, right, "element-right-ok", state_position_delta=1.0e-7, layer1_message_delta=1.0e-3
    )

    result = compare_reports(left_path, right_path, left_trace, right_trace)

    assert result["passed"]
    assert result["bitwise_exact"]
    assert result["element_trace_passed"]
    assert result["decision"] == "element_trace_within_registered_tolerance"
    assert result["numerical_tolerance_status"] == "within_registered_tolerance"


def test_element_trace_requires_exact_first_chunk_transparency_witness(tmp_path):
    left = _report()
    right = copy.deepcopy(left)
    left_path, right_path = _write_pair(tmp_path, left, right)
    left_trace = _write_element_sidecar(tmp_path, left, "element-left-transparency")
    right_trace = _write_element_sidecar(tmp_path, right, "element-right-transparency")
    right_metadata = json.loads(right_trace.read_text())
    right_metadata["capture_transparency"]["original_model_forward_vs_capture_forward"]["exact_equal"] = False
    right_metadata["capture_transparency"]["original_model_forward_vs_capture_forward"]["max_abs_error"] = 1.0e-7
    right_trace.write_text(json.dumps(right_metadata))

    result = compare_reports(left_path, right_path, left_trace, right_trace)

    assert not result["passed"]
    assert result["decision"] == "invalid_report"
    assert "element_trace:invalid_capture_transparency:right" in result["errors"]
