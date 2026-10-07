#!/usr/bin/env python3
"""Build the fresh184 F5 M101/T100 personal visual-review handoff.

Only JSON/XML/XMF metadata is read or hashed here.  Published PNGs are
verified by stat against the renderer's immutable publish receipt; their
producer-declared SHA values are copied without hashing the image bytes.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
QI = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F5_M101T100_actual1158_full801_complete_UID_N3_bed_actual_native_XMF_"
    "SourceDef_namespace_previsual_QI_1397/"
    "actual1158-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json"
)
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M101_T100_NEXT34"
PHYSICAL = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M101_T100"
CANONICAL = "1a04363bffefde127740d3da87de48ba66db566b7ae0cdf44d6c6f4b73137cf3"
LEGACY = "80039c17cc7a088b7bc0fdc5c7a74d9051aa72763652261e2823635fcd5ad93d"
SOURCE_DEF = "6c74924feda21861f0a15d1259871f3a536ae2a2264acc4047a60caee1b5d451"
SOURCE_PLAN = "366adc5200604490871116a0a5b8503c9bef4bfb1e72195df94995605fa7d324"
FRAMES = 801
PARTICLES = 194427
TIME_WINDOW = [0.0, 16.00015600764587]
KEY_FRAMES = (0, 100, 200, 300, 400, 500, 600, 700, 800)
CONTACT_COUNT = 34
FORBIDDEN_SUFFIXES = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
EVIDENCE_KEYS = (
    "bed_receipt", "bed_report", "gencase_receipt", "generated_xml",
    "initial_qa_receipt", "initial_qa_report", "native_receipt",
    "typed_receipt", "typed_report", "xmf_receipt", "xmf_manifest",
    "xmf_xml", "render_receipt", "render_report", "render_publish_receipt",
)
RECEIPT_KEYS = {
    "bed_receipt", "gencase_receipt", "initial_qa_receipt", "native_receipt",
    "typed_receipt", "xmf_receipt", "render_receipt",
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def read_json(path: Path, label: str) -> Any:
    if path.suffix.lower() != ".json" or not path.is_file():
        fail(f"invalid JSON for {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid JSON for {label}: {exc}")


def metadata_sha(path: Path, label: str) -> str:
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES:
        fail(f"scientific payload hash attempted for {label}: {path}")
    if suffix not in {".json", ".xml", ".xmf", ".py", ".md"} or not path.is_file():
        fail(f"invalid metadata reference for {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata_ref(path: Path, role: str) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        read_json(path, role)
    actual = metadata_sha(path, role)
    return {"path": str(path), "sha256": actual, "role": role}


def evidence_ref(qi: dict[str, Any], key: str, *, receipt: bool = False) -> dict[str, Any]:
    item = qi.get("actual_completed_metadata_evidence", {}).get(key)
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        fail(f"missing QI evidence {key}")
    path = Path(item["path"])
    actual = metadata_sha(path, f"QI evidence {key}")
    if actual != item.get("sha256"):
        fail(f"QI-declared SHA mismatch for {key}: {path}")
    result = {"path": str(path), "sha256": actual, "role": f"QI evidence {key}", "qi_declared_sha256": item["sha256"]}
    if receipt:
        obj = read_json(path, key)
        if obj.get("status") != "completed" or obj.get("returncode") != 0:
            fail(f"{key} is not completed/0")
        req = obj.get("request")
        if isinstance(req, dict):
            if req.get("case_id") not in (None, CASE) or req.get("physical_case_id") not in (None, PHYSICAL):
                fail(f"{key} identity mismatch")
            result.update({
                "status": obj.get("status"),
                "returncode": obj.get("returncode"),
                "attempt_id": req.get("attempt_id"),
                "request_physical_condition_sha256": req.get("physical_condition_sha256"),
                "request_actual_converter_scope_sha256": req.get("actual_converter_scope_sha256"),
            })
    return result


def png_index(publish: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = publish.get("files_excluding_receipt")
    if not isinstance(entries, list):
        fail("publish receipt has no files_excluding_receipt")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("relative_path"), str):
            fail("malformed producer PNG entry")
        result[entry["relative_path"]] = entry
    return result


def published_png_ref(publish: dict[str, Any], index: dict[str, dict[str, Any]], relative: str, role: str) -> dict[str, Any]:
    root = Path(str(publish.get("published_output_root", "")))
    entry = index.get(relative)
    if entry is None:
        fail(f"{role} absent from publish receipt: {relative}")
    path = root / relative
    try:
        path.relative_to(root)
    except ValueError:
        fail(f"{role} escapes published root")
    if path.suffix.lower() != ".png" or not path.is_file():
        fail(f"{role} is not a published PNG: {path}")
    if path.stat().st_size != entry.get("bytes"):
        fail(f"{role} producer byte count changed: {path}")
    return {
        "path": str(path),
        "relative_path": relative,
        "bytes": entry.get("bytes"),
        "declared_sha256": entry.get("sha256"),
        "sha256_source": "render_publish_receipt",
        "stat_checked": True,
        "personally_viewed_with_view_image": True,
        "content_read_or_hashed_by_reviewer": False,
        "role": role,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build() -> Path:
    qi = read_json(QI, "Root1397 own QI")
    if qi.get("case_id") != CASE or qi.get("physical_case_id") != PHYSICAL:
        fail("QI identity mismatch")
    if qi.get("full_frames") != FRAMES or qi.get("particles") != PARTICLES:
        fail("QI dimensions mismatch")
    if qi.get("actual_time_window_s") != TIME_WINDOW:
        fail("QI time window mismatch")
    if qi.get("canonical_actual_native_request_condition_sha256") != CANONICAL:
        fail("QI canonical scope mismatch")
    if qi.get("actual_converter_legacy_scope_sha256") != LEGACY:
        fail("QI typed legacy scope mismatch")
    if qi.get("all801_geometry_velocity_N3_times_UID_finite_verified") is not True or qi.get("all_native_UIDs_active_each_frame") is not True:
        fail("QI does not attest actual N3/finite/UID lifecycle")
    if qi.get("native_and_XMF_physical_plan_canonical_roles_and_separate_SourceDef_FILE_independently_verified") is not True:
        fail("QI plan/source-definition role evidence missing")
    if qi.get("main_scientific_payload_IO") is not False:
        fail("QI source-access boundary missing")

    refs: dict[str, Any] = {}
    for key in EVIDENCE_KEYS:
        refs[key] = evidence_ref(qi, key, receipt=key in RECEIPT_KEYS)
    prior = qi.get("original_previsual_dependency_review")
    if not isinstance(prior, dict) or not isinstance(prior.get("path"), str):
        fail("missing original previsual review")
    prior_path = Path(prior["path"])
    if metadata_sha(prior_path, "original previsual review") != prior.get("sha256"):
        fail("original previsual review SHA mismatch")
    refs["original_previsual_dependency_review"] = metadata_ref(prior_path, "original previsual review")

    publish = read_json(Path(refs["render_publish_receipt"]["path"]), "render publish receipt")
    if publish.get("status") != "published_after_atomic_rename":
        fail("render is not atomically published")
    report = read_json(Path(refs["render_report"]["path"]), "render report")
    manifest = read_json(Path(refs["xmf_manifest"]["path"]), "XMF manifest")
    render_receipt = read_json(Path(refs["render_receipt"]["path"]), "render receipt")
    render_req = render_receipt.get("request", {})
    if report.get("frames") != FRAMES or report.get("source_frames") != FRAMES or report.get("all_frames_rendered") is not True:
        fail("render report is not full 801")
    if report.get("actual_times_preserved_exactly") is not True:
        fail("render report does not preserve actual times")
    diagnostics = report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != FRAMES:
        fail("render diagnostics are not 801 rows")
    times: list[float] = []
    for i, row in enumerate(diagnostics):
        if not isinstance(row, dict) or row.get("frame") != i:
            fail(f"frame {i} identity is not contiguous")
        if row.get("active") != PARTICLES or row.get("missing") != 0:
            fail(f"frame {i} active/missing lifecycle differs")
        if row.get("finite_positions_active") is not True or row.get("identity_axis_preserved") is not True:
            fail(f"frame {i} finite/identity evidence missing")
        finite = row.get("finite_fields")
        if not isinstance(finite, dict) or any(finite.get(name, {}).get("finite_active") is not True for name in ("density", "mass", "pressure", "velocity")):
            fail(f"frame {i} finite field evidence missing")
        t = row.get("actual_time_s")
        if not isinstance(t, (int, float)):
            fail(f"frame {i} actual time missing")
        times.append(float(t))
    if times[0] != TIME_WINDOW[0] or times[-1] != TIME_WINDOW[1] or any(b <= a for a, b in zip(times, times[1:])):
        fail("render actual time sequence differs from QI")
    if report.get("manifest_sha256") != refs["xmf_manifest"]["sha256"]:
        fail("render report manifest binding differs")
    if manifest.get("case_id") != CASE or manifest.get("physical_case_id") != PHYSICAL:
        fail("XMF manifest identity mismatch")
    if manifest.get("frames") != FRAMES or manifest.get("particles") != PARTICLES:
        fail("XMF dimensions mismatch")
    if manifest.get("physical_condition_sha256") != CANONICAL:
        fail("XMF physical condition is not native canonical")
    if manifest.get("canonical_source_physical_condition_sha256") is not None or manifest.get("actual_converter_legacy_scope_sha256") is not None:
        fail("XMF unexpectedly filled independent canonical/legacy fields")
    if manifest.get("source_plan_condition_sha256") is not None or manifest.get("source_plan_physical_condition_sha256") != CANONICAL:
        fail("XMF source-plan role mismatch")
    if manifest.get("source_definition_sha256") != SOURCE_DEF:
        fail("XMF SourceDef role mismatch")
    if publish.get("report_sha256_after_rebind") != refs["render_report"]["sha256"]:
        fail("publish report binding differs")
    if publish.get("case_id") != CASE or publish.get("attempt_id") != render_req.get("attempt_id"):
        fail("publish identity mismatch")

    index = png_index(publish)
    outputs = report.get("outputs", {})
    contact_paths = outputs.get("contact_sheets")
    if not isinstance(contact_paths, list) or len(contact_paths) != CONTACT_COUNT:
        fail("render report contact count mismatch")
    root = Path(str(publish["published_output_root"]))
    contacts: list[dict[str, Any]] = []
    for i, absolute in enumerate(contact_paths):
        path = Path(absolute)
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            fail("contact path is outside published root")
        contacts.append(published_png_ref(publish, index, relative, f"contact_{i:02d}"))
    keys = [published_png_ref(publish, index, f"frames/frame_{frame:04d}.png", f"key_{frame:04d}") for frame in KEY_FRAMES]

    now = datetime.now(timezone.utc).isoformat()
    plan_fields = qi.get("actual_native_XMF_plan_field_namespaces")
    decision = {
        "schema": "ds02.f3.fresh184.personal-visual-review.v1",
        "fresh_id": "fresh184",
        "review_completed_at_utc": now,
        "configured_model": "gpt-5.6-luna/max",
        "model_substitution": False,
        "recursive_delegation": False,
        "assigned_worktree_family": "F3",
        "actual_case_family": "F5",
        "case_id": CASE,
        "physical_case_id": PHYSICAL,
        "physical_condition_roles": {
            "native_canonical_condition_sha256": CANONICAL,
            "typed_legacy_converter_scope_sha256": LEGACY,
            "xmf_physical_condition_sha256": manifest.get("physical_condition_sha256"),
            "xmf_source_plan_physical_condition_sha256": manifest.get("source_plan_physical_condition_sha256"),
            "xmf_actual_converter_legacy_scope_sha256": manifest.get("actual_converter_legacy_scope_sha256"),
            "bed_source_definition_sha256": SOURCE_DEF,
            "source_plan_file_sha256": SOURCE_PLAN,
            "native_and_xmf_plan_fields": plan_fields,
            "native_source_plan_condition_field": {"present": qi.get("actual_native_source_plan_condition_field_present"), "value": qi.get("actual_native_source_plan_condition_sha256")},
            "native_source_plan_physical_condition_field": {"present": qi.get("actual_native_source_plan_physical_condition_field_present"), "value": qi.get("actual_native_source_plan_physical_condition_sha256")},
            "xmf_source_plan_physical_condition_field": {"present": True, "value": qi.get("XMF_source_plan_physical_condition_field_sha256"), "native_canonical_role": qi.get("XMF_source_plan_physical_condition_field_has_native_canonical_role"), "SourceDef_role": qi.get("XMF_source_plan_physical_condition_field_has_SourceDef_role")},
            "bed_declared_source_plan_field": {"present": True, "value": qi.get("bed_declared_source_plan_field_sha256"), "SourceDef_role": qi.get("bed_declared_source_plan_field_has_SourceDef_role")},
            "interpretation": "Native/XMF physical plan is canonical; typed is an independent legacy converter scope; bed SourceDef and source-plan file are separate roles. Absent condition fields remain absent.",
        },
        "actual_dimensions": {
            "frames": FRAMES,
            "particles": PARTICLES,
            "initial_fluid_UIDs": qi.get("fluid_initial_UIDs"),
            "vector_shape": "N x 3",
            "time_window_s": TIME_WINDOW,
            "all801_geometry_velocity_N3_times_UID_finite_verified": qi.get("all801_geometry_velocity_N3_times_UID_finite_verified"),
            "all_native_UIDs_active_each_frame": qi.get("all_native_UIDs_active_each_frame"),
            "render_type_counts_from_report_frame0": diagnostics[0].get("type_counts_active"),
            "render_lifecycle": "All 801 report rows retain active=194427 and missing=0; this is producer metadata, not a payload re-read.",
        },
        "bed_diagnostics": {
            "all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked": qi.get("all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked"),
            "depth_diagnostic_bins_not_numerical_thresholds": qi.get("depth_diagnostic_bins_not_numerical_thresholds"),
            "subDP_positive_depth_not_quantified_by_zero_bins": qi.get("subDP_positive_depth_not_quantified_by_zero_bins"),
        },
        "precision_and_limits": {
            "actual_initial_QA_precision_negative": qi.get("actual_initial_QA_precision_negative"),
            "historical_negative_flags": qi.get("historical_negative_flags"),
            "q_n_granted": False,
            "q_e_granted": False,
            "case_credit": 0,
        },
        "actual_chain": refs,
        "producer_attestation": {
            "source_h5_sha256": report.get("source_h5_sha256"),
            "source_h5_sha256_source": "producer render report",
            "source_h5_opened_or_hashed_by_reviewer": False,
            "root_qi_is_independent_proof_not_runner_receipt": True,
            "genuine_receipts_completed0": True,
        },
        "visual_review": {
            "status": "visual-approved-by-delegated-agent",
            "screen": "pass_first_stage",
            "review_method": "Personally viewed all 34 published contact sheets and nine requested key frames with view_image after completed/0 and atomic publish.",
            "contact_sheets_viewed": CONTACT_COUNT,
            "key_frames_viewed": list(KEY_FRAMES),
            "observations": [
                "All 34 contact sheets and nine key frames were present, rendered, and visually inspectable.",
                "The sequence shows a coherent initial state, gradual run-up and downstream spreading, with continuous late-time evolution through the published 16-second window.",
                "Small detached or sprayed blue points are visible in later views and are recorded as a display observation only; they are not reclassified against the producer UID or bed diagnostics.",
                "No blank/corrupt image, abrupt truncation, whole-domain explosion, gross visible breakup, or obvious unexplained severe bed/wall breach was observed.",
            ],
            "physical_screen_limits": [
                "This is a visual screen only; it does not establish numerical precision, strict containment, sub-DP behavior, run-up magnitude, Q-N, Q-E, or production acceptance.",
                "The one-DP/two-DP bed bins remain diagnostics and do not quantify positive sub-DP depth.",
                "Visual inspection does not infer particle conservation, missing-particle identities, or numerical truth.",
            ],
            "precision_status": "not_accepted",
            "scientific_payload_opened_or_hashed_by_reviewer": False,
            "scientific_jobs_started_or_restarted": False,
            "shared_state_modified": False,
            "case_credit": 0,
            "q_n_granted": False,
            "q_e_granted": False,
        },
        "visual_evidence": {"contacts": contacts, "keys": keys},
        "provenance": {
            "qi_proof": {"path": str(QI), "sha256": metadata_sha(QI, "Root1397 QI"), "role": "independent completed/0 QI"},
            "qi_main_commit": "45f272dd0d63958e1839420dc61dbba9a4d7239d",
            "publisher_png_sha_source": "immutable render-publish-receipt.json; declared SHA copied, PNG content not hashed by reviewer",
            "review_timestamp_source": "recorded after the completed personal view_image session",
        },
    }
    decision_path = HERE / "metadata/actual1158-personal-visual-decision.json"
    png_path = HERE / "metadata/png-evidence/actual1158.json"
    write_json(decision_path, decision)
    write_json(png_path, {
        "schema": "ds02.f3.fresh184.png-evidence.v1",
        "case_id": CASE,
        "physical_case_id": PHYSICAL,
        "contacts": contacts,
        "keys": keys,
        "all_paths_stat_checked": True,
        "personally_viewed_after_atomic_publish": True,
        "content_read_or_hashed_by_reviewer": False,
        "declared_sha_source": "render-publish-receipt.json",
    })
    files = [HERE / "README.md", HERE / "build_fresh184.py", HERE / "validate_fresh184.py", decision_path, png_path]
    write_json(HERE / "package-manifest.json", {
        "schema": "ds02.f3.fresh184.package-manifest.v1",
        "fresh_id": "fresh184",
        "package_manifest_excluded_from_own_hash": True,
        "files": [{"path": str(p.relative_to(HERE)), "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
    })
    return decision_path


if __name__ == "__main__":
    print(build())
