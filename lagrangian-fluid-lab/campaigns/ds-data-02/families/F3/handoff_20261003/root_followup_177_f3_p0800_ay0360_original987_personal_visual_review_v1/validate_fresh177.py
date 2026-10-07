#!/usr/bin/env python3
"""Read-only validator for the fresh177 F3 visual review.

JSON/XML metadata is read and hashed.  PNGs are only checked with ``stat``;
their digests must be the publisher-declared values.  Scientific payloads
are rejected before any open/hash operation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FORBIDDEN_SUFFIXES = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
KEY_FRAMES = (0, 100, 200, 300, 400, 500, 600, 700, 835)


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
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        fail(f"scientific payload hash attempted: {label}: {path}")
    if path.suffix.lower() not in {".json", ".xml", ".xmf", ".py", ".md"}:
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
    obj = load_json(path, label)
    if obj.get("status") != "completed" or obj.get("returncode") != 0:
        fail(f"{label} is not completed/0")
    return obj


def validate_manifest() -> None:
    manifest_path = HERE / "package-manifest.json"
    manifest = load_json(manifest_path, "package manifest")
    if manifest.get("schema") != "ds02.f3.fresh177.package-manifest.v1":
        fail("package manifest schema mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        fail("package manifest has no files")
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            fail("malformed package manifest entry")
        path = HERE / entry["path"]
        if not path.is_file():
            fail(f"missing package file: {path}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            fail(f"scientific payload in package: {path}")
        expected = entry.get("sha256")
        if not isinstance(expected, str):
            fail(f"missing package file SHA: {path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            fail(f"package file SHA mismatch: {path}")


def main() -> None:
    validate_manifest()
    decision_path = HERE / "metadata/actual987-personal-visual-decision.json"
    png_path = HERE / "metadata/png-evidence/actual987.json"
    decision = load_json(decision_path, "visual decision")
    png_evidence = load_json(png_path, "PNG evidence")
    if decision.get("schema") != "ds02.f3.fresh177.personal-visual-review.v1":
        fail("decision schema mismatch")
    if decision.get("fresh_id") != "fresh177":
        fail("fresh ID mismatch")
    if decision.get("case_id") != "F3_STAGE1_DP006_P0800_AY0360":
        fail("case ID mismatch")
    if decision.get("physical_case_id") != "F3_TWOAXIS_P0800_AY0360_STAGE1_FIRST48_PITCH_VARIANT":
        fail("physical case ID mismatch")
    roles = decision.get("physical_condition_roles", {})
    if roles.get("native_request_condition_sha256") != "7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5":
        fail("canonical condition mismatch")
    fields = roles.get("native_and_xmf_plan_fields", {})
    for name in (
        "native_source_plan_condition_sha256",
        "native_source_plan_physical_condition_sha256",
        "xmf_source_plan_condition_sha256",
        "xmf_source_plan_physical_condition_sha256",
    ):
        if fields.get(name) != {"present": False, "value": None}:
            fail(f"plan field was normalized or backfilled: {name}")

    chain = decision.get("actual_chain", {})
    for role in ("native", "typed", "xmf", "render"):
        receipt = chain[role] if role == "native" else chain[role]["receipt"]
        check_receipt(receipt, f"{role} receipt")
    for label in ("conversion_report", "manifest", "xml", "report", "atomic_publish"):
        if label == "conversion_report":
            check_ref(chain["typed"][label], label, json_only=True)
        elif label in {"manifest", "report", "atomic_publish"}:
            check_ref(chain["xmf"][label] if label == "manifest" else chain["render"][label], label, json_only=True)
        else:
            check_ref(chain["xmf"][label], label, json_only=False)

    qi_ref = decision["provenance"]["qi_proof"]
    qi_path = check_ref(qi_ref, "Root1355 QI proof", json_only=True)
    qi = load_json(qi_path, "Root1355 QI proof")
    if qi.get("all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified") is not True:
        fail("Root1355 QI does not attest full N3/finite/time verification")
    if qi.get("all_native_UIds_active_each_frame") is not True:
        fail("Root1355 QI does not attest active UID lifecycle")
    if qi.get("visual_status") != "pending delegated personal35contacts9keys":
        fail("QI provenance unexpectedly changed")

    render_report_path = check_ref(chain["render"]["report"], "render report", json_only=True)
    render_report = load_json(render_report_path, "render report")
    if render_report.get("frames") != 836 or render_report.get("source_frames") != 836:
        fail("render report frame count mismatch")
    diagnostics = render_report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != 836:
        fail("render report diagnostic count mismatch")
    expected_counts = {"fixed": 111708, "fluid": 67500, "moving": 0, "floating": 0, "unknown": 0}
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict) or diagnostic.get("active") != 179208 or diagnostic.get("missing") != 0:
            fail("render report active/missing counts are not stable")
        if diagnostic.get("type_counts_active") != expected_counts:
            fail("render report type partition differs from actual producer metadata")
    dimensions = decision.get("actual_dimensions", {})
    if dimensions.get("frames") != 836 or dimensions.get("particles") != 179208:
        fail("decision dimensions are not actual 836/179208")
    for field, expected in (("fixed", 111708), ("fluid", 67500), ("moving", 0), ("floating", 0)):
        if dimensions.get(field) != expected:
            fail(f"decision {field} count is not producer-observed")
    contacts = render_report.get("outputs", {}).get("contact_sheets")
    if not isinstance(contacts, list) or len(contacts) != 35:
        fail("render report contact count mismatch")
    publish_path = check_ref(chain["render"]["atomic_publish"], "publish receipt", json_only=True)
    publish = load_json(publish_path, "publish receipt")
    if publish.get("status") != "published_after_atomic_rename":
        fail("publish status mismatch")
    root = Path(publish["published_output_root"])
    entries = publish.get("files_excluding_receipt")
    index = {e.get("relative_path"): e for e in entries if isinstance(e, dict)}

    evidence = decision.get("visual_evidence", {})
    contact_refs = evidence.get("contacts")
    key_refs = evidence.get("keys")
    if not isinstance(contact_refs, list) or len(contact_refs) != 35:
        fail("decision contact evidence count mismatch")
    if not isinstance(key_refs, list) or [int(Path(r["relative_path"]).stem.split("_")[-1]) for r in key_refs] != list(KEY_FRAMES):
        fail("decision key evidence indices mismatch")
    if png_evidence.get("contacts") != contact_refs or png_evidence.get("keys") != key_refs:
        fail("PNG sidecar and decision differ")

    for refs, label in ((contact_refs, "contact"), (key_refs, "key")):
        for ref in refs:
            path = Path(ref["path"])
            if path.suffix.lower() != ".png" or not path.is_file():
                fail(f"missing {label} PNG: {path}")
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                fail(f"{label} PNG escapes published root: {path}")
            entry = index.get(relative)
            if not isinstance(entry, dict):
                fail(f"{label} PNG absent from publish receipt: {relative}")
            if path.stat().st_size != entry.get("bytes") or ref.get("bytes") != entry.get("bytes"):
                fail(f"{label} PNG stat differs from publish receipt: {relative}")
            if ref.get("declared_sha256") != entry.get("sha256"):
                fail(f"{label} PNG digest is not the producer-declared digest: {relative}")
            if ref.get("sha256_source") != "render_publish_receipt":
                fail(f"{label} PNG digest source is not publisher receipt: {relative}")
            if ref.get("personally_viewed_with_view_image") is not True:
                fail(f"{label} PNG is not recorded as personally viewed: {relative}")
    visual = decision.get("visual_review", {})
    if visual.get("status") != "visual-approved-by-delegated-agent" or visual.get("screen") != "pass_first_stage":
        fail("visual decision is not the requested first-stage delegated status")
    if visual.get("contact_sheets_viewed") != 35 or visual.get("key_frames_viewed") != list(KEY_FRAMES):
        fail("visual viewed counts mismatch")
    if visual.get("scientific_payload_opened_or_hashed_by_reviewer") is not False:
        fail("scientific payload boundary is not explicit")
    if visual.get("new_case_credit") != 0 or visual.get("q_n_granted") is not False or visual.get("q_e_granted") is not False:
        fail("visual review incorrectly grants qualification or credit")
    envelope = decision.get("historical_outer_envelope", {})
    if envelope.get("outer_request_expected_frames") != 801 or envelope.get("actual_loaded_wrapper_frames") != 836:
        fail("outer envelope distinction lost")
    print(json.dumps({"status": "PASS", "fresh": "fresh177", "contacts": 35, "keys": 9, "case_credit": 0}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ValidationError as exc:
        raise SystemExit(f"fresh177 validation failed: {exc}")
