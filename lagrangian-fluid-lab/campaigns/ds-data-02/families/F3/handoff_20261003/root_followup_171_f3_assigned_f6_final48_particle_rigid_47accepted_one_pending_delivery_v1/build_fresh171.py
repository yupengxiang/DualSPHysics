#!/usr/bin/env python3
"""Build fresh171 from authoritative JSON metadata only.

The builder never opens or hashes H5/BI4/CSV/DAT/VTK/XMF/XML/PNG payloads.
It hashes only JSON source products and the JSON package it creates.  XMF/XML
and PNG references are retained as producer/visual references and checked only
with filesystem stat by the validator.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
CP = HANDOFF / (
    "root_stage1_source170_F6_fixedactual24_particle_XMF_fulltime_rigid_join_"
    "same_native_receipts_times_and_baseline_absence_main_delivery_1313/"
    "full336-current295-actual-final48-delivery-progress-index.json"
)
ROOT1313 = HANDOFF / (
    "root_stage1_source170_F6_fixedactual24_particle_XMF_fulltime_rigid_join_"
    "same_native_receipts_times_and_baseline_absence_main_delivery_1313/"
    "F6-ACTUAL_FIRST24-PARTICLE-RIGID-JOINED-DELIVERY.json"
)
ROOT1305 = HANDOFF / (
    "root_stage1_F6_actual48_fulltime_official_rigid_motion_47new241rows_"
    "one_existing_history_CPU2_and_pendingF5_1131_1180_ownQI_checkpoint_1305/"
    "F6-FINAL48-FULLTIME-RIGID-MOTION-DELIVERY.json"
)
ROOT1320 = HANDOFF / (
    "root_stage1_F6_47_actual_native_receipts_34_old_nulls_recovered_full336_331_unique_digest_"
    "five_true_legacy_absences_1320/full336-native-field-role-closure-331-unique-five-real-absences.json"
)

SCHEMA = "ds02.f3.assigned-f6.fresh171.final48-particle-rigid-47accepted-one-pending.v1"
CATALOG = HERE / "F6-FINAL48-PARTICLE-RIGID-47ACCEPTED-ONE-PENDING.json"


def die(message: str) -> None:
    raise RuntimeError(message)


def read_json(path: Path, label: str) -> Any:
    if path.suffix.lower() != ".json":
        die(f"{label} is not JSON: {path}")
    if not path.is_file():
        die(f"missing {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"invalid JSON {label}: {path}: {exc}")


def sha_json(path: Path, label: str) -> str:
    if path.suffix.lower() != ".json":
        die(f"only JSON may be hashed: {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_ref(path: Path, label: str) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha_json(path, label)}


def is_path_string(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("/")


def clone_ref(value: Any, label: str, role: str) -> dict[str, Any] | None:
    """Copy a source ref without interpreting scientific payload bytes."""
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        out = copy.deepcopy(value)
        out["source_key"] = label
        out["role"] = role
        return out
    if is_path_string(value):
        return {"path": value, "source_key": label, "role": role}
    return None


def first_nested_ref(value: Any, keys: tuple[str, ...], label: str, role: str) -> dict[str, Any] | None:
    """Select an explicitly named metadata path, never a first-match arbitrary path."""
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                ref = clone_ref(value[key], f"{label}.{key}", role)
                if ref is not None:
                    return ref
        # Direct path is only accepted after named child keys.
        ref = clone_ref(value, label, role)
        if ref is not None:
            return ref
    return None


def direct_ref(container: dict[str, Any], keys: tuple[str, ...], label: str, role: str) -> dict[str, Any] | None:
    for key in keys:
        if key in container:
            ref = clone_ref(container[key], f"{label}.{key}", role)
            if ref is not None:
                return ref
    return None


def direct_or_nested(container: dict[str, Any], direct_keys: tuple[str, ...], nested_key: str,
                     nested_keys: tuple[str, ...], label: str, role: str) -> dict[str, Any] | None:
    ref = direct_ref(container, direct_keys, label, role)
    if ref is not None:
        return ref
    value = container.get(nested_key)
    if isinstance(value, dict):
        return first_nested_ref(value, nested_keys, f"{label}.{nested_key}", role)
    return None


def json_probe(ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        return None
    path = Path(ref["path"])
    suffix = path.suffix.lower()
    out: dict[str, Any] = {
        "path_exists": path.is_file(),
        "content_read_or_hashed": False,
        "suffix": suffix,
    }
    if path.is_file():
        try:
            out["bytes_stat"] = path.stat().st_size
        except OSError:
            out["bytes_stat"] = None
    if suffix == ".json" and path.is_file():
        raw = path.read_bytes()
        out["content_read_or_hashed"] = True
        out["json_sha256"] = hashlib.sha256(raw).hexdigest()
        try:
            value = json.loads(raw.decode("utf-8"))
            out["json_type"] = "object" if isinstance(value, dict) else "array" if isinstance(value, list) else type(value).__name__
            if isinstance(value, dict):
                out["top_level_keys"] = sorted(value.keys())[:80]
                for key in ("family_id", "case_id", "physical_case_id", "status", "returncode",
                            "frames", "source_frames", "expected_frames", "particles", "published_status",
                            "all_frames_rendered", "xdmf", "case_xmf", "manifest"):
                    if key in value and isinstance(value[key], (str, int, float, bool, type(None), list)):
                        out[f"top.{key}"] = value[key]
                # A manifest's XML target is metadata. It is not opened here.
                for key in ("xdmf", "case_xmf", "xmf", "case_xmf_path"):
                    if isinstance(value.get(key), str) and value[key].startswith("/"):
                        out["declared_xmf_path"] = value[key]
                        out["declared_xmf_key"] = key
                        break
        except Exception as exc:
            out["json_parse_error"] = str(exc)
        declared = ref.get("sha256")
        if isinstance(declared, str):
            out["declared_sha256"] = declared
            out["declared_sha256_matches_json"] = declared == out.get("json_sha256")
    return out


def annotate(ref: dict[str, Any] | None, role: str) -> dict[str, Any] | None:
    if ref is None:
        return None
    out = copy.deepcopy(ref)
    out["role"] = role
    out["metadata_probe"] = json_probe(out)
    return out


def derive_manifest_xml(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    probe = manifest.get("metadata_probe", {})
    path = probe.get("declared_xmf_path") if isinstance(probe, dict) else None
    if not isinstance(path, str):
        return None
    return {
        "path": path,
        "source_key": f"{manifest.get('source_key', 'manifest')}.metadata_probe.declared_xmf_path",
        "role": "primary_xmf_xml_derived_from_own_manifest_json",
        "declared_sha256": None,
        "metadata_probe": {
            "path_exists": Path(path).is_file(),
            "content_read_or_hashed": False,
            "suffix": Path(path).suffix.lower(),
            "bytes_stat": Path(path).stat().st_size if Path(path).is_file() else None,
            "derivation": "manifest JSON declared xdmf/case_xmf path; XML content was not opened or hashed",
        },
    }


def semantic_receipt_from_actual_receipts(bindings: dict[str, Any], role: str, label: str) -> dict[str, Any] | None:
    """Classify an explicitly supplied actual_receipts list by its path role.

    The list is producer metadata, not a license to choose its first item.  A
    receipt is selected only when its own path contains the role-specific
    execution token, so a render receipt cannot silently become a native or
    typed receipt.
    """
    values = bindings.get("actual_receipts")
    if not isinstance(values, list):
        return None
    candidates: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        ref = clone_ref(value, f"{label}.actual_receipts[{index}]", role)
        if ref is None:
            continue
        path = str(ref.get("path", "")).lower()
        if role == "primary_render_receipt":
            matches = ("render-" in path or "/render/" in path or "render" in Path(path).parent.name)
            excludes = "xmf" in path and "render" not in Path(path).parent.name
        elif role == "typed_receipt":
            matches = "typed-" in path or "/typed/" in path
            excludes = "render" in path or "xmf" in path
        elif role == "native_receipt":
            matches = "native-" in path or "/native/" in path
            excludes = "render" in path or "typed" in path or "xmf" in path
        else:
            matches = False
            excludes = False
        if matches and not excludes:
            candidates.append(ref)
    if len(candidates) == 1:
        return candidates[0]
    # Ambiguous or absent producer receipt remains explicit absence; never
    # invent a role from list position.
    return None


def root1320_native_role(native_row: dict[str, Any] | None, source_ref_1320: dict[str, Any]) -> dict[str, Any] | None:
    """Return the independently closed native role without changing visual roles.

    Root1320 is a metadata-only field-role closure.  Its receipt is an actual
    native producer reference, not a visual decision and not a replacement for
    the decision's own canonical/source/legacy scope fields.  The baseline is
    intentionally absent from this map and remains null in the catalog.
    """
    if not isinstance(native_row, dict):
        return None
    receipt = native_row.get("actual_native_receipt")
    if not isinstance(receipt, dict) or not isinstance(receipt.get("path"), str):
        return None
    return {
        "source": copy.deepcopy(source_ref_1320),
        "role": "actual_native_receipt_field_role_closure",
        "physical_case_id": native_row.get("physical_case_id"),
        "actual_complete_native_receipt": copy.deepcopy(receipt),
        "actual_native_case_id": native_row.get("actual_native_case_id"),
        "actual_native_physical_case_id": native_row.get("actual_native_physical_case_id"),
        "actual_native_condition_sha256": native_row.get("actual_native_condition_sha256"),
        "actual_native_status": native_row.get("actual_native_status"),
        "actual_native_returncode": native_row.get("actual_native_returncode"),
        "actual_native_request_condition_field_present": native_row.get("actual_native_request_condition_field_present"),
        "fulltime_rigid_export_report": copy.deepcopy(native_row.get("fulltime_rigid_export_report")),
        "field_role_closure_is_not_visual_acceptance": True,
    }


def select_visual_refs(decision: dict[str, Any], decision_ref: dict[str, Any], closure: dict[str, Any] | None,
                       closure_ref: dict[str, Any] | None) -> dict[str, Any]:
    evidence = decision.get("actual_completed_metadata_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    bindings = decision.get("bindings")
    bindings = bindings if isinstance(bindings, dict) else {}
    closure = closure if isinstance(closure, dict) else {}

    # Own case XMF metadata: prefer the explicit xmf manifest/case_xmf pair,
    # then own normal manifest/normal_xdmf, then the closure's own pair.
    manifest = direct_ref(evidence, ("xmf_manifest",), "decision.actual_completed_metadata_evidence", "primary_xmf_manifest")
    if manifest is None:
        manifest = direct_or_nested(evidence, (), "xmf", ("manifest", "xmf_manifest"),
                                    "decision.actual_completed_metadata_evidence", "primary_xmf_manifest")
    if manifest is None:
        manifest = direct_ref(bindings, ("normal_manifest", "dynamic_xdmf_manifest"), "decision.bindings", "primary_xmf_manifest")
    if manifest is None:
        manifest = direct_ref(closure, ("xmf_manifest",), "independent_metadata_closure", "primary_xmf_manifest")
    manifest = annotate(manifest, "primary_xmf_manifest")

    xml = direct_ref(evidence, ("xmf_xml", "case_xmf"), "decision.actual_completed_metadata_evidence", "primary_xmf_xml")
    if xml is None:
        xml = direct_or_nested(evidence, (), "xmf", ("case_xmf", "xdmf", "xmf_xml"),
                               "decision.actual_completed_metadata_evidence", "primary_xmf_xml")
    if xml is None:
        xml = direct_ref(bindings, ("normal_xdmf", "dynamic_xdmf"), "decision.bindings", "primary_xmf_xml")
    if xml is None:
        xml = direct_ref(closure, ("xmf_xml", "case_xmf"), "independent_metadata_closure", "primary_xmf_xml")
    xml = annotate(xml, "primary_xmf_xml")
    if xml is None:
        xml = derive_manifest_xml(manifest)

    render_report = direct_ref(evidence, ("render_report",), "decision.actual_completed_metadata_evidence", "primary_render_report")
    if render_report is None:
        render_report = direct_or_nested(evidence, (), "render", ("report", "render_report", "full_render_report"),
                                          "decision.actual_completed_metadata_evidence", "primary_render_report")
    if render_report is None:
        render_report = direct_ref(bindings, ("native_full_render_report", "animation_integrity_report"), "decision.bindings", "primary_render_report")
    if render_report is None:
        render_report = direct_ref(closure, ("full_render_report", "render_report"), "independent_metadata_closure", "primary_render_report")
    render_report = annotate(render_report, "primary_render_report")

    render_receipt = direct_ref(evidence, ("render_receipt",), "decision.actual_completed_metadata_evidence", "primary_render_receipt")
    if render_receipt is None:
        render_receipt = direct_or_nested(evidence, (), "render", ("receipt", "execution_receipt", "full_render_receipt"),
                                           "decision.actual_completed_metadata_evidence", "primary_render_receipt")
    if render_receipt is None:
        render_receipt = direct_or_nested(bindings, (), "render", ("receipt", "execution_receipt"),
                                           "decision.bindings", "primary_render_receipt")
    if render_receipt is None:
        render_receipt = direct_ref(bindings, ("animation_receipt",), "decision.bindings", "primary_render_receipt")
    if render_receipt is None:
        render_receipt = semantic_receipt_from_actual_receipts(bindings, "primary_render_receipt", "decision.bindings")
    if render_receipt is None:
        render_receipt = direct_ref(closure, ("full_render_receipt", "render_receipt"), "independent_metadata_closure", "primary_render_receipt")
    render_receipt = annotate(render_receipt, "primary_render_receipt")

    typed_report = direct_ref(evidence, ("typed_report",), "decision.actual_completed_metadata_evidence", "typed_report")
    if typed_report is None:
        typed_report = direct_or_nested(evidence, (), "typed", ("conversion_report", "report", "typed_report"),
                                        "decision.actual_completed_metadata_evidence", "typed_report")
    if typed_report is None:
        typed_report = direct_ref(bindings, ("typed_conversion_report",), "decision.bindings", "typed_report")
    if typed_report is None:
        typed_report = direct_ref(closure, ("typed_report",), "independent_metadata_closure", "typed_report")
    typed_report = annotate(typed_report, "typed_report")

    typed_receipt = direct_ref(evidence, ("typed_conversion_receipt",), "decision.actual_completed_metadata_evidence", "typed_receipt")
    if typed_receipt is None:
        typed_receipt = direct_or_nested(evidence, (), "typed", ("receipt", "execution_receipt", "typed_receipt"),
                                         "decision.actual_completed_metadata_evidence", "typed_receipt")
    if typed_receipt is None:
        typed_receipt = direct_or_nested(bindings, (), "typed", ("receipt", "execution_receipt"),
                                         "decision.bindings", "typed_receipt")
    if typed_receipt is None:
        typed_receipt = semantic_receipt_from_actual_receipts(bindings, "typed_receipt", "decision.bindings")
    typed_receipt = annotate(typed_receipt, "typed_receipt")

    native_receipt = direct_ref(evidence, ("full_native_receipt",), "decision.actual_completed_metadata_evidence", "native_receipt")
    if native_receipt is None:
        for key in ("native_full241", "native_full", "native"):
            if isinstance(evidence.get(key), dict):
                native_receipt = first_nested_ref(evidence[key], ("execution_receipt", "receipt", "path"),
                                                  f"decision.actual_completed_metadata_evidence.{key}", "native_receipt")
                if native_receipt:
                    break
    if native_receipt is None:
        for key in ("native", "native_full"):
            if isinstance(bindings.get(key), dict):
                native_receipt = first_nested_ref(bindings[key], ("execution_receipt", "receipt", "path"),
                                                  f"decision.bindings.{key}", "native_receipt")
                if native_receipt:
                    break
    if native_receipt is None:
        native_receipt = semantic_receipt_from_actual_receipts(bindings, "native_receipt", "decision.bindings")
    native_receipt = annotate(native_receipt, "native_receipt")

    gencase_refs: list[dict[str, Any]] = []
    for key in ("gencase_receipt",):
        ref = direct_ref(evidence, (key,), "decision.actual_completed_metadata_evidence", "gencase_receipt")
        if ref:
            gencase_refs.append(annotate(ref, "gencase_receipt"))
    if isinstance(evidence.get("gencase"), dict):
        for key in ("execution_receipt", "prepared_input_report", "generated_xml", "generated_definition_xml"):
            ref = first_nested_ref(evidence["gencase"], (key,), "decision.actual_completed_metadata_evidence.gencase", f"gencase_{key}")
            if ref:
                gencase_refs.append(annotate(ref, f"gencase_{key}"))
    gencase_refs = dedup_refs(gencase_refs)

    qa_refs: list[dict[str, Any]] = []
    ref = direct_ref(evidence, ("initial_native_qa_receipt",), "decision.actual_completed_metadata_evidence", "initial_native_qa_receipt")
    if ref:
        qa_refs.append(annotate(ref, "initial_native_qa_receipt"))
    for key in ("initial_native_qa", "floatinginfo_state0", "native_full241", "native_full"):
        value = evidence.get(key)
        if isinstance(value, dict):
            for sub in ("execution_receipt", "report", "index", "audit_report", "summary"):
                ref = first_nested_ref(value, (sub,), f"decision.actual_completed_metadata_evidence.{key}", f"{key}_{sub}")
                if ref:
                    qa_refs.append(annotate(ref, f"{key}_{sub}"))
    qa_refs = dedup_refs(qa_refs)

    owner_refs: list[dict[str, Any]] = []
    for source, label in ((evidence, "decision.actual_completed_metadata_evidence"), (bindings, "decision.bindings"), (decision.get("scope_separation", {}), "decision.scope_separation")):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if key in {"canonical_owner", "classified_owner", "source_owner_file", "classified_owner_file", "source_plan_path", "source_definition", "owner_metadata"}:
                ref = clone_ref(value, f"{label}.{key}", "owner_or_source")
                if ref:
                    owner_refs.append(annotate(ref, "owner_or_source"))
    owner_refs = dedup_refs(owner_refs)

    verified = decision.get("verified_PNG_hashes")
    contacts: list[Any] = []
    keys: list[Any] = []
    png_sources: list[dict[str, Any]] = []
    if isinstance(verified, dict):
        if isinstance(verified.get("contact_sheets"), list):
            contacts = copy.deepcopy(verified["contact_sheets"])
        if isinstance(verified.get("key_frames"), list):
            keys = copy.deepcopy(verified["key_frames"])
        png_sources.append({"source": "decision.verified_PNG_hashes", "metadata": {
            k: verified.get(k) for k in ("computed_after_view_image", "viewed_with", "reviewed_contact_sheet_indices", "reviewed_key_frame_indices", "render_report_file") if k in verified
        }})
    if not contacts and isinstance(decision.get("contact_sheets"), list):
        contacts = copy.deepcopy(decision["contact_sheets"])
        png_sources.append({"source": "decision.contact_sheets"})
    if not keys and isinstance(decision.get("key_events"), list):
        keys = copy.deepcopy(decision["key_events"])
        png_sources.append({"source": "decision.key_events"})
    report_contacts, report_keys, report_png_meta = report_png_refs(render_report)
    if not contacts and report_contacts:
        contacts = copy.deepcopy(report_contacts)
        png_sources.append({"source": "actual_render_report.outputs.contact_sheets", "metadata": report_png_meta})
    if not keys and report_keys:
        keys = copy.deepcopy(report_keys)
        png_sources.append({"source": "actual_render_report.outputs.key_frames", "metadata": report_png_meta})
    if report_png_meta is not None and not report_contacts and not report_keys:
        png_sources.append({"source": "actual_render_report.outputs", "metadata": report_png_meta,
                            "key_path_boundary": "no named key-frame PNG paths were present in this report"})
    if closure_ref:
        png_sources.append({"source": "independent_metadata_closure", "ref": copy.deepcopy(closure_ref),
                            "declared_visual_evidence": {
                                "all_contacts_and_keys_viewed": closure.get("delegated_all11_contact_and9_keyframes_viewed_and_hashed"),
                                "main_png_personal_review": closure.get("main_PNG_personal_review"),
                            }})

    decision_visual = {
        "decision_status": decision.get("status"),
        "visual_reviewer": decision.get("visual_reviewer"),
        "agent_personally_viewed_all_contacts_and_keys": decision.get("agent_personally_viewed_all_contacts_and_keys"),
        "main_personally_viewed_pngs": decision.get("main_personally_viewed_pngs", decision.get("main_personally_viewed_PNGs")),
        "visual_review_method": decision.get("visual_review_method"),
        "verified_png_metadata": decision.get("verified_PNG_hashes"),
        "frames": decision.get("actual_frames", decision.get("full_native_frames", decision.get("frames"))),
        "particles": decision.get("actual_particles", decision.get("particles")),
        "actual_last_time_s": decision.get("actual_last_time_s"),
        "precision_status": decision.get("precision_status", decision.get("numerical_precision_status")),
        "q_n": decision.get("q_n_granted", decision.get("q_n")),
        "q_e": decision.get("q_e_granted", decision.get("q_e")),
    }
    selected = {
        "accepted_decision": copy.deepcopy(decision_ref),
        "independent_metadata_closure": copy.deepcopy(closure_ref) if closure_ref else None,
        "actual_xmf_manifest": manifest,
        "actual_xmf_xml": xml,
        "actual_render_report": render_report,
        "actual_render_receipt": render_receipt,
        "native_refs": [native_receipt] if native_receipt else [],
        "typed_refs": [x for x in (typed_receipt, typed_report) if x is not None],
        "gencase_or_definition_refs": gencase_refs,
        "initial_qa_or_audit_refs": qa_refs,
        "owner_or_source_refs": owner_refs,
        "contact_png_refs": annotate_png_refs(contacts, "contact_png"),
        "key_png_refs": annotate_png_refs(keys, "key_png"),
        "png_evidence_sources": png_sources,
        "decision_visual_metadata": decision_visual,
        "primary_visual_evidence": {
            "primary_refs_are_selected_from_own_decision_or_own_closure": True,
            "manifest_json_probe": manifest.get("metadata_probe") if manifest else None,
            "render_report_json_probe": render_report.get("metadata_probe") if render_report else None,
            "render_receipt_json_probe": render_receipt.get("metadata_probe") if render_receipt else None,
            "manifest_declared_xmf_path_is_used_when_xml_ref_is_derived": bool(xml and "derived_from_own_manifest_json" in str(xml.get("role"))),
            "named_key_png_paths_available": bool(keys),
            "key_png_paths_absent_reason": None if keys else "immutable decision/render metadata published no named key-frame PNG path; no frame-directory inference was performed",
            "visual_PNG_path_boundary": "explicit PNG refs are copied only when present in the immutable decision; closure-only visual counts remain counts, not invented paths",
        },
    }
    selected["source_scope"] = {
        "decision_scope_separation": copy.deepcopy(decision.get("scope_separation")),
        "decision_source_plan_condition_sha256": decision.get("source_plan_condition_sha256"),
        "decision_physical_condition_sha256": decision.get("physical_condition_sha256"),
    }
    return selected


def annotate_png_refs(values: list[Any], role: str) -> list[Any]:
    out = []
    for index, value in enumerate(values):
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            item = copy.deepcopy(value)
            item["role"] = role
            # PNG is visual payload: stat only, never content/hash.
            path = Path(item["path"])
            item["metadata_probe"] = {
                "path_exists": path.is_file(),
                "bytes_stat": path.stat().st_size if path.is_file() else None,
                "content_read_or_hashed": False,
                "source_index": index,
            }
            out.append(item)
        else:
            out.append(copy.deepcopy(value))
    return out


def report_png_refs(render_report: dict[str, Any] | None) -> tuple[list[Any], list[Any], dict[str, Any] | None]:
    """Read only a render-report JSON's explicit PNG output metadata.

    No PNG bytes are opened or hashed.  The report may publish contact sheets
    and, for some older cases, no named key-frame paths; that absence is kept
    explicit instead of synthesising key paths from a frame directory.
    """
    if not isinstance(render_report, dict) or not isinstance(render_report.get("path"), str):
        return [], [], None
    path = Path(render_report["path"])
    if path.suffix.lower() != ".json" or not path.is_file():
        return [], [], None
    report = read_json(path, f"render report {path}")
    outputs = report.get("outputs") if isinstance(report, dict) else None
    if not isinstance(outputs, dict):
        return [], [], {"report_outputs_present": False}
    contacts: list[Any] = []
    keys: list[Any] = []
    for key in ("contact_sheets", "contact_pages"):
        if isinstance(outputs.get(key), list):
            contacts.extend(outputs[key])
    for key in ("key_frames", "keyframes", "key_events"):
        if isinstance(outputs.get(key), list):
            keys.extend(outputs[key])
    return contacts, keys, {
        "report_outputs_present": True,
        "contact_output_count": len(contacts),
        "key_output_count": len(keys),
        "source_report_path": str(path),
        "source_report_json_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "content_read_or_hashed": True,
        "png_content_read_or_hashed": False,
    }


def dedup_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen = set()
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        key = (ref.get("path"), ref.get("role"), ref.get("source_key"))
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def build() -> dict[str, Any]:
    cp = read_json(CP, "cp242 final48 progress index")
    root1313 = read_json(ROOT1313, "Root1313 first24 joined product")
    root1305 = read_json(ROOT1305, "Root1305 full48 rigid product")
    root1320 = read_json(ROOT1320, "Root1320 native field-role closure")
    require = lambda c, m: die(m) if not c else None
    require(cp.get("schema") == "ds02.stage1.full336.role-aware-progress-index.v6", "cp242 schema mismatch")
    require(root1313.get("schema") == "ds02.main.F6.fixedactual24.particle-rigid-joined-delivery.v1", "Root1313 schema mismatch")
    require(root1305.get("schema") == "ds02.main.F6.final48.fulltime-rigid-motion-delivery.v1", "Root1305 schema mismatch")
    require(root1320.get("schema") == "ds02.main.full336-native-condition-field-role-closure.v1", "Root1320 schema mismatch")
    progress_rows = [row for row in cp.get("cases", []) if row.get("family_id") == "F6"]
    rigid_rows = {row.get("physical_case_id"): row for row in root1305.get("rows", []) if row.get("family_id") == "F6"}
    require(len(progress_rows) == 48, f"expected 48 F6 cp rows, got {len(progress_rows)}")
    require(len(rigid_rows) == 48, f"expected 48 F6 rigid rows, got {len(rigid_rows)}")
    first24_rows = {row.get("physical_case_id"): row for row in root1313.get("rows", [])}
    first24_sidecars = {row.get("physical_case_id"): row for row in root1313.get("main_native_particle_rigid_binding_sidecars", [])}
    first8 = copy.deepcopy(root1313.get("membership", {}).get("frozen_first8_physical_case_ids", []))
    first24 = copy.deepcopy(root1313.get("membership", {}).get("actual_first24_physical_case_ids", []))
    final48 = copy.deepcopy(root1313.get("membership", {}).get("registered_final48_physical_case_ids", []))
    require(len(first8) == 8 and len(first24) == 24 and len(final48) == 48, "membership source count mismatch")
    require(set(first8) <= set(first24) <= set(final48), "Root1313 subset relation absent")
    require(set(final48) == set(rigid_rows) == {row.get("physical_case_id") for row in progress_rows}, "F6 physical membership mismatch")
    root1320_rows = {
        row.get("physical_case_id"): row
        for row in root1320.get("actual47_F6_native_receipt_checks", [])
        if isinstance(row, dict)
    }
    baseline_id = "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE"
    require(set(root1320_rows) == set(final48) - {baseline_id}, "Root1320 F6 native role set must be final48 minus baseline")
    require(root1320.get("true_actual_field_absence_physical_case_ids", []).count(baseline_id) == 1,
            "Root1320 baseline native field absence must remain explicit")
    root1320_ref = source_ref(ROOT1320, "Root1320 native field-role closure")

    rows: list[dict[str, Any]] = []
    accepted_count = 0
    pending_rows = []
    for order, progress in enumerate(progress_rows, 1):
        physical = progress["physical_case_id"]
        rigid = rigid_rows[physical]
        accepted = isinstance(progress.get("accepted_decision"), dict)
        if accepted:
            accepted_count += 1
            dref = copy.deepcopy(progress["accepted_decision"])
            dpath = Path(dref["path"])
            decision = read_json(dpath, f"accepted decision {physical}")
            actual_decision_sha = sha_json(dpath, f"accepted decision {physical}")
            require(actual_decision_sha == dref.get("sha256"), f"accepted decision SHA mismatch: {physical}")
            closure_ref = decision.get("independent_metadata_closure") if isinstance(decision.get("independent_metadata_closure"), dict) else None
            closure = None
            if closure_ref:
                cpath = Path(closure_ref["path"])
                closure = read_json(cpath, f"independent metadata closure {physical}")
                require(sha_json(cpath, f"independent metadata closure {physical}") == closure_ref.get("sha256"), f"closure SHA mismatch: {physical}")
            visual = select_visual_refs(decision, dref, closure, closure_ref)
            native_role = root1320_native_role(root1320_rows.get(physical), root1320_ref)
            # Root1320 closes actual native receipt roles for the 46 accepted
            # non-baseline F6 rows plus the one pending native row.  Fill only
            # a missing native visual metadata ref from that explicit role;
            # retain any decision-owned ref and all scope hashes unchanged.
            if native_role is not None and not visual["native_refs"]:
                receipt_ref = annotate(clone_ref(
                    native_role["actual_complete_native_receipt"],
                    "Root1320.actual47_F6_native_receipt_checks[].actual_native_receipt",
                    "native_receipt_from_root1320_field_role_closure",
                ), "native_receipt_from_root1320_field_role_closure")
                if receipt_ref is not None:
                    visual["native_refs"] = [receipt_ref]
            if native_role is not None:
                visual["root1320_native_field_role_closure"] = native_role
            elif physical == baseline_id:
                visual["root1320_native_field_role_closure"] = {
                    "source": copy.deepcopy(root1320_ref),
                    "role": "true_legacy_native_field_absence",
                    "physical_case_id": physical,
                    "actual_complete_native_receipt": None,
                    "actual_native_condition_field_present": False,
                    "actual_native_physical_id_field_present": False,
                    "field_role_closure_is_not_visual_acceptance": True,
                }
            # The first24 sidecar is a cross-check, never a replacement for the
            # accepted decision's own refs.
            first24_sidecar = copy.deepcopy(first24_sidecars.get(physical)) if physical in first24_sidecars else None
            row = {
                "delivery_order": order,
                "family_id": "F6",
                "case_id": progress.get("case_id"),
                "physical_case_id": physical,
                "visual_status": "accepted_visual_decision_in_cp242",
                "membership": {
                    "frozen_first8_member": physical in first8,
                    "actual_first24_member": physical in first24,
                    "registered_final48_member": physical in final48,
                    "authoritative_order": "cp242 F6 row order; no lexical or directory ordering",
                },
                "accepted_visual_metadata": visual,
                "accepted_visual_decision_summary": {
                    "status": decision.get("status"),
                    "at_utc": decision.get("at_utc"),
                    "physical_condition_sha256": decision.get("physical_condition_sha256"),
                    "source_plan_condition_sha256": decision.get("source_plan_condition_sha256"),
                    "precision_status": decision.get("precision_status", decision.get("numerical_precision_status")),
                    "q_n": decision.get("q_n_granted", decision.get("q_n")),
                    "q_e": decision.get("q_e_granted", decision.get("q_e")),
                    "independent_case_increment": decision.get("independent_case_increment", decision.get("independent_physical_case_count_increment")),
                },
                "scope_roles": {
                    "cp242_declared": {
                        "accepted_decision_top_condition_sha256": progress.get("accepted_decision_top_condition_sha256"),
                        "accepted_decision_top_hash_role": progress.get("accepted_decision_top_hash_role"),
                        "declared_source_plan_condition_sha256": progress.get("declared_source_plan_condition_sha256"),
                        "declared_source_definition_sha256": progress.get("declared_source_definition_sha256"),
                        "declared_actual_converter_scope_sha256": progress.get("declared_actual_converter_scope_sha256"),
                        "native_request_scope": copy.deepcopy(progress.get("native_request_scope")),
                        "top_or_render_declared_condition_equals_actual_native_request": progress.get("top_or_render_declared_condition_equals_actual_native_request"),
                    },
                    "visual_decision_scope_separation": copy.deepcopy(decision.get("scope_separation")),
                    "roles_must_remain_distinct": True,
                },
                "progress_index_row": copy.deepcopy(progress),
                "rigid_motion_join": copy.deepcopy(rigid),
                "root1313_first24_sidecar_crosscheck": first24_sidecar,
                "credit_and_precision": {
                    "case_credit": 0,
                    "new_visual_credit": 0,
                    "Q_N": 0,
                    "Q_E": 0,
                    "numeric_precision_accepted": False,
                },
            }
        else:
            pending_rows.append(physical)
            row = {
                "delivery_order": order,
                "family_id": "F6",
                "case_id": progress.get("case_id"),
                "physical_case_id": physical,
                "visual_status": "pending_visual_render_not_accepted",
                "membership": {
                    "frozen_first8_member": physical in first8,
                    "actual_first24_member": physical in first24,
                    "registered_final48_member": physical in final48,
                    "authoritative_order": "cp242 F6 row order; no lexical or directory ordering",
                },
                "pending_visual_boundary": {
                    "accepted_decision": None,
                    "primary_particle_xmf_render_refs": None,
                    "primary_png_refs": None,
                    "reason": "cp242 has no accepted_decision; current render/controller observation is live/incomplete and cannot become visual evidence",
                    "latest_registered_render_request": copy.deepcopy(progress.get("latest_registered_render_request")),
                    "current_controller_observation": copy.deepcopy(progress.get("current_controller_observation")),
                    "actual_wrapper_contract_and_live_observation": copy.deepcopy(progress.get("actual_wrapper_contract_and_live_observation")),
                    "expected_frames": progress.get("expected_frames"),
                    "expected_contact_sheets": progress.get("expected_contact_sheets"),
                    "no_visual_credit": True,
                },
                "root1320_native_field_role_closure": root1320_native_role(root1320_rows.get(physical), root1320_ref),
                "scope_roles": {
                    "cp242_declared": {
                        "declared_render_request_condition_sha256": progress.get("declared_render_request_condition_sha256"),
                        "declared_actual_converter_scope_sha256": progress.get("declared_actual_converter_scope_sha256"),
                        "native_request_scope": copy.deepcopy(progress.get("native_request_scope")),
                        "top_or_render_declared_condition_equals_actual_native_request": progress.get("top_or_render_declared_condition_equals_actual_native_request"),
                    },
                    "visual_decision_scope_separation": None,
                    "roles_must_remain_distinct": True,
                },
                "progress_index_row": copy.deepcopy(progress),
                "rigid_motion_join": copy.deepcopy(rigid),
                "root1313_first24_sidecar_crosscheck": None,
                "credit_and_precision": {
                    "case_credit": 0,
                    "new_visual_credit": 0,
                    "Q_N": 0,
                    "Q_E": 0,
                    "numeric_precision_accepted": False,
                },
            }
        rows.append(row)

    require(accepted_count == 47 and len(pending_rows) == 1, f"expected 47 accepted + 1 pending, got {accepted_count}+{len(pending_rows)}")
    require(pending_rows == ["F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025"], "pending visual case is not the authoritative last F6 row")
    require([row["physical_case_id"] for row in rows] == [row["physical_case_id"] for row in progress_rows], "catalog row order changed")

    catalog = {
        "schema": SCHEMA,
        "status": "metadata_complete_47_accepted_one_pending",
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "assignment": {
            "assigned_family": "F3",
            "actual_family": "F6",
            "source_package_role": "read-only final48 particle-dynamic/XMF + official full-time rigid-motion joined delivery",
            "package_name": HERE.name,
            "scientific_payload_read_or_hashed_by_source": False,
            "new_science_jobs": 0,
            "new_case_credit": 0,
            "Q_N": 0,
            "Q_E": 0,
            "numeric_precision_accepted": False,
        },
        "authoritative_sources": {
            "cp242_progress_index": source_ref(CP, "cp242 progress index"),
            "root1305_f6_final48_fulltime_rigid": source_ref(ROOT1305, "Root1305 final48 rigid product"),
            "root1313_f6_actual_first24_particle_rigid": source_ref(ROOT1313, "Root1313 actual first24 product"),
            "root1320_f6_native_field_role_closure": root1320_ref,
        },
        "membership": {
            "frozen_first8_physical_case_ids": first8,
            "actual_first24_physical_case_ids": first24,
            "registered_final48_physical_case_ids": final48,
            "frozen8_subset_actual24_subset_registered48": True,
            "first24_source_product": source_ref(ROOT1313, "Root1313 first24 product"),
            "membership_selection": "copied from Root1313/CP authoritative arrays; no directory or lexical selection",
        },
        "delivery": {
            "registered_final48_count": 48,
            "accepted_visual_count": 47,
            "pending_visual_count": 1,
            "accepted_visual_delivery_complete": False,
            "accepted_case_ids": [row["physical_case_id"] for row in rows if row["visual_status"].startswith("accepted")],
            "pending_case_ids": pending_rows,
            "pending_case_is_not_visual_acceptance": True,
            "rigid_motion_rows_all48_complete": True,
            "rigid_motion_product": source_ref(ROOT1305, "Root1305 rigid product"),
        },
        "baseline_boundary": {
            "physical_case_id": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE",
            "case_id": "F6_ANGULAR_RELEASE_DP025",
            "legacy_Part_column_validation_field_present": False,
            "legacy_Part_unique_count": None,
            "fresh170_or_1313_independent_baseline_Part_validation": False,
            "boundary": "historical baseline alias and Part false/null are preserved; baseline is not promoted to a new-export Part certificate",
            "native_condition_and_physical_id_fields": "historical baseline role remains separate where absent",
        },
        "scope_policy": {
            "particle_xmf_render_refs_are_each_case_local": True,
            "rigid_motion_is_joined_by_physical_case_id": True,
            "native_condition_vs_actual_converter_vs_source_plan_vs_SourceDef": "preserved as separate roles; no hash role is relabeled",
            "root1283_root709_last_case_rule": "the pending last case retains the own Root709 manifest path from its loaded wrapper; planned stale manifest paths are not used",
            "visual_status_rule": "accepted decisions supply primary visual refs; pending row supplies no primary visual refs or PNG credit",
            "PNG_scope": "explicit PNG refs are preserved only when present in immutable decision metadata; closure-only counts remain counts",
            "native_field_role_closure": "Root1320 actual native receipt roles are added only as metadata closure; baseline true field absence remains null and no native role is relabeled as visual acceptance",
            "source_scientific_payload_boundary": "source reads JSON metadata only; XMF/XML/PNG are stat-only references and H5/BI4/CSV/DAT/VTK content is not opened or hashed",
        },
        "rows": rows,
    }
    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    return catalog


if __name__ == "__main__":
    result = build()
    print(json.dumps({"status": "BUILT", "catalog": str(CATALOG), "rows": len(result["rows"]),
                      "accepted": result["delivery"]["accepted_visual_count"],
                      "pending": result["delivery"]["pending_visual_count"]}, sort_keys=True))
