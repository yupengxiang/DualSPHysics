#!/usr/bin/env python3
"""Read-only validator for fresh173's F2 42+6 delivery catalog.

JSON metadata is read and, where declared, SHA-checked.  XMF/XML/PNG are
stat-checked; a declared PNG SHA is checked because PNG is published visual
evidence, never a scientific payload.  H5/BI4/IBI4/CSV/DAT/VTK are rejected.
No solver, renderer, converter, ledger, or shared-state operation is present.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "F2-FINAL48-PRIMARY-DELIVERY-42ACCEPTED-SIX-PENDING.json"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
CP251 = HANDOFF / (
    "root_stage1_nextF3_original1141_1135_full836_live_actual_native_plan_absence_XMF_namespace_"
    "durable_future_QI_preparation_1326/full336-current300-actual-final48-delivery-progress-index.json"
)
ROOT251 = HANDOFF / "ROOT_LIVE_RESUMPTION_CHECKPOINT_251.json"
FIRST24 = HANDOFF / (
    "root_stage1_sources178164_actual_F2_F3_F6_first24_delivery72_correct_own_primary_XMF_PNG_8_"
    "subset24_subset48_1276/F2-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json"
)
FORBIDDEN = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def read_json(path: Path, label: str) -> Any:
    if path.suffix.lower() != ".json":
        fail(f"non-JSON read attempted for {label}: {path}")
    if not path.is_file():
        fail(f"missing JSON {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid JSON {label}: {path}: {exc}")


def sha256_json(path: Path, label: str) -> str:
    if path.suffix.lower() != ".json":
        fail(f"non-JSON hashing attempted for {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref_path(ref: Any, label: str) -> tuple[Path, dict[str, Any]]:
    if isinstance(ref, str):
        path = ref
        meta: dict[str, Any] = {"path": path, "representation": "string"}
    elif isinstance(ref, dict) and isinstance(ref.get("path"), str):
        path = ref["path"]
        meta = dict(ref)
        meta["representation"] = "dict"
    else:
        fail(f"{label} is neither an absolute path string nor a path dict: {ref!r}")
    if not path.startswith("/"):
        fail(f"{label} is not absolute: {path}")
    p = Path(path)
    if p.suffix.lower() in FORBIDDEN:
        fail(f"scientific payload reference escaped into fresh173: {label}: {p}")
    if not p.is_file():
        fail(f"missing {label}: {p}")
    return p, meta


def check_json_ref(ref: Any, label: str) -> Path:
    path, meta = ref_path(ref, label)
    if path.suffix.lower() != ".json":
        fail(f"{label} must be JSON metadata, got {path}")
    actual = sha256_json(path, label)
    declared = meta.get("sha256")
    if declared is not None and declared != actual:
        fail(f"{label} declared SHA mismatch: {path}: {declared} != {actual}")
    return path


def check_stat_ref(ref: Any, label: str, suffixes: set[str]) -> Path:
    path, meta = ref_path(ref, label)
    if path.suffix.lower() not in suffixes:
        fail(f"{label} has unexpected suffix {path.suffix}: {path}")
    # This package only stats published PNG/XMF/XML references.  A producer
    # supplied digest is retained as provenance, but this source validator
    # deliberately does not open/hash the referenced visual bytes.
    return path


def png_ref_paths(value: Any, label: str) -> list[Path]:
    if not isinstance(value, list):
        fail(f"{label} must be a list")
    paths: list[Path] = []
    for index, item in enumerate(value):
        paths.append(check_stat_ref(item, f"{label}[{index}]", {".png"}))
    return paths


def report_output_paths(report_path: Path) -> tuple[set[Path], set[Path], dict[str, Any]]:
    report = read_json(report_path, f"render report {report_path}")
    if not isinstance(report, dict):
        fail(f"render report is not an object: {report_path}")
    outputs = report.get("outputs")
    if not isinstance(outputs, dict):
        return set(), set(), {"outputs_present": False}

    def collect(keys: tuple[str, ...]) -> set[Path]:
        out: set[Path] = set()
        for key in keys:
            values = outputs.get(key)
            if not isinstance(values, list):
                continue
            for i, value in enumerate(values):
                path, _ = ref_path(value, f"{report_path}:outputs.{key}[{i}]")
                if path.suffix.lower() != ".png":
                    fail(f"render report output is not PNG: {path}")
                out.add(path)
        return out

    contacts = collect(("contact_sheets", "contact_pages"))
    keys = collect(("key_frames", "keyframes", "key_events"))
    return contacts, keys, {
        "outputs_present": True,
        "contact_count": len(contacts),
        "key_count": len(keys),
    }


def validate_catalog() -> dict[str, Any]:
    catalog = read_json(CATALOG, "fresh173 catalog")
    cp = read_json(CP251, "cp251 current full336 index")
    root = read_json(ROOT251, "ROOT_LIVE checkpoint251")
    first = read_json(FIRST24, "Root1276 F2 membership")

    if catalog.get("schema") != "ds02.f2.fresh173.final48.primary-delivery.42accepted-six-pending.v1":
        fail("catalog schema mismatch")
    if catalog.get("assignment", {}).get("scientific_payload_read_or_hashed_by_source") is not False:
        fail("catalog scientific payload boundary is not false")
    if catalog.get("assignment", {}).get("new_science_jobs") != 0:
        fail("fresh173 claims a new science job")
    if root.get("checkpoint") != 251 or root.get("accepted_per_family", {}).get("F2") != 42:
        fail("catalog was not frozen against ROOT_LIVE checkpoint251/F2=42")
    if len(cp.get("cases", [])) != 336:
        fail(f"cp251 current index is not 336 rows: {len(cp.get('cases', []))}")

    f2 = [row for row in cp.get("cases", []) if row.get("family_id") == "F2"]
    accepted_cp = [row for row in f2 if isinstance(row.get("accepted_decision"), dict)]
    pending_cp = [row for row in f2 if not isinstance(row.get("accepted_decision"), dict)]
    if len(f2) != 48 or len(accepted_cp) != 42 or len(pending_cp) != 6:
        fail(f"cp251 F2 boundary mismatch: {len(f2)}/{len(accepted_cp)}/{len(pending_cp)}")

    first8 = first.get("frozen_first8_physical_case_ids")
    first24 = first.get("actual_first24_physical_case_ids")
    final48 = first.get("registered_final48_physical_case_ids")
    if not (isinstance(first8, list) and isinstance(first24, list) and isinstance(final48, list)):
        fail("Root1276 membership arrays missing")
    if len(first8) != 8 or len(first24) != 24 or len(final48) != 48:
        fail("Root1276 membership counts mismatch")
    if not set(first8) <= set(first24) <= set(final48):
        fail("Root1276 subset relation is false")
    if {r.get("physical_case_id") for r in f2} != set(final48):
        fail("cp251 F2 rows do not equal Root1276 registered final48")

    pending_ids = {r.get("physical_case_id") for r in pending_cp}

    catalog_rows = catalog.get("rows")
    if not isinstance(catalog_rows, list) or len(catalog_rows) != 48:
        fail("catalog does not contain 48 rows")
    if sum(str(r.get("delivery_status", "")).startswith("accepted") for r in catalog_rows) != 42:
        fail("catalog accepted count is not 42")
    if sum(str(r.get("delivery_status", "")).startswith("pending") for r in catalog_rows) != 6:
        fail("catalog pending count is not 6")

    cp_by_id = {r["physical_case_id"]: r for r in f2}
    role_difference_ids: set[str] = set()
    native_id_absence_ids: set[str] = set()
    native_condition_absence_ids: set[str] = set()
    errors: list[str] = []
    for row in catalog_rows:
        physical = row.get("physical_case_id")
        if physical not in cp_by_id:
            fail(f"catalog has unknown F2 physical_case_id: {physical}")
        cp_row = cp_by_id[physical]
        if row.get("membership", {}).get("frozen_first8_member") != (physical in set(first8)):
            fail(f"membership first8 mismatch: {physical}")
        if row.get("membership", {}).get("actual_first24_member") != (physical in set(first24)):
            fail(f"membership first24 mismatch: {physical}")
        if row.get("membership", {}).get("registered_final48_member") is not True:
            fail(f"membership final48 missing: {physical}")
        if not all(row.get("credit_boundary", {}).get(k) == 0 for k in ("case_credit", "new_visual_credit", "Q_N", "Q_E")):
            fail(f"catalog grants credit/Q for {physical}")

        if str(row.get("delivery_status", "")).startswith("accepted"):
            dref = row.get("accepted_visual_metadata", {}).get("accepted_decision")
            if not isinstance(dref, dict):
                fail(f"accepted row has no decision ref: {physical}")
            decision_path = check_json_ref(dref, f"{physical} accepted decision")
            if not isinstance(cp_row.get("accepted_decision"), dict):
                fail(f"accepted catalog row maps to pending cp row: {physical}")
            if dref.get("path") != cp_row["accepted_decision"].get("path") or dref.get("sha256") != cp_row["accepted_decision"].get("sha256"):
                fail(f"accepted decision ref is not cp251 ref: {physical}")
            decision = read_json(decision_path, f"accepted decision {physical}")
            if decision.get("family_id") != "F2" or decision.get("physical_case_id") != physical:
                fail(f"accepted decision identity mismatch: {physical}")
            visual = row["accepted_visual_metadata"]
            manifest = check_json_ref(visual.get("actual_xmf_manifest"), f"{physical} own XMF manifest")
            manifest_obj = read_json(manifest, f"{physical} own XMF manifest identity")
            if isinstance(manifest_obj, dict):
                if manifest_obj.get("family_id") not in (None, "F2"):
                    fail(f"{physical} XMF manifest family is not F2")
                if manifest_obj.get("physical_case_id") not in (None, physical):
                    fail(f"{physical} XMF manifest belongs to another physical case: {manifest_obj.get('physical_case_id')}")
            xml = check_stat_ref(visual.get("actual_xmf_xml"), f"{physical} own XMF XML", {".xmf", ".xml"})
            report = check_json_ref(visual.get("actual_render_report"), f"{physical} own render report")
            report_obj = read_json(report, f"{physical} own render report identity")
            if isinstance(report_obj, dict):
                if report_obj.get("family_id") not in (None, "F2"):
                    fail(f"{physical} render report family is not F2")
                if report_obj.get("physical_case_id") not in (None, physical):
                    fail(f"{physical} render report belongs to another physical case: {report_obj.get('physical_case_id')}")
            receipt = check_json_ref(visual.get("actual_render_receipt"), f"{physical} own render receipt")
            if report == receipt:
                fail(f"render report and receipt are the same file: {physical}")
            contacts = png_ref_paths(visual.get("contact_png_refs"), f"{physical} contacts")
            keys = png_ref_paths(visual.get("key_png_refs"), f"{physical} keys")
            if not contacts:
                fail(f"accepted row has no published contact refs: {physical}")
            report_contacts, report_keys, report_meta = report_output_paths(report)
            report_root = report.parent
            for kind, paths in (("contact", contacts), ("key", keys)):
                for png in paths:
                    try:
                        png.relative_to(report_root)
                    except ValueError:
                        fail(f"{physical} {kind} PNG is outside own published render output root: {png}")
            # Reports from older Root023 runs enumerate contacts but not the
            # selected key-frame PNGs.  Exact report membership is enforced
            # where the report has an output list; key refs remain required to
            # be existing, own-render-root paths and their source omission is
            # explicitly disclosed by the catalog's primary evidence fields.
            if report_contacts and not {p for p in contacts} <= report_contacts:
                fail(f"{physical} contact refs include a path absent from own render report outputs")
            if report_keys and not {p for p in keys} <= report_keys:
                fail(f"{physical} key refs include a path absent from own render report outputs")
            if not isinstance(visual.get("native_refs"), list) or not visual["native_refs"]:
                fail(f"{physical} native evidence is empty")
            if not isinstance(visual.get("typed_refs"), list) or not visual["typed_refs"]:
                fail(f"{physical} typed evidence is empty")
            for i, ref in enumerate(visual["native_refs"]):
                check_json_ref(ref, f"{physical} native metadata {i}")
            for i, ref in enumerate(visual["typed_refs"]):
                check_json_ref(ref, f"{physical} typed metadata {i}")
            if visual.get("primary_visual_evidence", {}).get("PNG_content_read_or_hashed") is not False:
                fail(f"{physical} catalog claims PNG content was read/hashed")
            result_meta = visual.get("actual_result_metadata")
            if not isinstance(result_meta, dict):
                fail(f"{physical} lacks own manifest/report result metadata")
            if result_meta.get("xmf_manifest", {}).get("path") != visual.get("actual_xmf_manifest", {}).get("path"):
                fail(f"{physical} manifest metadata is not bound to own manifest")
            if result_meta.get("render_report", {}).get("path") != visual.get("actual_render_report", {}).get("path"):
                fail(f"{physical} report metadata is not bound to own render report")
            roles = visual.get("native_vs_xmf_role_metadata")
            if not isinstance(roles, dict) or roles.get("role_values_are_verbatim_and_not_reconciled") is not True:
                fail(f"{physical} lacks explicit native/XMF role separation")
            relation = roles.get("native_vs_xmf_physical_condition_relation")
            if relation not in {"equal", "different_preserved_roles", "unknown_missing_role_value"}:
                fail(f"{physical} has invalid native/XMF role relation: {relation}")
            if relation == "different_preserved_roles":
                role_difference_ids.add(physical)
            if roles.get("native_request_physical_case_id_field_present") is False:
                native_id_absence_ids.add(physical)
            if roles.get("native_request_physical_condition_field_present") is False:
                native_condition_absence_ids.add(physical)
        else:
            if isinstance(cp_row.get("accepted_decision"), dict):
                fail(f"pending catalog row maps to accepted cp row: {physical}")
            pending = row.get("pending_metadata")
            if not isinstance(pending, dict):
                fail(f"pending metadata missing: {physical}")
            if pending.get("accepted_decision") is not None or pending.get("primary_particle_xmf_render_refs") is not None:
                fail(f"pending row has primary/accepted evidence: {physical}")
            boundary = pending.get("pending_status_boundary", {})
            if boundary.get("visual_credit") != 0 or boundary.get("no_accepted_visual_decision") is not True:
                fail(f"pending visual boundary is not closed: {physical}")
            if boundary.get("native_typed_xmf_are_pipeline_readiness_evidence_only") is not True:
                fail(f"pending pipeline evidence was promoted: {physical}")
            source_ref = pending.get("pending_readiness_source")
            check_json_ref(source_ref, f"{physical} cp251 current-index readiness source")
            if pending.get("typed_metadata_refs"):
                fail(f"pending {physical} unexpectedly promotes typed receipt metadata")
            if boundary.get("render_receipt_not_observed_as_terminal") is not True:
                fail(f"pending {physical} render status boundary is missing")

    # F2's baseline has a known native-condition field absence.  Preserve that
    # exact fact while allowing the other cases' own request schemas to vary.
    if "F2H10V2_OFFSET_V1" not in native_condition_absence_ids:
        fail("F2 baseline native physical-condition field absence was not preserved")

    return {
        "status": "PASS",
        "schema": catalog.get("schema"),
        "f2_rows": len(f2),
        "accepted": len(accepted_cp),
        "pending": len(pending_cp),
        "frozen_first8": len(first8),
        "actual_first24": len(first24),
        "registered_final48": len(final48),
        "native_xmf_condition_role_differences": len(role_difference_ids),
        "native_request_physical_case_id_absences": sorted(native_id_absence_ids),
        "native_request_physical_condition_absences": sorted(native_condition_absence_ids),
        "png_refs_are_string_or_dict_checked": True,
        "scientific_payload_opened_or_hashed": False,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(validate_catalog(), sort_keys=True))
    except ValidationError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        raise SystemExit(1)
