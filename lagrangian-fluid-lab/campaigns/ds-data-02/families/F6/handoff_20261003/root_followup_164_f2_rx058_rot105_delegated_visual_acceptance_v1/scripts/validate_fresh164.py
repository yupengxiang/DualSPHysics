#!/usr/bin/env python3
"""Fresh164 metadata/PNG validator.

It reads JSON/XML/source metadata and published PNGs only.  It never opens or
hashes H5, BI4, CSV, DAT, VTK, or other scientific payloads.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DENIED = {".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz"}

def safe_json(path: Path):
    assert path.suffix.lower() not in DENIED, f"payload read denied: {path}"
    return json.loads(path.read_text())

def safe_sha(path: Path):
    assert path.suffix.lower() not in DENIED, f"payload hash denied: {path}"
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def receipt_ok(path: Path):
    data = safe_json(path)
    assert data.get("status") == "completed", (path, data.get("status"))
    assert data.get("returncode") == 0, (path, data.get("returncode"))
    return data

def main():
    source = safe_json(ROOT / "metadata/source-binding.json")
    limits_pkg = safe_json(ROOT / "metadata/producer-limits-derived.json")
    visual = safe_json(ROOT / "metadata/visual-review.json")
    decision = safe_json(next((ROOT / "decisions").glob("*-decision.json")))
    png = safe_json(ROOT / "metadata/png-evidence.json")
    chain = safe_json(ROOT / "metadata/chain-integrity.json")
    eligibility = safe_json(ROOT / "metadata/eligibility-snapshot.json")
    manifest = safe_json(ROOT / "manifest.json")

    assert manifest["fresh_id"] == "fresh164"
    assert source["fresh_id"] == "fresh164"
    assert source["source_chain"]["fresh_id"] == "fresh163"
    assert source["source_chain"]["immutable"] is True
    assert source["scope_roles"]["scope_equality_claimed"] is False
    assert source["raw_science_payload_opened_or_hashed"] is False
    assert source["source_h5_policy"]["raw_h5_opened_or_hashed_by_this_review"] is False
    assert source["source_h5_policy"]["digest_value_copied_into_this_package"] is False

    case_id = source["reviewed_case"]["case_id"]
    physical_id = source["reviewed_case"]["physical_case_id"]
    assert case_id == decision["case_id"] == visual["case_id"] == chain["case_id"]
    assert physical_id == decision["physical_case_id"] == visual["physical_case_id"] == chain["physical_case_id"]
    assert decision["status"] == visual.get("status", "visual-approved-by-delegated-agent")
    assert decision["agent_personally_viewed_all_contacts_and_keys"] is True
    assert decision["main_personally_viewed_pngs"] is False
    assert visual["agent_personally_viewed_all_contacts_and_keys"] is True
    assert decision["case_credit"] == visual["case_credit"] == 0
    assert decision["global_acceptance"] is False and visual["global_acceptance"] is False
    assert decision["science_payload_read_or_hashed"] is False

    # Verify every referenced producer metadata file and its frozen metadata SHA.
    for ref in source["producer_metadata"]:
        path = Path(ref["path"])
        assert path.exists(), path
        assert path.suffix.lower() not in DENIED, path
        assert safe_sha(path) == ref["sha256"], path

    # Actual conversion lifecycle derivation.  This is JSON metadata, not raw H5.
    report_path = Path(limits_pkg["derived"]["actual_conversion_report_path"])
    report = safe_json(report_path)
    assert safe_sha(report_path) == limits_pkg["derived"]["actual_conversion_report_sha256"]
    ledger = report["lifecycle"]["frame_summary"]
    life = report["lifecycle"]
    missing = [row for row in ledger if row.get("missing_particles", 0) > 0]
    derived = {
        "frame_count": len(ledger),
        "frames_with_any_missing_particles": sum(1 for row in ledger if row.get("missing_particles", 0) > 0),
        "particle_frame_omissions_sum": sum(row.get("missing_particles", 0) for row in ledger),
        "maximum_missing_particles_single_frame": max((row.get("missing_particles", 0) for row in ledger), default=0),
        "final_missing_particles": ledger[-1].get("missing_particles"),
        "first_missing_frame": missing[0].get("frame") if missing else None,
        "first_missing_frame_by_type": life.get("first_missing_frame_by_type"),
        "first_missing_frame_by_mk": life.get("first_missing_frame_by_mk"),
        "transient_missing_frame_count": life.get("transient_missing_frame_count"),
        "transient_missing_by_type_frame_events": life.get("transient_missing_by_type_frame_events"),
        "transient_missing_by_mk_frame_events": life.get("transient_missing_by_mk_frame_events"),
        "cause": "unknown; preserve producer lifecycle counts and do not infer final UID causality",
        "derived_from": "conversion-report.lifecycle.frame_summary",
        "actual_conversion_report_path": str(report_path),
        "actual_conversion_report_sha256": limits_pkg["derived"]["actual_conversion_report_sha256"],
        "scientific_payload_read_or_hashed": False,
    }
    assert derived == limits_pkg["derived"]
    assert report["conversion_status"] == "completed" and report["frames"] == 401
    assert report["solver_dimension"]["solver_dimension"] == 3
    assert report["time_evidence"]["strictly_increasing"] is True
    assert report["partvtk_validation"]["all_passed"] is True
    assert source["typed_metadata"]["frames"] == 401
    assert source["typed_metadata"]["dimension"] == 3

    expected_counts = {"total": 418104, "fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21114, "dimension": 3}
    assert source["actual_counts_from_metadata"] == expected_counts
    assert safe_json(Path(source["producer_metadata"][1]["path"]))["actual_total_particles"] == 418104

    # Receipts in the immutable chain are terminal completed/0.
    for row in chain["metadata_chain"][:6]:
        receipt_ok(Path(row["path"]))
        assert safe_sha(Path(row["path"])) == row["sha256"]
    assert chain["all_metadata_receipts_completed_returncode0"] is True
    assert chain["render_report_contract"]["frames"] == 401
    assert chain["render_report_contract"]["all_frames_rendered"] is True
    assert chain["render_report_contract"]["actual_times_preserved_exactly"] is True
    assert chain["render_report_contract"]["nonfinite_active_states"] == 0
    assert chain["render_report_contract"]["source_h5_read_only"] is True
    assert chain["render_report_contract"]["publish_status"] == "published_after_atomic_rename"
    assert chain["render_report_contract"]["contact_sheets"] == 17
    assert chain["render_report_contract"]["key_frames"] == 9
    render_report = safe_json(Path(chain["metadata_chain"][6]["path"]))
    publish = safe_json(Path(chain["metadata_chain"][7]["path"]))
    assert safe_sha(Path(chain["metadata_chain"][6]["path"])) == chain["metadata_chain"][6]["sha256"]
    assert safe_sha(Path(chain["metadata_chain"][7]["path"])) == chain["metadata_chain"][7]["sha256"]
    assert render_report["frames"] == 401 and render_report["all_frames_rendered"] is True
    assert render_report["actual_times_preserved_exactly"] is True
    assert render_report["nonfinite_active_states"] == 0
    assert publish["status"] == "published_after_atomic_rename"
    assert len(render_report["outputs"]["contact_sheets"]) == 17

    # Exact scope separation is part of the evidence contract.
    assert source["scope_roles"]["actual_converter_scope_sha256"] != source["scope_roles"]["source_plan_and_canonical_scope_sha256"]
    xmf = safe_json(Path([r for r in source["producer_metadata"] if r["role"] == "actual N3 XMF manifest"][0]["path"]))
    assert xmf["producer_scope_schema"] == "legacy-owner-scope.v0"
    assert xmf["scope_equality_not_claimed"] is True
    assert xmf["physical_condition_sha256"] == source["scope_roles"]["actual_converter_scope_sha256"]
    assert xmf["canonical_source_physical_condition_sha256"] == source["scope_roles"]["source_plan_and_canonical_scope_sha256"]
    assert xmf["actual_converter_legacy_scope_sha256"] == source["scope_roles"]["actual_converter_scope_sha256"]

    # Frozen membership snapshot excludes this case; no live checkpoint is needed for validation.
    f2_membership = eligibility["accepted_f2_records"]
    assert eligibility["accepted_f2_count"] == len(f2_membership) == 32
    assert physical_id not in {row["physical_case_id"] for row in f2_membership}
    assert eligibility["reviewed_case_in_checkpoint_accepted_set"] is False
    assert eligibility["render_eligibility"]["eligible_unaccepted_at_snapshot"] is True
    assert eligibility["case_credit"] == 0 and eligibility["global_acceptance"] is False

    # PNG evidence: 17 contacts + 9 keys, personally viewed, exact current bytes.
    contacts = png["contact_sheets"]; keys = png["key_frames"]
    assert len(contacts) == 17 and len(keys) == 9 and png["count"] == 26
    assert all(row["viewed_with_view_image"] is True for row in contacts + keys)
    for row in contacts + keys:
        path = Path(row["path"])
        assert path.exists() and path.suffix.lower() == ".png", path
        assert safe_sha(path) == row["sha256"], path
    assert [row["frame"] for row in keys] == [0, 50, 100, 150, 200, 250, 300, 350, 400]

    # Corrected producer limits must be identical in decision and visual blocks.
    assert decision["producer_limits"] == limits_pkg["derived"]
    assert visual["producer_limits"] == limits_pkg["derived"]
    print("fresh164 validator PASS: actual completed/0 Root1120, 401-frame N3 chain, 17 contacts + 9 keys viewed; limits derived from own typed frame ledger; no scientific payload IO")

if __name__ == "__main__":
    main()
