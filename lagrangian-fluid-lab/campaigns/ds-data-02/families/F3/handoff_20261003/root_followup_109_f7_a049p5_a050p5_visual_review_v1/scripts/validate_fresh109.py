#!/usr/bin/env python3
from pathlib import Path
import hashlib, json
ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "metadata/fresh109-visual-review.json"
REPORT = ROOT / "metadata/fresh109-validator-report.json"
FORBIDDEN = {".bi4", ".h5", ".csv", ".dat", ".vtk", ".npy", ".npz"}
SAFE = {".json", ".xml", ".xmf", ".png", ".py", ".md"}

def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def ref(r, errors):
    p = Path(r["path"])
    if p.suffix.lower() in FORBIDDEN:
        errors.append(f"forbidden payload reference: {p}")
        return
    if p.suffix.lower() not in SAFE:
        errors.append(f"unapproved evidence suffix: {p}")
        return
    if not p.exists():
        errors.append(f"missing evidence: {p}")
        return
    if r.get("sha256") and sha(p) != r["sha256"]:
        errors.append(f"SHA mismatch: {p}")

def main():
    m = json.loads(META.read_text())
    errors = []
    if m.get("schema") != "ds02.f3.fresh109.f7.visual-review-handoff.v1":
        errors.append("schema")
    if m.get("source_only_package") is not True or m.get("no_jobs_started") is not True or m.get("no_science_payload_read_or_hashed") is not True:
        errors.append("source-only boundary")
    sb = m["selection_boundary"]
    for key in ["root792_frontier", "checkpoint116", "checkpoint118_latest", "checkpoint119_latest", "root902"]:
        obj = sb[key]
        ref({"path": obj["path"], "sha256": obj["sha256"]}, errors)
    obj = sb["actor123_pending_current_id_scan"]
    ref({"path": obj["frontier_report_path"], "sha256": obj["frontier_report_sha256"]}, errors)
    if any(sb["checkpoint116"]["accepted_target_id_matches"].values()):
        errors.append("target accepted in checkpoint116")
    if any(sb["checkpoint118_latest"]["accepted_target_id_matches"].values()):
        errors.append("target accepted in checkpoint118")
    if any(sb["checkpoint119_latest"]["accepted_target_id_matches"].values()):
        errors.append("target accepted in checkpoint119")
    if any(sb["root902"]["target_id_matches"].values()):
        errors.append("target present in Root902")
    if len(m.get("cases", [])) != 2:
        errors.append("case count")
    for c in m["cases"]:
        if c["case_id"] not in {"F7_OBSTACLE_QUINTIC_B08_A049P5", "F7_OBSTACLE_QUINTIC_B08_A050P5"}:
            errors.append(f"wrong case {c['case_id']}")
        if c["qualification_boundary"]["case_credit_granted"] or c["qualification_boundary"]["independent_case_count_increment"] != 0:
            errors.append(f"credit boundary {c['case_id']}")
        if c["qualification_boundary"]["precision_status"] != "not_accepted":
            errors.append(f"precision boundary {c['case_id']}")
        sp = c["source_inputs"]["source_plan"]
        if sp["historical_length"] != 64 or sp["actual_length"] != 64 or not sp["historical_equals_actual"]:
            errors.append(f"source-plan equality {c['case_id']}")
        if sp["sha256_actual_file"] != sha(sp["path"]):
            errors.append(f"source-plan SHA {c['case_id']}")
        sc = c["scope_separation"]
        if len({sc["source_plan_condition_sha256"], sc["original_owner_canonical_physical_binding_sha256"], sc["actual_converter_scope_sha256"]}) != 3:
            errors.append(f"scope collapse {c['case_id']}")
        if c["actual_condition"]["counts_from_actual_native_qa"]["total"] != 70179:
            errors.append(f"actual total {c['case_id']}")
        chain = c["producer_chain"]
        for value in chain.values():
            if isinstance(value, dict) and "path" in value:
                ref(value, errors)
            elif isinstance(value, dict) and "execution_receipt" in value:
                ref(value["execution_receipt"], errors)
        e = c["render_evidence"]
        if e["inventory"] != {"contact_sheet_count": 26, "event_keyframe_count": 10, "saved_frame_count": 601}:
            errors.append(f"inventory {c['case_id']}")
        for value in e["contact_sheets"] + e["event_keyframes"]:
            ref(value, errors)
        for value in e["all_saved_frame_pngs"]:
            if not Path(value["path"]).exists():
                errors.append(f"missing saved frame {value['path']}")
        if not e["reviewed_all_contact_sheets"] or not e["reviewed_all_event_keyframes"]:
            errors.append(f"review completeness {c['case_id']}")
        if e["render_receipt"]["status"] != "completed" or e["render_receipt"]["returncode"] != 0:
            errors.append(f"render receipt {c['case_id']}")
        if e["render_report"]["frames"] != 601 or e["render_report"]["all_frames_rendered"] is not True:
            errors.append(f"render report {c['case_id']}")
        if not c["producer_chain"]["all_stage_receipts_completed_zero"]:
            errors.append(f"stage completion {c['case_id']}")
    result = {"schema": "ds02.f3.fresh109.validator-report.v1", "valid": not errors, "errors": errors, "cases_checked": len(m.get("cases", [])), "source_only": True, "science_payloads_opened": False}
    REPORT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 1 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
