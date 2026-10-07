#!/usr/bin/env python3
"""Read-only validator for fresh179.

It opens/hashes JSON/XML/XMF metadata only.  Published PNGs are checked by
stat against the producer's publish receipt; their bytes are never opened or
rehashed here.  Scientific payload suffixes are rejected before any access.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M102_T095_NEXT34"
PHYSICAL_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M102_T095"
CANONICAL = "4e06ddfc9c871e619f543397f8faba245de6e24df33950f0561d34ff6a9eb920"
LEGACY = "e561820d8792eda4b59e77a36cf41b6b9d07953553851b25eba4ad9938dd64e3"
SOURCE_DEF_SHA = "7530ddff20117a6d478fba2fc4ec90a05177a2ffccaec383eaf1fe03fc4139a1"
QI_SHA256 = "310384c2ef349ba9f30e8facfecf7395facd6c1a5830675a97797b86e8f8e6b6"
# The exact QI SHA above is checked again below against the immutable path; the
# spelling is intentionally kept as a single constant for the package proof.
QI_SHA256 = "310384c2ef349ba9f30e8facfecf7395facd6c1a5830675a97797b86e8f8e6b6"
KEY_FRAMES = (0, 100, 200, 300, 400, 500, 600, 700, 800)
FORBIDDEN_SUFFIXES = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def read_json(path: Path, label: str) -> Any:
    if path.suffix.lower() != ".json":
        fail(f"non-JSON read for {label}: {path}")
    if not path.is_file():
        fail(f"missing {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid {label}: {path}: {exc}")


def metadata_sha(path: Path, label: str) -> str:
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES:
        fail(f"scientific payload hash attempted: {label}: {path}")
    if suffix not in {".json", ".xml", ".xmf", ".py", ".md"}:
        fail(f"unsupported metadata hash: {label}: {path}")
    if not path.is_file():
        fail(f"missing metadata: {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_ref(value: Any, label: str, *, json_only: bool = False) -> Path:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        fail(f"malformed ref {label}")
    path = Path(value["path"])
    if not path.is_absolute():
        fail(f"non-absolute ref {label}: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        fail(f"forbidden scientific payload ref {label}: {path}")
    if json_only and path.suffix.lower() != ".json":
        fail(f"{label} must be JSON: {path}")
    actual = metadata_sha(path, label)
    if value.get("sha256") != actual:
        fail(f"metadata SHA mismatch for {label}: {value.get('sha256')} != {actual}")
    return path


def check_receipt(value: Any, label: str) -> dict[str, Any]:
    path = check_ref(value, label, json_only=True)
    obj = read_json(path, label)
    if not isinstance(obj, dict) or obj.get("status") != "completed" or obj.get("returncode") != 0:
        fail(f"{label} is not completed/0")
    return obj


def validate_package_manifest() -> None:
    manifest_path = HERE / "package-manifest.json"
    manifest = read_json(manifest_path, "package manifest")
    if manifest.get("schema") != "ds02.f3.fresh179.package-manifest.v1":
        fail("package manifest schema mismatch")
    if manifest.get("package_manifest_excluded_from_own_hash") is not True:
        fail("package manifest self-exclusion is missing")
    entries = manifest.get("files")
    expected = {
        "README.md",
        "build_fresh179.py",
        "validate_fresh179.py",
        "metadata/m102-t095-personal-visual-decision.json",
        "metadata/png-evidence/m102-t095.json",
    }
    if not isinstance(entries, list) or {e.get("path") for e in entries if isinstance(e, dict)} != expected:
        fail("package manifest file set mismatch")
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            fail("malformed package manifest entry")
        path = HERE / entry["path"]
        if not path.is_file() or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            fail(f"missing or forbidden package file: {path}")
        if metadata_sha(path, f"package file {path}") != entry.get("sha256"):
            fail(f"package file SHA mismatch: {path}")
        if path.stat().st_size != entry.get("bytes"):
            fail(f"package file byte mismatch: {path}")


def validate() -> None:
    validate_package_manifest()
    decision = read_json(HERE / "metadata/m102-t095-personal-visual-decision.json", "decision")
    png_sidecar = read_json(HERE / "metadata/png-evidence/m102-t095.json", "PNG sidecar")
    if decision.get("schema") != "ds02.f3.fresh179.personal-visual-review.v1":
        fail("decision schema mismatch")
    if decision.get("fresh_id") != "fresh179":
        fail("fresh ID mismatch")
    if decision.get("assigned_worktree_family") != "F3" or decision.get("actual_case_family") != "F5":
        fail("assigned and actual family roles are not distinct")
    if decision.get("case_id") != CASE_ID or decision.get("physical_case_id") != PHYSICAL_ID:
        fail("case identity mismatch")
    reviewer = decision.get("reviewer_configuration", {})
    if reviewer.get("model") != "gpt-5.6-luna" or reviewer.get("reasoning_effort") != "max":
        fail("reviewer configuration mismatch")
    if reviewer.get("configured_profile") != "gpt-5.6-luna/max":
        fail("configured profile mismatch")
    if reviewer.get("model_substitution") is not False or reviewer.get("recursive_delegation") is not False:
        fail("model substitution/recursion boundary changed")
    if reviewer.get("reviewed_at_utc") != "2026-10-07T07:37:40Z":
        fail("review timestamp is not the recorded post-view timestamp")

    roles = decision.get("physical_condition_roles", {})
    if roles.get("native_request_condition_sha256") != CANONICAL:
        fail("native canonical SHA mismatch")
    if roles.get("actual_native_canonical_scope_sha256") != CANONICAL:
        fail("native canonical scope mismatch")
    if roles.get("actual_converter_legacy_scope_sha256") != LEGACY:
        fail("legacy scope mismatch")
    if roles.get("source_definition_bed_role_sha256") != SOURCE_DEF_SHA:
        fail("bed SourceDef SHA mismatch")
    fields = roles.get("native_and_xmf_plan_fields", {})
    if fields.get("native_source_plan_condition_sha256") != {"present": False, "value": None}:
        fail("native condition plan was backfilled")
    if fields.get("native_source_plan_physical_condition_sha256") != {"present": True, "value": CANONICAL}:
        fail("native physical plan role mismatch")
    if fields.get("xmf_source_plan_condition_sha256") != {"present": False, "value": None}:
        fail("XMF condition plan was backfilled")
    if fields.get("xmf_source_plan_physical_condition_sha256") != {"present": True, "value": CANONICAL}:
        fail("XMF physical plan role mismatch")
    if fields.get("xmf_source_plan_physical_condition_has_native_canonical_role") is not True:
        fail("XMF canonical role missing")
    if fields.get("xmf_source_plan_physical_condition_has_SourceDef_role") is not False:
        fail("XMF physical plan incorrectly assigned SourceDef")
    source_def_ref = check_ref(roles.get("actual_SourceDef"), "actual SourceDef")
    if source_def_ref.suffix.lower() not in {".xml", ".xmf"}:
        fail("SourceDef is not XML metadata")

    dims = decision.get("actual_dimensions", {})
    for field, value in (("frames", 801), ("particles", 194427), ("fixed", 158559), ("fluid", 31658), ("moving", 4210), ("floating", 0)):
        if dims.get(field) != value:
            fail(f"actual dimension {field} mismatch")
    if dims.get("time_window_s") != [0.0, 16.00010761371514] or dims.get("vector_shape") != "N x 3":
        fail("actual time/vector scope mismatch")

    qi_path = check_ref(decision.get("root_qi"), "Root1371 QI proof", json_only=True)
    if metadata_sha(qi_path, "Root1371 QI proof") != QI_SHA256:
        fail("Root1371 QI SHA mismatch")
    qi = read_json(qi_path, "Root1371 QI proof")
    if qi.get("case_id") != CASE_ID or qi.get("physical_case_id") != PHYSICAL_ID:
        fail("QI identity mismatch")
    if qi.get("visual_status") != "pending delegated personal34contacts9keys":
        fail("QI was relabeled before review")
    if qi.get("main_scientific_payload_IO") is not False or qi.get("main_personally_viewed_PNGs") is not False:
        fail("QI boundary changed")
    if qi.get("all801_geometry_velocity_N3_times_UID_finite_verified") is not True or qi.get("all_native_UIDs_active_each_frame") is not True:
        fail("QI full-chain N3/UID evidence missing")

    chain = decision.get("actual_chain", {})
    for label, ref in (
        ("GenCase receipt", chain.get("gencase", {}).get("receipt")),
        ("initial QA receipt", chain.get("initial_qa", {}).get("receipt")),
        ("native receipt", chain.get("native")),
        ("typed receipt", chain.get("typed", {}).get("receipt")),
        ("XMF receipt", chain.get("xmf", {}).get("receipt")),
        ("bed receipt", chain.get("bed", {}).get("receipt")),
        ("render receipt", chain.get("render", {}).get("receipt")),
    ):
        check_receipt(ref, label)
    for label, ref in (
        ("generated XML", chain.get("gencase", {}).get("generated_xml")),
        ("initial QA report", chain.get("initial_qa", {}).get("report")),
        ("typed conversion report", chain.get("typed", {}).get("conversion_report")),
        ("XMF manifest", chain.get("xmf", {}).get("manifest")),
        ("XMF XML", chain.get("xmf", {}).get("xml")),
        ("bed report", chain.get("bed", {}).get("report")),
        ("render report", chain.get("render", {}).get("report")),
        ("render publish receipt", chain.get("render", {}).get("atomic_publish")),
    ):
        check_ref(ref, label, json_only=label not in {"generated XML", "XMF XML"})

    report_path = check_ref(chain["render"]["report"], "render report", json_only=True)
    report = read_json(report_path, "render report")
    if report.get("frames") != 801 or report.get("source_frames") != 801:
        fail("render report frames mismatch")
    diagnostics = report.get("frame_diagnostics")
    expected_counts = {"fixed": 158559, "fluid": 31658, "moving": 4210, "floating": 0, "unknown": 0}
    if not isinstance(diagnostics, list) or len(diagnostics) != 801:
        fail("render diagnostics count mismatch")
    for row in diagnostics:
        if not isinstance(row, dict) or row.get("active") != 194427 or row.get("missing") != 0 or row.get("type_counts_active") != expected_counts:
            fail("render diagnostic lifecycle/count mismatch")
    if chain.get("source_h5_producer_sha256") != report.get("source_h5_sha256"):
        fail("producer H5 attestation was changed or omitted")

    publish_path = check_ref(chain["render"]["atomic_publish"], "atomic publish receipt", json_only=True)
    publish = read_json(publish_path, "atomic publish receipt")
    if publish.get("status") != "published_after_atomic_rename":
        fail("atomic publish status mismatch")
    root = Path(str(publish.get("published_output_root", "")))
    entries = publish.get("files_excluding_receipt")
    if not isinstance(entries, list):
        fail("publish file list missing")
    index = {e.get("relative_path"): e for e in entries if isinstance(e, dict)}
    evidence = decision.get("visual_evidence", {})
    contact_refs = evidence.get("contacts")
    key_refs = evidence.get("keys")
    if not isinstance(contact_refs, list) or len(contact_refs) != 34:
        fail("contact evidence count mismatch")
    if not isinstance(key_refs, list) or [int(Path(r["relative_path"]).stem.split("_")[-1]) for r in key_refs] != list(KEY_FRAMES):
        fail("key evidence indices mismatch")
    if png_sidecar.get("contacts") != contact_refs or png_sidecar.get("keys") != key_refs:
        fail("PNG sidecar differs from decision")
    if png_sidecar.get("reviewed_at_utc") != reviewer.get("reviewed_at_utc"):
        fail("PNG sidecar review timestamp mismatch")
    for refs, label in ((contact_refs, "contact"), (key_refs, "key")):
        for ref in refs:
            path = Path(ref["path"])
            if path.suffix.lower() != ".png" or not path.is_file():
                fail(f"missing {label} PNG: {path}")
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                fail(f"{label} PNG escapes publish root: {path}")
            item = index.get(relative)
            if not isinstance(item, dict):
                fail(f"{label} PNG absent from publish receipt: {relative}")
            if path.stat().st_size != item.get("bytes") or ref.get("bytes") != item.get("bytes"):
                fail(f"{label} PNG stat differs from publish receipt: {relative}")
            if ref.get("declared_sha256") != item.get("sha256"):
                fail(f"{label} PNG digest is not publisher-declared: {relative}")
            if ref.get("sha256_source") != "render_publish_receipt" or ref.get("personally_viewed_with_view_image") is not True:
                fail(f"{label} PNG review/source boundary mismatch: {relative}")

    visual = decision.get("visual_review", {})
    if visual.get("status") != "visual-approved-by-delegated-agent" or visual.get("screen") != "pass_first_stage":
        fail("visual decision status mismatch")
    if visual.get("contact_sheets_viewed") != 34 or visual.get("key_frames_viewed") != list(KEY_FRAMES):
        fail("viewed PNG counts mismatch")
    if visual.get("scientific_payload_opened_or_hashed_by_reviewer") is not False or visual.get("scientific_jobs_started_or_restarted") is not False:
        fail("scientific boundary mismatch")
    if visual.get("shared_state_modified") is not False:
        fail("shared-state boundary mismatch")
    if visual.get("new_case_credit") != 0 or visual.get("q_n_granted") is not False or visual.get("q_e_granted") is not False:
        fail("visual review granted credit or qualification")
    if decision.get("root_qi_status_before_review") != "pending delegated personal34contacts9keys":
        fail("review ordering evidence missing")

    print(json.dumps({"status": "PASS", "fresh": "fresh179", "actual_family": "F5", "contacts": 34, "keys": 9, "case_credit": 0}, sort_keys=True))


if __name__ == "__main__":
    try:
        validate()
    except ValidationError as exc:
        raise SystemExit(f"fresh179 validation failed: {exc}")
