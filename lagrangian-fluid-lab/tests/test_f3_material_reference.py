"""Temporary arrays/H5 and fake CPU workers only; no campaign execution."""
from contextlib import contextmanager
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from scripts import f3_material_reference as reference
from scripts import f3_material_reference_score as score


def forbidden(*args, **kwargs):
    raise AssertionError("real campaign operation forbidden in this test")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    out = tmp_path/"continuation"
    out.mkdir()
    monkeypatch.setattr(reference, "LAB", tmp_path)
    monkeypatch.setattr(reference, "OUT", out)
    monkeypatch.setattr(reference, "DATA", tmp_path/"material-data")
    monkeypatch.setattr(reference, "cpu_slot", forbidden)
    monkeypatch.setattr(reference.qualification, "verify_stage_gate", forbidden)
    monkeypatch.setattr(reference.source_score, "_source", forbidden)
    for name in ("begin_activity_window", "ledger", "resource_limits", "material_usage"):
        monkeypatch.setattr(reference.resources, name, forbidden)


def small_trace():
    seeds = dict(tracer_id=np.array(["left", "right"]),
                 initial_position=np.array([[-.01, 0., .04], [.01, 0., .04]]),
                 mass_fraction=np.array([.75, .25]), source_label=np.array([0, 1]))
    trace = dict(time=np.array([0., 1., 2.]),
                 position=np.tile(seeds["initial_position"], (3, 1, 1)),
                 reliability_history=np.ones((3, 2), dtype=bool))
    return trace, seeds


def test_observed_event_survives_later_failure_and_residence_is_not_renormalized():
    trace, seeds = small_trace()
    trace["position"][1, 0, 0] = .01
    trace["position"][2, 0] = np.nan
    trace["reliability_history"][2, 0] = False
    trace["wall_crossing"] = np.array([[False, False], [True, False]])
    value = score.label_trace(trace, seeds)
    assert value["first_passage_s"][0] == .5
    assert value["first_passage_status"].tolist() == ["observed", "valid_no_event"]
    assert value["terminal_label"].tolist() == [2, 1]
    assert value["first_failure_reason"][0] == "wall_contact_or_crossing"
    assert value["first_failure_frame"].tolist() == [2, -1]
    np.testing.assert_allclose(value["residence_left_s"], [.5, 0])
    np.testing.assert_allclose(value["residence_right_s"], [.5, 2])
    np.testing.assert_allclose(value["residence_unknown_s"], [1, 0])
    actual = score.compare(value, value)
    assert actual["by_source"][0]["initial_mass_fraction"] == .75
    assert actual["by_source"][0]["unknown_fraction_max"] == [1., 1.]
    assert actual["path_statistics"] is None
    assert actual["qualified_T2_macro"] is actual["qualified_T2_path"] is False


def test_two_censored_events_are_not_agreement_on_no_event():
    trace, seeds = small_trace()
    trace["reliability_history"][1:, 0] = False
    value = score.label_trace(trace, seeds)
    assert value["first_passage_status"][0] == "censored"
    report = score.compare(value, value)
    row = report["by_source"][0]
    assert row["first_passage_cdf_worst_bound_difference"] == 1
    assert row["terminal_mass_worst_bound_difference"] == 1
    assert row["common_observed_event_mass_fraction_over_source"] == 0
    assert row["observed_event_weighted_mae_s"] is None
    assert row["event_time_status"] == "not_applicable"
    assert row["within_candidate_budget"] is False


@pytest.mark.parametrize("change", ["weights", "ids", "source", "time", "reappeared", "nonfinite", "mask_type"])
def test_invalid_seed_time_or_reliability_contract_is_rejected(change):
    trace, seeds = small_trace()
    if change == "weights": seeds["mass_fraction"][0] = .5
    elif change == "ids": seeds["tracer_id"][1] = "left"
    elif change == "source": seeds["source_label"][0] = 1
    elif change == "time": trace["time"][1] = 2
    elif change == "reappeared": trace["reliability_history"][1, 0] = False
    elif change == "nonfinite": trace["position"][1, 0, 0] = np.nan
    else: trace["reliability_history"] = trace["reliability_history"].astype(float)
    with pytest.raises(ValueError): score.label_trace(trace, seeds)


