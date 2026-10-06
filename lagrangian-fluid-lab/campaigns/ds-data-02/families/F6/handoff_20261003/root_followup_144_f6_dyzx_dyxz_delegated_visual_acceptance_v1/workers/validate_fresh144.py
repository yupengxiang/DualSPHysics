#!/usr/bin/env python3
"""Validate fresh144 metadata and rendered PNG evidence without scientific payload IO.

Only JSON/XML metadata and PNG visual artifacts are opened or hashed here.
BI4/H5/CSV/DAT/VTK payloads are rejected by suffix before any read/hash.
"""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "metadata"
FORBIDDEN = {".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtp", ".vtu"}
KEYS = [0, 24, 48, 72, 96, 120, 168, 192, 240]
CASES = {
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S0875_YAWP06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S1625_YAWM18_DP025",
}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def load(path: Path):
    if path.suffix.lower() in FORBIDDEN:
        fail(f"scientific payload read refused: {path}")
    if not path.is_file():
        fail(f"missing file: {path}")
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    if path.suffix.lower() in FORBIDDEN:
        fail(f"scientific payload hash refused: {path}")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_ref(ref, label: str, *, receipt: bool = False) -> Path:
    path = Path(ref["path"])
    if path.suffix.lower() in FORBIDDEN:
        fail(f"{label}: forbidden payload path")
    if "actual-progress.json" in str(path) or "controller-result.json" in str(path):
        fail(f"{label}: mutable routing evidence is frozen")
    if not path.is_file():
        fail(f"{label}: missing {path}")
    if ref.get("sha256") != digest(path):
        fail(f"{label}: SHA mismatch {path}")
    if receipt:
        d = load(path)
        if d.get("status") != "completed" or d.get("returncode") != 0:
            fail(f"{label}: not terminal completed/0")
    return path


def report_ref(ref, label: str) -> tuple[Path, dict]:
    p = check_ref(ref, label)
    return p, load(p)


