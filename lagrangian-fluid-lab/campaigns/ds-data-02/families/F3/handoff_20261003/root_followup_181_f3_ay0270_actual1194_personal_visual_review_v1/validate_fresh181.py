#!/usr/bin/env python3
"""Read-only validator for fresh181.

The validator may read and hash JSON/XML/XMF/Python/Markdown metadata.  It
only stats published PNGs and compares their producer-declared SHA/byte values
with the immutable publish receipt.  Scientific payload suffixes are rejected
before any open or hash operation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FORBIDDEN_SUFFIXES = {
    ".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu",
}
CASE = "F3_STAGE1_DP006_P1000_AY0270"
PHYSICAL = "F3_TWOAXIS_PITCH1000_AY0270_STAGE1_FIRST24_NEW"
CANONICAL = "a6a7dfcc6a3c45b895ae096d652c4bf4d203b6b3b9d228e40c7c7518e8d109e9"
LEGACY = "217fbe56b0a884a75199c2aabef347872558260395688dcaee30c0c9a3719413"
FRAMES = 836
PARTICLES = 179208
COUNTS = {"fixed": 111708, "fluid": 67500, "moving": 0, "floating": 0}
TIME_WINDOW = [0.0, 8.3500164870623]
KEY_FRAMES = (0, 104, 208, 312, 417, 521, 626, 730, 835)


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def load_json(path: Path, label: str) -> Any:
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
        fail(f"malformed metadata ref {label}")
    path = Path(value["path"])
    if not path.is_absolute():
        fail(f"non-absolute metadata ref {label}: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        fail(f"forbidden scientific payload ref {label}: {path}")
    if json_only and path.suffix.lower() != ".json":
        fail(f"{label} is not JSON: {path}")
    actual = metadata_sha(path, label)
    if value.get("sha256") != actual:
        fail(f"metadata SHA mismatch for {label}: {value.get('sha256')} != {actual}")
    return path


def check_receipt(value: Any, label: str) -> dict[str, Any]:
    path = check_ref(value, label, json_only=True)
    obj = load_json(path, label)
    if obj.get("status") != "completed" or obj.get("returncode") != 0:
        fail(f"{label} is not completed/0")
    request = obj.get("request")
    if isinstance(request, dict):
        if request.get("case_id") not in (None, CASE):
            fail(f"{label} case identity mismatch")
        if request.get("physical_case_id") not in (None, PHYSICAL):
            fail(f"{label} physical identity mismatch")
    return obj


def check_unknown_original(value: Any) -> None:
    path = check_ref(value, "original typed154 receipt", json_only=True)
    obj = load_json(path, "original typed154 receipt")
    if obj.get("status") != "running" or "returncode" in obj:
        fail("original typed154 receipt was reclassified or gained a returncode")
    request = obj.get("request", {})
    if request.get("case_id") != CASE or request.get("physical_case_id") != PHYSICAL:
        fail("original typed154 identity mismatch")
    if value.get("returncode_field_present") is not False or value.get("returncode") is not None:
        fail("unknown original returncode was normalized")


def validate_package_manifest() -> None:
    path = HERE / "package-manifest.json"
    manifest = load_json(path, "package manifest")
    if manifest.get("schema") != "ds02.f3.fresh181.package-manifest.v1":
        fail("package manifest schema mismatch")
    if manifest.get("package_manifest_excluded_from_own_hash") is not True:
        fail("package manifest self-exclusion is not explicit")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        fail("package manifest has no files")
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            fail("malformed package file entry")
        path = HERE / entry["path"]
        if not path.is_file() or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            fail(f"invalid package file: {path}")
        if entry.get("bytes") != path.stat().st_size:
            fail(f"package byte count mismatch: {path}")
        if entry.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            fail(f"package file SHA mismatch: {path}")


def check_png_ref(
    value: Any,
    label: str,
    root: Path,
    index: dict[str, dict[str, Any]],
) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        fail(f"malformed PNG ref {label}")
    path = Path(value["path"])
    if path.suffix.lower() != ".png" or not path.is_file():
        fail(f"missing PNG {label}: {path}")
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        fail(f"PNG escapes published root {label}: {path}")
    entry = index.get(rel)
    if not isinstance(entry, dict):
        fail(f"PNG not present in producer publish receipt {label}: {rel}")
    if path.stat().st_size != entry.get("bytes") or value.get("bytes") != entry.get("bytes"):
        fail(f"PNG stat differs from producer receipt {label}: {rel}")
    if value.get("declared_sha256") != entry.get("sha256"):
        fail(f"PNG SHA is not the publisher-declared SHA {label}: {rel}")
    if value.get("sha256_source") != "render_publish_receipt":
        fail(f"PNG SHA source is not publisher receipt {label}: {rel}")
    if value.get("stat_checked") is not True or value.get("personally_viewed_with_view_image") is not True:
        fail(f"PNG view/stat evidence missing {label}: {rel}")
    if value.get("content_read_or_hashed_by_reviewer") is not False:
        fail(f"PNG content boundary is not explicit {label}: {rel}")


def main() -> None:
    validate_package_manifest()
    decision_path = HERE / "metadata/actual1194-personal-visual-decision.json"
    png_path = HERE / "metadata/png-evidence/actual1194.json"
    decision = load_json(decision_path, "fresh181 visual decision")
    png_evidence = load_json(png_path, "fresh181 PNG evidence")
    if decision.get("schema") != "ds02.f3.fresh181.personal-visual-review.v1":
        fail("decision schema mismatch")
    if decision.get("fresh_id") != "fresh181" or decision.get("assigned_worktree_family") != "F3":
        fail("fresh/worktree identity mismatch")
    if decision.get("actual_case_family") != "F3" or decision.get("case_id") != CASE:
        fail("case identity mismatch")
    if decision.get("physical_case_id") != PHYSICAL:
        fail("physical identity mismatch")
    timestamp = decision.get("review_completed_at_utc")
    if not isinstance(timestamp, str) or "T" not in timestamp or not timestamp.endswith("+00:00"):
        fail("review completion timestamp is not an explicit UTC instant")
    if decision.get("configured_model") != "gpt-5.6-luna/max" or decision.get("model_substitution") is not False:
        fail("configured model provenance mismatch")
    if decision.get("recursive_delegation") is not False:
        fail("recursive delegation boundary is not explicit")

    roles = decision.get("physical_condition_roles", {})
    if roles.get("native_canonical_condition_sha256") != CANONICAL:
        fail("native canonical scope mismatch")
    if roles.get("typed_legacy_converter_scope_sha256") != LEGACY:
        fail("typed legacy scope mismatch")
    if roles.get("xmf_physical_condition_sha256") != CANONICAL:
        fail("XMF physical condition mismatch")
    if roles.get("xmf_actual_converter_scope_sha256") != LEGACY:
        fail("XMF actual converter scope mismatch")
    plan_fields = roles.get("native_and_xmf_plan_fields", {})
    absent = {"present": False, "value": None}
    for name in (
        "native_source_plan_condition_sha256",
        "native_source_plan_physical_condition_sha256",
        "xmf_source_plan_condition_sha256",
        "xmf_source_plan_physical_condition_sha256",
    ):
        if plan_fields.get(name) != absent:
            fail(f"source-plan absence was not preserved: {name}")

    dims = decision.get("actual_dimensions", {})
    if dims.get("frames") != FRAMES or dims.get("particles") != PARTICLES:
        fail("actual dimensions mismatch")
    for name, expected in COUNTS.items():
        if dims.get(name) != expected:
            fail(f"actual {name} count mismatch")
    if dims.get("vector_shape") != "N x 3" or dims.get("time_window_s") != TIME_WINDOW:
        fail("N3/time contract mismatch")

    chain = decision.get("actual_chain", {})
    native = check_receipt(chain.get("native"), "actual native receipt")
    if native.get("request", {}).get("physical_condition_sha256") != CANONICAL:
        fail("native receipt condition is not canonical")
    typed = chain.get("typed", {})
    typed_report_path = check_ref(typed.get("conversion_report"), "typed conversion report", json_only=True)
    typed_report = load_json(typed_report_path, "typed conversion report")
    if typed_report.get("frames") != FRAMES or typed_report.get("particles") != PARTICLES:
        fail("typed producer dimensions mismatch")

    audit = chain.get("artifact_audit", {})
    check_receipt(audit.get("receipt"), "artifact audit receipt")
    audit_path = check_ref(audit.get("report"), "artifact audit report", json_only=True)
    audit_report = load_json(audit_path, "artifact audit report")
    if audit_report.get("artifact_integrity_status") != "completed":
        fail("artifact audit is not completed")
    if audit_report.get("field_audit", {}).get("frames") != FRAMES:
        fail("artifact audit frame count mismatch")

    xmf = chain.get("xmf", {})
    check_receipt(xmf.get("receipt"), "actual XMF receipt")
    xmf_path = check_ref(xmf.get("manifest"), "actual XMF manifest", json_only=True)
    xmf_manifest = load_json(xmf_path, "actual XMF manifest")
    check_ref(xmf.get("xml"), "actual XMF XML")
    if xmf_manifest.get("frames") != FRAMES or xmf_manifest.get("particles") != PARTICLES:
        fail("XMF dimensions mismatch")
    if xmf_manifest.get("physical_condition_sha256") != CANONICAL:
        fail("XMF physical canonical mismatch")
    if xmf_manifest.get("canonical_source_physical_condition_sha256") != CANONICAL:
        fail("XMF canonical source mismatch")
    if xmf_manifest.get("actual_converter_scope_sha256") != LEGACY:
        fail("XMF converter legacy scope mismatch")
    if xmf_manifest.get("source_plan_scope_sha256") is not None:
        fail("XMF source plan scope was backfilled")

    render = chain.get("render", {})
    check_receipt(render.get("receipt"), "actual render receipt")
    report_path = check_ref(render.get("report"), "actual render report", json_only=True)
    report = load_json(report_path, "actual render report")
    if report.get("frames") != FRAMES or report.get("source_frames") != FRAMES:
        fail("render frame count mismatch")
    diagnostics = report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != FRAMES:
        fail("render diagnostic count mismatch")
    expected_type_counts = {**COUNTS, "unknown": 0}
    for index, row in enumerate(diagnostics):
        if not isinstance(row, dict) or row.get("frame") != index:
            fail("render frame diagnostics are not contiguous")
        if row.get("active") != PARTICLES or row.get("missing") != 0:
            fail("render UID lifecycle mismatch")
        if row.get("type_counts_active") != expected_type_counts:
            fail("render type partition mismatch")
        if row.get("finite_positions_active") is not True or row.get("identity_axis_preserved") is not True:
            fail("render finite/identity evidence missing")
        finite = row.get("finite_fields")
        if not isinstance(finite, dict) or any(
            not isinstance(finite.get(name), dict) or finite[name].get("finite_active") is not True
            for name in ("density", "mass", "pressure", "velocity")
        ):
            fail("render finite field evidence missing")
    report_times = [row["actual_time_s"] for row in diagnostics]
    if report_times[0] != TIME_WINDOW[0] or report_times[-1] != TIME_WINDOW[1]:
        fail("render time window mismatch")
    xmf_times = xmf_manifest.get("actual_time_s")
    if not isinstance(xmf_times, list) or xmf_times != report_times:
        fail("XMF and render times are not exact metadata matches")

    publish_path = check_ref(render.get("atomic_publish"), "atomic publish receipt", json_only=True)
    publish = load_json(publish_path, "atomic publish receipt")
    if publish.get("status") != "published_after_atomic_rename":
        fail("atomic publish status mismatch")
    if publish.get("report_sha256_after_rebind") != decision["actual_chain"]["render"]["report"]["sha256"]:
        fail("atomic publish report SHA binding mismatch")
    root = Path(str(publish.get("published_output_root", "")))
    entries = publish.get("files_excluding_receipt")
    if not isinstance(entries, list):
        fail("publish receipt file list missing")
    index = {item.get("relative_path"): item for item in entries if isinstance(item, dict)}
    visual_evidence = decision.get("visual_evidence", {})
    contacts = visual_evidence.get("contacts")
    keys = visual_evidence.get("keys")
    if not isinstance(contacts, list) or len(contacts) != 35:
        fail("contact evidence count mismatch")
    if not isinstance(keys, list) or len(keys) != len(KEY_FRAMES):
        fail("key evidence count mismatch")
    if [int(Path(item["relative_path"]).stem.split("_")[-1]) for item in keys] != list(KEY_FRAMES):
        fail("key evidence indices mismatch")
    if png_evidence.get("contacts") != contacts or png_evidence.get("keys") != keys:
        fail("PNG evidence sidecar differs from decision")
    for i, ref in enumerate(contacts):
        check_png_ref(ref, f"contact_{i:02d}", root, index)
    for frame, ref in zip(KEY_FRAMES, keys):
        check_png_ref(ref, f"key_{frame:04d}", root, index)
    if png_evidence.get("content_read_or_hashed_by_reviewer") is not False:
        fail("PNG content boundary missing")
    if png_evidence.get("all_paths_stat_checked") is not True:
        fail("PNG stat evidence missing")

    check_unknown_original(decision.get("original_conversion_unknown_lifecycle"))
    visual = decision.get("visual_review", {})
    if visual.get("status") != "visual-approved-by-delegated-agent" or visual.get("screen") != "pass_first_stage":
        fail("visual first-stage status mismatch")
    if visual.get("contact_sheets_viewed") != 35 or visual.get("key_frames_viewed") != list(KEY_FRAMES):
        fail("visual coverage mismatch")
    if visual.get("scientific_payload_opened_or_hashed_by_reviewer") is not False:
        fail("scientific payload boundary mismatch")
    if visual.get("scientific_jobs_started_or_restarted") is not False or visual.get("shared_state_modified") is not False:
        fail("job/shared-state boundary mismatch")
    if visual.get("case_credit") != 0 or visual.get("q_n_granted") is not False or visual.get("q_e_granted") is not False:
        fail("visual review incorrectly grants credit or qualification")

    envelope = decision.get("historical_outer_envelope", {})
    if envelope.get("outer_request_expected_frames") != 801 or envelope.get("outer_request_expected_particles") != 194427:
        fail("historical outer envelope was lost")
    if envelope.get("actual_loaded_wrapper_frames") != FRAMES or envelope.get("actual_loaded_wrapper_particles") != PARTICLES:
        fail("actual loaded wrapper distinction was lost")
    print(json.dumps({"status": "PASS", "fresh": "fresh181", "contacts": 35, "keys": 9, "case_credit": 0}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ValidationError as exc:
        raise SystemExit(f"fresh181 validation failed: {exc}")
