#!/usr/bin/env python3
"""Metadata-only validator for fresh216; never opens producer science payloads."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
CASE = "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010"
PHYS = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
ATTEMPT = "root-stage1-f2-rx056-rot090-actual1077-full401-116-023-nvme-hard2gib-root1097"
CAN = "868a719b79737c9ed2460651a54a29ee1a20904121cc505f6cb044950002d630"
LEG = "f5bab12237a82b9d91b86eb375cea952ca904154bcddfa58347f9fc59a2e7565"
KEYS = [0, 50, 100, 150, 200, 250, 300, 350, 400]

def req(ok, msg):
    if not ok:
        raise AssertionError(msg)

def load(rel):
    return json.loads((ROOT / rel).read_text())

def dg(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    req(manifest["source_only"] is True, "source_only")
    req(manifest["science_payloads_copied"] is False, "payload copied")
    req(manifest["scientific_jobs_started_by_source_agent"] is False, "job started")
    req(manifest["shared_state_written_by_source_agent"] is False, "shared state")
    req(manifest["manifest_excludes_self"] is True, "manifest self")
    expected = {
        "README.md",
        "metadata/actual-render-metadata.json",
        "metadata/physical-stage-closure.json",
        "metadata/png-visual-evidence.json",
        "metadata/upstream-evidence.json",
        "metadata/visual-decision.json",
        "scripts/validate_fresh216.py",
    }
    entries = {x["path"]: x for x in manifest["files"]}
    req(set(entries) == expected, "package file set")
    req("manifest.json" not in entries, "manifest self listed")
    for rel, entry in entries.items():
        path = ROOT / rel
        req(path.is_file(), "missing " + rel)
        req(path.stat().st_size == entry["bytes"], "bytes " + rel)
        req(dg(path) == entry["sha256"], "hash " + rel)

    render = load("metadata/actual-render-metadata.json")
    close = load("metadata/physical-stage-closure.json")
    png = load("metadata/png-visual-evidence.json")
    upstream = load("metadata/upstream-evidence.json")
    visual = load("metadata/visual-decision.json")
    for data in (render, close, png, upstream, visual):
        req(data["case_id"] == CASE, "case")
        req(data["physical_case_id"] == PHYS, "physical case")
    req(render["attempt_id"] == ATTEMPT, "attempt")
    execution = render["execution_receipt"]
    req(execution["status"] == "completed" and execution["returncode"] == 0, "execution")
    req(render["publish_receipt"]["status"] == "published_after_atomic_rename", "publish")
    expected_actual = render["expected_and_actual"]
    req(expected_actual["frames"] == 401 and expected_actual["source_frames"] == 401, "frame count")
    req(expected_actual["particles"] == 418104 and expected_actual["contact_sheets"] == 17, "particle/contact count")
    req(expected_actual["keyframe_indices"] == KEYS, "keyframes")
    req(expected_actual["all_frames_rendered"] is True and expected_actual["actual_times_preserved_exactly"] is True, "frame closure")
    req(expected_actual["native_identity_axis_preserved"] is True and expected_actual["nonfinite_active_states"] == 0, "identity/nonfinite")
    counts = render["producer_counts"]
    req(counts == {
        "data2d": False, "solver_dimension": 3,
        "fixed_initial": 372840, "moving_initial": 24150, "floating_initial": 0,
        "fluid_initial": 21114, "total_initial": 418104,
        "fixed_terminal": 372840, "moving_terminal": 24150, "floating_terminal": 0,
        "fluid_terminal": 21111, "total_terminal": 418101,
    }, "counts")
    req(render["render_report"]["numerical_precision_status"] == "not accepted", "precision")

    lifecycle = close["typed_lifecycle"]
    req(lifecycle["initial_fluid_uids"] == 21114 and lifecycle["terminal_fluid_uids"] == 21111, "fluid counts")
    req(lifecycle["final_missing_particles"] == 3 and lifecycle["max_missing_per_frame"] == 3, "missing count")
    req(lifecycle["first_missing_frame"] == 154 and lifecycle["cumulative_particle_frame_omissions"] == 635, "omission timing")
    req(lifecycle["producer_attested_final_Idp_sample"] == [397194, 403829, 404024], "missing IDs")
    req(lifecycle["unknown_missing_locations_states_causes"] is True and lifecycle["no_missing_particle_state_reconstructed"] is True, "omission semantics")

    scopes = upstream["producer_scope_roles"]
    req(scopes["canonical_native_request_condition_sha256"] == CAN, "canonical scope")
    req(scopes["actual_converter_legacy_scope_sha256"] == LEG, "legacy scope")
    req(scopes["native_source_plan_condition_field_present"] is False and scopes["native_source_plan_condition_sha256"] is None, "native condition absent")
    req(scopes["native_source_plan_physical_condition_field_present"] is True and scopes["native_source_plan_physical_condition_sha256"] == CAN, "native physical scope")
    req(scopes["xmf_source_plan_condition_field_present"] is False and scopes["xmf_source_plan_condition_sha256"] is None, "XMF condition absent")
    req(scopes["xmf_source_plan_physical_condition_field_present"] is False and scopes["xmf_source_plan_physical_condition_sha256"] is None, "XMF physical absent")
    req(scopes["scope_equality_claimed"] is False, "scope equality")
    req(upstream["source_definition_role"]["field_present_in_this_qi_evidence"] is False, "source definition inference")

    req(len(png["producer_attested_contact_sheets"]) == 17, "contacts")
    req(all(item["reviewed"] for item in png["producer_attested_contact_sheets"]), "contacts reviewed")
    req(len(png["producer_attested_keyframes"]) == 9, "keyframes")
    req([item["frame_index"] for item in png["producer_attested_keyframes"]] == KEYS, "keyframe indices")
    req(all(item["reviewed"] for item in png["producer_attested_keyframes"]), "keyframes reviewed")
    req(all(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in png["producer_attested_contact_sheets"] + png["producer_attested_keyframes"]), "producer PNG hashes")
    req(png["review_coverage"]["source_agent_computed_png_hashes"] is False, "source PNG hashing")
    req(close["open_rim_visual_observation"]["strict_container_guarantee"] is False, "strict container")
    req(close["open_rim_visual_observation"]["sub_dp_penetration_claim"] is False, "sub-DP")

    decision = visual["decision"]
    req(decision["standalone_first_stage_visual_approved"] is True and decision["severe_visual_failure"] is False, "visual decision")
    req(decision["needs_root_image_intervention"] is False, "root intervention")
    req(decision["strict_container_guarantee"] is False and decision["sub_dp_penetration_absence_claim"] is False, "visual limits")
    req(decision["numerical_precision_accepted"] is False, "visual precision")
    req(decision["q_n_granted"] is False and decision["q_e_granted"] is False and decision["independent_case_count_increment"] == 0, "credit")
    review_time = datetime.fromisoformat(visual["reviewed_at_utc"].replace("Z", "+00:00"))
    finish = datetime.fromisoformat(execution["finished_at_utc"].replace("Z", "+00:00"))
    req(review_time >= finish, "review before producer finish")

    io = render["source_agent_science_payload_io"]
    req(io["raw_h5_bi4_csv_dat_vtk_read"] is False and io["raw_h5_bi4_csv_dat_vtk_hash"] is False, "payload IO")
    req(io["scientific_job_started"] is False and io["shared_state_written"] is False, "source execution")
    req(upstream["main_qi"]["stage1_QI_full_native_identity_and_state_verified"] is True, "main QI")
    req(upstream["main_qi"]["root_QI_is_independent_proof_not_runner_receipt"] is True, "QI role")
    print("fresh216 metadata/visual handoff validation PASS")
    print("package=" + str(ROOT))
    print("case=F2 RX056/ROT090 frames=401 particles=418104 contacts=17 keyframes=9 final_missing_fluid=3")

if __name__ == "__main__":
    main()