def test_comparison_rejects_seed_permutation_time_change_and_fabricated_labels():
    trace, seeds = small_trace()
    first = score.label_trace(trace, seeds)
    second = copy.deepcopy(first)
    second["tracer_id"] = second["tracer_id"][::-1]
    with pytest.raises(ValueError, match="immutable seeds"):
        score.compare(first, second)
    second = copy.deepcopy(trace)
    second["time"][1] = .5
    with pytest.raises(ValueError, match="identical times"):
        score.compare(first, score.label_trace(second, seeds))
    second = copy.deepcopy(first)
    second["first_passage_status"][0] = "observed"
    with pytest.raises(ValueError, match="label differs"):
        score.compare(first, second)


def test_full_path_gate_is_stricter_for_substeps_and_never_qualifies_a_matrix():
    seeds = reference.frozen_seeds()
    trace = dict(time=np.array([0., 1., 8.35]),
                 position=np.tile(seeds["initial_position"], (3, 1, 1)),
                 reliability_history=np.ones((3, 512), bool))
    a = score.label_trace(trace, seeds)
    trace["position"][1:, :, 1] += .001
    b = score.label_trace(trace, seeds)
    spatial = score.compare(a, b)
    temporal = score.compare(a, b, kind="substep")
    assert spatial["path_within_candidate_budget"]
    assert not temporal["path_within_candidate_budget"]
    assert temporal["budget_multiplier"] == .2
    assert spatial["path_statistics"]["rms_max_m"] == pytest.approx(.001)
    assert spatial["quadrature_status"] == "pending"
    assert not spatial["qualified_T2_path"]


def test_cadence_scores_event_cdf_between_coarse_outputs():
    trace, seeds = small_trace()
    a = score.label_trace(trace, seeds)
    dense = dict(time=np.array([0., .5, 1., 1.5, 2.]),
                 position=np.tile(seeds["initial_position"], (5, 1, 1)),
                 reliability_history=np.ones((5, 2), bool))
    dense["position"][1, 0, 0] = .01  # Leaves and returns before next coarse output.
    b = score.label_trace(dense, seeds)
    report = score.compare(a, b, kind="cadence")
    assert report["by_source"][0]["first_passage_cdf_worst_bound_difference"] == 1
    assert not report["macro_within_candidate_budget"]


@pytest.fixture
def calibration(tmp_path, monkeypatch):
    hashes = {name: "a"*64 for name in (
        "scripts/passive_tracers.py", "scripts/f3_material_neighbors.py",
        "scripts/f3_material_calibration.py", "scripts/f3_material_calibration_v2.py")}
    monkeypatch.setattr(reference, "code_hashes", lambda: dict(hashes))
    axes = [[-.021, -.007, .007, .021], [-.021, -.007, .007, .021], [.024, .036, .048, .060]]
    points = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    value = dict(status="completed", calibrated=True, configuration_charge=4,
                 tracer_sha256="a"*64, interpolator_sha256="a"*64,
                 program_path="scripts/f3_material_calibration_v2.py", program_sha256="a"*64,
                 design=dict(seeds=64, substeps=2, time_window_s=[0, .5], output_interval_s=.01,
                             neighbours=24, regularization_m=.004, maximum_support_distance_m=.03,
                             seed_positions_m=points.tolist(), same_physical_seeds_across_resolutions=True,
                             acceptance=dict(maximum_path_error_m=.001, maximum_residence_error_s=.01,
                                             required_reliable_fraction=1., terminal_disagreement_fraction=0.)), results=[])
    for flow in ("shear", "rotation"):
        for dp in (.01, .006):
            path = tmp_path/f"{flow}-{dp}.npz"
            path.write_bytes(b"manufactured fixture")
            path.with_suffix(".h5").write_bytes(b"manufactured source fixture")
            value["results"].append(dict(flow=flow, dp_m=dp, passed=True, max_path_error_m=0.,
                maximum_residence_error_s=0., reliable_fraction=1., terminal_disagreement_fraction=0.,
                artifact=path.name, artifact_sha256=reference.sha256(path),
                source_sha256=reference.sha256(path.with_suffix(".h5"))))
    path = tmp_path/"calibration.json"
    reference.atomic_json(path, value)
    return reference._reference(path)


