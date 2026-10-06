#!/usr/bin/env python3
"""Validate fresh149 metadata and visual artifacts without scientific payload IO.

This validator reads JSON/XML and PNG artifacts only.  It refuses BI4/H5/CSV/DAT/
VTK-like paths before opening or hashing them.  It validates actual terminal
receipts and the producer-reported 241-frame/3-D contracts; it does not infer
physics, UID survival, precision, Q-N/Q-E, or production approval from images.
"""
from __future__ import annotations
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "metadata"
FORBIDDEN = {".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtp", ".vtu", ".raw", ".npy", ".npz"}
CASES = {
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1125_YAWP12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1375_YAWP18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1625_YAWM18_DP025",
}
KEYS = [0, 24, 48, 72, 96, 120, 168, 192, 240]
COUNTS = {"fixed": 73441, "moving": 0, "fluid": 327680, "floating": 16384, "total": 417505}
GEN_COUNTS = {"fixed": 73441, "moving": 0, "fluid": 327680, "floating": 16384}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def load(path: Path):
    if path.suffix.lower() in FORBIDDEN:
        fail(f"scientific payload read refused: {path}")
    if not path.is_file():
        fail(f"missing metadata: {path}")
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        fail(f"invalid JSON {path}: {exc}")


def digest(path: Path) -> str:
    if path.suffix.lower() in FORBIDDEN:
        fail(f"scientific payload hash refused: {path}")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_ref(ref: dict, label: str, *, receipt: bool = False):
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not isinstance(ref.get("sha256"), str):
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
    p = check_ref(ref, label)
    return p, load(p)


def all_true(value: dict, label: str):
    if not isinstance(value, dict) or any(v is not True for v in value.values()):
        fail(f"{label}: missing or false check")


