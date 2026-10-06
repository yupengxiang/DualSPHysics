#!/usr/bin/env python3
"""Validate fresh145 without opening or hashing scientific payloads.

Only JSON/XML metadata and PNG visual artifacts are read.  BI4/H5/CSV/DAT/VTK
and related payload suffixes are rejected before any filesystem read/hash.
"""
from __future__ import annotations
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "metadata"
FORBIDDEN = {".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtp", ".vtu", ".raw"}
CASES = {
    "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0625_YAWM06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0875_YAWP06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S1125_YAWP12_DP025",
}
KEYS = [0, 24, 48, 72, 96, 120, 168, 192, 240]
COUNTS = {"fixed": 73441, "moving": 0, "fluid": 327680, "floating": 16384}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def digest(path: Path) -> str:
    if path.suffix.lower() in FORBIDDEN:
        fail(f"scientific payload hash refused: {path}")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path):
    if path.suffix.lower() in FORBIDDEN:
        fail(f"scientific payload read refused: {path}")
    if not path.is_file():
        fail(f"missing metadata: {path}")
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        fail(f"invalid JSON {path}: {exc}")


def check_ref(ref: dict, label: str, *, receipt: bool = False) -> Path:
    if not isinstance(ref, dict) or "path" not in ref or "sha256" not in ref:
        fail(f"{label}: malformed reference")
    path = Path(ref["path"])
    if path.suffix.lower() in FORBIDDEN:
        fail(f"{label}: forbidden payload path")
    if "actual-progress.json" in str(path) or "controller-result.json" in str(path):
        fail(f"{label}: mutable routing evidence is not admissible")
    if not path.is_file():
        fail(f"{label}: missing {path}")
    if digest(path) != ref["sha256"]:
        fail(f"{label}: SHA mismatch {path}")
    if receipt:
        obj = load(path)
        if obj.get("status") != "completed" or obj.get("returncode") != 0:
            fail(f"{label}: receipt is not completed/0")
    return path


def report_ref(ref: dict, label: str):
    path = check_ref(ref, label)
    return path, load(path)


def all_true(obj: dict, label: str) -> None:
    if not obj or any(value is not True for value in obj.values()):
        fail(f"{label}: a declared check is false or missing")


