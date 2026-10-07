#!/usr/bin/env python3
"""Fail-closed metadata/stat validator for fresh186."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FORBIDDEN_SUFFIXES = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
CASE = "F3_STAGE1_DP006_P1200_AY0540"
PHYSICAL = "F3_TWOAXIS_P1200_AY0540_STAGE1_FIRST48_PITCH_VARIANT"
CANONICAL = "02c172c6742f50817771e41c6adef8703641b9179dc022859a1ed6a9b2a9b2f3"
FRAMES = 836
PARTICLES = 179208
TIME_WINDOW = [0.0, 8.350014835784549]
KEY_FRAMES = (0, 104, 208, 312, 417, 521, 626, 730, 835)


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
    if not path.is_absolute() or metadata_sha(path, label) != value.get("sha256"):
        fail(f"metadata ref mismatch: {label}")
    return path


def check_receipt(value: Any, label: str, exact_identity: bool = True) -> dict[str, Any]:
    obj = load_json(check_ref(value, label), label)
    if obj.get("status") != "completed" or obj.get("returncode") != 0:
        fail(f"{label} is not completed/0")
    req = obj.get("request")
    if exact_identity and isinstance(req, dict) and (
        req.get("case_id") not in (None, CASE) or req.get("physical_case_id") not in (None, PHYSICAL)
    ):
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
        fail(f"PNG producer stat mismatch: {label}")
    if value.get("declared_sha256") != entry.get("sha256") or value.get("sha256_source") != "render_publish_receipt":
        fail(f"PNG SHA provenance mismatch: {label}")
    if value.get("stat_checked") is not True or value.get("personally_viewed_with_view_image") is not True or value.get("png_bytes_read_or_hashed_by_reviewer") is not False:
        fail(f"PNG review/boundary evidence missing: {label}")


def check_manifest() -> None:
    manifest = load_json(HERE / "package-manifest.json", "package manifest")
    if manifest.get("schema") != "ds02.f3.fresh186.package-manifest.v1" or manifest.get("package_manifest_excluded_from_own_hash") is not True:
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
    decision = load_json(HERE / "metadata/actual1129-personal-visual-decision.json", "visual decision")
    png = load_json(HERE / "metadata/png-evidence/actual1129.json", "PNG evidence")
    if decision.get("schema") != "ds02.f3.fresh186.personal-visual-review.v1" or decision.get("fresh_id") != "fresh186":
        fail("decision schema/fresh mismatch")
    if decision.get("assigned_worktree_family") != "F3" or decision.get("actual_case_family") != "F3":
        fail("family assignment mismatch")
    if decision.get("case_id") != CASE or decision.get("physical_case_id") != PHYSICAL:
        fail("case identity mismatch")
    stamp = decision.get("review_completed_at_utc")
    if not isinstance(stamp, str) or "T" not in stamp or not stamp.endswith("+00:00"):
        fail("review timestamp is not an explicit UTC instant")
    if decision.get("configured_model") != "gpt-5.6-luna/max" or decision.get("model_substitution") is not False or decision.get("recursive_delegation") is not False:
        fail("model/delegation provenance mismatch")

    roles = decision.get("physical_condition_roles", {})
    if roles.get("native_canonical_condition_sha256") != CANONICAL or roles.get("typed_legacy_converter_scope_sha256") != CANONICAL or roles.get("xmf_physical_condition_sha256") != CANONICAL:
        fail("canonical/typed/XMF scope mismatch")
    native = roles.get("native_and_xmf_plan_field_namespaces")
    if not isinstance(native, dict) or native.get("native", {}).get("source_plan_condition_sha256") != {"present": False, "value": None} or native.get("native", {}).get("source_plan_physical_condition_sha256") != {"present": False, "value": None}:
        fail("native plan namespace mask mismatch")
    if native.get("XMF", {}).get("source_plan_condition_sha256") != {"present": True, "value": "5f62205c3ba7074b7e56e88774b092b971cff9e4550ea4814c4ac287272ce075"} or native.get("XMF", {}).get("source_plan_physical_condition_sha256") != {"present": False, "value": None}:
        fail("XMF plan namespace mask mismatch")
    if roles.get("native_source_plan_condition_field") != {"present": False, "value": None} or roles.get("native_source_plan_physical_condition_field") != {"present": False, "value": None}:
        fail("native plan absence role mismatch")
    if roles.get("xmf_source_plan_condition_field") != {"present": True, "value": "5f62205c3ba7074b7e56e88774b092b971cff9e4550ea4814c4ac287272ce075"} or roles.get("xmf_source_plan_physical_condition_field") != {"present": False, "value": None}:
        fail("XMF plan absence role mismatch")
    masks = roles.get("manifest_observed_plan_field_masks", {})
    if masks != {
        "source_plan_condition_sha256": {"present": True, "value": "5f62205c3ba7074b7e56e88774b092b971cff9e4550ea4814c4ac287272ce075"},
        "source_plan_physical_condition_sha256": {"present": False, "value": None},
    }:
        fail("manifest plan field mask/value mismatch")

    dims = decision.get("actual_dimensions", {})
    if dims.get("frames") != FRAMES or dims.get("particles") != PARTICLES or dims.get("vector_shape") != "N x 3" or dims.get("time_window_s") != TIME_WINDOW:
        fail("actual dimensions mismatch")
    limits = decision.get("precision_and_limits", {})
    if limits.get("case_credit") != 0 or limits.get("q_n_granted") is not False or limits.get("q_e_granted") is not False:
        fail("credit/qualification boundary changed")
    visual = decision.get("visual_review", {})
    if visual.get("status") != "visual-approved-by-delegated-agent" or visual.get("contact_sheets_viewed") != 35 or visual.get("key_frames_viewed") != list(KEY_FRAMES):
        fail("visual review cardinality/status mismatch")
    if visual.get("png_files_opened_with_view_image") is not True or visual.get("png_bytes_read_or_hashed_by_reviewer") is not False:
        fail("visual review boundary mismatch")

    chain = decision.get("actual_chain")
    if not isinstance(chain, dict):
        fail("actual chain missing")
    for key, value in chain.items():
        if key.endswith("receipt") or key.endswith("_receipt"):
            check_receipt(value, key, exact_identity=key in {"native_receipt", "typed_receipt", "xmf_receipt", "render_receipt"})
        else:
            check_ref(value, key)

    render_receipt = load_json(check_ref(chain["render_receipt"], "render receipt"), "render receipt")
    render_report = load_json(check_ref(chain["render_report"], "render report"), "render report")
    publish = load_json(check_ref(chain["publish"], "publish receipt"), "publish receipt")
    manifest = load_json(check_ref(chain["XMF_manifest"], "XMF manifest"), "XMF manifest")
    if publish.get("status") != "published_after_atomic_rename" or publish.get("case_id") != CASE or publish.get("attempt_id") != render_receipt.get("request", {}).get("attempt_id"):
        fail("publish/receipt identity mismatch")
    if render_report.get("frames") != FRAMES or render_report.get("source_frames") != FRAMES or render_report.get("all_frames_rendered") is not True or render_report.get("actual_times_preserved_exactly") is not True:
        fail("render report full-time contract mismatch")
    if render_report.get("manifest_sha256") != chain["XMF_manifest"]["sha256"] or publish.get("report_sha256_after_rebind") != chain["render_report"]["sha256"]:
        fail("render/report/XMF SHA binding mismatch")
    diagnostics = render_report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != FRAMES:
        fail("render diagnostics missing")
    actual_times = []
    for i, row in enumerate(diagnostics):
        if not isinstance(row, dict) or row.get("frame") != i or row.get("active") != PARTICLES or row.get("missing") != 0:
            fail(f"frame {i} lifecycle mismatch")
        if row.get("finite_positions_active") is not True or row.get("identity_axis_preserved") is not True:
            fail(f"frame {i} finite/N3 identity mismatch")
        finite = row.get("finite_fields", {})
        if any(not isinstance(finite.get(name), dict) or finite[name].get("finite_active") is not True for name in ("density", "mass", "pressure", "velocity")):
            fail(f"frame {i} finite field mismatch")
        if not isinstance(row.get("actual_time_s"), (int, float)):
            fail(f"frame {i} time missing")
        actual_times.append(float(row["actual_time_s"]))
    if actual_times[0] != TIME_WINDOW[0] or actual_times[-1] != TIME_WINDOW[1] or any(b <= a for a, b in zip(actual_times, actual_times[1:])):
        fail("render time sequence mismatch")
    if manifest.get("case_id") != CASE or manifest.get("physical_case_id") != PHYSICAL or manifest.get("frames") != FRAMES or manifest.get("particles") != PARTICLES:
        fail("XMF identity/dimensions mismatch")
    if manifest.get("physical_condition_sha256") != CANONICAL or manifest.get("actual_converter_scope_sha256") != CANONICAL:
        fail("XMF canonical scope mismatch")
    if manifest.get("source_plan_condition_sha256") != "5f62205c3ba7074b7e56e88774b092b971cff9e4550ea4814c4ac287272ce075" or "source_plan_physical_condition_sha256" in manifest:
        fail("XMF plan namespace fields changed")

    root = Path(str(publish.get("published_output_root", "")))
    index = {x.get("relative_path"): x for x in publish.get("files_excluding_receipt", []) if isinstance(x, dict)}
    evidence = decision.get("visual_evidence", {})
    contacts = evidence.get("contacts")
    keys = evidence.get("keys")
    if not isinstance(contacts, list) or len(contacts) != 35 or not isinstance(keys, list) or [x.get("relative_path") for x in keys] != [f"frames/frame_{n:04d}.png" for n in KEY_FRAMES]:
        fail("PNG evidence cardinality mismatch")
    for i, item in enumerate(contacts):
        check_png(item, f"contact_{i:02d}", root, index)
    for n, item in zip(KEY_FRAMES, keys):
        check_png(item, f"key_{n:04d}", root, index)
    if png.get("case_id") != CASE or png.get("physical_case_id") != PHYSICAL or png.get("personally_viewed_after_atomic_publish_and_own_qi") is not True or png.get("png_bytes_read_or_hashed_by_reviewer") is not False:
        fail("PNG evidence identity/boundary mismatch")
    if len(png.get("contacts", [])) != 35 or len(png.get("keys", [])) != 9:
        fail("PNG evidence count mismatch")
    print("fresh186 validator PASS: F3 P1200/AY0540 completed/0, 836-frame metadata, 35 contacts, 9 keys, native/XMF plan roles preserved")


if __name__ == "__main__":
    main()
