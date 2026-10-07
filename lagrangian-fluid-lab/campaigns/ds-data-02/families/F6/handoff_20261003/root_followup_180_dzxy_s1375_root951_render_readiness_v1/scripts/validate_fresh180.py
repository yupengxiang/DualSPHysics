#!/usr/bin/env python3
"""Read-only metadata validator for the fresh180 Root951 render gate."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

FORBIDDEN = (".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtu")
ALLOWED = {".json", ".xml", ".xmf", ".py"}
CASE = "F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025"
NATIVE_SCOPE = "13c383a2ba67e520613cacb83f595a1c0745b2ac8ad2c67c9c6beaf43a6e4640"
PRODUCER_SCOPE = "a92da26df8424649239124012c23f1f893327573a302dc6914e962ceec5a0d90"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_ref(item: dict) -> Path:
    assert isinstance(item, dict), item
    for key in ("path", "sha256", "bytes", "kind"):
        assert key in item, (key, item)
    path = Path(item["path"])
    assert path.is_file(), path
    suffix = path.suffix.lower()
    assert suffix in ALLOWED, path
    assert not any(str(path).lower().endswith(x) for x in FORBIDDEN), path
    assert path.stat().st_size == item["bytes"], (path, path.stat().st_size, item["bytes"])
    assert sha256(path) == item["sha256"], ("SHA drift", path)
    return path


def contains_value(obj, value) -> bool:
    if obj == value:
        return True
    if isinstance(obj, dict):
        return any(contains_value(k, value) or contains_value(v, value) for k, v in obj.items())
    if isinstance(obj, list):
        return any(contains_value(v, value) for v in obj)
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, default=Path(__file__).parents[1])
    pkg = ap.parse_args().package
    closure = json.loads((pkg / "metadata/readiness-closure.json").read_text())

    assert closure["schema"] == "ds02.f6.fresh180.dzxy-s1375-render-readiness.v1"
    assert closure["fresh_id"] == "fresh180"
    assert closure["assigned_family"] == "F6"
    assert closure["physical_case_id"] == CASE and closure["case_id"] == CASE
    assert closure["model"] == "gpt-5.6-luna" and closure["reasoning_effort"] == "max"
    assert closure["status"] == "render_pending_same_root951_controller"
    assert closure["case_credit"] == 0
    assert closure["visual_review_performed"] is False
    assert closure["q_n_granted"] is False and closure["q_e_granted"] is False
    assert closure["production_approval"] is False
    assert closure["no_particle_v0_to_omega_inference"] is True

    admission = closure["admission_observation"]
    assert admission["status_at_fresh180_snapshot"] == "controller_live_target_not_terminal"
    assert admission["current_exact_wait_reason_not_inferred_from_missing_receipt"] is True
    assert admission["no_input_or_guard_failure_claimed"] is True
    prior_fit = admission["prior_fresh172_queue_audit"]
    assert prior_fit["wait_class"] == "shared-render-capacity-and-cpu-headroom"
    assert prior_fit["cpu_fit"] is False and prior_fit["renderer_cap_fit"] is False
    assert prior_fit["home_storage_fit"] is True
    assert prior_fit["input_or_guard_failure"] is False and prior_fit["qualification_failure"] is False

    roles = closure["scope_roles"]
    assert roles["native_initial_qa_and_native_request_scope_sha256"] == NATIVE_SCOPE
    assert roles["typed_and_xmf_producer_scope_sha256"] == PRODUCER_SCOPE
    assert roles["source_plan_condition_sha256"] == "c503e879744b5f3e533ebf193b888d7cea57c3cf8a3e0a5c64a831ba8013fc41"
    assert "distinct" in roles["scope_relation"]

    contract = closure["physical_contract"]
    assert contract["dimension"] == 3
    assert contract["native_particles"] == 417505
    assert contract["expected_frames"] == 241
    assert contract["expected_contact_sheets"] == 11
    assert contract["native_counts"] == {"fixed": 73441, "floating": 16384, "fluid": 327680, "moving": 0}
    assert contract["physical_mass_kg"] == 128.0 and contract["native_support_mass_kg"] == 256.0
    assert contract["no_mass_rescale"] is True
    assert contract["state0_status"] == "pass"
    assert len(contract["declared_angular_velocity_rad_s"]) == 3
    assert len(contract["observed_state0_angular_velocity_rad_s"]) == 3

    static = closure["static_inputs"]
    refs = {name: check_ref(item) for name, item in static.items()}
    assert refs["manifest"].suffix.lower() == ".json"
    assert refs["case_xmf"].suffix.lower() == ".xmf"
    assert refs["source_definition"].suffix.lower() == ".xml"

    # Every producer stage is metadata-complete/0. This reads JSON receipts/reports only.
    stages = closure["producer_chain"]
    assert [x["stage"] for x in stages] == [
        "genuine_gencase", "initial_native_qa", "full241_native",
        "floatinginfo_state0", "typed_conversion", "typed_h5_integrity_audit", "normal_n3_xmf"
    ]
    stage_reports = {}
    for stage in stages:
        receipt_path = check_ref(stage["execution_receipt"])
        receipt = json.loads(receipt_path.read_text())
        assert receipt.get("status") == "completed", (stage["stage"], receipt.get("status"))
        assert receipt.get("returncode") == 0, (stage["stage"], receipt.get("returncode"))
        if "metadata_report" in stage:
            report_path = check_ref(stage["metadata_report"])
            stage_reports[stage["stage"]] = json.loads(report_path.read_text())

    qa = stage_reports["initial_native_qa"]
    assert qa.get("pass") is True
    assert qa.get("physical_condition_sha256") == NATIVE_SCOPE
    state0 = stage_reports["floatinginfo_state0"]
    assert state0.get("status") == "pass"
    typed = stage_reports["typed_conversion"]
    assert typed.get("conversion_status") == "completed"
    assert typed.get("frames") == 241 and typed.get("particles") == 417505
    assert isinstance(typed.get("solver_dimension"), dict)
    assert typed["solver_dimension"].get("solver_dimension") == 3
    manifest = stage_reports["normal_n3_xmf"]
    assert manifest.get("case_id") == CASE
    assert manifest.get("frames") == 241 and manifest.get("particles") == 417505
    assert manifest.get("expected_frames") == 241 and manifest.get("expected_particles") == 417505
    assert manifest.get("physical_condition_sha256") == PRODUCER_SCOPE
    assert manifest.get("producer_scope_sha256") == PRODUCER_SCOPE
    assert manifest.get("future_hashes_null") is True
    assert manifest.get("no_jobs_started") is True
    assert manifest.get("no_raw_scientific_payload_read_or_hash_by_source_package") is True

    # The registered request/wrapper and actual upstream requests must all retain this case identity.
    for name in ("registered_render_request", "loaded_wrapper", "source_native_request", "source_typed_request", "source_xmf_request"):
        data = json.loads(refs[name].read_text())
        assert contains_value(data, CASE), name
    render_request = json.loads(refs["registered_render_request"].read_text())
    assert contains_value(render_request, 241)
    assert contains_value(render_request, 417505)
    assert contains_value(render_request, PRODUCER_SCOPE)
    wrapper = json.loads(refs["loaded_wrapper"].read_text())
    assert contains_value(wrapper, CASE)

    gate = closure["render_gate"]
    assert gate["controller_pid"] == 4004579
    assert gate["controller_start_ticks"] == "207142232"
    assert gate["same_controller_required"] is True
    assert gate["must_wait_for_completed_zero_and_atomic_publish"] is True
    assert gate["do_not_restart_or_duplicate"] is True
    assert all(gate[key] is None for key in ("future_execution_receipt", "future_render_report", "future_publish_receipt", "future_pngs", "future_visual_decision"))

    snap = closure["live_observation_snapshot"]
    assert snap["same_handle_live_at_snapshot"] is True
    assert snap["start_ticks"] == "207142232"
    assert snap["target_in_results_at_snapshot"] is False
    assert snap["attempt_root_exists"] is False
    assert snap["execution_receipt_exists"] is False
    assert snap["render_report_exists"] is False
    assert snap["publish_receipt_exists"] is False
    assert snap["published0"] is False
    assert snap["actual_progress_is_mutable_and_not_hashed"] is True
    assert snap["status"] == "controller_live_target_not_terminal"

    bounds = closure["source_boundaries"]
    assert bounds == {
        "h5_bi4_csv_dat_vtk_opened_or_hashed_by_source_package": False,
        "science_job_started_by_source_package": False,
        "scientific_payload_read_or_hashed_by_source_package": False,
        "shared_state_written_by_source_package": False,
    }
    print("fresh180 validation PASS: native/state0/typed/XMF metadata chain completed/0; Root951 same-handle render pending; scopes separated; future render outputs null; no scientific payload IO or credit")


if __name__ == "__main__":
    main()
