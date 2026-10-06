#!/usr/bin/env python3
"""Metadata/PNG-only verifier for fresh148.

The verifier reads JSON/XML/XMF metadata and rendered PNGs only.  It rejects
BI4/H5/CSV/DAT/VTK science-payload paths before hashing anything.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
META = PKG / "metadata/fresh148-visual-review.json"
MANIFEST = PKG / "manifest.json"
EXPECTED_CASES = ("F7_OBSTACLE_QUINTIC_B08_A036", "F7_OBSTACLE_QUINTIC_B08_A037")
EXPECTED_COUNTS = {"dimension": 3, "total": 70179, "fixed": 27495, "moving": 1984, "floating": 0, "fluid": 40700}
KEYS = (0, 14, 125, 200, 300, 400, 450, 500, 550, 600)
SAFE_SUFFIXES = {".json", ".xml", ".xmf", ".png", ".py", ".md"}
FORBIDDEN_SUFFIXES = {".bi4", ".h5", ".csv", ".dat", ".vtk", ".npy", ".npz"}


def sha(path: Path) -> str:
    path = Path(path)
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise AssertionError(f"science payload hash forbidden: {path}")
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(Path(path).read_text())


def check(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def type_counts(tc):
    return {
        "fixed": int(tc.get("fixed", tc.get("0", 0))),
        "moving": int(tc.get("moving", tc.get("1", 0))),
        "floating": int(tc.get("floating", tc.get("2", 0))),
        "fluid": int(tc.get("fluid", tc.get("3", 0))),
        "unknown": int(tc.get("unknown", 0)),
    }


def check_receipt(item, case_id):
    path = Path(item["path"])
    d = read_json(path)
    check(path.suffix.lower() == ".json", f"receipt suffix {path}")
    check(d.get("status") == "completed" and d.get("returncode") == 0, f"receipt status {case_id}:{item['stage']}")
    check(sha(path) == item["sha256"], f"receipt SHA {case_id}:{item['stage']}")
    check(d.get("request", {}).get("attempt_id") == item["attempt_id"], f"receipt attempt {case_id}:{item['stage']}")


d = read_json(META)
check(d["schema"] == "ds02.f5.fresh148.f7.visual-review-handoff.v1", "schema")
check(d["source_only_package"] is True and d["no_jobs_started"] is True and d["no_science_payload_read_or_hashed"] is True, "source safety")
selection = d["root792_selection"]
root792 = Path(selection["source_path"])
check(root792.suffix.lower() == ".json" and sha(root792) == selection["source_sha256"], "Root792 provenance")
check(selection["selected_physical_case_ids"] == list(EXPECTED_CASES), "current selected cases")
prior = Path(selection["prior_fresh146_path"])
check(prior.exists() and sha(prior) == selection["prior_fresh146_sha256"], "prior fresh146 provenance")
check(selection["prior_fresh146_selected_physical_case_ids"] == ["F7_OBSTACLE_QUINTIC_B08_A031", "F7_OBSTACLE_QUINTIC_B08_A032"], "prior fresh146 selected IDs")
check(len(selection["prior_fresh146_selected_converter_scope_sha256"]) == 2, "prior fresh146 selected hash count")
check(selection["prior_fresh146_is_current_exclusion_authority"] is True, "prior fresh146 exclusion authority")
prior147 = Path(selection["prior_fresh147_path"])
check(prior147.exists() and sha(prior147) == selection["prior_fresh147_sha256"], "prior fresh147 provenance")
check(selection["prior_fresh147_selected_physical_case_ids"] == ["F7_OBSTACLE_QUINTIC_B08_A033", "F7_OBSTACLE_QUINTIC_B08_A034"], "prior fresh147 selected IDs")
check(len(selection["prior_fresh147_selected_converter_scope_sha256"]) == 2, "prior fresh147 selected hash count")
check(selection["prior_fresh147_is_current_exclusion_authority"] is True, "prior fresh147 exclusion authority")
check(selection["combined_prior_excluded_case_ids"] == [
    "F7_OBSTACLE_QUINTIC_B08_A031",
    "F7_OBSTACLE_QUINTIC_B08_A032",
    "F7_OBSTACLE_QUINTIC_B08_A033",
    "F7_OBSTACLE_QUINTIC_B08_A034",
], "combined prior case exclusions")
check(len(selection["combined_prior_excluded_converter_scope_sha256"]) == 4, "combined prior hash exclusions")
check(set(selection["combined_prior_excluded_converter_scope_sha256"]) == (
    set(selection["prior_fresh146_selected_converter_scope_sha256"])
    | set(selection["prior_fresh147_selected_converter_scope_sha256"])
), "combined prior hashes")
checkpoint114 = selection["checkpoint114_acceptance_audit"]
check(checkpoint114["accepted_decision_json_count"] == 170, "checkpoint114 decision count")
check(checkpoint114["accepted_decision_jsons_loaded_individually"] is True, "checkpoint114 decisions not individually loaded")
records = checkpoint114["accepted_decision_json_sha256_records"]
check(len(records) == 170, "checkpoint114 decision SHA record count")
for rec in records:
    rp = Path(rec["path"])
    check(rp.exists() and rp.suffix.lower() == ".json", f"checkpoint114 decision path {rp}")
    check(sha(rp) == rec["sha256"], f"checkpoint114 decision SHA {rp}")
selected_comparisons = checkpoint114["selected_pair_comparisons"]
check(len(selected_comparisons) == 2, "selected checkpoint114 comparison count")
for cmp in selected_comparisons:
    check(cmp["physical_case_id"] in EXPECTED_CASES, "selected checkpoint114 comparison identity")
    check(cmp["accepted_case_id_match"] is False and cmp["accepted_condition_hash_match"] is False and cmp["accepted_pair_match"] is False, f"checkpoint114 duplicate selection {cmp['physical_case_id']}")
    check(cmp["eligible_under_checkpoint114_pair_audit"] is True, f"checkpoint114 eligibility {cmp['physical_case_id']}")
    check(cmp["prior_fresh146_case_id_match"] is False and cmp["prior_fresh146_condition_hash_match"] is False, f"prior fresh146 duplicate selection {cmp['physical_case_id']}")
    check(cmp["physical_case_id"] not in selection["combined_prior_excluded_case_ids"], f"combined prior case selection {cmp['physical_case_id']}")
    check(cmp["candidate_condition_hash"] not in selection["combined_prior_excluded_converter_scope_sha256"], f"combined prior scope selection {cmp['physical_case_id']}")
check(selection["selected_rows_have_no_checkpoint114_case_id_or_hash_match"] is True, "checkpoint114 selection boundary")
check(selection["selected_rows_have_no_current_or_prior146_match"] is True, "current/prior selection boundary")
check(len(selection["explicit_accepted_p5_exclusions"]) == 12, "all first24 P5 exclusions")
check(all(x["accepted_in_checkpoint114"] is True for x in selection["explicit_accepted_p5_exclusions"]), "P5 exclusion acceptance")
exclusions = {(x["physical_case_id"], x["condition_hash"]) for x in selection["explicit_accepted_p5_exclusions"]}
check(("F7_OBSTACLE_QUINTIC_B08_A031P5", "7f1e4156d93c9d327ee94881ac81365f061650d03adc5a6e4aa109df54f3238b") in exclusions, "A031P5 exclusion")
check(("F7_OBSTACLE_QUINTIC_B08_A032P5", "8bd3a8052f36147cba51b25a9de3c7a121a4d8e4c08602855c6ced83ea5b426e") in exclusions, "A032P5 exclusion")
check(any(x[0] == "F7_OBSTACLE_QUINTIC_B08_A033P5" for x in exclusions), "A033P5 exclusion")
check(any(x[0] == "F7_OBSTACLE_QUINTIC_B08_A034P5" for x in exclusions), "A034P5 exclusion")
check(selection["frontier_jobs_started"] == 0 and selection["frontier_science_payload_read_or_hashed"] is False, "Root792 safety")
check(selection["frontier_independent_case_increment"] == 0 and selection["accepted_count_unchanged_by_frontier"] is True, "Root792 credit boundary")
check(len(d["cases"]) == 2, "case count")

seen = set()
for c in d["cases"]:
    case = c["case_id"]
    check(case in EXPECTED_CASES and case not in seen, f"case identity {case}")
    seen.add(case)
    check(c["frontier_row_already_accepted"] is False, f"frontier accepted flag {case}")
    check(c["frontier_row_independent_case_increment"] == 0, f"frontier increment {case}")
    check(c["case_id"] in ("F7_OBSTACLE_QUINTIC_B08_A036", "F7_OBSTACLE_QUINTIC_B08_A037"), f"integer selection identity {case}")
    row = next(r for r in selection["first24_rows"] if r["physical_case_id"] == case)
    check(row["actual_converter_physical_condition_sha256"] == c["scope_separation"]["actual_converter_scope_sha256"], f"first24 scope binding {case}")
    check(row["candidate_condition_hash"] == c["scope_separation"]["actual_converter_scope_sha256"], f"first24 candidate scope {case}")
    check(row["root792_already_accepted_record_only"] is False, f"Root792 stale flag {case}")
    counts = c["actual_counts_and_solver"]
    check({k: counts[k] for k in EXPECTED_COUNTS} == EXPECTED_COUNTS, f"counts {case}")
    check(counts["expected_frames"] == 601 and counts["physical_window_s"] == [0.0, 12.0], f"solver window {case}")
    check(counts["native_sampled_regular"] == "not C2; piecewise-linear native reader", f"motion semantics {case}")

    q = c["qualification_status"]
    check(q["precision_status"].startswith("not_accepted"), f"precision boundary {case}")
    check(q["q_n"] == "not_granted" and q["production_approval"] == "none", f"qualification {case}")
    check(q["case_credit_granted"] is False and q["independent_case_count_increment"] == 0 and q["full801_or_production_authorization"] is False, f"credit boundary {case}")

    scope = c["scope_separation"]
    check(scope["scopes_are_kept_distinct"] is True and scope["canonical_equals_source_plan_claim"] is False, f"scope separation {case}")
    check(scope["owner_declared_source_plan_sha256_length"] == 63, f"historical owner plan length {case}")
    check(scope["owner_declared_source_plan_sha256_matches_plan_file"] is False, f"historical owner plan equality {case}")
    check(scope["owner_declared_source_plan_sha256"] != scope["batch_source_plan_file_sha256"], f"historical owner plan collision {case}")
    check(scope["owner_plan_digest_erratum"], f"historical owner plan erratum {case}")
    check(scope["batch_source_plan_file_sha256"] == sha(Path(scope["batch_source_plan_file"])), f"batch plan SHA {case}")
    check(scope["source_plan_declared_condition_sha256"] == scope["source_declared_physical_condition_sha256"], f"declared source scope {case}")
    check(scope["actual_converter_scope_sha256"] == scope["canonical_physical_binding_sha256"], f"converter scope {case}")
    check(scope["actual_converter_scope_sha256"] != scope["source_plan_declared_condition_sha256"], f"scope collision {case}")
    check(sha(Path(scope["canonical_owner_path"])) == scope["canonical_owner_sha256"], f"canonical owner SHA {case}")
    check(sha(Path(scope["legacy_source_owner_path"])) == scope["legacy_source_owner_sha256"], f"legacy owner SHA {case}")
    check(scope["no_cross_resolution_or_C2_claim"] is True, f"C2 boundary {case}")

    chain = c["producer_chain_metadata"]
    check(chain["typed_report"]["conversion_status"] == "completed" and chain["typed_report"]["frames"] == 601 and chain["typed_report"]["particles"] == 70179, f"typed chain {case}")
    for key in ("gencase_prepared_input_report", "generated_xml", "generated_definition", "typed_report", "manifest", "render_report"):
        item = chain[key]
        p = Path(item["path"])
        check(p.suffix.lower() in SAFE_SUFFIXES, f"unsafe chain input {p}")
        check(sha(p) == item["sha256"], f"chain SHA {case}:{key}")
    for item in chain["stage_receipts"]:
        check_receipt(item, case)

    render = c["actual_render_metadata"]
    report_path = Path(render["report_path"])
    report = read_json(report_path)
    manifest_path = Path(render["input_manifest"])
    manifest = read_json(manifest_path)
    xdmf_path = Path(render["xdmf"])
    check(sha(report_path) == render["report_sha256"], f"render report SHA {case}")
    check(report["manifest_sha256"] == sha(manifest_path) == render["manifest_sha256_attested_by_report"], f"manifest report SHA {case}")
    check(sha(xdmf_path) == report["xdmf_sha256_before"] == report["xdmf_sha256_after"], f"XDMF SHA {case}")
    check(report["frames"] == 601 and report["source_frames"] == 601 and report["all_frames_rendered"] is True, f"render frame metadata {case}")
    check(report["actual_times_preserved_exactly"] is True and report["native_identity_axis_preserved"] is True and report["nonfinite_active_states"] == 0, f"render integrity {case}")
    check(render["render_request_sha256"] == sha(Path(render["render_request_path"])), f"render request SHA {case}")
    check(render["all_frame_metadata_checks"] == {"missing_zero": True, "finite_positions": True, "finite_mass_velocity_density_pressure": True, "identity_axis_preserved": True, "expected_counts_match": True}, f"frame checks {case}")
    check(manifest["case_id"] == case and manifest["expected_particles"] == 70179 and manifest["expected_frames"] == 601, f"manifest identity {case}")
    check(manifest["canonical_physical_binding_sha256"] == scope["actual_converter_scope_sha256"] == manifest["producer_physical_condition_sha256"], f"manifest converter scope {case}")
    check(manifest["source_plan_condition_sha256"] == scope["source_plan_declared_condition_sha256"], f"manifest source scope {case}")

    visual = c["visual_scope"]
    frames = visual["all_601_saved_frame_pngs"]
    contacts = visual["all_26_contact_sheets"]
    keys = visual["ten_event_keyframes"]
    check(len(frames) == 601 and len(contacts) == 26 and len(keys) == 10, f"visual inventory {case}")
    check(visual["reviewed_all_contact_sheets"] is True and visual["reviewed_event_keyframes"] == list(KEYS), f"visual review inventory {case}")
    for frame in frames:
        p = Path(frame["path"])
        check(p.exists() and p.suffix.lower() == ".png", f"saved frame {case}:{frame['frame']}")
    for item in contacts + keys:
        p = Path(item["path"])
        check(p.exists() and p.suffix.lower() == ".png", f"review PNG {case}:{p}")
        check(sha(p) == item["sha256"], f"review PNG SHA {case}:{p}")
    obs = visual["visual_observations"]
    check(obs["coherent_tank_and_obstacle_evolution"] is True and obs["broad_explosive_dispersion_seen"] is False and obs["broad_wall_escape_seen"] is False and obs["premature_termination_seen"] is False, f"visual observations {case}")
    check(obs["strict_particle_level_containment_claim"] is False and obs["visual_screen_is_not_physics_acceptance"] is True, f"visual limitation {case}")

for item in d["external_metadata_inputs"]:
    p = Path(item["path"])
    check(p.exists() and p.suffix.lower() in SAFE_SUFFIXES, f"external metadata path {p}")
    check(p.suffix.lower() not in FORBIDDEN_SUFFIXES, f"science payload listed {p}")
    check(sha(p) == item["sha256"], f"external metadata SHA {p}")

# The package manifest excludes itself and this validator's generated report;
# it therefore has a stable fixed file list.
pkg_manifest = read_json(MANIFEST)
check(pkg_manifest["manifest_excludes"] == ["metadata/fresh148-validator-report.json", "manifest.json"], "manifest exclusions")
for rel, expected in pkg_manifest["files"].items():
    p = PKG / rel
    check(p.exists() and p.suffix.lower() in SAFE_SUFFIXES, f"package file {p}")
    check(sha(p) == expected, f"package file SHA {p}")

print(json.dumps({
    "status": "passed",
    "package": str(PKG),
    "cases": list(EXPECTED_CASES),
    "frames_per_case": 601,
    "contacts_per_case": 26,
    "keyframes_per_case": 10,
    "science_payload_opened": False,
    "scope_semantics_checked": True,
    "case_credit_granted": False,
}, indent=2))