def test_registration_freezes_eleven_512_point_configs_and_new_thresholds(calibration):
    plan = reference.register(calibration)
    assert len(plan["configurations"]) == 11
    assert sum(c["required_gate"] == "endpoints" for c in plan["configurations"]) == 4
    assert plan["configurations"][-1]["output_interval_s"] == .002
    assert plan["configurations"][-1]["substeps"] == 4
    assert plan["configuration_charge"] == 0 and plan["planned_total_material_count"] == 25
    assert plan["seed_design"]["mass_fraction"] == [1/512]*512
    assert len(set(plan["seed_design"]["tracer_id"])) == 512
    assert sum(plan["seed_design"]["source_label"]) == 256
    assert plan["thresholds"] == score.THRESHOLDS
    assert reference.register(calibration) == plan
    path = reference.OUT/reference.PLAN_NAME
    plan["configurations"][0]["seeds"] = 64
    reference.atomic_json(path, plan)
    with pytest.raises(ValueError, match="plan changed"):
        reference.register(calibration)


@pytest.mark.parametrize("change", ["missing_backend", "legacy_runner", "failed", "missing_row", "threshold", "artifact"])
def test_missing_or_changed_new_backend_calibration_fails_closed(calibration, change):
    path = Path(calibration["path"])
    value = json.loads(path.read_text())
    if change == "missing_backend": value.pop("interpolator_sha256")
    elif change == "legacy_runner": value["program_path"] = "scripts/f3_material_calibration.py"
    elif change == "failed": value["results"][0]["passed"] = False
    elif change == "missing_row": value["results"].pop()
    elif change == "threshold": value["design"]["acceptance"]["maximum_path_error_m"] = .5
    else: (reference.LAB/value["results"][0]["artifact"]).write_bytes(b"changed")
    reference.atomic_json(path, value)
    with pytest.raises(ValueError): reference.register(reference._reference(path))


def h5_source(tmp_path):
    target = reference.source_score.target_grid(.01)
    times = target.copy(); times[1:] += 1e-5
    path = tmp_path/"source.h5"
    p = np.tile(np.array([[-.01, 0., .04], [.01, 0., .04]]), (len(times), 1, 1))
    p[:, :, 0] += times[:, None]*.001
    with h5py.File(path, "w") as h:
        h["time"] = times; h["particle_id"] = [30, 40]
        h["position"] = p; h["velocity"] = np.full_like(p, .001)
        h["mass"] = np.full((len(times), 2), .5)
        h["valid"] = np.ones((len(times), 2), bool); h["type"] = np.full((len(times), 2), 3)
    return dict(plan_case_id="NP01", case_id="fixture", hdf5_path=path,
                entry=dict(output_interval_s=.01, dp_m=.01, amplitude=1.),
                native_timestep=dict(dt_max_s=.00002, last_time_s=float(times[-1])),
                audit=dict(frames=len(times), time_end_s=float(times[-1]), particle_axis_count=2,
                           initial_fluid_mass_kg=1., hdf5_sha256=reference.sha256(path)))


def test_alignment_uses_last_bracket_without_extending_control_or_changing_source(tmp_path):
    source = h5_source(tmp_path)
    result = reference.align_source(source, tmp_path/"aligned.h5")
    assert result["target_count"] == 836
    assert result["input_sha256_before"] == result["input_sha256_after"] == reference.sha256(source["hdf5_path"])
    with h5py.File(result["path"], "r") as h:
        assert h["time"][0] == 0 and h["time"][-1] == 8.35
        assert h["native_bracket_s"][-1, 1] > 8.35
        assert 0 < h["native_alpha"][-1] < 1
        np.testing.assert_allclose(h["position"][-1, :, 0], [-.00165, .01835], atol=1e-15)
        np.testing.assert_array_equal(h["particle_id"][:], [30, 40])
        assert h["valid"][:].all() and np.all(h["mass"][:] == .5)
    assert not (tmp_path/"aligned.h5.partial").exists()


