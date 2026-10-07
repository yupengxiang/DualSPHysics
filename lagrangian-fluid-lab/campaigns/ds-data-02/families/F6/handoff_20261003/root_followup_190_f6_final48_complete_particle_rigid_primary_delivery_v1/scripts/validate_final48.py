#!/usr/bin/env python3
"""Read-only validator for F6 fresh190 final48 delivery.

Only JSON/XML/XMF metadata is opened or hashed. PNGs are checked by stat and
producer-declared metadata. Scientific H5/BI4/CSV/DAT/VTK payloads are never
opened, hashed, copied, or parsed.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
META = PKG / "metadata/final48-delivery.json"
MANIFEST = PKG / "metadata/package-manifest.json"
META_SUFFIXES = {".json", ".xml", ".xmf"}
FORBIDDEN = (".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".vtp", ".pvd", ".raw")
LAST = "F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025"
BASELINE = "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text())


def check_ref(ref: dict, *, png: bool = False, source: bool = False):
    assert isinstance(ref, dict) and isinstance(ref.get("path"), str), ref
    p = Path(ref["path"])
    assert p.is_file(), p
    suffix = p.suffix.lower()
    assert not any(str(p).lower().endswith(x) for x in FORBIDDEN), p
    if png:
        assert suffix == ".png", p
        if "bytes" in ref:
            assert p.stat().st_size == ref["bytes"], (p, "PNG size")
        # sha256/producer_sha256 on PNG is an attestation; this validator does
        # not recompute it.
        assert ref.get("sha256") or ref.get("producer_sha256"), ref
        return
    if source and suffix == ".py":
        assert sha(p) == ref.get("sha256"), (p, "source sha")
        assert p.stat().st_size == ref.get("bytes"), (p, "source bytes")
        return
    if ref.get("kind") == "documentation" and suffix == ".md":
        assert sha(p) == ref.get("sha256"), (p, "documentation sha")
        assert p.stat().st_size == ref.get("bytes"), (p, "documentation bytes")
        return
    assert suffix in META_SUFFIXES, p
    assert sha(p) == ref.get("sha256"), (p, "metadata sha")
    if "bytes" in ref:
        assert p.stat().st_size == ref["bytes"], (p, "metadata bytes")


def check_ref_list(values):
    assert isinstance(values, list)
    for value in values:
        check_ref(value)


def check_png_list(values):
    assert isinstance(values, list) and values
    for value in values:
        check_ref(value, png=True)


def check_render_metadata(primary):
    render = primary["render"]
    assert render["receipt"] and render["report"]
    check_ref(render["receipt"])
    check_ref(render["report"])
    if render.get("publish_receipt"):
        check_ref(render["publish_receipt"])
    receipt = load(Path(render["receipt"]["path"]))
    assert receipt.get("status") == "completed" and receipt.get("returncode") == 0
    report = load(Path(render["report"]["path"]))
    assert report.get("frames") == 241 and report.get("source_frames") == 241
    assert report.get("all_frames_rendered") is True
    assert report.get("actual_times_preserved_exactly") is True


def check_rigid(row):
    rigid = row.get("rigid_motion_join")
    assert isinstance(rigid, dict)
    assert rigid.get("frames") == 241
    if "required_rigid_fields_finite_all241" in rigid:
        assert rigid["required_rigid_fields_finite_all241"] is True
    else:
        assert rigid.get("full_saved_rigid_history_finite_and_monotone_through12") is True
    if "native_time_tolerance_s" in rigid:
        assert rigid["native_time_tolerance_s"] == 1e-6
    if "official_times_not_resampled" in rigid:
        assert rigid["official_times_not_resampled"] is True
    for key in ("actual_export_receipt", "actual_export_report"):
        if isinstance(rigid.get(key), dict) and rigid[key].get("path"):
            check_ref(rigid[key])
    assert rigid.get("case_credit", 0) == 0


def main():
    d = load(META)
    assert d["schema"] == "ds02.f6.fresh190.final48-complete-particle-rigid-primary-delivery.v1"
    assert d["fresh_id"] == "fresh190" and d["family_id"] == d["assigned_family"] == d["actual_family"] == "F6"
    assert d["model"] == "gpt-5.6-luna" and d["reasoning_effort"] == "max" and d["recursive_delegation"] is False
    assert d["delivery"] == {
        "final48_count": 48,
        "accepted_visual_count_at_checkpoint262": 48,
        "pending_visual_count": 0,
        "all_rows_have_actual_native_typed_xmf_xml_render_png_metadata_roles": True,
        "new_case_credit": 0,
        "new_visual_credit": 0,
        "Q_N": False,
        "Q_E": False,
        "precision_status": "visual acceptance only; numeric precision not accepted",
        "production_approval": False,
    }
    assert d["source_boundaries"] == {"science_payload_read": False, "science_payload_hashed": False, "science_payload_copied": False, "new_science_jobs": False, "shared_registry_or_ledger_written": False, "historical_source_bytes_changed": False, "recursive_delegation": False}
    for ref in d["authoritative_sources"].values():
        check_ref(ref)
    membership = d["membership"]
    first8 = membership["frozen_first8_physical_case_ids"]
    first24 = membership["actual_first24_physical_case_ids"]
    final48 = membership["final48_physical_case_ids"]
    assert len(first8) == 8 and len(first24) == 24 and len(final48) == 48
    assert len(set(final48)) == 48 and set(first8).issubset(first24) and set(first24).issubset(final48)
    rows = d["rows"]
    assert len(rows) == 48 and [r["physical_case_id"] for r in rows] == final48
    for row in rows:
        pid = row["physical_case_id"]
        assert row["family_id"] == "F6" and row["case_id"]
        assert row["frozen_checkpoint_262_accepted"] is True
        current = row["current_accepted_decision_summary"]
        check_ref(current["accepted_decision"])
        decision = load(Path(current["accepted_decision"]["path"]))
        assert decision.get("physical_case_id") == pid
        assert "visual-approved" in str(decision.get("status", ""))
        assert row["credit_and_precision"]["case_credit"] == 0
        assert row["credit_and_precision"]["new_visual_credit"] == 0
        assert row["credit_and_precision"]["Q_N"] == 0 and row["credit_and_precision"]["Q_E"] == 0
        primary = row["primary_refs"]
        # Baseline's native physical-condition role is an explicit historical
        # absence; it is not replaced with a top-level or source hash.
        if pid == BASELINE:
            assert primary["native"] == [] and primary["typed"] == []
        else:
            check_ref_list(primary["native"])
            check_ref_list(primary["typed"])
        check_ref(primary["xmf"]["manifest"])
        check_ref(primary["xmf"]["xml"])
        check_render_metadata(primary)
        check_png_list(primary["png"]["contacts"])
        check_png_list(primary["png"]["navigation_previews"])
        check_rigid(row)
        # Normalized primary references must not introduce scientific payload
        # paths, even though historical row snapshots retain source role text.
        for group in (primary["native"], primary["typed"], primary["gencase_or_definition"], primary["initial_qa_or_audit"], primary["owner_or_source"]):
            for ref in group:
                assert not any(str(ref.get("path", "")).lower().endswith(x) for x in FORBIDDEN), ref
    assert d["scope_policy"]["F6_OMEGA_BASELINE_V1_actual_native_condition_field"] == {"present": False, "value": None, "role": "preserved true absence from Root1320/1321 baseline metadata"}
    assert d["scope_policy"]["baseline_legacy_part_field"] == {"present": False, "value": None, "role": "preserved boundary; no new full-CSV vector certification"}
    assert d["scope_policy"]["full_csv_time_vector_independently_reverified_in_this_package"] is False
    assert d["mass_semantics"] == {"physical_mass_kg": 128, "native_support_mass_kg": 256, "mass_equality_claimed": False, "rescaling": False}
    lim = d["last_case_limits"]
    assert lim["physical_case_id"] == LAST
    assert (lim["final_missing_fluid"], lim["first_missing_frame"], lim["frames_with_any_missing"], lim["cumulative_particle_frame_omissions"]) == (3, 7, 234, 700)
    assert lim["missing_location_state_cause_unknown"] is True and lim["all_native_uids_active_claim"] is False
    assert d["rows"][22]["physical_case_id"] == LAST
    last_meta = d["rows"][22]["accepted_visual_metadata"]
    assert last_meta["source_scope"]["source_plan_physical_condition_sha256"] is None
    assert last_meta["limits"]["physical_mass_kg"] == 128 and last_meta["limits"]["native_support_mass_kg"] == 256
    manifest = load(MANIFEST)
    assert manifest["schema"] == "ds02.f6.fresh190.package-manifest.v1" and manifest["self_excluded"] is True
    for ref in manifest["files"]:
        check_ref(ref, source=ref.get("kind") == "source")
    print("fresh190 validation PASS: frozen8 subset actual24 subset final48; 48 accepted rows; native/typed/XMF/XML/render/PNG metadata closed; rigid boundary and scope absences preserved; no scientific payload IO; no new credit")


if __name__ == "__main__":
    main()