def main() -> None:
    selection = load(META / "selection.json")
    visual = load(META / "visual-review.json")
    chain = load(META / "chain-closure.json")
    evidence = load(META / "evidence-files.json")
    pngs = load(META / "png-hashes.json")
    frozen = load(META / "checkpoint-152-snapshot.json")
    for obj, label in ((selection, "selection"), (visual, "visual"), (chain, "chain"), (evidence, "evidence"), (pngs, "pngs")):
        if obj.get("package") != "fresh145":
            fail(f"{label}: package marker")
        if obj.get("family") not in (None, "F6"):
            fail(f"{label}: family marker")
    if set(selection.get("selected_cases", [])) != CASES or len(selection.get("selected_cases", [])) != 3:
        fail("selection case set")
    if selection.get("checkpoint_selection_assertion") is not True:
        fail("selection did not prove checkpoint de-duplication")
    if selection.get("frozen_checkpoint", {}).get("accepted_complete_count") != 231:
        fail("wrong frozen checkpoint count")
    if selection.get("case_credit") != 0 or selection.get("global_credit_updated_by_agent") is not False:
        fail("selection credit marker")
    if visual.get("reviewer") != "/root/f6_endpoint_initial_qa" or visual.get("agent_model") != "gpt-5.6-luna":
        fail("reviewer/model marker")
    if visual.get("case_credit") != 0 or visual.get("global_credit_updated_by_agent") is not False:
        fail("visual credit marker")
    if visual.get("scientific_payload_read_or_hashed") is not False:
        fail("scientific payload marker")
    if evidence.get("scientific_payload_hashing") != "none" or pngs.get("scientific_payload_hashing") != "none":
        fail("scientific payload hash policy")
    if evidence.get("forbidden_payloads_opened_or_hashed") != []:
        fail("forbidden payload evidence")
    if frozen.get("stage1_visual_accepted_complete_independent_cases") != 231:
        fail("frozen checkpoint is not cp152")
    frozen_text = json.dumps(frozen, sort_keys=True)
    if any(case in frozen_text for case in CASES):
        fail("selected physical ID appears in frozen accepted snapshot")

    for item in evidence.get("files", []):
        check_ref(item, "evidence")
    visual_cases = {item["case_id"]: item for item in visual.get("cases", [])}
    chain_cases = {item["case_id"]: item for item in chain.get("cases", [])}
    if set(visual_cases) != CASES or set(chain_cases) != CASES:
        fail("case set mismatch")
    if set(pngs.get("cases", {})) != CASES:
        fail("PNG case set mismatch")

    for case_id in sorted(CASES):
        v = visual_cases[case_id]
        c = chain_cases[case_id]
        if v.get("status") != "visual-approved-by-delegated-agent":
            fail(f"{case_id}: visual status")
        if v.get("agent_personally_viewed_all_contact_sheets") is not True or v.get("agent_personally_viewed_all_key_frames") is not True:
            fail(f"{case_id}: personal-view marker")
        if v.get("viewed_contact_sheet_indices") != list(range(11)) or v.get("viewed_key_frame_indices") != KEYS:
            fail(f"{case_id}: view inventory")
        if v.get("case_credit") != 0 or v.get("global_credit_updated_by_agent") is not False:
            fail(f"{case_id}: case credit")
        if v.get("producer_lifecycle", {}).get("final_uid_inferred_by_agent") is not False:
            fail(f"{case_id}: final UID inference")
        failure = v.get("observations", {}).get("failure_screen", {})
        for key in ("initial_geometry_visible", "severe_wall_or_body_penetration_obvious", "catastrophic_particle_explosion_obvious", "blank_or_cropped_camera_obvious", "premature_termination_obvious"):
            if key not in failure:
                fail(f"{case_id}: missing physical visual field {key}")
        scope = c.get("scope_separation", {})
        for key in ("source_plan_condition_sha256", "source_canonical_physical_condition_sha256", "classified_converter_scope_sha256", "actual_typed_producer_scope_sha256"):
            if not scope.get(key):
                fail(f"{case_id}: missing scope {key}")
        if len({scope["source_plan_condition_sha256"], scope["source_canonical_physical_condition_sha256"], scope["actual_typed_producer_scope_sha256"]}) != 3:
            fail(f"{case_id}: collapsed source/producer scopes")
        if scope.get("no_equivalence_assertion_between_source_canonical_and_classified_or_producer_scopes") is not True:
            fail(f"{case_id}: scope equivalence boundary")

        p = c.get("producer_chain", {})
        expected = ("gencase", "initial_native_qa", "full_native", "floatinginfo_state0", "typed_conversion", "typed_h5_audit", "xmf", "render")
        if set(p) != set(expected):
            fail(f"{case_id}: stage set")
        for stage in expected:
            check_ref(p[stage]["execution_receipt"], f"{case_id}:{stage} receipt", receipt=True)

        gen = p["gencase"]
        _, gen_report = report_ref(gen["prepared_input_report"], f"{case_id}: GenCase report")
        check_ref(gen["generated_xml"], f"{case_id}: generated XML")
        check_ref(gen["source_definition"], f"{case_id}: source Def")
        if gen.get("bi4_sha256_recomputed_by_this_package") is not False:
            fail(f"{case_id}: BI4 recompute marker")
        if not gen.get("producer_attested_bi4_sha256"):
            fail(f"{case_id}: producer BI4 attestation missing")
        if gen.get("actual_total_particles") != 417505 or gen_report.get("actual_total_particles") != 417505:
            fail(f"{case_id}: GenCase total")
        if gen_report.get("generated_xml_particle_counts") != COUNTS:
            fail(f"{case_id}: GenCase counts")
        if gen_report.get("actual_generated_constants", {}).get("data2d", {}).get("value") != "false":
            fail(f"{case_id}: GenCase 3D metadata")

        qa = p["initial_native_qa"]
        _, qa_report = report_ref(qa["report"], f"{case_id}: initial QA report")
        if qa.get("pass") is not True or qa.get("true_3d") is not True or qa_report.get("pass") is not True:
            fail(f"{case_id}: initial QA status")
        all_true(qa_report.get("checks", {}), f"{case_id}: initial QA checks")
        if qa.get("counts", {}).get("total") != 417505 or {k: qa.get("counts", {}).get(k) for k in COUNTS} != COUNTS:
            fail(f"{case_id}: QA counts")
        if qa.get("physical_mass_kg") != 128.0 or qa.get("native_support_mass_kg") != 256.0 or qa.get("native_mass_normalization_applied") is not False:
            fail(f"{case_id}: mass semantics")

        state = p["floatinginfo_state0"]
        _, state_report = report_ref(state["audit_report"], f"{case_id}: state0 audit")
        all_true(state_report.get("checks", {}), f"{case_id}: state0 checks")
        if state_report.get("status") != "pass" or state.get("status") != "pass":
            fail(f"{case_id}: state0 status")
        if state.get("particle_v0_is_not_angular_proof") is not True or not state.get("declared_omega_rad_s") or not state.get("observed_omega_rad_s"):
            fail(f"{case_id}: omega proof boundary")

        typed = p["typed_conversion"]
        _, typed_report = report_ref(typed["conversion_report"], f"{case_id}: typed report")
        if typed_report.get("conversion_status") != "completed" or typed_report.get("frames") != 241 or typed_report.get("particles") != 417505:
            fail(f"{case_id}: typed frame/particle contract")
        if typed_report.get("solver_dimension", {}).get("solver_dimension") != 3 or typed_report.get("partvtk_validation", {}).get("all_passed") is not True:
            fail(f"{case_id}: typed dimension/PartVTK metadata")
        if typed_report.get("time_evidence", {}).get("strictly_increasing") is not True or typed.get("source_package_did_not_read_or_hash_h5") is not True:
            fail(f"{case_id}: typed time/payload boundary")
        if typed.get("producer_scope_sha256") != scope.get("actual_typed_producer_scope_sha256"):
            fail(f"{case_id}: typed producer scope")

        h5 = p["typed_h5_audit"]
        _, h5_report = report_ref(h5["report"], f"{case_id}: H5 audit metadata")
        all_true(h5_report.get("checks", {}), f"{case_id}: H5 audit checks")
        if h5_report.get("status") != "pass" or h5.get("source_package_did_not_read_or_hash_h5") is not True:
            fail(f"{case_id}: H5 audit status/boundary")
        conv = h5_report.get("conversion_report", {})
        if {k: conv.get(k) for k in ("frames", "particles", "dimension")} != {"frames":241,"particles":417505,"dimension":3} or conv.get("partvtk_all_passed") is not True:
            fail(f"{case_id}: H5 conversion metadata")
        if h5.get("producer_physical_condition_sha256") != scope.get("actual_typed_producer_scope_sha256"):
            fail(f"{case_id}: H5 producer scope")

        xmf = p["xmf"]
        xmf_path, manifest = report_ref(xmf["manifest"], f"{case_id}: XMF manifest")
        xmf_xml = check_ref(xmf["case_xmf"], f"{case_id}: XMF XML")
        if manifest.get("case_id") != case_id or manifest.get("physical_case_id") != case_id:
            fail(f"{case_id}: XMF identity")
        if manifest.get("expected_frames") != 241 or manifest.get("expected_particles") != 417505 or manifest.get("expected_dimension") != 3:
            fail(f"{case_id}: XMF dimensions")
        if manifest.get("physical_condition_sha256") != scope.get("actual_typed_producer_scope_sha256") or manifest.get("producer_scope_schema") != "ds-data-02.physical-binding.v1":
            fail(f"{case_id}: XMF producer scope")
        if manifest.get("audit658_dependency", {}).get("audit_status") != "pass" or manifest.get("floatinginfo_state0", {}).get("audit_status") != "pass":
            fail(f"{case_id}: XMF audit dependencies")
        if manifest.get("no_particle_v0_inference") is not True:
            fail(f"{case_id}: XMF angular boundary")
        try:
            root = ET.parse(xmf_xml).getroot()
        except Exception as exc:
            fail(f"{case_id}: XMF XML parse: {exc}")
        xml_text = xmf_xml.read_text()
        dims = set(re.findall(r'Dimensions="([^"]+)"', xml_text))
        if "417505 3" not in dims or "241 417505 3" not in dims:
            fail(f"{case_id}: XMF N3 vector dimensions")
        if len(root.findall('.//{*}Grid')) < 242:
            fail(f"{case_id}: XMF temporal grid count")

        render = p["render"]
        _, render_report = report_ref(render["report"], f"{case_id}: render report")
        if render_report.get("frames") != 241 or render_report.get("source_frames") != 241 or render_report.get("all_frames_rendered") is not True or render_report.get("actual_times_preserved_exactly") is not True or render_report.get("nonfinite_active_states") != 0:
            fail(f"{case_id}: render integrity")
        if render_report.get("native_identity_axis_preserved") is not True or render_report.get("source_h5_read_only") is not True:
            fail(f"{case_id}: render identity/source contract")
        _, pub = report_ref(render["publish_receipt"], f"{case_id}: render publish receipt")
        if pub.get("status") != "published_after_atomic_rename":
            fail(f"{case_id}: publish status")
        inv = pngs["cases"][case_id]
        if [item.get("index") for item in inv.get("contact_sheets", [])] != list(range(11)) or [item.get("index") for item in inv.get("key_frames", [])] != KEYS:
            fail(f"{case_id}: PNG inventory")
        for item in inv["contact_sheets"] + inv["key_frames"]:
            path = Path(item["path"])
            if path.suffix.lower() != ".png" or digest(path) != item.get("sha256"):
                fail(f"{case_id}: PNG hash")
        if v.get("visual_evidence", {}).get("contact_sheet_count") != 11 or v.get("visual_evidence", {}).get("key_frame_count") != 9:
            fail(f"{case_id}: visual evidence counts")

    result = {
        "schema": "ds-data-02.fresh145.validator-result.v1",
        "status": "PASS",
        "package": "fresh145",
        "case_count": len(CASES),
        "contact_sheets_per_case": 11,
        "key_frames_per_case": 9,
        "terminal_receipts_checked": True,
        "state0_typed_h5_xmf_render_metadata_checked": True,
        "xmf_vector_dimensions_checked": True,
        "png_sha256_checked": True,
        "global_credit_updated": False,
        "scientific_payload_read_or_hashed": False,
        "metadata_and_png_only": True,
    }
    (META / "validator-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
