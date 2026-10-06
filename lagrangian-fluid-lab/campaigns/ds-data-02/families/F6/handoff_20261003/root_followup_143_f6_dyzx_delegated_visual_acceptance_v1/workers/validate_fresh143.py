#!/usr/bin/env python3
"""Metadata and rendered-PNG validator for fresh143.

The validator deliberately opens only JSON/XML metadata and PNG visual
artifacts.  It never opens or hashes BI4, H5, CSV, DAT, VTK, or other
scientific payloads.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VISUAL = ROOT / "metadata/visual-review.json"
CHAIN = ROOT / "metadata/chain-closure.json"
EVIDENCE = ROOT / "metadata/evidence-files.json"
PNGS = ROOT / "metadata/png-hashes.json"
FORBIDDEN = {".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtp", ".vtu"}
KEYS = [0, 24, 48, 72, 96, 120, 168, 192, 240]


def load(path: Path):
    return json.loads(path.read_text())


def sha(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fail(message: str):
    raise SystemExit(f"FAIL: {message}")


def check_receipt(record, label):
    path = Path(record["path"])
    if not path.is_file():
        fail(f"{label}: receipt missing: {path}")
    if path.suffix.lower() in FORBIDDEN:
        fail(f"{label}: forbidden receipt suffix: {path}")
    if record.get("sha256") != sha(path):
        fail(f"{label}: receipt SHA mismatch: {path}")
    receipt = load(path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        fail(f"{label}: receipt is not completed/0")


def check_metadata_path(record, label):
    path = Path(record["path"])
    if not path.is_file():
        fail(f"{label}: missing metadata: {path}")
    if path.suffix.lower() in FORBIDDEN:
        fail(f"{label}: forbidden metadata suffix: {path}")
    if record.get("sha256") != sha(path):
        fail(f"{label}: metadata SHA mismatch: {path}")


def main():
    visual = load(VISUAL)
    chain = load(CHAIN)
    evidence = load(EVIDENCE)
    pngs = load(PNGS)

    if visual.get("package") != "fresh143":
        fail("wrong visual package")
    if visual.get("family") != "F6":
        fail("wrong family")
    if visual.get("reviewer") != "/root/f6_endpoint_initial_qa":
        fail("wrong reviewer")
    if visual.get("case_credit") != 0 or visual.get("global_credit_updated_by_agent") is not False:
        fail("visual package claims global credit")
    if visual.get("scientific_payload_read_or_hashed") is not False:
        fail("scientific payload marker is not false")
    if chain.get("package") != "fresh143" or chain.get("global_credit_updated_by_agent") is not False:
        fail("chain package marker or credit marker invalid")
    if evidence.get("scientific_payload_hashing") != "none":
        fail("evidence package permits scientific hashing")
    if pngs.get("scientific_payload_hashing") != "none":
        fail("PNG inventory permits scientific hashing")

    for entry in evidence.get("files", []):
        path = Path(entry["path"])
        if path.suffix.lower() in FORBIDDEN:
            fail(f"forbidden scientific payload in evidence list: {path}")
        if "actual-progress.json" in str(path) or "controller-result.json" in str(path):
            fail(f"mutable routing evidence was frozen: {path}")
        check_metadata_path(entry, "evidence")

    visual_cases = {c["case_id"]: c for c in visual.get("cases", [])}
    chain_cases = {c["case_id"]: c for c in chain.get("cases", [])}
    png_cases = pngs.get("cases", {})
    if set(visual_cases) != set(chain_cases) or len(visual_cases) != 2:
        fail("expected two matching cases in visual and chain packages")

    for case_id, case in visual_cases.items():
        if case.get("status") != "visual-approved-by-delegated-agent":
            fail(f"{case_id}: invalid delegated status")
        if case.get("agent_personally_viewed_all_contact_sheets") is not True:
            fail(f"{case_id}: contacts were not personally viewed")
        if case.get("agent_personally_viewed_all_key_frames") is not True:
            fail(f"{case_id}: keys were not personally viewed")
        if case.get("case_credit") != 0 or case.get("global_credit_updated_by_agent") is not False:
            fail(f"{case_id}: case credit marker invalid")
        if case.get("viewed_contact_sheet_indices") != list(range(11)):
            fail(f"{case_id}: contact inventory is not 0..10")
        if case.get("viewed_key_frame_indices") != KEYS:
            fail(f"{case_id}: key inventory mismatch")
        scope = case.get("scope_separation", {})
        statement = scope.get("scope_statement", "")
        if "separate roles" not in statement or "does not use inherited" not in statement:
            fail(f"{case_id}: scope separation is incomplete")
        lifecycle = case.get("producer_lifecycle", {})
        if lifecycle.get("final_uid_inferred_by_agent") is not False:
            fail(f"{case_id}: agent inferred final UID")
        chain_case = chain_cases[case_id]
        producer = chain_case.get("producer_chain", {})
        for label in ("gencase", "initial_native_qa", "full_native", "floatinginfo_state0", "typed_conversion", "typed_h5_audit", "xmf", "render"):
            if label not in producer:
                fail(f"{case_id}: missing chain stage {label}")
        for stage in ("gencase", "initial_native_qa", "full_native", "floatinginfo_state0", "typed_conversion", "typed_h5_audit", "xmf", "render"):
            stage_data = producer[stage]
            receipt = stage_data.get("execution_receipt")
            if receipt:
                check_receipt(receipt, f"{case_id}:{stage}")
        qa = producer["initial_native_qa"]
        if qa.get("pass") is not True or qa.get("true_3d") is not True:
            fail(f"{case_id}: initial QA metadata does not pass/3D")
        qa_counts = qa.get("counts", {})
        if sum(int(qa_counts.get(k, 0)) for k in ("fixed", "moving", "fluid", "floating")) != 417505:
            fail(f"{case_id}: wrong QA total")
        state_audit = producer["floatinginfo_state0"]["audit_report"]
        state_path = Path(state_audit["path"])
        state = load(state_path)
        if state.get("status") != "pass" or not all(state.get("checks", {}).values()):
            fail(f"{case_id}: state0 audit is not pass/all checks")
        if producer["floatinginfo_state0"].get("particle_v0_is_not_angular_proof") is not True:
            fail(f"{case_id}: missing v0 inference boundary")
        typed_report = producer["typed_conversion"]["conversion_report"]
        typed = load(Path(typed_report["path"]))
        if typed.get("conversion_status") != "completed" or typed.get("frames") != 241:
            fail(f"{case_id}: typed conversion not completed/241")
        if typed.get("solver_dimension", {}).get("solver_dimension") != 3:
            fail(f"{case_id}: typed solver is not 3D")
        if typed_report.get("particles") != 417505 or typed_report.get("partvtk_all_passed") is not True:
            fail(f"{case_id}: typed particle contract failed")
        h5_data = producer["typed_h5_audit"]["report"]
        h5 = load(Path(h5_data["path"]))
        if h5.get("status") != "pass" or not all(h5.get("checks", {}).values()):
            fail(f"{case_id}: H5 audit is not pass/all checks")
        if producer["typed_h5_audit"].get("source_package_did_not_read_or_hash_h5") is not True:
            fail(f"{case_id}: H5 read/hash boundary missing")
        if h5.get("conversion_report", {}).get("frames") != 241 or h5.get("conversion_report", {}).get("dimension") != 3:
            fail(f"{case_id}: H5 audit conversion metadata mismatch")
        manifest_data = producer["xmf"]["manifest"]
        manifest = load(Path(manifest_data["path"]))
        if manifest.get("frames") != 241 or manifest.get("expected_particles") != 417505 or manifest.get("expected_dimension") != 3:
            fail(f"{case_id}: XMF manifest contract failed")
        if manifest_data.get("audit_dependency", {}).get("audit_status") != "pass":
            fail(f"{case_id}: XMF audit dependency is not pass")
        render_data = producer["render"]["report"]
        render = load(Path(render_data["path"]))
        for key, expected in (("frames", 241), ("source_frames", 241), ("all_frames_rendered", True), ("actual_times_preserved_exactly", True), ("nonfinite_active_states", 0)):
            if render.get(key) != expected:
                fail(f"{case_id}: render {key}={render.get(key)!r}, expected {expected!r}")
        if render_data.get("visual_review_field_before_delegated_review") != "pending root inspection of the full animation and every contact sheet":
            fail(f"{case_id}: unexpected source visual-review marker")
        inventory = png_cases.get(case_id)
        if not inventory:
            fail(f"{case_id}: PNG inventory missing")
        contacts = inventory.get("contact_sheets", [])
        keys = inventory.get("key_frames", [])
        if len(contacts) != 11 or [x.get("index") for x in contacts] != list(range(11)):
            fail(f"{case_id}: contact PNG inventory invalid")
        if len(keys) != 9 or [x.get("index") for x in keys] != KEYS:
            fail(f"{case_id}: key PNG inventory invalid")
        for item in contacts + keys:
            path = Path(item["path"])
            if not path.is_file() or path.suffix.lower() != ".png":
                fail(f"{case_id}: missing/non-PNG visual artifact {path}")
            if sha(path) != item.get("sha256"):
                fail(f"{case_id}: PNG SHA mismatch {path}")

    result = {
        "schema": "ds-data-02.fresh143.validator-result.v1",
        "status": "PASS",
        "case_count": len(visual_cases),
        "contact_sheets_per_case": 11,
        "key_frames_per_case": 9,
        "terminal_receipts_checked": True,
        "state0_and_typed_h5_metadata_checked": True,
        "science_payload_read_or_hashed": False,
        "global_credit_updated": False,
    }
    (ROOT / "metadata/validator-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
