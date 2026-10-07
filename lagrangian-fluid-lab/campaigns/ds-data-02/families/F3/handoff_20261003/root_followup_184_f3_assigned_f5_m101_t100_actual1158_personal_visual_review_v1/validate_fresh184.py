#!/usr/bin/env python3
"""Fail-closed validator for the fresh184 metadata/PNG-stat handoff."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FORBIDDEN_SUFFIXES = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M101_T100_NEXT34"
PHYSICAL = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M101_T100"
CANONICAL = "1a04363bffefde127740d3da87de48ba66db566b7ae0cdf44d6c6f4b73137cf3"
LEGACY = "80039c17cc7a088b7bc0fdc5c7a74d9051aa72763652261e2823635fcd5ad93d"
SOURCE_DEF = "6c74924feda21861f0a15d1259871f3a536ae2a2264acc4047a60caee1b5d451"
FRAMES = 801
PARTICLES = 194427
KEY_FRAMES = (0, 100, 200, 300, 400, 500, 600, 700, 800)


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def load_json(path: Path, label: str) -> Any:
    if path.suffix.lower() != ".json" or not path.is_file():
        fail(f"invalid JSON path for {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid JSON {label}: {exc}")


def metadata_sha(path: Path, label: str) -> str:
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES:
        fail(f"scientific payload hash attempted: {label}: {path}")
    if suffix not in {".json", ".xml", ".xmf", ".py", ".md"} or not path.is_file():
        fail(f"invalid metadata reference: {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_ref(value: Any, label: str) -> Path:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        fail(f"malformed metadata ref: {label}")
    path = Path(value["path"])
    if not path.is_absolute() or value.get("sha256") != metadata_sha(path, label):
        fail(f"metadata ref mismatch: {label}")
    return path


def check_receipt(value: Any, label: str) -> dict[str, Any]:
    obj = load_json(check_ref(value, label), label)
    if obj.get("status") != "completed" or obj.get("returncode") != 0:
        fail(f"{label} is not completed/0")
    req = obj.get("request")
    if isinstance(req, dict) and (req.get("case_id") not in (None, CASE) or req.get("physical_case_id") not in (None, PHYSICAL)):
        fail(f"{label} identity mismatch")
    return obj


def check_png(value: Any, label: str, root: Path, index: dict[str, dict[str, Any]]) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        fail(f"malformed PNG evidence: {label}")
    path = Path(value["path"])
    if path.suffix.lower() != ".png" or not path.is_file():
        fail(f"missing PNG: {label}")
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        fail(f"PNG outside published root: {label}")
    entry = index.get(relative)
    if not isinstance(entry, dict) or path.stat().st_size != entry.get("bytes") or value.get("bytes") != entry.get("bytes"):
        fail(f"PNG stat/producer bytes mismatch: {label}")
    if value.get("declared_sha256") != entry.get("sha256") or value.get("sha256_source") != "render_publish_receipt":
        fail(f"PNG SHA provenance mismatch: {label}")
    if value.get("stat_checked") is not True or value.get("personally_viewed_with_view_image") is not True or value.get("content_read_or_hashed_by_reviewer") is not False:
        fail(f"PNG personal/boundary evidence missing: {label}")


def check_manifest() -> None:
    manifest = load_json(HERE / "package-manifest.json", "package manifest")
    if manifest.get("schema") != "ds02.f3.fresh184.package-manifest.v1" or manifest.get("package_manifest_excluded_from_own_hash") is not True:
        fail("package manifest schema/self exclusion mismatch")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        fail("package manifest files missing")
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            fail("malformed package manifest entry")
        path = HERE / item["path"]
        if not path.is_file() or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            fail(f"invalid package file {path}")
        if path.stat().st_size != item.get("bytes") or hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            fail(f"package manifest byte/SHA mismatch: {path}")


def main() -> None:
    check_manifest()
    decision = load_json(HERE / "metadata/actual1158-personal-visual-decision.json", "visual decision")
    png = load_json(HERE / "metadata/png-evidence/actual1158.json", "PNG evidence")
    if decision.get("schema") != "ds02.f3.fresh184.personal-visual-review.v1" or decision.get("fresh_id") != "fresh184":
        fail("decision schema/fresh mismatch")
    if decision.get("assigned_worktree_family") != "F3" or decision.get("actual_case_family") != "F5":
        fail("assigned/actual family mismatch")
    if decision.get("case_id") != CASE or decision.get("physical_case_id") != PHYSICAL:
        fail("case identity mismatch")
    stamp = decision.get("review_completed_at_utc")
    if not isinstance(stamp, str) or "T" not in stamp or not stamp.endswith("+00:00"):
        fail("review timestamp is not an explicit UTC instant")
    if decision.get("configured_model") != "gpt-5.6-luna/max" or decision.get("model_substitution") is not False or decision.get("recursive_delegation") is not False:
        fail("model/delegation provenance mismatch")

    roles = decision.get("physical_condition_roles", {})
    if roles.get("native_canonical_condition_sha256") != CANONICAL or roles.get("typed_legacy_converter_scope_sha256") != LEGACY or roles.get("bed_source_definition_sha256") != SOURCE_DEF:
        fail("native/typed/bed roles mismatch")
    if roles.get("xmf_physical_condition_sha256") != CANONICAL or roles.get("xmf_source_plan_physical_condition_sha256") != CANONICAL:
        fail("XMF canonical roles mismatch")
    if roles.get("xmf_actual_converter_legacy_scope_sha256") is not None:
        fail("XMF legacy field was incorrectly filled")
    native_cond = roles.get("native_source_plan_condition_field", {})
    native_phys = roles.get("native_source_plan_physical_condition_field", {})
    if native_cond != {"present": False, "value": None} or native_phys != {"present": True, "value": CANONICAL}:
        fail("native plan field mask mismatch")
    xmf = roles.get("xmf_source_plan_physical_condition_field", {})
    if xmf.get("present") is not True or xmf.get("value") != CANONICAL or xmf.get("native_canonical_role") is not True or xmf.get("SourceDef_role") is not False:
        fail("XMF source-plan role mask mismatch")
    bed = roles.get("bed_declared_source_plan_field", {})
    if bed.get("present") is not True or bed.get("value") != SOURCE_DEF or bed.get("SourceDef_role") is not True:
        fail("bed SourceDef role mask mismatch")

    dims = decision.get("actual_dimensions", {})
    if dims.get("frames") != FRAMES or dims.get("particles") != PARTICLES or dims.get("vector_shape") != "N x 3" or dims.get("time_window_s") != [0.0, 16.00015600764587]:
        fail("actual dimensions mismatch")
    if dims.get("all801_geometry_velocity_N3_times_UID_finite_verified") is not True or dims.get("all_native_UIDs_active_each_frame") is not True:
        fail("actual QI lifecycle fields missing")
    limits = decision.get("precision_and_limits", {})
    if limits.get("case_credit") != 0 or limits.get("q_n_granted") is not False or limits.get("q_e_granted") is not False:
        fail("credit/qualification boundary changed")

    chain = decision.get("actual_chain")
    if not isinstance(chain, dict):
        fail("actual chain missing")
    for key, value in chain.items():
        if key == "original_previsual_dependency_review":
            check_ref(value, key)
        elif key == "render_publish_receipt":
            load_json(check_ref(value, key), key)
        else:
            check_receipt(value, key) if key.endswith("receipt") else check_ref(value, key)

    publish = load_json(check_ref(chain["render_publish_receipt"], "render publish receipt"), "render publish receipt")
    report = load_json(check_ref(chain["render_report"], "render report"), "render report")
    manifest = load_json(check_ref(chain["xmf_manifest"], "XMF manifest"), "XMF manifest")
    render_receipt = load_json(check_ref(chain["render_receipt"], "render receipt"), "render receipt")
    if publish.get("status") != "published_after_atomic_rename" or publish.get("case_id") != CASE or publish.get("attempt_id") != render_receipt.get("request", {}).get("attempt_id"):
        fail("publish receipt status/identity mismatch")
    if report.get("frames") != FRAMES or report.get("source_frames") != FRAMES or report.get("all_frames_rendered") is not True or report.get("manifest_sha256") != chain["xmf_manifest"]["sha256"]:
        fail("render report binding mismatch")
    diagnostics = report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != FRAMES:
        fail("render diagnostics missing")
    for i, row in enumerate(diagnostics):
        if not isinstance(row, dict) or row.get("frame") != i or row.get("active") != PARTICLES or row.get("missing") != 0:
            fail(f"frame {i} lifecycle mismatch")
        if row.get("finite_positions_active") is not True or row.get("identity_axis_preserved") is not True:
            fail(f"frame {i} identity/finite mismatch")
    if manifest.get("case_id") != CASE or manifest.get("physical_case_id") != PHYSICAL or manifest.get("frames") != FRAMES or manifest.get("particles") != PARTICLES:
        fail("XMF manifest identity/dimensions mismatch")
    if manifest.get("physical_condition_sha256") != CANONICAL or manifest.get("source_plan_physical_condition_sha256") != CANONICAL or manifest.get("source_definition_sha256") != SOURCE_DEF:
        fail("XMF canonical/source-definition mismatch")
    if manifest.get("source_plan_condition_sha256") is not None or manifest.get("canonical_source_physical_condition_sha256") is not None or manifest.get("actual_converter_legacy_scope_sha256") is not None:
        fail("XMF absent fields were backfilled")
    if publish.get("report_sha256_after_rebind") != chain["render_report"]["sha256"]:
        fail("publish report SHA mismatch")

    root = Path(str(publish.get("published_output_root", "")))
    index = {entry.get("relative_path"): entry for entry in publish.get("files_excluding_receipt", []) if isinstance(entry, dict)}
    evidence = decision.get("visual_evidence", {})
    contacts = evidence.get("contacts")
    keys = evidence.get("keys")
    if not isinstance(contacts, list) or len(contacts) != 34 or not isinstance(keys, list) or [item.get("relative_path") for item in keys] != [f"frames/frame_{n:04d}.png" for n in KEY_FRAMES]:
        fail("visual evidence contact/key cardinality mismatch")
    for i, item in enumerate(contacts):
        check_png(item, f"contact_{i:02d}", root, index)
    for n, item in zip(KEY_FRAMES, keys):
        check_png(item, f"key_{n:04d}", root, index)
    if png.get("case_id") != CASE or png.get("physical_case_id") != PHYSICAL or png.get("personally_viewed_after_atomic_publish") is not True:
        fail("PNG evidence identity/status mismatch")
    if len(png.get("contacts", [])) != 34 or len(png.get("keys", [])) != 9:
        fail("PNG evidence cardinality mismatch")
    print("fresh184 validator PASS: F5 M101/T100 completed/0, 801-frame metadata, 34 contacts, 9 keys, role masks closed")


if __name__ == "__main__":
    main()