def main() -> None:
    selection = load(META / "selection.json")
    frozen = load(META / "checkpoint-159-snapshot.json")
    chain = load(META / "chain-closure.json")
    visual = load(META / "visual-review.json")
    evidence = load(META / "evidence-files.json")
    pngs = load(META / "png-evidence.json")
    objs = [(selection, "selection"), (chain, "chain"), (visual, "visual"), (evidence, "evidence"), (pngs, "pngs")]
    for obj, label in objs:
        if obj.get("package") != "fresh149":
            fail(f"{label}: package marker")
    if selection.get("family") != "F6" or selection.get("agent_model") != "gpt-5.6-luna":
        fail("selection family/model")
    if set(selection.get("selected_cases", [])) != CASES or len(selection.get("selected_cases", [])) != 3:
        fail("selection case set")
    if selection.get("checkpoint_selection_assertion") is not True:
        fail("selection checkpoint assertion")
    if frozen.get("checkpoint") != 159 or frozen.get("stage1_visual_accepted_complete_independent_cases") != 243:
        fail("checkpoint snapshot")
    if frozen.get("accepted_per_family", {}).get("F6") != 41:
        fail("checkpoint F6 count")
    if any(case in json.dumps(frozen, sort_keys=True) for case in CASES):
        fail("selected physical ID appears in checkpoint accepted snapshot")
    for marker, label in ((selection, "selection"), (visual, "visual"), (chain, "chain")):
        if marker.get("case_credit") != 0 or marker.get("global_credit_updated_by_agent") is not False:
            fail(f"{label}: credit marker")
        if marker.get("scientific_payload_read_or_hashed") is not False:
            fail(f"{label}: scientific payload marker")
    if evidence.get("forbidden_payloads_opened_or_hashed") != [] or evidence.get("scientific_payload_hashing") != "none":
        fail("evidence payload policy")
    if pngs.get("scientific_payload_hashing") != "none":
        fail("PNG payload policy")

    # Every evidence reference is JSON/XML/source metadata; PNGs are checked separately.
    for item in evidence.get("files", []):
        check_ref(item, "evidence")
    chain_cases = {c.get("case_id"): c for c in chain.get("cases", [])}
    visual_cases = {c.get("case_id"): c for c in visual.get("cases", [])}
    if set(chain_cases) != CASES or set(visual_cases) != CASES or set(pngs.get("cases", {})) != CASES:
        fail("case set mismatch")

    for case in sorted(CASES):
        c = chain_cases[case]
        v = visual_cases[case]
        p = c.get("producer_chain", {})
        if v.get("status") != "visual-approved-by-delegated-agent":
            fail(f"{case}: visual status")
        if v.get("reviewer") != "/root/f6_endpoint_initial_qa" or v.get("agent_model") != "gpt-5.6-luna":
            fail(f"{case}: reviewer/model")
        if v.get("agent_personally_viewed_all_contact_sheets") is not True or v.get("agent_personally_viewed_all_key_frames") is not True:
            fail(f"{case}: personal-view marker")
        if v.get("viewed_contact_sheet_indices") != list(range(11)) or v.get("viewed_key_frame_indices") != KEYS:
            fail(f"{case}: view inventory")
        failure = v.get("observations", {}).get("failure_screen", {})
        for key in ("initial_geometry_visible", "blank_or_cropped_camera_obvious", "severe_wall_or_body_penetration_obvious", "catastrophic_particle_explosion_obvious", "premature_termination_obvious"):
            if key not in failure:
                fail(f"{case}: physical visual field {key}")
        if v.get("producer_lifecycle", {}).get("final_uid_inferred_by_agent") is not False:
            fail(f"{case}: final UID inference")
        if v.get("producer_lifecycle", {}).get("state0_omega_inferred_from_particle_v0") is not False:
            fail(f"{case}: omega inference boundary")
        for key in ("gencase", "initial_native_qa", "full_native", "floatinginfo_state0", "typed_conversion", "typed_h5_audit", "xmf", "render"):
            if key not in p:
                fail(f"{case}: missing stage {key}")
            check_ref(p[key]["execution_receipt"], f"{case}:{key} receipt", receipt=True)

        scope = c.get("scope_separation", {})
        for key in ("source_plan_condition_sha256", "source_canonical_physical_condition_sha256", "classified_converter_scope_sha256", "actual_typed_producer_scope_sha256", "actual_h5_producer_scope_sha256", "actual_xmf_scope_sha256"):
            if not scope.get(key):
                fail(f"{case}: missing scope {key}")
        if len({scope["source_plan_condition_sha256"], scope["source_canonical_physical_condition_sha256"], scope["actual_typed_producer_scope_sha256"]}) != 3:
            fail(f"{case}: source/producer scope collapse")
        if scope.get("no_equivalence_assertion_between_source_canonical_classified_or_producer_scopes") is not True:
            fail(f"{case}: scope equivalence boundary")

        gen = p["gencase"]
        _, gen_report = report_ref(gen["prepared_input_report"], f"{case}: GenCase report")
        check_ref(gen["generated_xml"], f"{case}: generated XML")
        check_ref(gen["source_definition"], f"{case}: source Def")
        if gen.get("bi4_sha256_recomputed_by_this_package") is not False or not gen.get("producer_attested_bi4_sha256"):
            fail(f"{case}: BI4 attestation boundary")
        if gen.get("actual_total_particles") != 417505 or gen_report.get("actual_total_particles") != 417505:
            fail(f"{case}: GenCase total")
        if gen_report.get("generated_xml_particle_counts") != GEN_COUNTS:
            fail(f"{case}: GenCase counts")
        if gen.get("dimension_3d_from_xml_metadata") is not True:
            fail(f"{case}: GenCase 3D")

        qa = p["initial_native_qa"]
        _, qa_report = report_ref(qa["report"], f"{case}: initial QA report")
        if qa.get("pass") is not True or qa.get("true_3d") is not True or qa_report.get("pass") is not True:
            fail(f"{case}: initial QA status")
        all_true(qa_report.get("checks"), f"{case}: initial QA checks")
        if qa.get("counts") != COUNTS or qa.get("physical_mass_kg") != 128.0 or qa.get("native_support_mass_kg") != 256.0 or qa.get("native_mass_normalization_applied") is not False:
            fail(f"{case}: QA counts/mass")

        state = p["floatinginfo_state0"]
        _, state_report = report_ref(state["audit_report"], f"{case}: state0 report")
        check_ref(state["summary"], f"{case}: state0 summary")
        if state.get("status") != "pass" or state_report.get("status") != "pass":
            fail(f"{case}: state0 status")
        all_true(state_report.get("checks"), f"{case}: state0 checks")
        if state.get("particle_v0_is_not_angular_proof") is not True or not state.get("declared_omega_rad_s") or not state.get("observed_omega_rad_s"):
            fail(f"{case}: omega boundary")

        typed = p["typed_conversion"]
        _, typed_report = report_ref(typed["conversion_report"], f"{case}: typed report")
        if typed_report.get("conversion_status") != "completed" or typed_report.get("frames") != 241 or typed_report.get("particles") != 417505:
            fail(f"{case}: typed contract")
        if typed_report.get("solver_dimension", {}).get("solver_dimension") != 3 or typed_report.get("partvtk_validation", {}).get("all_passed") is not True:
            fail(f"{case}: typed dimension/PartVTK")
        if typed_report.get("time_evidence", {}).get("strictly_increasing") is not True or typed.get("source_package_did_not_read_or_hash_h5") is not True:
            fail(f"{case}: typed time/payload policy")
        if typed.get("producer_scope_sha256") != scope.get("actual_typed_producer_scope_sha256"):
            fail(f"{case}: typed scope")

        h5 = p["typed_h5_audit"]
        _, h5_report = report_ref(h5["report"], f"{case}: H5 audit report")
        if h5.get("status") != "pass" or h5.get("source_package_did_not_read_or_hash_h5") is not True:
            fail(f"{case}: H5 audit status/policy")
        all_true(h5_report.get("checks"), f"{case}: H5 audit checks")
        if h5.get("producer_physical_condition_sha256") != scope.get("actual_h5_producer_scope_sha256"):
            fail(f"{case}: H5 scope")

        xmf = p["xmf"]
        xmf_xml, manifest = report_ref(xmf["manifest"], f"{case}: XMF manifest")
        xmf_xml_path = check_ref(xmf["case_xmf"], f"{case}: XMF XML")
        if manifest.get("case_id") != case or manifest.get("physical_case_id") != case:
            fail(f"{case}: XMF identity")
        if manifest.get("expected_frames") != 241 or manifest.get("expected_particles") != 417505 or manifest.get("expected_dimension") != 3:
            fail(f"{case}: XMF dimensions")
        if manifest.get("physical_condition_sha256") != scope.get("actual_xmf_scope_sha256") or manifest.get("producer_scope_schema") != "ds-data-02.physical-binding.v1":
            fail(f"{case}: XMF scope")
        if manifest.get("audit658_dependency", {}).get("audit_status") != "pass" or manifest.get("floatinginfo_state0", {}).get("audit_status") != "pass":
            fail(f"{case}: XMF audit dependencies")
        if manifest.get("no_particle_v0_inference") is not True:
            fail(f"{case}: XMF angular boundary")
        xml_text = xmf_xml_path.read_text()
        try:
            root = ET.fromstring(xml_text)
        except Exception as exc:
            fail(f"{case}: XMF XML parse: {exc}")
        dims = set(re.findall(r'Dimensions="([^"]+)"', xml_text))
        if "417505 3" not in dims or "241 417505 3" not in dims:
            fail(f"{case}: XMF N3 dimensions")
        if len(root.findall('.//{*}Grid')) < 242:
            fail(f"{case}: XMF temporal grids")

        render = p["render"]
        _, render_report = report_ref(render["report"], f"{case}: render report")
        if render_report.get("frames") != 241 or render_report.get("source_frames") != 241 or render_report.get("all_frames_rendered") is not True or render_report.get("actual_times_preserved_exactly") is not True or render_report.get("nonfinite_active_states") != 0:
            fail(f"{case}: render integrity")
        if render_report.get("native_identity_axis_preserved") is not True or render_report.get("source_h5_read_only") is not True:
            fail(f"{case}: render identity/payload policy")
        _, pub = report_ref(render["publish_receipt"], f"{case}: publish receipt")
        if pub.get("status") != "published_after_atomic_rename":
            fail(f"{case}: publish status")

        inventory = pngs["cases"][case]
        if [i.get("index") for i in inventory.get("contact_sheets", [])] != list(range(11)) or [i.get("index") for i in inventory.get("key_frames", [])] != KEYS:
            fail(f"{case}: PNG inventory")
        for item in inventory["contact_sheets"] + inventory["key_frames"]:
            path = Path(item["path"])
            if path.suffix.lower() != ".png" or digest(path) != item.get("sha256"):
                fail(f"{case}: PNG evidence hash")
        if v.get("visual_evidence", {}).get("contact_sheet_count") != 11 or v.get("visual_evidence", {}).get("key_frame_count") != 9:
            fail(f"{case}: visual evidence counts")

    result = {
        "schema":"ds-data-02.fresh149.validator-result.v1","package":"fresh149","status":"PASS","case_count":3,
        "contact_sheets_per_case":11,"key_frames_per_case":9,"terminal_receipts_checked":True,
        "state0_typed_h5_xmf_render_metadata_checked":True,"xmf_vector_dimensions_checked":True,"png_sha256_checked":True,
        "metadata_and_png_only":True,"scientific_payload_read_or_hashed":False,"global_credit_updated":False,
    }
    (META / "validator-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
