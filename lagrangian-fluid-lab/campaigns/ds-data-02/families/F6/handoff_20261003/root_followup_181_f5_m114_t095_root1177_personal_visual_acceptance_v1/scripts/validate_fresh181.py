#!/usr/bin/env python3
"""Read-only validator for F6 fresh181 F5 M114/T095 personal visual evidence.

The validator reads JSON/XML/XMF metadata and published PNG visualization products
only. It never opens scientific H5/BI4/CSV/DAT/VTK payloads and never launches work.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

FORBIDDEN = (".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk")
META = (".json", ".xml", ".xmf")
VIS = (".png",)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_ref(item: dict, *, kind: str) -> Path:
    assert isinstance(item, dict), item
    assert set(("path", "sha256", "bytes", "role", "kind")) <= set(item), item
    p = Path(item["path"])
    assert p.is_file(), p
    low = str(p).lower()
    assert not any(low.endswith(s) for s in FORBIDDEN), p
    assert p.suffix.lower() in (META if kind == "metadata" else VIS), p
    assert item["kind"] == kind, (p, item["kind"], kind)
    assert sha(p) == item["sha256"], (p, "sha drift")
    assert p.stat().st_size == item["bytes"], (p, "size drift")
    return p


def completed_receipt(item: dict) -> dict:
    p = check_ref(item, kind="metadata")
    d = json.loads(p.read_text())
    assert d.get("schema") == "ds02.execution-receipt.v1", (p, d.get("schema"))
    assert d.get("status") == "completed", (p, d.get("status"))
    assert d.get("returncode") == 0, (p, d.get("returncode"))
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, default=Path(__file__).parents[1])
    args = ap.parse_args()
    pkg = args.package
    d = json.loads((pkg / "metadata/personal-visual-decision.json").read_text())

    assert d["schema"] == "ds02.f6.fresh181.f5-personal-visual-review.v1"
    assert d["fresh_id"] == "fresh181"
    assert d["family_id"] == "F6" and d["assigned_family"] == "F6"
    assert d["actual_family"] == "F5"
    assert d["model"] == "gpt-5.6-luna" and d["reasoning_effort"] == "max"
    assert d["recursive_delegation"] is False

    pred = d["predecessor"]
    old = check_ref({**pred, "kind": "metadata"}, kind="metadata")
    old_d = json.loads(old.read_text())
    assert old_d["schema"] == "ds02.f6.fresh180.dzxy-s1375-render-readiness.v1"
    assert pred["fresh_id"] == "fresh180" and pred["must_remain_unchanged"] is True

    c = d["case"]
    assert c["case_id"] == "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M114_T095_NEXT34"
    assert c["physical_case_id"] == "F5_COMPACT_RUNUP_RECOVERY_C082S1_M114_T095"
    assert c["canonical_native_physical_condition_sha256"] == "f82a302b6ec7e025d0d3252857efd451d265d69b92949f2fa84b2533e362af00"
    assert c["actual_native_source_plan_physical_condition_sha256"] == c["canonical_native_physical_condition_sha256"]
    assert c["typed_legacy_and_actual_converter_scope_sha256"] == "de536746ffa4432f0f792ac8c228a5f05a67c9eead048ef813213365b9c523ab"
    assert c["xmf_source_plan_and_SourceDef_sha256"] == "c2132fbc52a0e80f132a759c88a3ff6bb54ab7bf3ecef2749ba04d6a16fca319"
    assert c["scope_roles"]["native_plan_equals_xmf_plan"] is False
    assert c["scope_roles"]["equality_claimed"] is False
    assert c["declared_counts"] == {"fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658, "total": 194427}
    assert c["dimension"] == 3 and c["expected_frames"] == 801
    assert c["actual_time_s"] == [0.0, 16.00013584927783]

    dec = d["decision"]
    assert dec["status"] == "visual-approved-by-delegated-agent"
    assert dec["case_credit"] == 0 and dec["global_acceptance"] is False
    assert dec["precision_status"] == "not accepted"
    assert dec["q_n_granted"] is False and dec["q_e_granted"] is False
    assert dec["production_approval"] is False

    ev = d["evidence"]
    for key, item in ev.items():
        check_ref(item, kind="metadata")
    for key in ("gencase_receipt", "initial_qa_receipt", "native_receipt", "typed_receipt", "xmf_receipt", "render_receipt"):
        completed_receipt(ev[key])
    qa = json.loads(Path(ev["initial_qa_report"]["path"]).read_text())
    assert qa.get("all_basic_placement_checks_pass") is True
    assert qa.get("diagnostic_only") is True
    assert qa.get("numerical_precision_result_accepted") is False

    manifest = json.loads(Path(ev["xmf_manifest"]["path"]).read_text())
    assert manifest["expected_frames"] == manifest["frames"] == 801
    assert manifest["expected_particles"] == 194427
    assert manifest["actual_counts"]["solver_dimension"] == 3
    assert manifest["canonical_physical_scope"]["physical_condition_sha256"] == c["canonical_native_physical_condition_sha256"]
    assert manifest["canonical_physical_scope"]["source_plan_physical_condition_sha256"] == c["xmf_source_plan_and_SourceDef_sha256"]
    assert manifest["canonical_physical_scope"]["canonical_and_source_plan_are_distinct"] is True

    report = json.loads(Path(ev["render_report"]["path"]).read_text())
    assert report["schema"] == "ds02.stage1.paraview-full-animation-integrity.v1"
    assert report["frames"] == report["source_frames"] == 801
    assert report["all_frames_rendered"] is True
    assert report["actual_times_preserved_exactly"] is True
    assert report["native_identity_axis_preserved"] is True
    assert report["nonfinite_active_states"] == 0
    assert report["numerical_precision_status"] == "not accepted"
    assert len(report["outputs"]["contact_sheets"]) == 34
    assert report["frame_diagnostics"][0]["actual_time_s"] == 0.0
    assert report["frame_diagnostics"][0]["type_counts_active"] == {"fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658, "unknown": 0}
    assert report["frame_diagnostics"][-1]["active"] == 194427
    assert report["frame_diagnostics"][-1]["type_counts_active"] == report["frame_diagnostics"][0]["type_counts_active"]

    pub = json.loads(Path(ev["publish_receipt"]["path"]).read_text())
    assert pub["status"] == "published_after_atomic_rename"
    assert pub["source_h5_opened_or_hashed_by_wrapper"] is False
    ctrl = json.loads(Path(ev["controller_result"]["path"]).read_text())
    assert ctrl["status"] == "completed" and ctrl["returncode"] == 0 and ctrl["launcher_returncode"] == 0

    vr = d["visual_review"]
    assert vr["personally_viewed_with"] == "view_image"
    assert vr["contact_sheet_count"] == len(vr["contact_sheets"]) == 34
    assert vr["key_frame_count"] == len(vr["key_frames"]) == 9
    assert vr["key_frame_indices"] == [0,100,200,300,400,500,600,700,800]
    for i, item in enumerate(vr["contact_sheets"]):
        p = check_ref(item, kind="visualization")
        assert item["sheet_index"] == i and p.name == f"all_frames_{i:03d}.png"
    for item in vr["key_frames"]:
        p = check_ref(item, kind="visualization")
        assert item["frame"] in vr["key_frame_indices"]
        assert p.name == f"frame_{item['frame']:04d}.png"

    assert d["render_product"]["source_h5_opened_or_hashed_by_this_agent"] is False
    assert d["source_boundaries"]["science_payload_read"] is False
    assert d["source_boundaries"]["science_payload_hashed"] is False
    assert d["source_boundaries"]["science_jobs_started"] is False
    assert d["source_boundaries"]["shared_registry_or_ledger_written"] is False
    assert d["future_work"]["no_new_render_or_solver_request"] is True

    print("fresh181 validation PASS: F5 M114/T095 Root1177 completed/0 and published; 34 contacts + 9 keys personally viewed; fixed/moving/fluid roles preserved with floating=0; native/typed/XMF scopes distinct; no case credit")


if __name__ == "__main__":
    main()
