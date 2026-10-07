#!/usr/bin/env python3
"""Build the fresh181 F3 AY0270 personal visual-review handoff.

Only JSON/XML/XMF/Python/Markdown metadata is opened or hashed here.  The
published PNGs are checked with ``stat`` and their digests are copied from the
immutable renderer publish receipt.  This builder deliberately never opens,
copies, or hashes H5/BI4/CSV/DAT/VTK scientific payloads.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
QI = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F3_AY0270_actual1194_full836_UID_N3_time_ownQI_original154_"
    "runtimeunknown_audit1166_XMF1193_true_parentQA_1387/"
    "actual1194-full836-recovery-aware-QI-nativecanonical-typedlegacy-original154-"
    "unknown-previsual-proof.json"
)
BASE = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/"
    "F3_STAGE1_DP006_P1000_AY0270/"
    "root-stage1-f3-ay0270-actual1193-audit-qualified-original154-unknown-"
    "full836-116023-root1194"
)
CANONICAL = "a6a7dfcc6a3c45b895ae096d652c4bf4d203b6b3b9d228e40c7c7518e8d109e9"
LEGACY = "217fbe56b0a884a75199c2aabef347872558260395688dcaee30c0c9a3719413"
CASE = "F3_STAGE1_DP006_P1000_AY0270"
PHYSICAL = "F3_TWOAXIS_PITCH1000_AY0270_STAGE1_FIRST24_NEW"
FRAMES = 836
PARTICLES = 179208
COUNTS = {"fixed": 111708, "fluid": 67500, "moving": 0, "floating": 0}
TIME_WINDOW = [0.0, 8.3500164870623]
KEY_FRAMES = (0, 104, 208, 312, 417, 521, 626, 730, 835)
CONTACT_COUNT = 35
FORBIDDEN_SUFFIXES = {
    ".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu",
}


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


def metadata_sha(path: Path, label: str) -> str:
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES:
        fail(f"scientific payload hash attempted for {label}: {path}")
    if suffix not in {".json", ".xml", ".xmf", ".py", ".md"}:
        fail(f"unsupported metadata hash for {label}: {path}")
    if not path.is_file():
        fail(f"missing metadata for {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata_ref(path: Path, role: str, *, json_only: bool = False) -> dict[str, Any]:
    if json_only:
        read_json(path, role)
    elif path.suffix.lower() == ".json":
        read_json(path, role)
    elif path.suffix.lower() not in {".xml", ".xmf"}:
        fail(f"metadata reference is not JSON/XML: {role}: {path}")
    return {"path": str(path), "sha256": metadata_sha(path, role), "role": role}


def receipt_ref(
    path: Path,
    role: str,
    *,
    case_id: str = CASE,
    physical_case_id: str = PHYSICAL,
    require_completed: bool = True,
    check_identity: bool = True,
) -> dict[str, Any]:
    value = read_json(path, role)
    if not isinstance(value, dict):
        fail(f"{role} is not an object: {path}")
    if require_completed and (value.get("status") != "completed" or value.get("returncode") != 0):
        fail(f"{role} is not completed/0: {value.get('status')}/{value.get('returncode')}")
    request = value.get("request")
    if isinstance(request, dict) and check_identity:
        if request.get("case_id") not in (None, case_id):
            fail(f"{role} case binding mismatch: {request.get('case_id')}")
        if request.get("physical_case_id") not in (None, physical_case_id):
            fail(f"{role} physical binding mismatch: {request.get('physical_case_id')}")
        if request.get("physical_condition_sha256") not in (None, CANONICAL):
            fail(f"{role} native condition binding mismatch")
    result = {
        "path": str(path),
        "sha256": metadata_sha(path, role),
        "role": role,
        "status": value.get("status"),
        "returncode": value.get("returncode"),
    }
    if isinstance(request, dict):
        result["attempt_id"] = request.get("attempt_id")
        result["case_id"] = request.get("case_id")
        result["physical_case_id"] = request.get("physical_case_id")
        result["condition_sha256"] = request.get("physical_condition_sha256")
    return result


def unknown_receipt_ref(path: Path, role: str) -> dict[str, Any]:
    value = read_json(path, role)
    if value.get("status") != "running" or "returncode" in value:
        fail("original typed154 receipt no longer has the required unknown lifecycle")
    request = value.get("request", {})
    if request.get("case_id") != CASE or request.get("physical_case_id") != PHYSICAL:
        fail("original typed154 receipt identity mismatch")
    return {
        "path": str(path),
        "sha256": metadata_sha(path, role),
        "role": role,
        "status": "running",
        "returncode_field_present": False,
        "returncode": None,
        "reclassified_as_completed": False,
        "attempt_id": request.get("attempt_id"),
    }


def evidence_ref(
    qi: dict[str, Any], key: str, role: str, *, receipt=False, completed=True,
    check_identity: bool = True,
) -> dict[str, Any]:
    item = qi["actual_completed_metadata_evidence"].get(key)
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        fail(f"missing QI evidence reference {key}")
    path = Path(item["path"])
    if item.get("sha256") != metadata_sha(path, role):
        fail(f"QI evidence SHA mismatch for {role}")
    if receipt:
        result = receipt_ref(path, role, require_completed=completed, check_identity=check_identity)
    else:
        result = metadata_ref(path, role, json_only=path.suffix.lower() == ".json")
    result["qi_declared_sha256"] = item.get("sha256")
    return result


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def png_index(publish: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = publish.get("files_excluding_receipt")
    if not isinstance(entries, list):
        fail("publish receipt has no files_excluding_receipt list")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("relative_path"), str):
            fail("malformed publish entry")
        result[entry["relative_path"]] = entry
    return result


def published_png_ref(
    publish: dict[str, Any], index: dict[str, dict[str, Any]], relative: str, role: str
) -> dict[str, Any]:
    root = Path(str(publish.get("published_output_root", "")))
    entry = index.get(relative)
    if entry is None:
        fail(f"{role} is missing from publish receipt: {relative}")
    path = root / relative
    try:
        path.relative_to(root)
    except ValueError:
        fail(f"{role} escapes published root: {path}")
    if path.suffix.lower() != ".png" or not path.is_file():
        fail(f"{role} is not a published PNG: {path}")
    size = path.stat().st_size
    if size != entry.get("bytes"):
        fail(f"{role} stat differs from producer receipt: {path}")
    return {
        "path": str(path),
        "relative_path": relative,
        "bytes": entry.get("bytes"),
        "declared_sha256": entry.get("sha256"),
        "sha256_source": "render_publish_receipt",
        "stat_checked": True,
        "content_read_or_hashed_by_reviewer": False,
        "personally_viewed_with_view_image": True,
        "role": role,
    }


def build() -> Path:
    qi = read_json(QI, "Root1387 own QI")
    if qi.get("case_id") != CASE or qi.get("physical_case_id") != PHYSICAL:
        fail("QI case identity mismatch")
    if qi.get("frames") != FRAMES or qi.get("particles") != PARTICLES:
        fail("QI dimensions are not actual 836/179208")
    if qi.get("actual_time_window_s") != TIME_WINDOW:
        fail("QI time window mismatch")
    if qi.get("native_request_condition_sha256") != CANONICAL:
        fail("native canonical scope mismatch")
    if qi.get("actual_converter_condition_sha256") != LEGACY:
        fail("typed legacy scope mismatch")
    if qi.get("all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified") is not True:
        fail("QI does not attest full N3/finite/time evidence")
    if qi.get("all_native_UIDs_active_each_frame") is not True:
        fail("QI does not attest UID lifecycle")
    if qi.get("original_OS_exit_zero_not_claimed") is not True:
        fail("QI does not preserve original unknown OS lifecycle")
    if qi.get("original_typed154_runtime") != {
        "not_reclassified": True,
        "returncode": None,
        "returncode_field_present": False,
        "status": "running",
    }:
        fail("QI original typed154 lifecycle changed")
    namespaces = qi.get("actual_native_XMF_plan_field_namespaces")
    expected_absent = {"present": False, "value": None}
    if namespaces != {
        "native": {
            "source_plan_condition_sha256": expected_absent,
            "source_plan_physical_condition_sha256": expected_absent,
        },
        "XMF": {
            "source_plan_condition_sha256": expected_absent,
            "source_plan_physical_condition_sha256": expected_absent,
        },
    }:
        fail("native/XMF source-plan field presence is not explicit")

    qi_ref = metadata_ref(QI, "Root1387 own QI", json_only=True)
    native_receipt = evidence_ref(qi, "actual_native_receipt", "actual native receipt", receipt=True)
    typed_report = evidence_ref(qi, "actual_producer_conversion_report", "typed conversion report")
    xmf_receipt = evidence_ref(qi, "actual_XMF_receipt", "actual XMF receipt", receipt=True)
    xmf_manifest = evidence_ref(qi, "actual_XMF_manifest", "actual XMF manifest")
    xmf_xml = evidence_ref(qi, "actual_XMF_XML", "actual XMF XML")
    render_receipt = evidence_ref(qi, "actual_render_receipt", "actual render receipt", receipt=True)
    render_report_ref = evidence_ref(qi, "actual_render_report", "actual render report")
    publish_ref = evidence_ref(qi, "actual_render_publish_receipt", "atomic publish receipt")
    artifact_receipt = evidence_ref(qi, "actual_artifact_audit_receipt", "artifact audit receipt", receipt=True)
    artifact_report = evidence_ref(qi, "actual_artifact_audit_report", "artifact audit report")
    parent_qa_receipt = evidence_ref(
        qi, "genuine_parent_initial_QA_receipt", "parent initial QA receipt", receipt=True,
        check_identity=False,
    )
    parent_qa_report = evidence_ref(qi, "genuine_parent_initial_QA_report", "parent initial QA report")
    clone_receipt = evidence_ref(
        qi, "actual_initial_clone_preparation_receipt", "exact initial clone receipt", receipt=True,
        check_identity=False,
    )
    preparation_report = evidence_ref(qi, "actual_preparation_report", "prepared input report")
    gencase_receipt = evidence_ref(
        qi, "typed_source_gencase_receipt", "reused GenCase receipt", receipt=True,
        check_identity=False,
    )
    generated_xml = evidence_ref(qi, "typed_source_generated_xml", "source generated XML")
    owner_metadata = evidence_ref(qi, "typed_source_owner_metadata", "source owner metadata")
    original_conversion_receipt = evidence_ref(qi, "original_conversion_receipt", "original typed154 receipt")
    original_value = read_json(Path(original_conversion_receipt["path"]), "original typed154 receipt")
    if original_value.get("status") != "running" or "returncode" in original_value:
        fail("original typed154 receipt changed while building")
    original_conversion_receipt = unknown_receipt_ref(Path(original_conversion_receipt["path"]), "original typed154 receipt")

    report = read_json(Path(render_report_ref["path"]), "actual render report")
    publish = read_json(Path(publish_ref["path"]), "atomic publish receipt")
    manifest = read_json(Path(xmf_manifest["path"]), "actual XMF manifest")
    conversion = read_json(Path(typed_report["path"]), "typed conversion report")
    artifact = read_json(Path(artifact_report["path"]), "artifact audit report")
    if report.get("frames") != FRAMES or report.get("source_frames") != FRAMES:
        fail("render report is not full 836")
    outputs = report.get("outputs", {})
    contacts_paths = outputs.get("contact_sheets")
    if not isinstance(contacts_paths, list) or len(contacts_paths) != CONTACT_COUNT:
        fail("render report does not expose exactly 35 contact sheets")
    diagnostics = report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != FRAMES:
        fail("render report does not expose 836 diagnostics")
    for i, row in enumerate(diagnostics):
        if not isinstance(row, dict) or row.get("frame") != i:
            fail("render frame diagnostic index is not contiguous")
        if row.get("active") != PARTICLES or row.get("missing") != 0:
            fail("render active/missing lifecycle differs from actual producer evidence")
        if row.get("type_counts_active") != {**COUNTS, "unknown": 0}:
            fail("render type partition differs from producer evidence")
        if row.get("finite_positions_active") is not True or row.get("identity_axis_preserved") is not True:
            fail("render finite/identity evidence is incomplete")
        finite = row.get("finite_fields")
        if not isinstance(finite, dict) or any(
            not isinstance(finite.get(name), dict) or finite[name].get("finite_active") is not True
            for name in ("density", "mass", "pressure", "velocity")
        ):
            fail("render finite field evidence is incomplete")
    actual_times = [row["actual_time_s"] for row in diagnostics]
    if actual_times[0] != TIME_WINDOW[0] or actual_times[-1] != TIME_WINDOW[1]:
        fail("render time endpoints differ from QI")
    xmf_times = manifest.get("actual_time_s")
    if not isinstance(xmf_times, list) or len(xmf_times) != FRAMES or xmf_times != actual_times:
        fail("XMF actual times do not exactly match render report")
    if manifest.get("frames") != FRAMES or manifest.get("particles") != PARTICLES:
        fail("XMF dimensions mismatch")
    if manifest.get("physical_condition_sha256") != CANONICAL:
        fail("XMF physical condition is not native canonical")
    if manifest.get("canonical_source_physical_condition_sha256") != CANONICAL:
        fail("XMF canonical source scope mismatch")
    if manifest.get("actual_converter_scope_sha256") != LEGACY:
        fail("XMF legacy converter scope mismatch")
    if manifest.get("source_plan_scope_sha256") is not None:
        fail("XMF source plan scope was backfilled")
    if conversion.get("frames") != FRAMES or conversion.get("particles") != PARTICLES:
        fail("typed producer report dimensions mismatch")
    if artifact.get("artifact_integrity_status") != "completed":
        fail("artifact audit report is not completed")
    if artifact.get("field_audit", {}).get("frames") != FRAMES:
        fail("artifact audit frame evidence mismatch")
    if publish.get("status") != "published_after_atomic_rename":
        fail("render publish is not atomic/published")
    if publish.get("report_sha256_after_rebind") != render_report_ref["sha256"]:
        fail("publish receipt is not bound to actual report SHA")
    if report.get("source_h5_sha256") != manifest.get("source_h5_sha256"):
        fail("render/XMF producer H5 attestations differ")

    index = png_index(publish)
    published_root = Path(str(publish["published_output_root"]))
    contacts: list[dict[str, Any]] = []
    for i, absolute in enumerate(contacts_paths):
        path = Path(absolute)
        relative = path.relative_to(published_root).as_posix()
        contacts.append(published_png_ref(publish, index, relative, f"contact_sheet_{i:02d}"))
    keys: list[dict[str, Any]] = []
    for frame in KEY_FRAMES:
        relative = f"frames/frame_{frame:04d}.png"
        keys.append(published_png_ref(publish, index, relative, f"key_frame_{frame:04d}"))

    # This is the actual completion time of the personal review, recorded from
    # the completed visual review session rather than inferred from a receipt.
    review_completed_at = "2026-10-07T08:31:35.007894728+00:00"
    decision = {
        "schema": "ds02.f3.fresh181.personal-visual-review.v1",
        "fresh_id": "fresh181",
        "review_completed_at_utc": review_completed_at,
        "configured_model": "gpt-5.6-luna/max",
        "model_substitution": False,
        "recursive_delegation": False,
        "assigned_worktree_family": "F3",
        "actual_case_family": "F3",
        "case_id": CASE,
        "physical_case_id": PHYSICAL,
        "physical_condition_roles": {
            "native_canonical_condition_sha256": CANONICAL,
            "typed_legacy_converter_scope_sha256": LEGACY,
            "xmf_physical_condition_sha256": manifest.get("physical_condition_sha256"),
            "xmf_actual_converter_scope_sha256": manifest.get("actual_converter_scope_sha256"),
            "scope_schema": qi.get("scope_schema"),
            "native_and_xmf_plan_fields": {
                "native_source_plan_condition_sha256": {"present": False, "value": None},
                "native_source_plan_physical_condition_sha256": {"present": False, "value": None},
                "xmf_source_plan_condition_sha256": {"present": False, "value": None},
                "xmf_source_plan_physical_condition_sha256": {"present": False, "value": None},
                "interpretation": "Absent fields remain absent; the native canonical digest is not copied into a source-plan field.",
            },
        },
        "actual_dimensions": {
            "frames": FRAMES,
            "particles": PARTICLES,
            **COUNTS,
            "vector_shape": "N x 3",
            "time_window_s": TIME_WINDOW,
            "uid_lifecycle": "all native UIDs active each frame per Root1387 QI",
        },
        "actual_chain": {
            "native": native_receipt,
            "typed": {"conversion_report": typed_report},
            "artifact_audit": {"receipt": artifact_receipt, "report": artifact_report},
            "xmf": {"receipt": xmf_receipt, "manifest": xmf_manifest, "xml": xmf_xml},
            "render": {"receipt": render_receipt, "report": render_report_ref, "atomic_publish": publish_ref},
            "source_h5_producer_sha256": report.get("source_h5_sha256"),
        },
        "reused_initialization": {
            "parent_initial_qa_report": parent_qa_report,
            "parent_initial_qa_receipt": parent_qa_receipt,
            "exact_initial_clone_preparation_receipt": clone_receipt,
            "source_preparation_report": preparation_report,
            "reused_gencase_receipt": gencase_receipt,
            "source_generated_xml": generated_xml,
            "source_owner_metadata": owner_metadata,
            "interpretation": "Parent QA/GenCase/clone evidence is reused provenance, not a newly fabricated independent per-case QA receipt.",
        },
        "original_conversion_unknown_lifecycle": original_conversion_receipt,
        "independent_recovery_evidence": {
            "artifact_audit_completed0": True,
            "recovery_xmf_completed0": True,
            "old_conversion_not_reclassified": True,
        },
        "historical_outer_envelope": {
            "outer_request_expected_frames": 801,
            "outer_request_expected_particles": 194427,
            "outer_request_expected_contact_sheets": 34,
            "actual_loaded_wrapper_frames": FRAMES,
            "actual_loaded_wrapper_particles": PARTICLES,
            "actual_contact_sheets": CONTACT_COUNT,
            "authority": "The completed loaded wrapper and published producer reports are authoritative; the stale outer envelope remains historical metadata.",
        },
        "visual_review": {
            "status": "visual-approved-by-delegated-agent",
            "screen": "pass_first_stage",
            "review_method": "personally viewed with view_image after completed/0, atomic publish, and Root1387 QI",
            "contact_sheets_viewed": CONTACT_COUNT,
            "key_frames_viewed": list(KEY_FRAMES),
            "observations": [
                "The initial blue fluid layer is coherent and regular at the tank floor against the gray fixed boundary.",
                "A coherent travelling crest/run-up and return/decay pattern moves through the domain.",
                "Steep/high right-boundary crests appear in several phases while remaining visually within the displayed tank domain.",
                "No obvious gross breakup, blank/corrupt frame, abrupt truncation, abnormal initial state, whole-domain explosion, or severe visible bed/wall breach was observed.",
                "Small point/raster edge speckle at crest regions is retained as a display observation only.",
            ],
            "physical_screen_limits": [
                "This is a first-stage visual screen, not numerical-precision, strict-containment, sub-DP, run-up-magnitude, or production qualification.",
                "The screen does not establish Q-N, Q-E, particle conservation beyond producer metadata, or global case credit.",
                "UID/type/time/finite/N3 evidence comes from Root1387 QI and producer metadata, not visual inference.",
            ],
            "scientific_payload_opened_or_hashed_by_reviewer": False,
            "scientific_jobs_started_or_restarted": False,
            "shared_state_modified": False,
            "case_credit": 0,
            "q_n_granted": False,
            "q_e_granted": False,
            "precision_status": "not_accepted",
        },
        "visual_evidence": {"contacts": contacts, "keys": keys},
        "provenance": {
            "qi_proof": qi_ref,
            "qi_at_utc": qi.get("at_utc"),
            "qi_sha256": qi_ref["sha256"],
            "publisher_png_sha_source": "immutable render-publish-receipt.json; reviewer only stat-checked PNGs",
            "actual_review_utc_source": "personal review session timestamp recorded after all published PNGs were viewed",
        },
    }
    decision_path = HERE / "metadata/actual1194-personal-visual-decision.json"
    png_path = HERE / "metadata/png-evidence/actual1194.json"
    write_json(decision_path, decision)
    write_json(
        png_path,
        {
            "schema": "ds02.f3.fresh181.png-evidence.v1",
            "case_id": CASE,
            "physical_case_id": PHYSICAL,
            "source": "render-publish-receipt.json",
            "contacts": contacts,
            "keys": keys,
            "content_read_or_hashed_by_reviewer": False,
            "all_paths_stat_checked": True,
            "personally_viewed_after_atomic_publish": True,
        },
    )
    manifest_path = HERE / "package-manifest.json"
    package_files = [
        HERE / "README.md",
        HERE / "build_fresh181.py",
        HERE / "validate_fresh181.py",
        decision_path,
        png_path,
    ]
    write_json(
        manifest_path,
        {
            "schema": "ds02.f3.fresh181.package-manifest.v1",
            "fresh_id": "fresh181",
            "package_manifest_excluded_from_own_hash": True,
            "files": [
                {
                    "path": str(path.relative_to(HERE)),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in package_files
            ],
        },
    )
    return decision_path


if __name__ == "__main__":
    print(build())
