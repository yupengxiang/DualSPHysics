#!/usr/bin/env python3
"""Build the fresh177 personal visual-review handoff.

This builder reads JSON/XML metadata and uses ``stat`` for the already
published PNGs.  It deliberately never opens or hashes H5, BI4, CSV, DAT,
VTK, or any other scientific payload.  PNG SHA values are copied from the
immutable renderer publish receipt; they are not recomputed here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DATA = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/"
    "F3_STAGE1_DP006_P0800_AY0360/"
    "root-stage1-f3-p0800-ay0360-actual977-full836-116-023-nvme-hard2gib-root987"
)
QI = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F3_P0800AY0360_actual987_full836_UID_N3_time_actual_native_and_XMF_"
    "both_plan_fields_absent_previsual_QI_1355/"
    "actual987-full836-completed-QI-UID-N3-native-scope-previsual-proof.json"
)
CONTACT_COUNT = 35
KEY_FRAMES = (0, 100, 200, 300, 400, 500, 600, 700, 835)
FORBIDDEN_SUFFIXES = {
    ".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu",
}
CANONICAL = "7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5"


def fail(message: str) -> None:
    raise RuntimeError(message)


def read_json(path: Path, label: str) -> Any:
    if path.suffix.lower() != ".json":
        fail(f"non-JSON read attempted for {label}: {path}")
    if not path.is_file():
        fail(f"missing {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - diagnostic path
        fail(f"invalid JSON {label}: {path}: {exc}")


def sha_metadata(path: Path, label: str) -> str:
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        fail(f"scientific payload hash attempted for {label}: {path}")
    if path.suffix.lower() not in {".json", ".xml", ".xmf", ".py", ".md"}:
        fail(f"unsupported metadata hash for {label}: {path}")
    if not path.is_file():
        fail(f"missing metadata for {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata_ref(path: Path, role: str) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        read_json(path, role)
    elif path.suffix.lower() not in {".xml", ".xmf"}:
        fail(f"fresh177 metadata ref is not JSON/XML: {role}: {path}")
    return {"path": str(path), "sha256": sha_metadata(path, role), "role": role}


def receipt_ref(path: Path, role: str, declared_sha: str | None = None) -> dict[str, Any]:
    value = read_json(path, role)
    if not isinstance(value, dict):
        fail(f"{role} is not an object: {path}")
    actual_sha = sha_metadata(path, role)
    if declared_sha is not None and declared_sha != actual_sha:
        fail(f"{role} declared SHA mismatch: {declared_sha} != {actual_sha}")
    if value.get("status") != "completed" or value.get("returncode") != 0:
        fail(f"{role} is not completed/0: {path}: {value.get('status')}/{value.get('returncode')}")
    return {
        "path": str(path),
        "sha256": actual_sha,
        "role": role,
        "status": value.get("status"),
        "returncode": value.get("returncode"),
        "attempt_id": value.get("request", {}).get("attempt_id")
        if isinstance(value.get("request"), dict) else None,
    }


def ref_from_qi(qi: dict[str, Any], key: str, role: str) -> dict[str, Any]:
    item = qi.get(key)
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        fail(f"QI reference missing: {key}")
    return metadata_ref(Path(item["path"]), role) | {
        "qi_declared_sha256": item.get("sha256"),
    }


def png_entry_index(publish: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = publish.get("files_excluding_receipt")
    if not isinstance(entries, list):
        fail("publish receipt has no files_excluding_receipt list")
    index: dict[str, dict[str, Any]] = {}
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("relative_path"), str):
            fail("malformed publish file entry")
        rel = item["relative_path"]
        if rel.endswith((".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk")):
            continue
        index[rel] = item
    return index


def published_png_ref(
    publish: dict[str, Any], index: dict[str, dict[str, Any]], relative_path: str, role: str
) -> dict[str, Any]:
    root = Path(str(publish.get("published_output_root", "")))
    item = index.get(relative_path)
    if item is None:
        fail(f"{role} is not in publish receipt: {relative_path}")
    path = root / relative_path
    try:
        path.relative_to(root)
    except ValueError:
        fail(f"{role} escapes published root: {path}")
    if path.suffix.lower() != ".png" or not path.is_file():
        fail(f"{role} is not a published PNG: {path}")
    # Stat only: the producer receipt is the source of the PNG digest.
    size = path.stat().st_size
    if size != item.get("bytes"):
        fail(f"{role} byte size differs from publish receipt: {path}")
    return {
        "path": str(path),
        "relative_path": relative_path,
        "bytes": item.get("bytes"),
        "declared_sha256": item.get("sha256"),
        "sha256_source": "render_publish_receipt",
        "stat_checked": True,
        "content_read_or_hashed_by_reviewer": False,
        "personally_viewed_with_view_image": True,
        "role": role,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build() -> Path:
    qi = read_json(QI, "Root1355 QI proof")
    if qi.get("case_id") != "F3_STAGE1_DP006_P0800_AY0360":
        fail("unexpected QI case")
    if qi.get("physical_case_id") != "F3_TWOAXIS_P0800_AY0360_STAGE1_FIRST48_PITCH_VARIANT":
        fail("unexpected QI physical case")
    if qi.get("native_request_condition_sha256") != CANONICAL or qi.get("actual_converter_condition_sha256") != CANONICAL:
        fail("canonical condition is not the actual native/converter condition")
    if qi.get("actual_time_window_s") != [0.0, 8.35001341871951]:
        fail("unexpected actual time window")
    for field in (
        "native_source_plan_condition_field_present",
        "native_source_plan_physical_condition_field_present",
        "XMF_source_plan_condition_field_present",
        "XMF_source_plan_physical_condition_field_present",
    ):
        if qi.get(field) is not False:
            fail(f"{field} is not explicitly absent")

    qi_ref = metadata_ref(QI, "Root1355 QI proof")
    actual = qi["actual_completed_receipts"]
    receipt_paths: dict[str, dict[str, Any]] = {}
    for role in ("native", "typed", "xmf", "render"):
        item = actual.get(role)
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            fail(f"missing actual {role} receipt in QI")
        receipt_paths[role] = receipt_ref(Path(item["path"]), f"actual {role} receipt", item.get("sha256"))

    typed_report_ref = ref_from_qi(qi, "typed_report", "typed conversion report")
    xmf_manifest_ref = ref_from_qi(qi, "XMF_manifest", "actual XMF manifest")
    xmf_xml_ref = ref_from_qi(qi, "XMF_XML", "actual XMF XML")
    render_report_ref = ref_from_qi(qi, "render_report", "actual render report")
    publish_ref = ref_from_qi(qi, "publish", "atomic publish receipt")
    parent_qa_report_ref = ref_from_qi(qi, "initial_parent_QA_report", "reused parent initial QA report")
    parent_qa_receipt_ref = ref_from_qi(qi, "initial_parent_QA_receipt", "reused parent initial QA receipt")
    source_prep_ref = ref_from_qi(qi, "source_preparation_report", "source preparation report")

    render_report = read_json(Path(render_report_ref["path"]), "actual render report")
    publish = read_json(Path(publish_ref["path"]), "atomic publish receipt")
    xmf = read_json(Path(xmf_manifest_ref["path"]), "actual XMF manifest")
    typed_report = read_json(Path(typed_report_ref["path"]), "typed conversion report")
    if render_report.get("frames") != 836 or render_report.get("source_frames") != 836:
        fail("render report is not full 836")
    if len(render_report.get("outputs", {}).get("contact_sheets", [])) != CONTACT_COUNT:
        fail("render report does not expose 35 contact sheets")
    diagnostics = render_report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != 836:
        fail("render report does not expose one diagnostic per actual frame")
    first_counts = diagnostics[0].get("type_counts_active") if isinstance(diagnostics[0], dict) else None
    if not isinstance(first_counts, dict):
        fail("first-frame active type counts are absent")
    expected_counts = {"fixed": 111708, "fluid": 67500, "moving": 0, "floating": 0, "unknown": 0}
    if first_counts != expected_counts:
        fail(f"unexpected first-frame active type counts: {first_counts}")
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            fail("malformed frame diagnostic")
        if diagnostic.get("active") != 179208 or diagnostic.get("missing") != 0:
            fail("actual active/missing counts are not stable across frames")
        if diagnostic.get("type_counts_active") != expected_counts:
            fail("actual type partition changed across frames")
    if typed_report.get("frames") != 836 or typed_report.get("particles") != 179208:
        fail("typed report does not expose actual 836/179208")
    if xmf.get("frames") != 836 or xmf.get("expected_frames") != 836 or xmf.get("particles") != 179208:
        fail("XMF manifest does not expose actual 836/179208")
    if publish.get("status") != "published_after_atomic_rename":
        fail("publish is not atomic/published")
    if render_report.get("source_h5_sha256") != xmf.get("trajectory_h5_sha256"):
        fail("render and XMF producer H5 attestations differ")

    index = png_entry_index(publish)
    contacts: list[dict[str, Any]] = []
    for path in render_report["outputs"]["contact_sheets"]:
        relative = str(Path(path).relative_to(Path(publish["published_output_root"])))
        contacts.append(published_png_ref(publish, index, relative, "contact_sheet"))
    if len(contacts) != CONTACT_COUNT:
        fail("contact sheet count changed")
    keys = [
        published_png_ref(
            publish, index, f"frames/frame_{frame:04d}.png", f"key_frame_{frame:04d}"
        )
        for frame in KEY_FRAMES
    ]

    decision = {
        "schema": "ds02.f3.fresh177.personal-visual-review.v1",
        "fresh_id": "fresh177",
        "reviewed_date_utc": "2026-10-07",
        "assigned_worktree_family": "F3",
        "actual_case_family": "F3",
        "case_id": qi["case_id"],
        "physical_case_id": qi["physical_case_id"],
        "physical_condition_roles": {
            "native_request_condition_sha256": CANONICAL,
            "actual_converter_scope_sha256": CANONICAL,
            "native_and_xmf_plan_fields": {
                "native_source_plan_condition_sha256": {"present": False, "value": None},
                "native_source_plan_physical_condition_sha256": {"present": False, "value": None},
                "xmf_source_plan_condition_sha256": {"present": False, "value": None},
                "xmf_source_plan_physical_condition_sha256": {"present": False, "value": None},
                "interpretation": "absent fields remain absent; canonical digest is not copied into a source-plan field",
            },
            "scope_schema": qi["scope_schema"],
        },
        "actual_dimensions": {
            "frames": 836,
            "particles": 179208,
            "fixed": first_counts["fixed"],
            "fluid": first_counts["fluid"],
            "moving": first_counts["moving"],
            "floating": first_counts["floating"],
            "vector_shape": "N x 3",
            "time_window_s": qi["actual_time_window_s"],
            "uid_lifecycle": "all native UIDs active each frame per Root1355 QI",
        },
        "actual_chain": {
            "native": receipt_paths["native"],
            "typed": {"receipt": receipt_paths["typed"], "conversion_report": typed_report_ref},
            "xmf": {"receipt": receipt_paths["xmf"], "manifest": xmf_manifest_ref, "xml": xmf_xml_ref},
            "render": {
                "receipt": receipt_paths["render"],
                "report": render_report_ref,
                "atomic_publish": publish_ref,
            },
            "source_h5_producer_sha256": render_report["source_h5_sha256"],
        },
        "reused_initialization": {
            "parent_initial_qa_report": parent_qa_report_ref,
            "parent_initial_qa_receipt": parent_qa_receipt_ref,
            "source_preparation_report": source_prep_ref,
            "interpretation": "reused parent initialization evidence; not a new independent QA claim",
        },
        "historical_outer_envelope": {
            "outer_request_expected_frames": 801,
            "outer_request_expected_particles": 194427,
            "outer_request_expected_contact_sheets": 34,
            "actual_loaded_wrapper_frames": 836,
            "actual_loaded_wrapper_particles": 179208,
            "actual_contact_sheets": CONTACT_COUNT,
            "authority": "actual loaded wrapper and completed reports; stale outer envelope retained as history",
        },
        "visual_review": {
            "status": "visual-approved-by-delegated-agent",
            "screen": "pass_first_stage",
            "review_method": "personally viewed with view_image",
            "contact_sheets_viewed": len(contacts),
            "key_frames_viewed": list(KEY_FRAMES),
            "key_frame_paths_are_event_selection": True,
            "observations": [
                "The initial blue fluid field is continuous at the tank base against the gray fixed boundary.",
                "The crest develops, migrates and rebounds through the middle contacts while remaining visually bounded by the tank.",
                "The late contacts show an oscillatory/decaying tail without an obvious whole-domain explosion or abrupt renderer truncation.",
                "No obvious gross blank frame, severe visible bed/wall breach, abnormal initial state, or unexplained large visual loss was observed.",
                "Small edge speckle and point/raster texture are retained as display observations, not physical classifications.",
            ],
            "limitations": [
                "This is a first-stage visual screen only; it is not a numerical-precision, strict-containment, sub-DP, or runup-magnitude qualification.",
                "The screen does not establish Q-N, Q-E, production qualification, or a global case credit.",
                "UID/type/time/finite/N3 evidence comes from the independent Root1355 QI and producer metadata, not from visual inference.",
            ],
            "new_case_credit": 0,
            "q_n_granted": False,
            "q_e_granted": False,
            "scientific_payload_opened_or_hashed_by_reviewer": False,
            "scientific_jobs_started_or_restarted": False,
            "shared_state_modified": False,
        },
        "visual_evidence": {"contacts": contacts, "keys": keys},
        "provenance": {
            "qi_proof": qi_ref,
            "qi_visual_status_before_review": qi.get("visual_status"),
            "qi_main_personally_viewed_PNGs_before_review": qi.get("main_personally_viewed_PNGs"),
            "render_report_visual_status_before_review": render_report.get("visual_review"),
            "publish_receipt_status": publish.get("status"),
            "reviewer_png_sha_source": "publisher-declared receipt SHA; reviewer did not hash PNG bytes",
        },
    }
    decision_path = HERE / "metadata/actual987-personal-visual-decision.json"
    png_path = HERE / "metadata/png-evidence/actual987.json"
    write_json(decision_path, decision)
    write_json(
        png_path,
        {
            "schema": "ds02.f3.fresh177.png-evidence.v1",
            "case_id": qi["case_id"],
            "physical_case_id": qi["physical_case_id"],
            "source": "render-publish-receipt.json",
            "contacts": contacts,
            "keys": keys,
            "content_read_or_hashed_by_reviewer": False,
            "all_paths_stat_checked": True,
        },
    )
    return decision_path


if __name__ == "__main__":
    print(build())