def main() -> None:
    selection = load(META / "selection.json")
    visual = load(META / "visual-review.json")
    chain = load(META / "chain-closure.json")
    evidence = load(META / "evidence-files.json")
    pngs = load(META / "png-hashes.json")

    for obj, name in ((selection, "selection"), (visual, "visual"), (chain, "chain"), (evidence, "evidence"), (pngs, "pngs")):
        if obj.get("package") != "fresh144":
            fail(f"{name}: package marker")
        if obj.get("family") not in (None, "F6"):
            fail(f"{name}: family marker")
    if set(selection.get("selected_cases", [])) != CASES or len(selection.get("selected_cases", [])) != 2:
        fail("selection case set mismatch")
    if visual.get("reviewer") != "/root/f6_endpoint_initial_qa":
        fail("visual reviewer mismatch")
    if visual.get("agent_model") != "gpt-5.6-luna":
        fail("model mismatch")
    if visual.get("case_credit") != 0 or visual.get("global_credit_updated_by_agent") is not False:
        fail("global credit marker")
    if visual.get("scientific_payload_read_or_hashed") is not False:
        fail("scientific payload marker")
    if evidence.get("scientific_payload_hashing") != "none" or pngs.get("scientific_payload_hashing") != "none":
        fail("scientific hashing policy")
    if evidence.get("forbidden_payloads_opened_or_hashed") != []:
        fail("forbidden payload evidence")

    # Validate every declared metadata reference before interpreting stage fields.
    for item in evidence.get("files", []):
        check_ref(item, "evidence")

    visual_cases = {x["case_id"]: x for x in visual.get("cases", [])}
    chain_cases = {x["case_id"]: x for x in chain.get("cases", [])}
    if set(visual_cases) != CASES or set(chain_cases) != CASES:
        fail("selected case sets are not exact")
    png_case_map = pngs.get("cases", {})
    if set(png_case_map) != CASES:
        fail("PNG case set mismatch")

    for case_id in sorted(CASES):
        v = visual_cases[case_id]
        c = chain_cases[case_id]
        if v.get("status") != "visual-approved-by-delegated-agent":
            fail(f"{case_id}: status")
        if v.get("agent_personally_viewed_all_contact_sheets") is not True or v.get("agent_personally_viewed_all_key_frames") is not True:
            fail(f"{case_id}: personal-view markers")
        if v.get("viewed_contact_sheet_indices") != list(range(11)) or v.get("viewed_key_frame_indices") != KEYS:
            fail(f"{case_id}: view inventory")
        if v.get("case_credit") != 0 or v.get("global_credit_updated_by_agent") is not False:
            fail(f"{case_id}: case-credit marker")
        lifecycle = v.get("producer_lifecycle", {})
        if lifecycle.get("final_uid_inferred_by_agent") is not False:
            fail(f"{case_id}: final UID inferred")
        scope = v.get("scope_separation", {})
        if not (scope.get("source_plan_condition_sha256") and scope.get("source_canonical_physical_condition_sha256") and scope.get("actual_typed_producer_scope_sha256")):
            fail(f"{case_id}: incomplete scope separation")
        if scope["source_plan_condition_sha256"] == scope["source_canonical_physical_condition_sha256"]:
            fail(f"{case_id}: source plan and canonical scope collapsed")
        if scope["source_canonical_physical_condition_sha256"] == scope["actual_typed_producer_scope_sha256"]:
            fail(f"{case_id}: canonical and actual scope collapsed")
        if "separate roles" not in scope.get("scope_statement", "") or "does not use inherited" not in scope.get("scope_statement", ""):
            fail(f"{case_id}: scope statement")

        p = c["producer_chain"]
        expected_stages = ("gencase", "initial_native_qa", "full_native", "floatinginfo_state0", "typed_conversion", "typed_h5_audit", "xmf", "render")
        if set(p) != set(expected_stages):
            fail(f"{case_id}: stage set")
        for stage in expected_stages:
            if "execution_receipt" not in p[stage]:
                fail(f"{case_id}:{stage}: receipt missing")
            check_ref(p[stage]["execution_receipt"], f"{case_id}:{stage} receipt", receipt=True)

        gen = p["gencase"]
        gen_report_path, gen_report = report_ref(gen["prepared_input_report"], f"{case_id}: GenCase report")
        check_ref(gen["generated_xml"], f"{case_id}: generated XML")
        check_ref(gen["source_definition"], f"{case_id}: source Def")
        if gen.get("bi4_sha256_recomputed_by_this_package") is not False:
            fail(f"{case_id}: package recomputed BI4")
        if not gen.get("producer_attested_bi4_sha256"):
            fail(f"{case_id}: missing producer BI4 attestation")
        if gen_report.get("actual_total_particles") != 417505 or gen.get("actual_total_particles") != 417505:
            fail(f"{case_id}: GenCase total")
        counts = gen_report.get("generated_xml_particle_counts", {})
        if counts != {"fixed": 73441, "floating": 16384, "fluid": 327680, "moving": 0}:
            fail(f"{case_id}: GenCase count metadata")
        if gen_report.get("actual_generated_constants", {}).get("data2d", {}).get("value") != "false":
            fail(f"{case_id}: GenCase data2d")

        qa = p["initial_native_qa"]
        qa_path, qa_report = report_ref(qa["report"], f"{case_id}: initial QA report")
        if qa.get("pass") is not True or qa.get("true_3d") is not True or qa_report.get("pass") is not True:
            fail(f"{case_id}: initial QA pass/3D")
        if not all(qa_report.get("checks", {}).values()):
            fail(f"{case_id}: initial QA check false")
        if sum(int(qa.get("counts", {}).get(k, 0)) for k in ("fixed", "moving", "fluid", "floating")) != 417505:
            fail(f"{case_id}: QA count total")
        if qa.get("native_mass_normalization_applied") is not False or qa.get("physical_mass_kg") != 128.0 or qa.get("native_support_mass_kg") != 256.0:
            fail(f"{case_id}: mass semantics")

        state = p["floatinginfo_state0"]
        state_path, state_report = report_ref(state["audit_report"], f"{case_id}: state0 report")
        if state_report.get("status") != "pass" or not state_report.get("checks") or not all(state_report["checks"].values()):
            fail(f"{case_id}: state0 report")
        if state.get("particle_v0_is_not_angular_proof") is not True:
            fail(f"{case_id}: V0/angular boundary")
        if not state.get("declared_omega_rad_s") or not state.get("observed_omega_rad_s"):
            fail(f"{case_id}: omega evidence")

        typed = p["typed_conversion"]
        typed_path, typed_report = report_ref(typed["conversion_report"], f"{case_id}: typed report")
        if typed_report.get("conversion_status") != "completed" or typed_report.get("frames") != 241 or typed_report.get("particles") != 417505:
            fail(f"{case_id}: typed conversion contract")
        solver_dim = typed_report.get("solver_dimension", {})
        if not isinstance(solver_dim, dict) or solver_dim.get("solver_dimension") != 3:
            fail(f"{case_id}: typed dimension")
        if typed_report.get("partvtk_validation", {}).get("all_passed") is not True:
            fail(f"{case_id}: typed PartVTK contract")
        if typed.get("source_package_did_not_read_or_hash_h5") is not True:
            fail(f"{case_id}: typed H5 boundary")
        if typed.get("producer_scope_sha256") != scope.get("actual_typed_producer_scope_sha256"):
            fail(f"{case_id}: typed scope mismatch")
        if typed_report.get("time_evidence", {}).get("strictly_increasing") is not True:
            fail(f"{case_id}: typed time contract")

        h5 = p["typed_h5_audit"]
        h5_path, h5_report = report_ref(h5["report"], f"{case_id}: H5 audit report")
        if h5_report.get("status") != "pass" or not h5_report.get("checks") or not all(h5_report["checks"].values()):
            fail(f"{case_id}: H5 audit")
        if h5.get("source_package_did_not_read_or_hash_h5") is not True:
            fail(f"{case_id}: H5 source boundary")
        h5_conversion = h5_report.get("conversion_report", {})
        if h5_conversion.get("frames") != 241 or h5_conversion.get("particles") != 417505 or h5_conversion.get("dimension") != 3 or h5_conversion.get("partvtk_all_passed") is not True:
            fail(f"{case_id}: H5 audit conversion metadata")
        if h5.get("producer_physical_condition_sha256") != scope.get("actual_typed_producer_scope_sha256"):
            fail(f"{case_id}: H5 producer scope")

        xmf = p["xmf"]
        manifest_path, manifest = report_ref(xmf["manifest"], f"{case_id}: XMF manifest")
        xmf_path = check_ref(xmf["case_xmf"], f"{case_id}: XMF XML")
        if manifest.get("case_id") != case_id or manifest.get("physical_case_id") != case_id:
            fail(f"{case_id}: XMF physical identity")
        if manifest.get("frames") != 241 or manifest.get("expected_frames") != 241 or manifest.get("expected_particles") != 417505 or manifest.get("expected_dimension") != 3:
            fail(f"{case_id}: XMF dimensions")
        if manifest.get("producer_scope_schema") != "ds-data-02.physical-binding.v1":
            fail(f"{case_id}: XMF producer scope schema")
        if manifest.get("audit658_dependency", {}).get("audit_status") != "pass" or manifest.get("audit658_dependency", {}).get("checks_all_pass") is not True:
            fail(f"{case_id}: XMF H5-audit dependency")
        if manifest.get("no_particle_v0_inference") is not True or manifest.get("source_h5_read_only") is not True:
            fail(f"{case_id}: XMF source boundary")
        if manifest.get("physical_condition_sha256") != scope.get("actual_typed_producer_scope_sha256"):
            fail(f"{case_id}: XMF physical scope")
        try:
            root = ET.parse(xmf_path).getroot()
        except Exception as exc:
            fail(f"{case_id}: XMF XML parse: {exc}")
        xml_text = xmf_path.read_text()
        dims = set(re.findall(r'Dimensions="([^"]+)"', xml_text))
        if "417505 3" not in dims or "241 417505 3" not in dims:
            fail(f"{case_id}: XMF vector dimensions")
        grids = root.findall('.//{*}Grid')
        if len(grids) < 242:
            fail(f"{case_id}: XMF grid count {len(grids)}")

        render = p["render"]
        render_path, render_report = report_ref(render["report"], f"{case_id}: render report")
        if render_report.get("frames") != 241 or render_report.get("source_frames") != 241 or render_report.get("all_frames_rendered") is not True or render_report.get("actual_times_preserved_exactly") is not True or render_report.get("nonfinite_active_states") != 0:
            fail(f"{case_id}: render report contract")
        if render_report.get("native_identity_axis_preserved") is not True or render_report.get("source_h5_read_only") is not True:
            fail(f"{case_id}: render identity/source contract")
        if render_report.get("visual_review") != "pending root inspection of the full animation and every contact sheet":
            fail(f"{case_id}: source visual review marker")
        pub_path, pub = report_ref(render["publish_receipt"], f"{case_id}: publish receipt")
        if pub.get("status") != "published_after_atomic_rename":
            fail(f"{case_id}: publish status")
        inv = png_case_map[case_id]
        contacts = inv.get("contact_sheets", [])
        keys = inv.get("key_frames", [])
        if [x.get("index") for x in contacts] != list(range(11)) or [x.get("index") for x in keys] != KEYS:
            fail(f"{case_id}: PNG inventory indices")
        for item in contacts + keys:
            path = Path(item["path"])
            if path.suffix.lower() != ".png" or digest(path) != item.get("sha256"):
                fail(f"{case_id}: PNG hash/path")
        if v.get("render_report", {}).get("sha256") != render["report"].get("sha256"):
            fail(f"{case_id}: visual/render ref mismatch")

    result = {
        "schema": "ds-data-02.fresh144.validator-result.v1",
        "status": "PASS",
        "package": "fresh144",
        "case_count": 2,
        "contact_sheets_per_case": 11,
        "key_frames_per_case": 9,
        "terminal_receipts_checked": True,
        "state0_typed_h5_xmf_metadata_checked": True,
        "xmf_vector_dimensions_checked": True,
        "png_sha256_checked": True,
        "science_payload_read_or_hashed": False,
        "global_credit_updated": False,
    }
    (META / "validator-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
