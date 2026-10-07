#!/usr/bin/env python3
"""Assemble the F3 47-accepted/one-pending primary delivery from frozen metadata.

The 39 already accepted rows remain case-local references to the immutable
Root1328 product.  The eight later accepted rows are rebuilt from their own
cp317 progress rows and accepted decisions, with explicit native/typed/XMF/
render roles.  JSON metadata is read and checked; XML/XMF/PNG references are
stat-checked.  H5, BI4, IBI4, CSV, DAT, VTK and solver data are never opened or
hashed, and this script does not launch work or write shared state.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
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
CATALOG = HERE / "F3-ACTUAL-FINAL48-PRIMARY-47ACCEPTED-ONE-PENDING.json"
MANIFEST = HERE / "manifest.json"
SCHEMA = "ds02.f3.fresh190.actual-final48.primary-delivery.47accepted-one-pending.v1"
FORBIDDEN = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
EXPECTED_NEW_CASES = {
    "F3_STAGE1_DP006_P0800_AY0360",
    "F3_STAGE1_DP006_P0800_AY0500",
    "F3_STAGE1_DP006_P0800_AY0570",
    "F3_STAGE1_DP006_P1200_AY0430",
    "F3_STAGE1_DP006_P1200_AY0540",
    "F3_STAGE1_DP006_P1200_AY0570",
    "F3_STAGE1_DP006_P1200_AY0640",
    "F3_STAGE1_DP006_P1000_AY0270",
}


def die(message: str) -> None:
    raise RuntimeError(message)


def read_json(path: Path, label: str) -> Any:
    if path.suffix.lower() != ".json":
        die(f"non-JSON read attempted for {label}: {path}")
    if not path.is_file():
        die(f"missing {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"invalid JSON {label}: {path}: {exc}")


def sha_json(path: Path, label: str) -> str:
    if path.suffix.lower() != ".json":
        die(f"non-JSON hash attempted for {label}: {path}")
    if not path.is_file():
        die(f"missing JSON for {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_ref(path: Path, label: str) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha_json(path, label), "role": "authoritative_json_source"}


def scalar_metadata(obj: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "status", "returncode", "returncode_field_present", "attempt_id", "finished_at_utc",
        "frames", "expected_frames", "particles", "expected_particles", "published_status",
        "schema", "family_id", "case_id", "physical_case_id", "physical_condition_sha256",
    ):
        if key in obj and isinstance(obj[key], (str, int, float, bool, type(None))):
            out[key] = obj[key]
    return out


def normalize_ref(value: Any, source_key: str, role: str) -> dict[str, Any] | None:
    if isinstance(value, str):
        path = value
        declared: str | None = None
        extra: dict[str, Any] = {}
    elif isinstance(value, dict) and isinstance(value.get("path"), str):
        path = value["path"]
        declared = value.get("sha256") if isinstance(value.get("sha256"), str) else None
        extra = {k: value[k] for k in ("status", "returncode", "returncode_field_present", "attempt_id", "finished_at_utc", "role") if k in value}
    else:
        return None
    if not path.startswith("/"):
        return None
    suffix = Path(path).suffix.lower()
    if suffix in FORBIDDEN:
        die(f"scientific payload reference escaped catalog: {source_key}: {path}")
    out: dict[str, Any] = {"path": path, "source_key": source_key, "role": role}
    if declared:
        out["sha256"] = declared
    out.update(extra)
    return out


def enrich_ref(ref: dict[str, Any], label: str) -> dict[str, Any]:
    """Read/hash JSON metadata only; stat XML/XMF/PNG references."""
    out = copy.deepcopy(ref)
    path = Path(out["path"])
    out["path_exists"] = path.is_file()
    if not path.is_file():
        die(f"missing {label}: {path}")
    out["bytes_stat"] = path.stat().st_size
    if path.suffix.lower() == ".json":
        actual = sha_json(path, label)
        declared = out.get("sha256")
        if declared is not None and declared != actual:
            die(f"declared JSON SHA mismatch for {label}: {path}: {declared} != {actual}")
        out["content_read_or_hashed"] = True
        obj = read_json(path, label)
        if isinstance(obj, dict):
            out["metadata"] = scalar_metadata(obj)
        out["json_sha256"] = actual
    else:
        out["content_read_or_hashed"] = False
    return out


def dedup_refs(refs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = (ref.get("path", ""), ref.get("role", ""))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def explicit_refs(value: Any, aliases: tuple[str, ...], role: str, label: str) -> list[dict[str, Any]]:
    """Collect explicitly named role keys, prioritizing the evidence object.

    This deliberately does not select arbitrary nested path strings.  Nested
    ``actual_completed_receipts`` and role objects are searched only after the
    evidence object's named keys, preventing owner/source-plan aliases from
    becoming primary receipts.
    """
    found: list[dict[str, Any]] = []
    seen_nodes: set[int] = set()

    def visit(node: Any, node_label: str, depth: int) -> None:
        if depth > 4 or not isinstance(node, dict) or id(node) in seen_nodes:
            return
        seen_nodes.add(id(node))
        for alias in aliases:
            if alias in node:
                ref = normalize_ref(node[alias], f"{node_label}.{alias}", role)
                if ref is not None:
                    found.append(ref)
        # Only role-bearing containers are eligible for fallback recursion.
        for key in ("actual_completed_receipts", "native", "typed", "xmf", "render", "evidence"):
            child = node.get(key)
            if isinstance(child, dict):
                visit(child, f"{node_label}.{key}", depth + 1)

    visit(value, label, 0)
    return dedup_refs(found)


def first_ref(value: Any, aliases: tuple[str, ...], role: str, label: str) -> dict[str, Any] | None:
    refs = explicit_refs(value, aliases, role, label)
    return refs[0] if refs else None


def normalize_png_list(value: Any, source_key: str, role: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for i, item in enumerate(value):
        ref = normalize_ref(item, f"{source_key}[{i}]", role)
        if ref is None:
            continue
        path = Path(ref["path"])
        if path.suffix.lower() != ".png":
            die(f"non-PNG visual ref {source_key}[{i}]: {path}")
        if not path.is_file():
            die(f"missing published PNG {path}")
        ref["bytes_stat"] = path.stat().st_size
        # This value is copied from an immutable producer decision/receipt; the
        # source agent intentionally does not read or hash PNG bytes.
        if "sha256" in ref:
            ref["producer_declared_sha256"] = ref.pop("sha256")
        ref["content_read_or_hashed"] = False
        out.append(ref)
    return out


def compact_index_row(row: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "family_id", "case_id", "physical_case_id", "status", "case_credit", "new_case_credit",
        "declared_render_request_condition_sha256", "declared_actual_converter_scope_sha256",
        "expected_frames", "expected_contact_sheets", "expected_particles", "precision_status",
        "latest_registered_render_request", "accepted_decision", "actual_full836_QI",
        "current_main_previsual_QI", "current_actual_render_receipt", "current_atomic_publish_receipt",
        "native_request_scope", "F3_source147_raw_scope_fields_preserved",
        "current_controller_observation", "actual_wrapper_contract_and_live_observation",
        "original_index_expected_fields_preserved", "actual_native_XMF_plan_field_namespaces",
    )
    out: dict[str, Any] = {}
    for key in keep:
        if key in row:
            out[key] = copy.deepcopy(row[key])
    return out


def actual_role_refs(decision: dict[str, Any], physical: str) -> dict[str, Any]:
    evidence = decision.get("actual_completed_metadata_evidence")
    if not isinstance(evidence, dict):
        die(f"missing actual_completed_metadata_evidence: {physical}")
    role_defs = {
        "native_receipts": (("native_receipt", "actual_native_receipt", "full_native_receipt"), "native_receipt"),
        "typed_receipts": (("typed_receipt", "actual_typed_receipt", "typed_conversion_receipt"), "typed_receipt"),
        "original_conversion_receipts": (("original_conversion_receipt", "typed_source_solver_receipt"), "original_or_historical_typed_receipt"),
        "typed_reports": (("typed_report", "actual_producer_conversion_report", "conversion_report"), "typed_report"),
        "artifact_audit": (("actual_artifact_audit_receipt", "artifact_audit_receipt", "actual_artifact_audit_report", "artifact_audit_report"), "artifact_audit"),
        "xmf_receipts": (("xmf_receipt", "XMF_receipt", "actual_XMF_receipt"), "xmf_receipt"),
        "xmf_manifests": (("xmf_manifest", "XMF_manifest", "actual_XMF_manifest", "actual_xmf_manifest"), "xmf_manifest"),
        "xmf_xml": (("xmf_xml", "XMF_XML", "actual_XMF_XML", "actual_xmf_xml"), "xmf_xml"),
        "render_receipts": (("render_receipt", "actual_render_receipt"), "render_receipt"),
        "render_reports": (("render_report", "actual_render_report"), "render_report"),
        "publish_receipts": (("render_publish_receipt", "actual_render_publish_receipt", "publish"), "render_publish_receipt"),
        "parent_qa": (("initial_parent_QA_receipt", "genuine_parent_initial_QA_receipt", "initial_parent_QA_report", "genuine_parent_initial_QA_report"), "parent_initial_QA"),
        "source_preparation": (("source_preparation_report", "actual_preparation_report", "actual_initial_clone_preparation_receipt", "typed_source_generated_xml", "typed_source_owner_metadata"), "source_preparation"),
    }
    result: dict[str, Any] = {}
    for name, (aliases, role) in role_defs.items():
        refs = explicit_refs(evidence, aliases, role, f"decision.actual_completed_metadata_evidence[{physical}]")
        result[name] = [enrich_ref(ref, f"{physical} {name}") for ref in refs]
    required = ("native_receipts", "typed_reports", "xmf_manifests", "xmf_xml", "render_reports", "render_receipts", "publish_receipts")
    for key in required:
        if not result[key]:
            die(f"{physical} lacks explicit role evidence: {key}")
    return result


def build_new_primary(progress: dict[str, Any], old_catalog_ref: dict[str, Any]) -> dict[str, Any]:
    physical = progress["physical_case_id"]
    dref = copy.deepcopy(progress["accepted_decision"])
    decision_path = Path(dref["path"])
    decision = read_json(decision_path, f"accepted decision {physical}")
    if decision.get("family_id") != "F3" or decision.get("physical_case_id") != physical:
        die(f"accepted decision identity mismatch: {physical}")
    dref = enrich_ref(normalize_ref(dref, "cp317.accepted_decision", "accepted_decision") or {}, f"{physical} accepted decision")
    role_refs = actual_role_refs(decision, physical)
    qi_ref = normalize_ref(progress.get("actual_full836_QI"), "cp317.actual_full836_QI", "independent_full836_QI")
    if qi_ref is None:
        qi_ref = normalize_ref(decision.get("independent_full836_QI"), "decision.independent_full836_QI", "independent_full836_QI")
    if qi_ref is None:
        die(f"{physical} lacks own full836 QI")
    qi_ref = enrich_ref(qi_ref, f"{physical} own full836 QI")
    contacts = normalize_png_list(decision.get("contact_sheets"), f"{decision_path}:contact_sheets", "contact_png")
    keys = normalize_png_list(decision.get("keyframes"), f"{decision_path}:keyframes", "key_png")
    if len(contacts) != 35 or len(keys) != 9:
        die(f"{physical} expected 35 contacts + 9 keys, got {len(contacts)} + {len(keys)}")
    evidence = decision["actual_completed_metadata_evidence"]
    source_scope = {
        "accepted_decision_physical_condition_sha256": decision.get("physical_condition_sha256"),
        "accepted_decision_actual_converter_scope_sha256": decision.get("actual_converter_scope_sha256", decision.get("actual_converter_condition_sha256")),
        "decision_scope_schema": decision.get("scope_schema", decision.get("producer_scope_schema")),
        "actual_native_XMF_plan_field_namespaces": copy.deepcopy(decision.get("actual_native_XMF_plan_field_namespaces")),
        "native_XMF_plan_absence_or_presence_preserved_verbatim": True,
        "index_native_request_scope": copy.deepcopy(progress.get("native_request_scope")),
        "index_raw_scope_fields_preserved": copy.deepcopy(progress.get("F3_source147_raw_scope_fields_preserved")),
        "physical_case_id_is_the_only_case_join": True,
        "source_plan_or_native_field_absence_is_not_filled": True,
    }
    fields = {
        key: copy.deepcopy(decision.get(key))
        for key in (
            "status", "full_native_frames", "particle_count", "initial_fluid_particles", "actual_type_counts",
            "actual_physical_window_s", "actual_native_XMF_plan_field_namespaces", "precision_status",
            "q_n_granted", "q_e_granted", "independent_case_increment", "visual_observations",
            "visual_limits", "all836_UID_N3_actual_times_finite_states_verified",
            "all836_UID_type_mk_N3_actual_times_finite_active_states_verified",
            "all_native_UIDs_active_each_frame", "actual_native_XMF_plan_field_namespaces",
        ) if key in decision
    }
    return {
        "kind": "current_cp317_own_primary_case",
        "case_id": progress["case_id"],
        "physical_case_id": physical,
        "accepted_decision": dref,
        "own_full836_QI": qi_ref,
        "evidence_refs": role_refs,
        "contact_png_refs": contacts,
        "key_png_refs": keys,
        "png_evidence_boundary": {
            "contacts_count": len(contacts),
            "keys_count": len(keys),
            "paths_stat_checked": True,
            "producer_declared_png_sha_copied_only": True,
            "source_agent_did_not_read_or_hash_png_bytes": True,
        },
        "case_metadata_fields": fields,
        "scope_roles": source_scope,
        "typed_completion_boundary": {
            "original_conversion_receipt_is_separate_from_actual_typed_receipt": bool(role_refs["original_conversion_receipts"]),
            "artifact_audit_is_separate_evidence": bool(role_refs["artifact_audit"]),
            "native_typed_xmf_render_roles_are_not_reconciled": True,
        },
        "current_cp317_index_snapshot": compact_index_row(progress),
        "historical_39_catalog": copy.deepcopy(old_catalog_ref),
        "credit_boundary": {"case_credit": 0, "new_visual_credit": 0, "Q_N": 0, "Q_E": 0, "numeric_precision_accepted": False},
    }


def build() -> dict[str, Any]:
    checkpoint = read_json(CHECKPOINT, "ROOT_LIVE checkpoint317")
    index = read_json(INDEX, "cp317 current full336 index")
    old = read_json(OLD_CATALOG, "Root1328 F3 39-primary catalog")
    old_sha = sha_json(OLD_CATALOG, "Root1328 F3 39-primary catalog")
    if checkpoint.get("checkpoint") != 317 or checkpoint.get("accepted_per_family", {}).get("F3") != 47:
        die("checkpoint317 does not report F3=47")
    f3 = [row for row in index.get("cases", []) if row.get("family_id") == "F3"]
    accepted = [row for row in f3 if isinstance(row.get("accepted_decision"), dict) and str(row.get("status", "")).startswith("visual-approved")]
    pending = [row for row in f3 if not isinstance(row.get("accepted_decision"), dict)]
    if len(f3) != 48 or len(accepted) != 47 or len(pending) != 1:
        die(f"cp317 F3 boundary is {len(f3)}/{len(accepted)}/{len(pending)}")
    old_rows = old.get("main_accepted_primary_and_published_navigation_sidecars", [])
    old_ids = {row.get("physical_case_id") for row in old_rows}
    accepted_ids = {row["physical_case_id"] for row in accepted}
    new_rows = [row for row in accepted if row["physical_case_id"] not in old_ids]
    if len(old_rows) != 39 or old_ids - accepted_ids:
        die("Root1328 accepted39 is not a subset of current cp317 accepted F3")
    if {row["case_id"] for row in new_rows} != EXPECTED_NEW_CASES:
        die(f"new accepted rows differ from requested eight: {sorted({row['case_id'] for row in new_rows})}")
    membership = copy.deepcopy(old.get("membership"))
    if not isinstance(membership, dict):
        die("Root1328 membership missing")
    first8 = membership.get("frozen_first8_physical_case_ids")
    first24 = membership.get("actual_first24_physical_case_ids")
    final48 = membership.get("registered_final48_physical_case_ids")
    if not (isinstance(first8, list) and isinstance(first24, list) and isinstance(final48, list)):
        die("membership arrays missing")
    if (len(first8), len(first24), len(final48)) != (8, 24, 48) or not set(first8) <= set(first24) <= set(final48):
        die("membership subset/count contract failed")
    if set(final48) != {row["physical_case_id"] for row in f3}:
        die("current cp317 F3 set differs from frozen registered48")
    old_source_ref = {"path": str(OLD_CATALOG), "sha256": old_sha, "role": "Root1328 immutable 39-primary catalog"}
    rows: list[dict[str, Any]] = []
    old_lookup = {row["physical_case_id"]: row for row in old_rows}
    for order, progress in enumerate(f3, 1):
        physical = progress["physical_case_id"]
        if not isinstance(progress.get("accepted_decision"), dict):
            continue
        membership_row = {
            "frozen_first8_member": physical in set(first8),
            "actual_first24_member": physical in set(first24),
            "registered_final48_member": physical in set(final48),
            "membership_source": "Root1276/Root1328 explicit arrays; accepted count never redefines first24",
        }
        if physical in old_lookup:
            rows.append({
                "delivery_order": order,
                "family_id": "F3",
                "case_id": progress["case_id"],
                "physical_case_id": physical,
                "delivery_status": "accepted_visual_inherited_from_root1328",
                "membership": membership_row,
                "primary_source": {
                    "kind": "Root1328_main_accepted_primary_and_published_navigation_sidecars",
                    "catalog": old_source_ref,
                    "join_key": physical,
                    "source_row_order": old_lookup[physical].get("delivery_order"),
                    "historical_role_absences_and_unknowns_preserved": True,
                },
                "current_cp317_index_snapshot": compact_index_row(progress),
                "credit_boundary": {"case_credit": 0, "new_visual_credit": 0, "Q_N": 0, "Q_E": 0, "numeric_precision_accepted": False},
            })
        else:
            rows.append({
                "delivery_order": order,
                "family_id": "F3",
                "case_id": progress["case_id"],
                "physical_case_id": physical,
                "delivery_status": "accepted_visual_current_cp317_own_primary",
                "membership": membership_row,
                "primary_delivery": build_new_primary(progress, old_source_ref),
                "credit_boundary": {"case_credit": 0, "new_visual_credit": 0, "Q_N": 0, "Q_E": 0, "numeric_precision_accepted": False},
            })
    p = pending[0]
    pending_row = {
        "delivery_order": next(i for i, r in enumerate(f3, 1) if r is p),
        "family_id": "F3",
        "case_id": p["case_id"],
        "physical_case_id": p["physical_case_id"],
        "delivery_status": "pending_original_render_no_visual_decision",
        "membership": {
            "frozen_first8_member": p["physical_case_id"] in set(first8),
            "actual_first24_member": p["physical_case_id"] in set(first24),
            "registered_final48_member": True,
            "membership_source": "Root1276/Root1328 explicit arrays",
        },
        "pending_metadata": {
            "accepted_decision": None,
            "primary_particle_xmf_render_refs": None,
            "personal_visual_review": False,
            "visual_credit": 0,
            "pipeline_readiness_only": True,
            "current_cp317_index_snapshot": compact_index_row(p),
            "current_controller_observation": copy.deepcopy(p.get("current_controller_observation")),
            "latest_registered_render_request": copy.deepcopy(p.get("latest_registered_render_request")),
            "declared_scope_roles": {
                "native_request_scope": copy.deepcopy(p.get("native_request_scope")),
                "declared_render_request_condition_sha256": p.get("declared_render_request_condition_sha256"),
                "declared_actual_converter_scope_sha256": p.get("declared_actual_converter_scope_sha256"),
            },
            "original1101_is_not_promoted_to_completed_or_visual": True,
        },
        "credit_boundary": {"case_credit": 0, "new_visual_credit": 0, "Q_N": 0, "Q_E": 0, "numeric_precision_accepted": False},
    }
    rows.append(pending_row)
    rows.sort(key=lambda row: row["delivery_order"])
    catalog = {
        "schema": SCHEMA,
        "status": "metadata_complete_47_accepted_one_pending",
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "assignment": {
            "assigned_family": "F3",
            "actual_family": "F3",
            "source_package_role": "actual final48 primary delivery predecessor: 47 accepted, one original1101 pending",
            "package_name": HERE.name,
            "scientific_payload_read_or_hashed_by_source": False,
            "new_science_jobs": 0,
            "new_case_credit": 0,
            "Q_N": 0,
            "Q_E": 0,
            "numeric_precision_accepted": False,
        },
        "authoritative_sources": {
            "root_live_checkpoint_317": source_ref(CHECKPOINT, "ROOT_LIVE checkpoint317"),
            "cp317_current_full336_index": source_ref(INDEX, "cp317 current full336 index"),
            "root1328_f3_actual39_primary_catalog": old_source_ref,
            "root1328_membership_arrays": {
                "path": str(OLD_CATALOG), "sha256": old_sha,
                "role": "frozen8/actual24/registered48 arrays; no lexical reselection",
            },
        },
        "membership": {
            "frozen_first8_physical_case_ids": first8,
            "actual_first24_physical_case_ids": first24,
            "registered_final48_physical_case_ids": final48,
            "frozen8_subset_actual24_subset_registered48": True,
            "accepted_count_does_not_redefine_first24": True,
            "selection_source": "Root1276 arrays preserved by Root1328; current cp317 rows only provide status",
        },
        "delivery": {
            "registered_final48_count": 48,
            "accepted_visual_count": 47,
            "pending_visual_count": 1,
            "delivery_complete": False,
            "accepted_visual_delivery_complete": False,
            "pending_case_ids": [p["physical_case_id"]],
            "new_current_cp317_rows": sorted(EXPECTED_NEW_CASES),
            "pending_is_not_visual_acceptance": True,
        },
        "role_policy": {
            "physical_case_id_is_join_key": True,
            "native_canonical_typed_legacy_xmf_plan_source_def_roles_remain_distinct": True,
            "15_historical_native_xmf_scope_differences_and_mother_native_id_absence_preserved_in_root1328": True,
            "four_historical_native_runtime_unknowns_and_recovery_audits_are_not_relabelled": True,
            "source_plan_or_native_field_absence_is_not_backfilled": True,
            "PNG_refs_are_producer_declarations_and_stat_only_to_source_agent": True,
            "scientific_payload_boundary": "No H5/BI4/IBI4/CSV/DAT/VTK opened or hashed; no jobs or shared state writes",
        },
        "rows": rows,
    }
    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest = {
        "schema": "ds02.f3.fresh190.package-manifest.v1",
        "catalog": CATALOG.name,
        "files": [CATALOG.name, "README.md", "build_fresh190.py", "validate_fresh190.py"],
        "manifest_self_hash_excluded": True,
        "scientific_payload_read_or_hashed_by_source": False,
        "new_science_jobs": 0,
        "new_case_credit": 0,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return catalog


if __name__ == "__main__":
    built = build()
    print(json.dumps({"status": "BUILT", "catalog": str(CATALOG), "rows": len(built["rows"]), "accepted": built["delivery"]["accepted_visual_count"], "pending": built["delivery"]["pending_visual_count"]}, sort_keys=True))
