#!/usr/bin/env python3
"""Build the fresh179 F3-assigned/F5 personal visual-review handoff.

Only JSON/XML/XMF metadata is opened or hashed here.  Published PNGs are
stat-checked and their SHA values are copied from the immutable publisher
receipt; this builder never reads or hashes H5/BI4/CSV/DAT/VTK payloads.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DATA = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    """F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M102_T095_NEXT34/"""
    """root-stage1-f5-m102_t095-actual1171-bed0-full801-original116023-"""
    """frozen-progress-root1174"""
)
QI = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F5_M102T095_actual1174_full801_complete_UID_N3_bed_actual_native_XMF_"
    "SourceDef_namespace_previsual_QI_1371/"
    "actual1174-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json"
)
QI_SHA256 = "310384c2ef349ba9f30e8facfecf7395facd6c1a5830675a97797b86e8f8e6b6"
FRESH = "fresh179"
CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M102_T095_NEXT34"
PHYSICAL_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M102_T095"
CANONICAL = "4e06ddfc9c871e619f543397f8faba245de6e24df33950f0561d34ff6a9eb920"
LEGACY = "e561820d8792eda4b59e77a36cf41b6b9d07953553851b25eba4ad9938dd64e3"
SOURCE_DEF_SHA = "7530ddff20117a6d478fba2fc4ec90a05177a2ffccaec383eaf1fe03fc4139a1"
REVIEWED_AT_UTC = "2026-10-07T07:37:40Z"
KEY_FRAMES = (0, 100, 200, 300, 400, 500, 600, 700, 800)
FORBIDDEN_SUFFIXES = {
    ".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu",
}


class BuildError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise BuildError(message)


def read_json(path: Path, label: str) -> Any:
    if path.suffix.lower() != ".json":
        fail(f"non-JSON read attempted for {label}: {path}")
    if not path.is_file():
        fail(f"missing {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid {label}: {path}: {exc}")


def metadata_sha(path: Path, label: str) -> str:
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES:
        fail(f"scientific payload hash attempted for {label}: {path}")
    if suffix not in {".json", ".xml", ".xmf", ".py", ".md"}:
        fail(f"unsupported metadata hash for {label}: {path}")
    if not path.is_file():
        fail(f"missing metadata for {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata_ref(path: Path, role: str, declared_sha: str | None = None) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        read_json(path, role)
    elif path.suffix.lower() not in {".xml", ".xmf"}:
        fail(f"fresh179 metadata ref is not JSON/XML: {role}: {path}")
    actual = metadata_sha(path, role)
    if declared_sha is not None and declared_sha != actual:
        fail(f"{role} declared SHA mismatch: {declared_sha} != {actual}")
    return {"path": str(path), "sha256": actual, "role": role}


def qi_item(qi: dict[str, Any], key: str) -> dict[str, Any]:
    item = qi.get("actual_completed_metadata_evidence", {}).get(key)
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        fail(f"QI reference missing: {key}")
    return item


def qi_metadata_ref(qi: dict[str, Any], key: str, role: str) -> dict[str, Any]:
    item = qi_item(qi, key)
    ref = metadata_ref(Path(item["path"]), role, item.get("sha256"))
    ref["qi_declared_sha256"] = item.get("sha256")
    return ref


def qi_receipt_ref(qi: dict[str, Any], key: str, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    item = qi_item(qi, key)
    path = Path(item["path"])
    obj = read_json(path, role)
    if not isinstance(obj, dict) or obj.get("status") != "completed" or obj.get("returncode") != 0:
        fail(f"{role} is not completed/0: {path}")
    ref = metadata_ref(path, role, item.get("sha256"))
    ref.update({"status": obj.get("status"), "returncode": obj.get("returncode")})
    request = obj.get("request")
    if isinstance(request, dict):
        ref["attempt_id"] = request.get("attempt_id")
    return ref, obj


def published_png_ref(
    publish: dict[str, Any], index: dict[str, dict[str, Any]], relative_path: str, role: str
) -> dict[str, Any]:
    root = Path(str(publish.get("published_output_root", "")))
    item = index.get(relative_path)
    if not isinstance(item, dict):
        fail(f"{role} absent from publish receipt: {relative_path}")
    path = root / relative_path
    try:
        path.relative_to(root)
    except ValueError:
        fail(f"{role} escapes published root: {path}")
    if path.suffix.lower() != ".png" or not path.is_file():
        fail(f"{role} is not a published PNG: {path}")
    if path.stat().st_size != item.get("bytes"):
        fail(f"{role} stat differs from publisher bytes: {path}")
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
    qi = read_json(QI, "Root1371 QI proof")
    if metadata_sha(QI, "Root1371 QI proof") != QI_SHA256:
        fail("Root1371 QI SHA changed")
    if qi.get("case_id") != CASE_ID or qi.get("physical_case_id") != PHYSICAL_ID:
        fail("QI case identity mismatch")
    if qi.get("actual_time_window_s") != [0.0, 16.00010761371514]:
        fail("unexpected actual case time window")
    if qi.get("full_frames") != 801 or qi.get("particles") != 194427:
        fail("QI dimensions are not actual 801/194427")
    if qi.get("fluid_initial_UIDs") != 31658:
        fail("QI fluid count mismatch")
    if qi.get("canonical_actual_native_request_condition_sha256") != CANONICAL:
        fail("native canonical condition mismatch")
    if qi.get("actual_converter_legacy_scope_sha256") != LEGACY:
        fail("legacy converter scope mismatch")
    if qi.get("actual_native_source_plan_condition_field_present") is not False:
        fail("native condition-plan absence was not preserved")
    if qi.get("actual_native_source_plan_physical_condition_field_present") is not True:
        fail("native physical-plan presence was not preserved")
    if qi.get("XMF_source_plan_physical_condition_field_has_native_canonical_role") is not True:
        fail("XMF physical-plan native role was not attested")
    if qi.get("XMF_source_plan_physical_condition_field_has_SourceDef_role") is not False:
        fail("XMF physical-plan was incorrectly assigned SourceDef role")

    qi_ref = metadata_ref(QI, "Root1371 QI proof", QI_SHA256)
    native_ref, native_obj = qi_receipt_ref(qi, "native_receipt", "actual native receipt")
    typed_ref, typed_obj = qi_receipt_ref(qi, "typed_receipt", "actual typed receipt")
    xmf_ref, xmf_obj = qi_receipt_ref(qi, "xmf_receipt", "actual XMF receipt")
    render_ref, render_obj = qi_receipt_ref(qi, "render_receipt", "actual render receipt")
    bed_ref, bed_obj = qi_receipt_ref(qi, "bed_receipt", "actual bed receipt")
    gencase_ref, gencase_obj = qi_receipt_ref(qi, "gencase_receipt", "actual GenCase receipt")
    qa_ref, qa_obj = qi_receipt_ref(qi, "initial_qa_receipt", "actual initial QA receipt")

    typed_report_ref = qi_metadata_ref(qi, "typed_report", "typed conversion report")
    xmf_manifest_ref = qi_metadata_ref(qi, "xmf_manifest", "actual XMF manifest")
    xmf_xml_ref = qi_metadata_ref(qi, "xmf_xml", "actual XMF XML")
    render_report_ref = qi_metadata_ref(qi, "render_report", "actual render report")
    publish_ref = qi_metadata_ref(qi, "render_publish_receipt", "atomic render publish receipt")
    bed_report_ref = qi_metadata_ref(qi, "bed_report", "bed audit report")
    qa_report_ref = qi_metadata_ref(qi, "initial_qa_report", "initial QA report")
    generated_xml_ref = qi_metadata_ref(qi, "generated_xml", "generated XML")

    source_def = qi.get("actual_SourceDef")
    if not isinstance(source_def, dict) or not isinstance(source_def.get("path"), str):
        fail("QI SourceDef ref missing")
    source_def_ref = metadata_ref(Path(source_def["path"]), "actual bed SourceDef", source_def.get("sha256"))

    render_report = read_json(Path(render_report_ref["path"]), "actual render report")
    publish = read_json(Path(publish_ref["path"]), "atomic render publish receipt")
    if render_report.get("frames") != 801 or render_report.get("source_frames") != 801:
        fail("render report frame count mismatch")
    diagnostics = render_report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != 801:
        fail("render report diagnostics are not 801 rows")
    expected_counts = {"fixed": 158559, "fluid": 31658, "moving": 4210, "floating": 0, "unknown": 0}
    for row in diagnostics:
        if not isinstance(row, dict) or row.get("active") != 194427 or row.get("missing") != 0:
            fail("render report active/missing evidence mismatch")
        if row.get("type_counts_active") != expected_counts:
            fail("render report type partition mismatch")
    if publish.get("status") != "published_after_atomic_rename":
        fail("publish receipt is not atomic/published")
    index = {
        item.get("relative_path"): item
        for item in publish.get("files_excluding_receipt", [])
        if isinstance(item, dict) and isinstance(item.get("relative_path"), str)
    }
    contact_paths = render_report.get("outputs", {}).get("contact_sheets")
    if not isinstance(contact_paths, list) or len(contact_paths) != 34:
        fail("render report contact count is not 34")
    publish_root = Path(str(publish.get("published_output_root", "")))
    contacts: list[dict[str, Any]] = []
    for absolute in contact_paths:
        path = Path(str(absolute))
        try:
            relative = path.relative_to(publish_root).as_posix()
        except ValueError:
            fail(f"contact sheet is outside publish root: {path}")
        contacts.append(published_png_ref(publish, index, relative, "contact_sheet"))
    keys = [
        published_png_ref(publish, index, f"frames/frame_{frame:04d}.png", f"key_frame_{frame:04d}")
        for frame in KEY_FRAMES
    ]

    evidence_refs = {
        "bed_receipt": bed_ref,
        "bed_report": bed_report_ref,
        "native_receipt": native_ref,
        "typed_receipt": typed_ref,
        "typed_report": typed_report_ref,
        "xmf_receipt": xmf_ref,
        "xmf_manifest": xmf_manifest_ref,
        "gencase_receipt": gencase_ref,
        "initial_qa_receipt": qa_ref,
        "initial_qa_report": qa_report_ref,
        "generated_xml": generated_xml_ref,
        "xmf_xml": xmf_xml_ref,
        "render_receipt": render_ref,
        "render_report": render_report_ref,
        "render_publish_receipt": publish_ref,
    }

    decision = {
        "schema": "ds02.f3.fresh179.personal-visual-review.v1",
        "fresh_id": FRESH,
        "assigned_worktree_family": "F3",
        "actual_case_family": "F5",
        "case_id": CASE_ID,
        "physical_case_id": PHYSICAL_ID,
        "reviewer_configuration": {
            "model": "gpt-5.6-luna",
            "reasoning_effort": "max",
            "configured_profile": "gpt-5.6-luna/max",
            "model_substitution": False,
            "recursive_delegation": False,
            "reviewed_at_utc": REVIEWED_AT_UTC,
        },
        "physical_condition_roles": {
            "native_request_condition_sha256": CANONICAL,
            "actual_native_canonical_scope_sha256": CANONICAL,
            "actual_converter_legacy_scope_sha256": LEGACY,
            "source_definition_bed_role_sha256": SOURCE_DEF_SHA,
            "scope_schema": "ds02.f5.actual-native-canonical-physical-scope.v1",
            "native_and_xmf_plan_fields": {
                "native_source_plan_condition_sha256": {"present": False, "value": None},
                "native_source_plan_physical_condition_sha256": {"present": True, "value": CANONICAL},
                "xmf_source_plan_condition_sha256": {"present": False, "value": None},
                "xmf_source_plan_physical_condition_sha256": {"present": True, "value": CANONICAL},
                "xmf_source_plan_physical_condition_has_native_canonical_role": True,
                "xmf_source_plan_physical_condition_has_SourceDef_role": False,
                "interpretation": "The native/XMF physical-plan field is the canonical native role; the bed SourceDef is a separate XML role.",
            },
            "actual_SourceDef": source_def_ref,
        },
        "actual_dimensions": {
            "frames": 801,
            "particles": 194427,
            "fixed": 158559,
            "fluid": 31658,
            "moving": 4210,
            "floating": 0,
            "vector_shape": "N x 3",
            "time_window_s": qi["actual_time_window_s"],
            "uid_lifecycle": "all native UIDs active in each actual frame per Root1371 QI",
        },
        "actual_chain": {
            "gencase": {"receipt": gencase_ref, "generated_xml": generated_xml_ref},
            "initial_qa": {"receipt": qa_ref, "report": qa_report_ref},
            "native": native_ref,
            "typed": {"receipt": typed_ref, "conversion_report": typed_report_ref},
            "xmf": {"receipt": xmf_ref, "manifest": xmf_manifest_ref, "xml": xmf_xml_ref},
            "bed": {"receipt": bed_ref, "report": bed_report_ref},
            "render": {"receipt": render_ref, "report": render_report_ref, "atomic_publish": publish_ref},
            "source_h5_producer_sha256": render_report.get("source_h5_sha256"),
        },
        "root_qi": qi_ref,
        "root_qi_status_before_review": qi.get("visual_status"),
        "root_qi_is_independent_metadata_proof_not_runner_receipt": True,
        "historical_outer_envelope": {
            "outer_request_expected_frames": 801,
            "outer_request_expected_particles": 194427,
            "outer_request_expected_contact_sheets": 34,
            "actual_loaded_wrapper_frames": 801,
            "actual_loaded_wrapper_particles": 194427,
            "actual_contact_sheets": 34,
            "authority": "the completed native/typed/XMF/render chain and actual loaded wrapper; no values are borrowed from another case",
        },
        "visual_review": {
            "status": "visual-approved-by-delegated-agent",
            "screen": "pass_first_stage",
            "review_method": "personally viewed with view_image",
            "contact_sheets_viewed": 34,
            "key_frames_viewed": list(KEY_FRAMES),
            "observations": [
                "The initial blue fluid field is continuous at the tank base against the gray fixed boundary.",
                "The response remains coherent and bounded through the early, middle, and late contacts; the crest evolves and then settles into a weak oscillatory tail.",
                "No obvious whole-domain explosion, gross blank frame, severe visible bed or wall breach, abnormal initial state, abrupt truncation, or unexplained large visible loss was observed.",
                "Small edge speckle and point/raster texture are retained as display observations only.",
            ],
            "limitations": [
                "This is a first-stage visual screen, not a strict containment, sub-DP, runup-magnitude, or numerical-precision qualification.",
                "The screen does not establish Q-N, Q-E, production qualification, or a global case credit.",
                "The bed one/two-DP footprint audit is a diagnostic and is not a proof of sub-DP absence.",
                "UID/type/time/finite/N3 facts come from Root1371 QI and producer metadata, not visual inference.",
                "Historical initialization precision/AB negative evidence remains unchanged.",
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
            "publisher_png_digest_source": "render-publish-receipt.json; reviewer did not hash PNG bytes",
            "published_output_root": str(publish_root),
            "publish_receipt_status": publish.get("status"),
            "reviewed_after": {
                "render_receipt_status": render_obj.get("status"),
                "render_returncode": render_obj.get("returncode"),
                "atomic_publish_status": publish.get("status"),
                "root_qi_available": True,
            },
            "metadata_evidence": evidence_refs,
            "actual_initial_QA_precision_negative": qi.get("actual_initial_QA_precision_negative"),
            "depth_diagnostic_bins_not_numerical_thresholds": qi.get("depth_diagnostic_bins_not_numerical_thresholds"),
            "subDP_positive_depth_not_quantified_by_zero_bins": qi.get("subDP_positive_depth_not_quantified_by_zero_bins"),
        },
    }
    decision_path = HERE / "metadata/m102-t095-personal-visual-decision.json"
    png_path = HERE / "metadata/png-evidence/m102-t095.json"
    write_json(decision_path, decision)
    write_json(
        png_path,
        {
            "schema": "ds02.f3.fresh179.png-evidence.v1",
            "case_id": CASE_ID,
            "physical_case_id": PHYSICAL_ID,
            "source": "render-publish-receipt.json",
            "contacts": contacts,
            "keys": keys,
            "content_read_or_hashed_by_reviewer": False,
            "all_paths_stat_checked": True,
            "reviewed_at_utc": REVIEWED_AT_UTC,
        },
    )

    package_files = [
        "README.md",
        "build_fresh179.py",
        "validate_fresh179.py",
        "metadata/m102-t095-personal-visual-decision.json",
        "metadata/png-evidence/m102-t095.json",
    ]
    manifest = {
        "schema": "ds02.f3.fresh179.package-manifest.v1",
        "fresh_id": FRESH,
        "package_manifest_excluded_from_own_hash": True,
        "files": [
            {"path": p, "bytes": (HERE / p).stat().st_size, "sha256": hashlib.sha256((HERE / p).read_bytes()).hexdigest()}
            for p in package_files
        ],
    }
    write_json(HERE / "package-manifest.json", manifest)
    return decision_path


if __name__ == "__main__":
    print(build())
