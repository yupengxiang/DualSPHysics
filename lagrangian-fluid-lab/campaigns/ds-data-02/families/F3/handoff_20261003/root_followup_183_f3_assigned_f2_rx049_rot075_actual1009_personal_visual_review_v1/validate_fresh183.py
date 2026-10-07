#!/usr/bin/env python3
"""Fail-closed metadata/PNG-stat validator for fresh183.

It hashes JSON/XML/XMF/Python/Markdown metadata only.  Published PNGs are
checked by stat and compared to producer-declared bytes/SHA; their contents
are not opened or hashed by this validator.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FORBIDDEN_SUFFIXES = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
CASE = "F2_STAGE1_FIRST48_EXPANSION_RX049_RY014_FILL080_ROT075_DP010_SPATIAL_REFERENCE_SAVE010"
PHYSICAL = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX049_RY014_FILL080_ROT075"
CANONICAL = "27f952a271ff237e6fe2d09e21047786476f1ce9ad5157c94847097187026fa6"
LEGACY = "208d547c388db7caed982f1d088baf6fb942b46e48e4f8552a0e0cfe21cf1f9b"
FRAMES = 401
PARTICLES = 418104
KEY_FRAMES = (0, 50, 100, 150, 200, 250, 300, 350, 400)


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
        fail(f"forbidden scientific payload hash: {label}: {path}")
    if suffix not in {".json", ".xml", ".xmf", ".py", ".md"} or not path.is_file():
        fail(f"invalid metadata ref: {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_metadata_ref(value: Any, label: str) -> Path:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        fail(f"malformed metadata ref: {label}")
    path = Path(value["path"])
    if not path.is_absolute():
        fail(f"metadata path is not absolute: {label}")
    if value.get("sha256") != metadata_sha(path, label):
        fail(f"metadata SHA mismatch: {label}")
    return path


def check_receipt(value: Any, label: str, expected_scope: str | None = None) -> dict[str, Any]:
    path = check_metadata_ref(value, label)
    obj = load_json(path, label)
    if obj.get("status") != "completed" or obj.get("returncode") != 0:
        fail(f"{label} is not completed/0")
    req = obj.get("request")
    if isinstance(req, dict):
        if req.get("case_id") not in (None, CASE) or req.get("physical_case_id") not in (None, PHYSICAL):
            fail(f"{label} identity mismatch")
        if expected_scope is not None and req.get("physical_condition_sha256") not in (None, expected_scope):
            fail(f"{label} scope mismatch")
    return obj


def check_manifest() -> None:
    manifest = load_json(HERE / "package-manifest.json", "package manifest")
    if manifest.get("schema") != "ds02.f3.fresh183.package-manifest.v1" or manifest.get("package_manifest_excluded_from_own_hash") is not True:
        fail("package manifest schema/self exclusion mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        fail("package manifest files missing")
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            fail("malformed package manifest entry")
        path = HERE / item["path"]
        if not path.is_file() or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            fail(f"invalid package file {path}")
        if path.stat().st_size != item.get("bytes") or hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            fail(f"package manifest byte/SHA mismatch {path}")


def check_png(value: Any, label: str, root: Path, index: dict[str, dict[str, Any]]) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        fail(f"malformed PNG evidence {label}")
    path = Path(value["path"])
    if path.suffix.lower() != ".png" or not path.is_file():
        fail(f"missing PNG {label}: {path}")
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        fail(f"PNG outside published root {label}")
    entry = index.get(rel)
    if not isinstance(entry, dict):
        fail(f"PNG absent from publisher receipt {label}")
    if path.stat().st_size != entry.get("bytes") or value.get("bytes") != entry.get("bytes"):
        fail(f"PNG stat/producer bytes mismatch {label}")
    if value.get("declared_sha256") != entry.get("sha256") or value.get("sha256_source") != "render_publish_receipt":
        fail(f"PNG declared SHA provenance mismatch {label}")
    if value.get("stat_checked") is not True or value.get("personally_viewed_with_view_image") is not True:
        fail(f"PNG personal/stat evidence missing {label}")
    if value.get("content_read_or_hashed_by_reviewer") is not False:
        fail(f"PNG content boundary missing {label}")


def main() -> None:
    check_manifest()
    decision = load_json(HERE / "metadata/actual1009-personal-visual-decision.json", "visual decision")
    png = load_json(HERE / "metadata/png-evidence/actual1009.json", "PNG evidence")
    if decision.get("schema") != "ds02.f3.fresh183.personal-visual-review.v1" or decision.get("fresh_id") != "fresh183":
        fail("decision schema/fresh mismatch")
    if decision.get("assigned_worktree_family") != "F3" or decision.get("actual_case_family") != "F2":
        fail("assigned/actual family mismatch")
    if decision.get("case_id") != CASE or decision.get("physical_case_id") != PHYSICAL:
        fail("case identity mismatch")
    stamp = decision.get("review_completed_at_utc")
    if not isinstance(stamp, str) or "T" not in stamp or not stamp.endswith("+00:00"):
        fail("review timestamp is not an explicit UTC instant")
    if decision.get("configured_model") != "gpt-5.6-luna/max" or decision.get("model_substitution") is not False or decision.get("recursive_delegation") is not False:
        fail("model/delegation provenance mismatch")

    roles = decision.get("physical_condition_roles", {})
    if roles.get("native_canonical_condition_sha256") != CANONICAL or roles.get("typed_legacy_converter_scope_sha256") != LEGACY:
        fail("native/typed role mismatch")
    if roles.get("xmf_physical_condition_sha256") != LEGACY or roles.get("xmf_canonical_source_physical_condition_sha256") != CANONICAL or roles.get("xmf_actual_converter_legacy_scope_sha256") != LEGACY:
        fail("XMF role mismatch")
    plan = roles.get("native_and_xmf_plan_fields", {})
    if plan.get("native", {}).get("source_plan_condition_sha256") != {"present": False, "value": None}:
        fail("native source-plan condition absence changed")
    if plan.get("native", {}).get("source_plan_physical_condition_sha256", {}).get("present") is not True:
        fail("native physical source-plan evidence missing")
    if any(plan.get("XMF", {}).get(name) != {"present": False, "value": None} for name in ("source_plan_condition_sha256", "source_plan_physical_condition_sha256")):
        fail("XMF source-plan absence changed")

    dims = decision.get("actual_dimensions", {})
    if dims.get("frames") != FRAMES or dims.get("particles") != PARTICLES or dims.get("vector_shape") != "N x 3":
        fail("actual dimensions mismatch")
    if dims.get("initial_type_counts", {}).get("total") != PARTICLES or dims.get("terminal_type_counts", {}).get("total") != 418069:
        fail("actual counts mismatch")
    omissions = decision.get("lifecycle_omissions", {})
    if omissions.get("final_missing_particles") != 35 or omissions.get("first_missing_frame") != 137 or omissions.get("cumulative_particle_frame_omissions") != 8397:
        fail("lifecycle omission evidence mismatch")
    if omissions.get("final_Idp_sample_is_partial_not_all35") is not True or omissions.get("missing_location_state_cause_unknown") is not True:
        fail("lifecycle uncertainty was lost")

    chain = decision.get("actual_chain", {})
    check_receipt(chain.get("native_receipt"), "native receipt", CANONICAL)
    check_receipt(chain.get("initial_qa_receipt"), "initial QA receipt", CANONICAL)
    check_receipt(chain.get("typed_receipt"), "typed receipt", CANONICAL)
    check_receipt(chain.get("XMF_receipt"), "XMF receipt", LEGACY)
    check_receipt(chain.get("render_receipt"), "render receipt", LEGACY)
    for key in ("initial_qa_report", "typed_report", "XMF_manifest", "XMF_XML", "render_report", "typed_source_generated_xml", "typed_source_owner_metadata", "prior_full401_scientific_integrity_review"):
        check_metadata_ref(chain.get(key), key)
    publish_path = check_metadata_ref(chain.get("render_publish_receipt"), "render publish receipt")
    publish = load_json(publish_path, "render publish receipt")
    if publish.get("status") != "published_after_atomic_rename" or publish.get("case_id") != CASE:
        fail("publish receipt status/identity mismatch")
    report_path = check_metadata_ref(chain.get("render_report"), "render report")
    report = load_json(report_path, "render report")
    if report.get("frames") != FRAMES or report.get("source_frames") != FRAMES or report.get("all_frames_rendered") is not True or report.get("actual_times_preserved_exactly") is not True:
        fail("render report full/time gate mismatch")
    if report.get("manifest_sha256") != chain.get("XMF_manifest", {}).get("sha256") or publish.get("report_sha256_after_rebind") != chain.get("render_report", {}).get("sha256"):
        fail("render manifest/report closure mismatch")
    diagnostics = report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != FRAMES or diagnostics[0].get("actual_time_s") != 0.0 or diagnostics[-1].get("actual_time_s") != 4.00006189848381:
        fail("render diagnostics/time endpoints mismatch")
    for row in diagnostics:
        if not isinstance(row, dict) or row.get("finite_positions_active") is not True or row.get("identity_axis_preserved") is not True:
            fail("render finite/identity row mismatch")
        finite = row.get("finite_fields", {})
        if any(finite.get(n, {}).get("finite_active") is not True for n in ("density", "mass", "pressure", "velocity")):
            fail("render finite field row mismatch")

    root = Path(str(publish.get("published_output_root", "")))
    index = {x.get("relative_path"): x for x in publish.get("files_excluding_receipt", []) if isinstance(x, dict)}
    visual = decision.get("visual_evidence", {})
    contacts = visual.get("contacts")
    keys = visual.get("keys")
    if not isinstance(contacts, list) or len(contacts) != 17 or not isinstance(keys, list) or len(keys) != 9:
        fail("visual PNG coverage mismatch")
    if png.get("contacts") != contacts or png.get("keys") != keys:
        fail("PNG evidence sidecar mismatch")
    for i, ref in enumerate(contacts):
        check_png(ref, f"contact_{i:02d}", root, index)
    for frame, ref in zip(KEY_FRAMES, keys):
        if ref.get("relative_path") != f"frames/frame_{frame:04d}.png":
            fail(f"key frame path mismatch {frame}")
        check_png(ref, f"key_{frame:04d}", root, index)
    if png.get("all_paths_stat_checked") is not True or png.get("personally_viewed_after_atomic_publish") is not True or png.get("content_read_or_hashed_by_reviewer") is not False:
        fail("PNG sidecar boundary mismatch")

    visual_review = decision.get("visual_review", {})
    if visual_review.get("status") != "visual-approved-by-delegated-agent" or visual_review.get("screen") != "pass_first_stage":
        fail("visual status mismatch")
    if visual_review.get("contact_sheets_viewed") != 17 or visual_review.get("key_frames_viewed") != list(KEY_FRAMES):
        fail("personal visual coverage mismatch")
    if visual_review.get("scientific_payload_opened_or_hashed_by_reviewer") is not False or visual_review.get("scientific_jobs_started_or_restarted") is not False or visual_review.get("shared_state_modified") is not False:
        fail("scientific/shared boundary mismatch")
    if visual_review.get("case_credit") != 0 or visual_review.get("q_n_granted") is not False or visual_review.get("q_e_granted") is not False:
        fail("visual review grants forbidden credit")

    envelope = decision.get("historical_outer_envelope", {})
    if envelope.get("outer_request_expected_frames") != 801 or envelope.get("outer_request_expected_particles") != 194427:
        fail("old outer envelope was not preserved")
    if envelope.get("actual_loaded_wrapper_expected_frames") != 401 or envelope.get("actual_loaded_wrapper_expected_particles") != 418104:
        fail("actual wrapper authority was not preserved")
    print(json.dumps({"status": "PASS", "fresh": "fresh183", "contacts": 17, "keys": 9, "case_credit": 0}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ValidationError as exc:
        raise SystemExit(f"fresh183 validation failed: {exc}")