def test_alignment_rejects_changed_source_and_invalid_identity_mass(tmp_path):
    source = h5_source(tmp_path)
    with h5py.File(source["hdf5_path"], "r+") as h: h["mass"][1, 0] = .25
    with pytest.raises(ValueError, match="changed before"):
        reference.align_source(source, tmp_path/"out.h5")
    source["audit"]["hdf5_sha256"] = reference.sha256(source["hdf5_path"])
    with pytest.raises(ValueError, match="identity mass"):
        reference.align_source(source, tmp_path/"out.h5")
    assert not (tmp_path/"out.h5").exists()


def test_resource_preflight_uses_material_cpu_and_storage_without_qualification_pool(monkeypatch):
    budget = dict(cpu_core_hours_upper_bound=700., conservative_expiry_utc="2099-01-01T00:00:00+00:00")
    reference.atomic_json(reference.OUT/"RESOURCE-LEDGER.json", budget)
    monkeypatch.setattr(reference.resources, "begin_activity_window", lambda: None)
    monkeypatch.setattr(reference.resources, "ledger", lambda: None)
    monkeypatch.setattr(reference.resources, "material_usage", lambda: 24)
    limits = dict(materials=32, cpu_core_hours=768, storage_gib=512, qualification=0)
    monkeypatch.setattr(reference.resources, "resource_limits", lambda: limits)
    monkeypatch.setattr(reference.shutil, "disk_usage", lambda path: SimpleNamespace(total=1024**4, free=1024**4))
    result = reference.resource_preflight(3600, 1)
    assert result["cpu_forward_reserve_core_hours"] == pytest.approx((3600+605)*17.6/3600)
    limits["cpu_core_hours"] = 701
    with pytest.raises(RuntimeError, match="CPU timeout"): reference.resource_preflight(3600, 1)
    limits["cpu_core_hours"] = 768
    with pytest.raises(RuntimeError, match="storage cap"): reference.resource_preflight(1, 513*1024**3)
    monkeypatch.setattr(reference.resources, "material_usage", lambda: 32)
    with pytest.raises(RuntimeError, match="configuration cap"): reference.resource_preflight(1, 1)


def test_failed_execution_is_charged_once_and_requires_explicit_retry(tmp_path, monkeypatch, calibration):
    plan = reference.register(calibration)
    monkeypatch.setattr(reference, "verify_plan", lambda path: plan)
    monkeypatch.setattr(reference.qualification, "verify_stage_gate", lambda stage: {})
    source = h5_source(tmp_path)
    monkeypatch.setattr(reference.source_score, "_source", lambda case, bindings: copy.deepcopy(source))
    (reference.OUT/reference.source_score.GATES["nominal"]).write_text("{}")
    held = []
    @contextmanager
    def slot():
        held.append(True)
        try: yield
        finally: held.pop()
    monkeypatch.setattr(reference, "cpu_slot", slot)
    monkeypatch.setattr(reference, "resource_preflight", lambda *args: {"fixture": True})
    monkeypatch.setattr(reference.resources, "ledger", lambda: None)
    def fail(command, folder, timeout_seconds, env, *, on_spawn=None):
        assert held and timeout_seconds == 1
        assert env["OMP_NUM_THREADS"] == "1" and env["CUDA_VISIBLE_DEVICES"] == ""
        attempt = json.loads(next(reference.OUT.glob("F3-MATERIAL-REFERENCE-NP01-s2-*.json")).read_text())
        assert attempt["status"] == "running" and attempt["configuration_charge"] == 1
        raise subprocess.TimeoutExpired("fake worker", 1)
    monkeypatch.setattr(reference, "_run_process", fail)
    with pytest.raises(subprocess.TimeoutExpired): reference.run_one("NP01-s2", timeout_seconds=1)
    path = next(reference.OUT.glob("F3-MATERIAL-REFERENCE-NP01-s2-*.json"))
    result = json.loads(path.read_text())
    assert result["status"] == "failed" and result["configuration_charge"] == 1
    assert result["elapsed_seconds"] >= 0
    with pytest.raises(ValueError, match="explicit retry_of"):
        reference.run_one("NP01-s2", timeout_seconds=1)
    assert len(list(reference.OUT.glob("F3-MATERIAL-REFERENCE-NP01-s2-*.json"))) == 1


