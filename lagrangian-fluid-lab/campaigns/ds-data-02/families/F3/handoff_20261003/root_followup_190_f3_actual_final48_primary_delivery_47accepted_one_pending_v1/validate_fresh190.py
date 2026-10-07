#!/usr/bin/env python3
"""Read-only validator for the F3 47-accepted/one-pending catalog.

JSON metadata is read and SHA-checked.  XML/XMF/PNG references are only
existence/stat checked here; producer-declared PNG digests are validated as
shape only, never recomputed by this source agent.  Scientific payload
suffixes are rejected and no solver/renderer/ledger operation exists.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "F3-ACTUAL-FINAL48-PRIMARY-47ACCEPTED-ONE-PENDING.json"
MANIFEST = HERE / "manifest.json"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
CHECKPOINT = HANDOFF / "ROOT_LIVE_RESUMPTION_CHECKPOINT_317.json"
INDEX = HANDOFF / (
    "root_stage1_source189_actualF5_M110T080_original1159_full801QI_personal43PNG_"
    "native_XMF_canonical_SourceDef_FILE_actual_time_visual_acceptance_1428/"
    "full336-current328-actual-final48-delivery-progress-index.json"
)
OLD_CATALOG = HANDOFF / (
    "root_stage1_source172_F3_final48_actual39_visual_primary_bindings_15_native_"
    "XMF_role_differences_mother_id_absence_351_navigation_keys_nine_pending_1328/"
    "F3-FINAL48-ACTUAL39ACCEPTED-NINEPENDING-PRIMARY-DELIVERY.json"
)
FORBIDDEN = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
EXPECTED_NEW_CASES = {
    "F3_STAGE1_DP006_P0800_AY0360", "F3_STAGE1_DP006_P0800_AY0500",
    "F3_STAGE1_DP006_P0800_AY0570", "F3_STAGE1_DP006_P1200_AY0430",
    "F3_STAGE1_DP006_P1200_AY0540", "F3_STAGE1_DP006_P1200_AY0570",
    "F3_STAGE1_DP006_P1200_AY0640", "F3_STAGE1_DP006_P1000_AY0270",
}


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def read_json(path: Path, label: str) -> Any:
    if path.suffix.lower() != ".json":
        fail(f"non-JSON read attempted: {label}: {path}")
    if not path.is_file():
        fail(f"missing JSON: {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid JSON: {label}: {path}: {exc}")


def sha_json(path: Path, label: str) -> str:
    if path.suffix.lower() != ".json":
        fail(f"non-JSON hash attempted: {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_source_ref(ref: dict[str, Any], label: str) -> Path:
    path = Path(ref["path"])
    if not path.is_file():
        fail(f"missing {label}: {path}")
    declared = ref.get("sha256")
    actual = sha_json(path, label)
    if declared != actual:
        fail(f"source SHA mismatch {label}: {declared} != {actual}")
    return path


def check_ref(ref: Any, label: str, *, json_required: bool = False) -> Path:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        fail(f"{label} is not a path reference")
    path = Path(ref["path"])
    if path.suffix.lower() in FORBIDDEN:
        fail(f"forbidden scientific payload reference in {label}: {path}")
    if not path.is_file():
        fail(f"missing {label}: {path}")
    if json_required or path.suffix.lower() == ".json":
        actual = sha_json(path, label)
        declared = ref.get("sha256")
        if declared is not None and declared != actual:
            fail(f"JSON SHA mismatch {label}: {declared} != {actual}")
    else:
        ref["bytes_stat"] = path.stat().st_size
    return path


def check_identity(
    path: Path,
    family: str,
    case: str | None,
    physical: str | None,
    label: str,
) -> None:
    if path.suffix.lower() != ".json":
        return
    obj = read_json(path, label)
    if not isinstance(obj, dict):
        return
    for container in (obj, obj.get("request") if isinstance(obj.get("request"), dict) else {}, obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}):
        if container.get("family_id") is not None and container.get("family_id") != family:
            fail(f"family identity mismatch in {label}: {container.get('family_id')}")
        if case is not None and container.get("case_id") is not None and container.get("case_id") != case:
            fail(f"case identity mismatch in {label}: {container.get('case_id')} != {case}")
        if physical is not None and container.get("physical_case_id") is not None and container.get("physical_case_id") != physical:
            fail(f"physical identity mismatch in {label}: {container.get('physical_case_id')} != {physical}")


def walk_path_strings(value: Any, label: str = "catalog") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            walk_path_strings(child, f"{label}.{key}")
    elif isinstance(value, list):
        for i, child in enumerate(value):
            walk_path_strings(child, f"{label}[{i}]")
    elif isinstance(value, str) and value.startswith("/") and Path(value).suffix.lower() in FORBIDDEN:
        fail(f"forbidden scientific path in {label}: {value}")


def check_png_list(items: Any, label: str) -> None:
    if not isinstance(items, list):
        fail(f"{label} is not a list")
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            fail(f"{label}[{i}] is not a path dict")
        path = Path(item["path"])
        if path.suffix.lower() != ".png" or not path.is_file():
            fail(f"missing/non-PNG {label}[{i}]: {path}")
        if not isinstance(item.get("bytes_stat"), int) or item["bytes_stat"] != path.stat().st_size:
            fail(f"PNG stat mismatch {label}[{i}]: {path}")
        declared = item.get("producer_declared_sha256")
        if declared is not None and (not isinstance(declared, str) or len(declared) != 64):
            fail(f"invalid producer PNG SHA shape {label}[{i}]")
        if item.get("content_read_or_hashed") is not False:
            fail(f"source agent claims PNG content IO in {label}[{i}]")


def check_json_role_refs(primary: dict[str, Any], case: str, physical: str) -> None:
    roles = primary.get("evidence_refs")
    if not isinstance(roles, dict):
        fail(f"{physical} evidence_refs missing")
    required = ("native_receipts", "typed_reports", "xmf_manifests", "xmf_xml", "render_receipts", "render_reports", "publish_receipts")
    for key in required:
        if not isinstance(roles.get(key), list) or not roles[key]:
            fail(f"{physical} required role is empty: {key}")
    for role, refs in roles.items():
        if not isinstance(refs, list):
            fail(f"{physical} role is not a list: {role}")
        for i, ref in enumerate(refs):
            path = check_ref(ref, f"{physical} {role}[{i}]")
            if path.suffix.lower() == ".json":
                # The genuine parent initial-QA artifact is intentionally a
                # shared two-axis source artifact.  Its case/physical IDs
                # describe that producer, not each derived pitch/forcing
                # case.  Preserve the shared identity boundary while keeping
                # terminal native/typed/XMF/render identities strict.
                if role == "parent_qa":
                    check_identity(path, "F3", None, None, f"{physical} {role}[{i}]")
                elif role in {"original_conversion_receipts", "source_preparation"}:
                    # AY0270's original typed154 receipt is a preserved
                    # running/unknown historical reference and the shared
                    # source-preparation artifact may use their own aliases.
                    # Neither role is used as a completed runtime gate.
                    check_identity(path, "F3", None, None, f"{physical} {role}[{i}]")
                else:
                    check_identity(path, "F3", case, physical, f"{physical} {role}[{i}]")
    # Render/native/XMF receipts must be genuine terminal metadata.  The
    # original conversion receipt for AY0270 is intentionally outside this
    # gate and is checked only as a preserved unknown boundary.
    for role in ("native_receipts", "xmf_receipts", "render_receipts", "publish_receipts"):
        for ref in roles[role]:
            obj = read_json(Path(ref["path"]), f"{physical} {role}")
            status = obj.get("status") or obj.get("published_status")
            if status not in {"completed", "published_after_atomic_rename", "completed0", "success"}:
                fail(f"{physical} {role} is not terminal success: {status}")
            if "returncode" in obj and obj.get("returncode") != 0:
                fail(f"{physical} {role} returncode is not zero")


def validate() -> dict[str, Any]:
    catalog = read_json(CATALOG, "fresh190 catalog")
    cp = read_json(CHECKPOINT, "checkpoint317")
    index = read_json(INDEX, "cp317 current index")
    old = read_json(OLD_CATALOG, "Root1328 catalog")
    manifest = read_json(MANIFEST, "fresh190 manifest")
    if catalog.get("schema") != "ds02.f3.fresh190.actual-final48.primary-delivery.47accepted-one-pending.v1":
        fail("catalog schema mismatch")
    if cp.get("checkpoint") != 317 or cp.get("accepted_per_family", {}).get("F3") != 47:
        fail("checkpoint317/F3=47 boundary mismatch")
    f3 = [r for r in index.get("cases", []) if r.get("family_id") == "F3"]
    accepted_cp = [r for r in f3 if isinstance(r.get("accepted_decision"), dict) and str(r.get("status", "")).startswith("visual-approved")]
    pending_cp = [r for r in f3 if not isinstance(r.get("accepted_decision"), dict)]
    if len(f3) != 48 or len(accepted_cp) != 47 or len(pending_cp) != 1:
        fail(f"cp317 F3 rows mismatch: {len(f3)}/{len(accepted_cp)}/{len(pending_cp)}")
    membership = catalog.get("membership", {})
    first8 = membership.get("frozen_first8_physical_case_ids")
    first24 = membership.get("actual_first24_physical_case_ids")
    final48 = membership.get("registered_final48_physical_case_ids")
    if not (isinstance(first8, list) and isinstance(first24, list) and isinstance(final48, list)):
        fail("membership arrays missing")
    if (len(first8), len(first24), len(final48)) != (8, 24, 48) or not set(first8) <= set(first24) <= set(final48):
        fail("membership subset/count mismatch")
    if {r["physical_case_id"] for r in f3} != set(final48):
        fail("current F3 rows do not equal registered48")
    old_ref = catalog["authoritative_sources"]["root1328_f3_actual39_primary_catalog"]
    old_path = check_source_ref(old_ref, "Root1328 source catalog")
    old_rows = old.get("main_accepted_primary_and_published_navigation_sidecars", [])
    old_ids = {r.get("physical_case_id") for r in old_rows}
    if len(old_rows) != 39:
        fail("Root1328 source does not contain 39 accepted rows")
    expected_new = {r["physical_case_id"] for r in accepted_cp} - old_ids
    if {r["case_id"] for r in accepted_cp if r["physical_case_id"] in expected_new} != EXPECTED_NEW_CASES:
        fail("current eight-row extension differs from requested cases")
    rows = catalog.get("rows")
    if not isinstance(rows, list) or len(rows) != 48:
        fail("catalog rows are not 48")
    if sum(r.get("delivery_status", "").startswith("accepted") for r in rows) != 47:
        fail("catalog accepted count is not 47")
    if sum(r.get("delivery_status", "").startswith("pending") for r in rows) != 1:
        fail("catalog pending count is not 1")
    cp_by_physical = {r["physical_case_id"]: r for r in f3}
    for row in rows:
        physical = row.get("physical_case_id")
        if physical not in cp_by_physical:
            fail(f"unknown F3 physical ID: {physical}")
        if not all(row.get("credit_boundary", {}).get(k) == 0 for k in ("case_credit", "new_visual_credit", "Q_N", "Q_E")):
            fail(f"nonzero credit/Q in {physical}")
        if row.get("membership", {}).get("frozen_first8_member") != (physical in set(first8)):
            fail(f"first8 membership mismatch: {physical}")
        if row.get("membership", {}).get("actual_first24_member") != (physical in set(first24)):
            fail(f"first24 membership mismatch: {physical}")
        if row.get("membership", {}).get("registered_final48_member") is not True:
            fail(f"registered48 membership missing: {physical}")
        cp_row = cp_by_physical[physical]
        if row["delivery_status"].startswith("accepted_visual_inherited"):
            src = row.get("primary_source", {}).get("catalog")
            if not isinstance(src, dict) or src.get("path") != str(old_path):
                fail(f"{physical} does not inherit Root1328 catalog")
            if not isinstance(cp_row.get("accepted_decision"), dict):
                fail(f"inherited accepted row is pending in cp317: {physical}")
        elif row["delivery_status"].startswith("accepted_visual_current"):
            primary = row.get("primary_delivery")
            if not isinstance(primary, dict):
                fail(f"current accepted primary missing: {physical}")
            dref = primary.get("accepted_decision")
            if not isinstance(dref, dict) or dref.get("path") != cp_row["accepted_decision"].get("path") or dref.get("sha256") != cp_row["accepted_decision"].get("sha256"):
                fail(f"{physical} accepted decision is not cp317's own decision")
            dpath = check_ref(dref, f"{physical} accepted decision", json_required=True)
            decision = read_json(dpath, f"{physical} accepted decision")
            if decision.get("family_id") != "F3" or decision.get("physical_case_id") != physical:
                fail(f"{physical} accepted decision identity mismatch")
            qi = primary.get("own_full836_QI")
            qpath = check_ref(qi, f"{physical} own QI", json_required=True)
            check_identity(qpath, "F3", row["case_id"], physical, f"{physical} own QI")
            check_json_role_refs(primary, row["case_id"], physical)
            check_png_list(primary.get("contact_png_refs"), f"{physical} contacts")
            check_png_list(primary.get("key_png_refs"), f"{physical} keys")
            if primary.get("png_evidence_boundary", {}).get("source_agent_did_not_read_or_hash_png_bytes") is not True:
                fail(f"{physical} PNG boundary is not closed")
            if primary.get("scope_roles", {}).get("source_plan_or_native_field_absence_is_not_filled") is not True:
                fail(f"{physical} scope absence policy missing")
            if primary.get("typed_completion_boundary", {}).get("native_typed_xmf_render_roles_are_not_reconciled") is not True:
                fail(f"{physical} role separation missing")
        elif row["delivery_status"].startswith("pending"):
            if isinstance(cp_row.get("accepted_decision"), dict):
                fail(f"pending catalog row is accepted in cp317: {physical}")
            pending = row.get("pending_metadata", {})
            if pending.get("accepted_decision") is not None or pending.get("primary_particle_xmf_render_refs") is not None:
                fail(f"pending row has primary/accepted refs: {physical}")
            if pending.get("personal_visual_review") is not False or pending.get("visual_credit") != 0:
                fail(f"pending visual boundary failed: {physical}")
        else:
            fail(f"unknown delivery status: {row.get('delivery_status')}")
    pending_id = pending_cp[0]["physical_case_id"]
    if pending_id != "F3_TWOAXIS_P1200_AY0390_STAGE1_FIRST48_PITCH_VARIANT":
        fail(f"unexpected pending F3 case: {pending_id}")
    walk_path_strings(catalog)
    expected_files = set(manifest.get("files", []))
    actual_files = {p.name for p in HERE.iterdir() if p.is_file() and p.name != "manifest.json"}
    if not expected_files - {"manifest.json"} <= actual_files | {"manifest.json"}:
        fail("package manifest lists missing files")
    if manifest.get("manifest_self_hash_excluded") is not True:
        fail("manifest self-hash boundary missing")
    return {
        "status": "PASS",
        "schema": catalog["schema"],
        "checkpoint": 317,
        "f3_rows": 48,
        "accepted": 47,
        "pending": 1,
        "new_current_cp317_cases": sorted(EXPECTED_NEW_CASES),
        "frozen_first8": 8,
        "actual_first24": 24,
        "registered_final48": 48,
        "scientific_payload_opened_or_hashed": False,
        "png_bytes_opened_or_hashed": False,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(validate(), sort_keys=True))
    except ValidationError as exc:
        print(f"fresh190 validation FAILED: {exc}")
        raise SystemExit(1)