def test_cpu_fake_process_timeout_has_no_real_material_or_gpu_work(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        reference._run_process([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, .03,
                               {"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1"})


def test_worker_refuses_uncharged_direct_invocation(tmp_path):
    payload = tmp_path/"payload.json"
    attempt = tmp_path/"attempt.json"
    attempt.write_text(json.dumps(dict(schema=reference.ATTEMPT_SCHEMA, status="completed")))
    payload.write_text(json.dumps(dict(attempt_record_path=str(attempt))))
    with pytest.raises(ValueError, match="charged registration"):
        reference._worker(payload)


def test_fake_worker_success_preserves_diagnostics_backend_binding_and_candidate_status(tmp_path, monkeypatch, calibration):
    plan = reference.register(calibration)
    source = h5_source(tmp_path)
    monkeypatch.setattr(reference, "verify_plan", lambda path: plan)
    monkeypatch.setattr(reference.qualification, "verify_stage_gate", lambda stage: {})
    monkeypatch.setattr(reference.source_score, "_source", lambda case, bindings: copy.deepcopy(source))
    monkeypatch.setattr(reference.source_score, "_verify_bindings", lambda bindings: None)
    (reference.OUT/reference.source_score.GATES["nominal"]).write_text("{}")
    @contextmanager
    def slot(): yield
    monkeypatch.setattr(reference, "cpu_slot", slot)
    monkeypatch.setattr(reference, "resource_preflight", lambda *args: {"fixture": True})
    monkeypatch.setattr(reference.resources, "ledger", lambda: None)
    times = np.array([0., 1., 8.35])
    monkeypatch.setattr(reference.source_score, "target_grid", lambda step: times.copy())
    def align(source, target, *, step_s):
        target.write_bytes(b"isolated alignment fixture")
        return dict(path=str(target), sha256=reference.sha256(target), target_count=3,
                    time_window_s=[0., 8.35], input_sha256_before=source["audit"]["hdf5_sha256"],
                    input_sha256_after=source["audit"]["hdf5_sha256"])
    monkeypatch.setattr(reference, "align_source", align)
    def advect(path, points, *, velocity_interpolator, barrier_provider, **kwargs):
        assert velocity_interpolator.__module__ == "scripts.f3_material_neighbors"
        assert barrier_provider(None, 0, 1, .5).shape == (10, 3, 3)
        assert kwargs["support_gate"] == reference.SUPPORT and kwargs["substeps_per_interval"] == 2
        trace = dict(time=times.copy(), position=np.tile(points, (3, 1, 1)),
                     reliability_history=np.ones((3, 512), bool), support_gate=dict(reference.SUPPORT),
                     visibility_mode="isolated_fixture", motion_interpolation="none")
        for field in reference.DIAGNOSTICS:
            trace[field] = np.ones((2, 512), bool if field in ("support_gate_pass", "wall_crossing") else float)
        trace["wall_crossing"][:] = False
        trace["wall_crossing"][0, 0] = True
        trace["reliability_history"][1:, 0] = False
        return trace
    monkeypatch.setattr(reference.passive_tracers, "advect_hdf5", advect)
    # Simulate the controlled child only within this CPU fixture.
    monkeypatch.setattr(os, "getppid", os.getpid)
    def process(command, folder, timeout_seconds, env, *, on_spawn):
        on_spawn(12345)
        reference._worker(command[-1])
    monkeypatch.setattr(reference, "_run_process", process)
    result = reference.run_one("NP01-s2", timeout_seconds=1)
    assert result["status"] == "completed" and result["worker_pid"] == 12345
    assert result["process_group_id"] == 12345 and result["configuration_charge"] == 1
    bundle = json.loads(Path(result["result"]["path"]).read_text())
    assert bundle["status"] == "candidate" and not bundle["qualified_T2_macro"] and not bundle["qualified_T2_path"]
    with np.load(bundle["material"]["path"], allow_pickle=False) as arrays:
        for field in reference.DIAGNOSTICS: assert field in arrays
        assert arrays["first_failure_reason"][0] == "wall_contact_or_crossing"
        assert arrays["first_passage_status"][0] == "censored"
        assert arrays["mass_weight_kg"].sum() == 1.
        assert arrays["boundary_triangles_m"].shape == (10, 3, 3)
    with pytest.raises(RuntimeError, match="running or completed"):
        reference.run_one("NP01-s2", timeout_seconds=1)
