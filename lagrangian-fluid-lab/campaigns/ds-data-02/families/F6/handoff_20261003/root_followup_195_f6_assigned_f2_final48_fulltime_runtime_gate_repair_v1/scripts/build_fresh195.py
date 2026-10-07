#!/usr/bin/env python3
"""Build fresh195 from F2 JSON metadata only.

The builder opens and hashes JSON metadata only.  XMF/XML/PNG references are
stat checked; H5/BI4/IBI4/CSV/DAT/VTK scientific payloads are never opened or
hashed.  The catalog is a frozen metadata product and performs no launches.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
FORBIDDEN = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
EXPECTED_FRAMES = 401
EXECUTION_RECEIPT_SCHEMAS = {"ds02.execution-receipt.v1"}


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
    if not path.is_file():
        die(f"missing JSON {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_ref(path: Path, label: str) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha_json(path, label), "role": "authoritative_json_source"}


def is_abs_path(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("/")


def clone_ref(value: Any, source_key: str, role: str) -> dict[str, Any] | None:
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        out = {"path": value["path"], "source_key": source_key, "role": role}
        if isinstance(value.get("sha256"), str):
            out["sha256"] = value["sha256"]
        elif isinstance(value.get("SHA256"), str):
            out["sha256"] = value["SHA256"]
        return out
    if is_abs_path(value):
        return {"path": value, "source_key": source_key, "role": role}
    return None


def dedup(refs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            continue
        key = (ref.get("path"), ref.get("role"))
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def find_named(value: Any, keys: tuple[str, ...], label: str, role: str, depth: int = 0) -> dict[str, Any] | None:
    """Find only explicitly named metadata fields; never choose arbitrary paths."""
    if depth > 8:
        return None
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                ref = clone_ref(value[key], f"{label}.{key}", role)
                if ref is not None:
                    return ref
        for key, child in value.items():
            if key in {"path", "sha256", "SHA256", "command", "input_hashes_at_launch", "input_hashes_after_run"}:
                continue
            ref = find_named(child, keys, f"{label}.{key}", role, depth + 1)
            if ref is not None:
                return ref
    elif isinstance(value, list):
        for index, child in enumerate(value):
            ref = find_named(child, keys, f"{label}[{index}]", role, depth + 1)
            if ref is not None:
                return ref
    return None


def find_all_named(value: Any, keys: tuple[str, ...], label: str, role: str, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 8:
        return []
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                ref = clone_ref(value[key], f"{label}.{key}", role)
                if ref is not None:
                    found.append(ref)
        for key, child in value.items():
            if key in {"path", "sha256", "SHA256", "command", "input_hashes_at_launch", "input_hashes_after_run"}:
                continue
            found.extend(find_all_named(child, keys, f"{label}.{key}", role, depth + 1))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_all_named(child, keys, f"{label}[{index}]", role, depth + 1))
    return dedup(found)


def json_probe(ref: dict[str, Any]) -> dict[str, Any]:
    path = Path(ref["path"])
    probe: dict[str, Any] = {
        "path_exists": path.is_file(),
        "suffix": path.suffix.lower(),
        "content_read_or_hashed": False,
    }
    if path.is_file():
        probe["bytes_stat"] = path.stat().st_size
    if path.suffix.lower() == ".json" and path.is_file():
        raw = path.read_bytes()
        probe["content_read_or_hashed"] = True
        probe["json_sha256"] = hashlib.sha256(raw).hexdigest()
        try:
            obj = json.loads(raw.decode("utf-8"))
            probe["json_type"] = "object" if isinstance(obj, dict) else "array" if isinstance(obj, list) else type(obj).__name__
            if isinstance(obj, dict):
                probe["top_level_keys"] = sorted(obj.keys())[:100]
                for key in ("family_id", "case_id", "physical_case_id", "status", "returncode", "frames",
                            "expected_frames", "particles", "expected_particles", "published_status", "xdmf",
                            "case_xmf", "manifest", "schema"):
                    if key in obj and isinstance(obj[key], (str, int, float, bool, type(None))):
                        probe[f"top.{key}"] = obj[key]
        except Exception as exc:
            probe["json_parse_error"] = str(exc)
        declared = ref.get("sha256")
        if isinstance(declared, str):
            probe["declared_sha256"] = declared
            probe["declared_sha256_matches_json"] = declared == probe.get("json_sha256")
    return probe


def annotate_ref(ref: dict[str, Any] | None, role: str) -> dict[str, Any] | None:
    if ref is None:
        return None
    out = copy.deepcopy(ref)
    out["role"] = role
    out["metadata_probe"] = json_probe(out)
    return out


def normalize_png(value: Any, source_key: str, role: str) -> dict[str, Any] | None:
    ref = clone_ref(value, source_key, role)
    if ref is None:
        return None
    path = Path(ref["path"])
    ref["metadata_probe"] = {
        "path_exists": path.is_file(),
        "bytes_stat": path.stat().st_size if path.is_file() else None,
        "content_read_or_hashed": False,
        "source_representation": "dict" if isinstance(value, dict) else "string",
    }
    return ref


def list_png_values(value: Any, source_key: str, role: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        ref = normalize_png(item, f"{source_key}[{index}]", role)
        if ref is not None:
            out.append(ref)
    return out


def report_outputs(report_ref: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    if not isinstance(report_ref, dict) or not isinstance(report_ref.get("path"), str):
        return [], [], None
    path = Path(report_ref["path"])
    if path.suffix.lower() != ".json" or not path.is_file():
        return [], [], None
    report = read_json(path, f"render report {path}")
    outputs = report.get("outputs") if isinstance(report, dict) else None
    if not isinstance(outputs, dict):
        return [], [], {"report_outputs_present": False, "report_path": str(path)}
    contacts: list[dict[str, Any]] = []
    keys: list[dict[str, Any]] = []
    for key in ("contact_sheets", "contact_pages"):
        contacts.extend(list_png_values(outputs.get(key), f"{path}:outputs.{key}", "contact_png"))
    for key in ("key_frames", "keyframes", "key_events"):
        keys.extend(list_png_values(outputs.get(key), f"{path}:outputs.{key}", "key_png"))
    return contacts, keys, {
        "report_outputs_present": True,
        "contact_output_count": len(contacts),
        "key_output_count": len(keys),
        "source_report_path": str(path),
        "source_report_json_sha256": sha_json(path, f"render report {path}"),
        "content_read_or_hashed": True,
        "png_content_read_or_hashed": False,
    }


def role_scope_metadata(native_refs: list[dict[str, Any]], manifest: dict[str, Any] | None) -> dict[str, Any]:
    """Record native-request versus XMF-manifest condition roles verbatim.

    Several historical F2 decisions intentionally have different native and
    XMF condition digests; the mother native request also lacks a physical
    case ID.  Preserve those facts and field absence rather than normalizing
    them into one canonical value.
    """
    native_obj: dict[str, Any] = {}
    if native_refs and isinstance(native_refs[0].get("path"), str) and Path(native_refs[0]["path"]).suffix.lower() == ".json":
        path = Path(native_refs[0]["path"])
        if path.is_file():
            obj = read_json(path, f"native receipt for role closure {path}")
            if isinstance(obj, dict):
                native_obj = obj
    native_request = native_obj.get("request") if isinstance(native_obj.get("request"), dict) else {}
    manifest_obj: dict[str, Any] = {}
    if isinstance(manifest, dict) and isinstance(manifest.get("path"), str):
        path = Path(manifest["path"])
        if path.suffix.lower() == ".json" and path.is_file():
            obj = read_json(path, f"XMF manifest for role closure {path}")
            if isinstance(obj, dict):
                manifest_obj = obj
    native_id_present = "physical_case_id" in native_request
    native_condition_present = "physical_condition_sha256" in native_request
    xmf_id_present = "physical_case_id" in manifest_obj
    xmf_condition_present = "physical_condition_sha256" in manifest_obj
    native_condition = native_request.get("physical_condition_sha256") if native_condition_present else None
    xmf_condition = manifest_obj.get("physical_condition_sha256") if xmf_condition_present else None
    if native_condition is None or xmf_condition is None:
        relation = "unknown_missing_role_value"
    elif native_condition == xmf_condition:
        relation = "equal"
    else:
        relation = "different_preserved_roles"
    return {
        "native_request_physical_case_id": native_request.get("physical_case_id") if native_id_present else None,
        "native_request_physical_case_id_field_present": native_id_present,
        "native_request_physical_condition_sha256": native_condition,
        "native_request_physical_condition_field_present": native_condition_present,
        "xmf_manifest_physical_case_id": manifest_obj.get("physical_case_id") if xmf_id_present else None,
        "xmf_manifest_physical_case_id_field_present": xmf_id_present,
        "xmf_manifest_physical_condition_sha256": xmf_condition,
        "xmf_manifest_physical_condition_field_present": xmf_condition_present,
        "native_vs_xmf_physical_condition_relation": relation,
        "role_values_are_verbatim_and_not_reconciled": True,
    }


def first_ref(sources: list[tuple[str, Any]], keys: tuple[str, ...], role: str) -> dict[str, Any] | None:
    for label, source in sources:
        ref = find_named(source, keys, label, role)
        if ref is not None:
            return ref
    return None


def all_refs(sources: list[tuple[str, Any]], keys: tuple[str, ...], role: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for label, source in sources:
        found.extend(find_all_named(source, keys, label, role))
    return dedup(found)


def fallback_ref(row: dict[str, Any] | None, key: str, role: str) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    value = row.get(key)
    if isinstance(value, list):
        value = value[0] if value else None
    return clone_ref(value, f"Root1276.actual_own_primary_rows.{key}", role)


def fallback_list(row: dict[str, Any] | None, key: str, role: str) -> list[dict[str, Any]]:
    if not isinstance(row, dict) or not isinstance(row.get(key), list):
        return []
    out: list[dict[str, Any]] = []
    for i, value in enumerate(row[key]):
        ref = clone_ref(value, f"Root1276.actual_own_primary_rows.{key}[{i}]", role)
        if ref:
            out.append(ref)
    return dedup(out)


def derive_xml_from_manifest(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if not manifest or not isinstance(manifest.get("path"), str):
        return None
    path = Path(manifest["path"])
    if path.suffix.lower() != ".json" or not path.is_file():
        return None
    obj = read_json(path, f"XMF manifest {path}")
    for key in ("xdmf", "case_xmf", "xmf", "case_xmf_path"):
        value = obj.get(key) if isinstance(obj, dict) else None
        if isinstance(value, str) and value.startswith("/"):
            return annotate_ref(
                {"path": value, "source_key": f"{manifest.get('source_key')}.declared.{key}"},
                "primary_xmf_xml_derived_from_own_manifest_json",
            )
        if isinstance(value, dict):
            ref = clone_ref(value, f"{manifest.get('source_key')}.declared.{key}", "primary_xmf_xml_derived_from_own_manifest_json")
            if ref:
                return annotate_ref(ref, "primary_xmf_xml_derived_from_own_manifest_json")
    return None


def derive_standard_output_refs_from_receipt(receipt: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Resolve fixed XMF/render output names from an own JSON receipt.

    Some accepted decisions retain only a terminal XMF or render receipt.  Its
    ``output_root`` is an authoritative worker field, so resolving the fixed
    ``xdmf/manifest.json``, ``xdmf/case.xmf`` and render report names is
    metadata-only.  This does not scan a science tree or open H5/BI4/CSV/DAT/
    VTK payloads.
    """
    if not isinstance(receipt, dict) or not isinstance(receipt.get("path"), str):
        return {}
    receipt_path = Path(receipt["path"])
    if receipt_path.suffix.lower() != ".json" or not receipt_path.is_file():
        return {}
    obj = read_json(receipt_path, f"execution receipt {receipt_path}")
    output_root = obj.get("output_root") if isinstance(obj, dict) else None
    if not isinstance(output_root, str) or not output_root.startswith("/"):
        request = obj.get("request") if isinstance(obj, dict) else None
        output_root = request.get("attempt_root") if isinstance(request, dict) else None
    if not isinstance(output_root, str) or not output_root.startswith("/"):
        return {}
    root = Path(output_root)
    candidates = {
        "manifest": root / "xdmf/manifest.json",
        "xml": root / "xdmf/case.xmf",
        "render_report": root / "render/paraview-full-animation-report.json",
        "publish_receipt": root / "render/render-publish-receipt.json",
    }
    out: dict[str, dict[str, Any]] = {}
    for key, path in candidates.items():
        if path.is_file():
            out[key] = annotate_ref(
                {"path": str(path), "source_key": f"{receipt.get('source_key', receipt_path)}.output_root.{key}"},
                f"derived_from_own_execution_receipt_output_root_{key}",
            ) or {}
    return out


def select_accepted(decision: dict[str, Any], decision_ref: dict[str, Any], first24_row: dict[str, Any] | None) -> dict[str, Any]:
    evidence = decision.get("actual_completed_metadata_evidence") if isinstance(decision.get("actual_completed_metadata_evidence"), dict) else {}
    bindings = decision.get("bindings") if isinstance(decision.get("bindings"), dict) else {}
    sources = [
        ("decision.actual_completed_metadata_evidence", evidence),
        ("decision.bindings", bindings),
        ("decision.trajectory_binding", decision.get("trajectory_binding")),
        ("decision.actual_scope_schema_closure", decision.get("actual_scope_schema_closure")),
        ("decision", decision),
    ]

    # Modern decisions put the case-local receipts under four role objects:
    # evidence.native, evidence.typed, evidence.xmf, and evidence.render.
    # Resolve those role objects before the recursive legacy search.  This is
    # important because a recursive first-match can otherwise select a nested
    # historical receipt, owner JSON, or source-plan reference from another
    # namespace while still looking syntactically valid.
    actual_receipts = evidence.get("actual_completed_receipts") if isinstance(evidence.get("actual_completed_receipts"), dict) else {}
    native_role = evidence.get("native") if isinstance(evidence.get("native"), dict) else actual_receipts.get("native")
    typed_role = evidence.get("typed") if isinstance(evidence.get("typed"), dict) else actual_receipts.get("typed")
    xmf_role = evidence.get("xmf") if isinstance(evidence.get("xmf"), dict) else actual_receipts.get("xmf")
    render_role = evidence.get("render") if isinstance(evidence.get("render"), dict) else actual_receipts.get("render")

    def role_first(role_label: str, role_value: Any, keys: tuple[str, ...], role: str) -> dict[str, Any] | None:
        if not isinstance(role_value, dict):
            return None
        return first_ref([(role_label, role_value)], keys, role)

    manifest = role_first(
        "decision.actual_completed_metadata_evidence.xmf",
        xmf_role,
        ("manifest", "xmf_manifest", "actual_xmf_manifest", "dynamic_xdmf_manifest", "normal_manifest"),
        "primary_xmf_manifest",
    )
    if manifest is None:
        manifest = first_ref(sources, ("xmf_manifest", "actual_xmf_manifest", "dynamic_xdmf_manifest", "normal_manifest"), "primary_xmf_manifest")
    if manifest is None:
        manifest = fallback_ref(first24_row, "actual_xmf_manifest", "primary_xmf_manifest")
    manifest = annotate_ref(manifest, "primary_xmf_manifest")

    xml = role_first(
        "decision.actual_completed_metadata_evidence.xmf",
        xmf_role,
        ("xmf_xml", "actual_xmf_xml", "dynamic_xdmf", "normal_xdmf", "case_xmf"),
        "primary_xmf_xml",
    )
    if xml is None:
        xml = first_ref(sources, ("xmf_xml", "actual_xmf_xml", "dynamic_xdmf", "normal_xdmf", "case_xmf", "XMF_XML"), "primary_xmf_xml")
    if xml is None:
        xml = fallback_ref(first24_row, "actual_xmf_xml", "primary_xmf_xml")
    xml = annotate_ref(xml, "primary_xmf_xml")
    if xml is None:
        xml = derive_xml_from_manifest(manifest)

    report = role_first(
        "decision.actual_completed_metadata_evidence.render",
        render_role,
        ("report", "render_report", "actual_render_report", "animation_integrity_report", "full_render_report"),
        "primary_render_report",
    )
    if report is None:
        report = first_ref(sources, ("render_report", "actual_render_report", "animation_integrity_report", "full_render_report"), "primary_render_report")
    if report is None:
        report = fallback_ref(first24_row, "actual_render_report", "primary_render_report")
    report = annotate_ref(report, "primary_render_report")

    receipt = role_first(
        "decision.actual_completed_metadata_evidence.render",
        render_role,
        ("execution_receipt", "receipt", "render_receipt", "actual_render_receipt", "animation_receipt", "full_render_receipt", "path"),
        "primary_render_receipt",
    )
    if receipt is None:
        receipt = first_ref(sources, ("render_receipt", "actual_render_receipt", "animation_receipt", "full_render_receipt"), "primary_render_receipt")
    if receipt is None:
        receipt = fallback_ref(first24_row, "render_receipt_refs", "primary_render_receipt")
    receipt = annotate_ref(receipt, "primary_render_receipt")

    # Preserve uppercase compact schemas used by several accepted decisions,
    # then derive the fixed worker outputs from the own terminal receipts if
    # the decision stored only those receipts.
    if manifest is None:
        manifest = first_ref(
            [("decision.actual_completed_metadata_evidence", evidence)],
            ("XMF_manifest", "xmf_manifest", "actual_xmf_manifest", "dynamic_xdmf_manifest", "normal_manifest"),
            "primary_xmf_manifest",
        )
        manifest = annotate_ref(manifest, "primary_xmf_manifest")
    if xml is None:
        xml = first_ref(
            [("decision.actual_completed_metadata_evidence", evidence)],
            ("XMF_XML", "xmf_xml", "actual_xmf_xml", "dynamic_xdmf", "normal_xdmf", "case_xmf"),
            "primary_xmf_xml",
        )
        xml = annotate_ref(xml, "primary_xmf_xml")

    xmf_receipt_for_outputs = role_first(
        "decision.actual_completed_metadata_evidence.xmf",
        xmf_role,
        ("execution_receipt", "receipt", "xmf_receipt", "path"),
        "xmf_receipt",
    )
    render_receipt_for_outputs = role_first(
        "decision.actual_completed_metadata_evidence.render",
        render_role,
        ("execution_receipt", "receipt", "render_receipt", "path"),
        "render_receipt",
    )
    xmf_outputs = derive_standard_output_refs_from_receipt(xmf_receipt_for_outputs)
    render_outputs = derive_standard_output_refs_from_receipt(render_receipt_for_outputs or receipt)
    if manifest is None:
        manifest = annotate_ref(xmf_outputs.get("manifest"), "primary_xmf_manifest")
    if xml is None:
        xml = annotate_ref(xmf_outputs.get("xml"), "primary_xmf_xml")
    if xml is None:
        xml = derive_xml_from_manifest(manifest)
    if report is None:
        report = first_ref(
            [("decision.actual_completed_metadata_evidence", evidence)],
            ("animation_report", "render_report", "actual_render_report", "animation_integrity_report", "full_render_report"),
            "primary_render_report",
        )
        report = annotate_ref(report, "primary_render_report")
    if report is None:
        report = annotate_ref(render_outputs.get("render_report"), "primary_render_report")
    if receipt is None:
        receipt = annotate_ref(render_outputs.get("receipt"), "primary_render_receipt")

    native = []
    native_role_ref = role_first(
        "decision.actual_completed_metadata_evidence.native",
        native_role,
        ("execution_receipt", "receipt", "native_receipt", "full_native_receipt", "path"),
        "native_receipt",
    )
    if native_role_ref is not None:
        native.append(native_role_ref)
    native.extend(all_refs(sources, ("native_receipt", "full_native_receipt"), "native_receipt"))
    native += all_refs(sources, ("native",), "native_receipt")
    if not native:
        native = fallback_list(first24_row, "native_refs", "native_receipt")
    native = [annotate_ref(x, "native_receipt") for x in dedup(native)]

    typed = []
    typed_role_receipt = role_first(
        "decision.actual_completed_metadata_evidence.typed",
        typed_role,
        ("execution_receipt", "receipt", "typed_receipt", "typed_conversion_receipt", "path"),
        "typed_receipt",
    )
    if typed_role_receipt is not None:
        typed.append(typed_role_receipt)
    typed_role_report = role_first(
        "decision.actual_completed_metadata_evidence.typed",
        typed_role,
        ("report", "typed_report", "conversion_report", "typed_conversion_report"),
        "typed_report",
    )
    if typed_role_report is not None:
        typed.append(typed_role_report)
    typed += all_refs(sources, ("typed_receipt", "typed_conversion_receipt"), "typed_receipt")
    typed += all_refs(sources, ("typed_report", "conversion_report", "typed_conversion_report"), "typed_report")
    if not typed:
        typed = fallback_list(first24_row, "typed_refs", "typed_receipt_or_report")
    typed = [annotate_ref(x, "typed_receipt_or_report") for x in dedup(typed)]

    gencase = all_refs(sources, ("gencase_receipt", "generated_xml", "generated_definition_xml", "prepared_input_report"), "gencase_or_definition")
    if not gencase:
        gencase = fallback_list(first24_row, "gencase_or_definition_refs", "gencase_or_definition")
    gencase = [annotate_ref(x, "gencase_or_definition") for x in dedup(gencase)]

    qa = all_refs(sources, ("initial_native_qa", "native_initial_qa", "initial_qa", "artifact_audit_receipt", "audit_report", "chain_audit"), "initial_qa_or_audit")
    if not qa:
        qa = fallback_list(first24_row, "initial_qa_or_audit_refs", "initial_qa_or_audit")
    qa = [annotate_ref(x, "initial_qa_or_audit") for x in dedup(qa)]

    owners = all_refs(sources, ("owner_metadata", "physical_binding_semantic_source", "source_definition", "source_plan_path", "source_condition_template"), "owner_or_source")
    if not owners:
        owners = fallback_list(first24_row, "owner_or_source_refs", "owner_or_source")
    owners = [annotate_ref(x, "owner_or_source") for x in dedup(owners)]

    contacts: list[dict[str, Any]] = []
    keys: list[dict[str, Any]] = []
    png_sources: list[dict[str, Any]] = []
    verified = decision.get("verified_PNG_hashes")
    if isinstance(verified, dict):
        contacts = list_png_values(verified.get("contact_sheets"), "decision.verified_PNG_hashes.contact_sheets", "contact_png")
        keys = list_png_values(verified.get("key_frames"), "decision.verified_PNG_hashes.key_frames", "key_png")
        if not keys:
            keys = list_png_values(verified.get("keyframes"), "decision.verified_PNG_hashes.keyframes", "key_png")
        png_sources.append({"source": "decision.verified_PNG_hashes", "metadata": {k: verified.get(k) for k in ("computed_after_view_image", "reviewed_contact_sheet_indices", "reviewed_key_frame_indices") if k in verified}})
    if not contacts:
        contacts = list_png_values(decision.get("contact_sheets"), "decision.contact_sheets", "contact_png")
        if contacts:
            png_sources.append({"source": "decision.contact_sheets"})
    if not keys:
        keys = list_png_values(decision.get("keyframes"), "decision.keyframes", "key_png")
        keys += list_png_values(decision.get("key_events"), "decision.key_events", "key_png")
        if keys:
            png_sources.append({"source": "decision.keyframes_or_key_events"})
    # Some accepted decisions carry their published PNG references directly
    # on the case-local render role.  Accept both the legacy string form and
    # the newer {path, sha256} form, but never infer frame-directory contents.
    if render_role is not None:
        if not contacts:
            for key in ("contact_sheets", "contact_pages"):
                contacts.extend(list_png_values(render_role.get(key), f"decision.actual_completed_metadata_evidence.render.{key}", "contact_png"))
            if contacts:
                png_sources.append({"source": "actual_completed_metadata_evidence.render.contact_paths"})
        if not keys:
            for key in ("key_frames", "keyframes", "key_events"):
                keys.extend(list_png_values(render_role.get(key), f"decision.actual_completed_metadata_evidence.render.{key}", "key_png"))
            if keys:
                png_sources.append({"source": "actual_completed_metadata_evidence.render.key_paths"})
    rcontacts, rkeys, report_meta = report_outputs(report)
    if not contacts and rcontacts:
        contacts = rcontacts
        png_sources.append({"source": "actual_render_report.outputs.contact_sheets", "metadata": report_meta})
    if not keys and rkeys:
        keys = rkeys
        png_sources.append({"source": "actual_render_report.outputs.key_frames", "metadata": report_meta})
    if report_meta is not None and not keys:
        png_sources.append({"source": "actual_render_report.outputs", "metadata": report_meta, "key_path_boundary": "no named key path was available; no frame-directory inference"})
    if not contacts:
        contacts = [normalize_png(v, f"Root1276.actual_own_primary_rows.contact_png_refs[{i}]", "contact_png") for i, v in enumerate(first24_row.get("contact_png_refs", []) if isinstance(first24_row, dict) else [])]
        contacts = [v for v in contacts if v]
    if not keys and isinstance(first24_row, dict):
        keys = [normalize_png(v, f"Root1276.actual_own_primary_rows.key_png_refs[{i}]", "key_png") for i, v in enumerate(first24_row.get("key_png_refs", []))]
        keys = [v for v in keys if v]

    explicit_role_keys = (
        "actual_native_XMF_plan_field_namespaces",
        "native_and_XMF_plan_field_namespaces",
        "native_and_XMF_plan_field_observations",
        "source_plan_physical_condition_sha256",
        "source_plan_condition_sha256",
        "native_source_plan_physical_condition_sha256",
        "native_source_plan_condition_sha256",
        "xmf_source_plan_physical_condition_sha256",
        "xmf_source_plan_condition_sha256",
        "source_canonical_physical_condition_sha256",
        "actual_converter_scope_sha256",
        "producer_scope_schema_verified_from_actual_report",
        "scope_separation",
    )
    decision_plan_fields = {key: copy.deepcopy(decision[key]) for key in explicit_role_keys if key in decision}
    evidence_role_keys = sorted(actual_receipts.keys()) if isinstance(actual_receipts, dict) else []
    evidence_role_keys = sorted(set(evidence_role_keys) | set(evidence.keys())) if isinstance(evidence, dict) else evidence_role_keys

    return {
        "accepted_decision": copy.deepcopy(decision_ref),
        "metadata_role_presence": {
            "decision_actual_completed_metadata_evidence_keys": evidence_role_keys,
            "decision_bindings_keys": sorted(bindings.keys()) if isinstance(bindings, dict) else [],
            "decision_explicit_plan_and_scope_fields": decision_plan_fields,
            "native_vs_xmf_plan_field_namespaces_verbatim": copy.deepcopy(
                decision.get("actual_native_XMF_plan_field_namespaces", decision.get("native_and_XMF_plan_field_namespaces", decision.get("native_and_XMF_plan_field_observations")))
            ),
            "native_request_and_xmf_manifest_field_presence_is_not_filled": True,
            "selected_primary_refs_are_role_labeled": True,
            "runtime_status_returncode_are_only_from_selected_json_metadata_probes": True,
            "scientific_payload_refs_are_rejected_before_open_or_hash": True,
        },
        "accepted_decision_metadata": {
            "status": decision.get("status"),
            "family_id": decision.get("family_id"),
            "case_id": decision.get("case_id"),
            "physical_case_id": decision.get("physical_case_id"),
            "at_utc": decision.get("at_utc", decision.get("reviewed_at_utc")),
            "frames": decision.get("actual_frames", decision.get("full_native_frames", decision.get("frames"))),
            "particles": decision.get("actual_particles", decision.get("particles")),
            "actual_last_time_s": decision.get("actual_last_time_s"),
            "precision_status": decision.get("precision_status", decision.get("numerical_precision_status")),
            "q_n": decision.get("q_n_granted", decision.get("q_n")),
            "q_e": decision.get("q_e_granted", decision.get("q_e")),
            "independent_case_increment": decision.get("independent_case_increment", decision.get("independent_physical_case_count_increment")),
        },
        "actual_xmf_manifest": manifest,
        "actual_xmf_xml": xml,
        "actual_render_report": report,
        "actual_render_receipt": receipt,
        "native_refs": native,
        "typed_refs": typed,
        "gencase_or_definition_refs": gencase,
        "initial_qa_or_audit_refs": qa,
        "owner_or_source_refs": owners,
        "contact_png_refs": contacts,
        "key_png_refs": keys,
        "png_evidence_sources": png_sources,
        "primary_visual_evidence": {
            "primary_refs_selected_from_own_decision_or_first24_own_metadata": True,
            "named_key_png_paths_available": bool(keys),
            "key_png_paths_absent_reason": None if keys else "immutable decision/render metadata did not enumerate named key PNG paths; no frame-directory inference",
            "PNG_content_read_or_hashed": False,
            "contacts_and_keys_are_refs_only": True,
        },
        "scope_roles": {
            "physical_condition_sha256": decision.get("physical_condition_sha256"),
            "actual_converter_scope_sha256": decision.get("actual_converter_scope_sha256"),
            "canonical_scope_sha256": decision.get("canonical_scope_sha256"),
            "source_plan_condition_sha256": decision.get("source_plan_condition_sha256"),
            "source_scope_fields": copy.deepcopy(decision.get("scope_separation")),
            "native_request_scope": copy.deepcopy(decision.get("native_request_scope")),
        },
        "native_vs_xmf_role_metadata": role_scope_metadata(native, manifest),
        "decision_visual_metadata": {
            "visual_reviewer": decision.get("visual_reviewer"),
            "agent_personally_viewed_all_contacts_and_keys": decision.get("agent_personally_viewed_all_contacts_and_keys"),
            "main_personally_viewed_pngs": decision.get("main_personally_viewed_pngs", decision.get("main_personally_viewed_PNGs")),
            "review_method": decision.get("review_method"),
            "visual_observations": decision.get("visual_observations", decision.get("agent_observations")),
            "source_review_commit": decision.get("source_review_commit"),
        },
    }


def select_pending(progress: dict[str, Any], ready: dict[str, Any], readiness_ref: dict[str, Any]) -> dict[str, Any]:
    evidence = ready.get("actual_metadata_evidence") if isinstance(ready.get("actual_metadata_evidence"), dict) else {}
    native = first_ref([("source166.actual_metadata_evidence", evidence)], ("native_receipt", "native"), "pending_native_receipt")
    typed = all_refs([("source166.actual_metadata_evidence", evidence)], ("typed_receipt", "typed_report"), "pending_typed")
    xmf = all_refs([("source166.actual_metadata_evidence", evidence)], ("xmf_receipt", "xmf_manifest", "xmf_xml"), "pending_xmf")
    audit = all_refs([("source166.actual_metadata_evidence", evidence)], ("artifact_audit_receipt", "audit_report"), "pending_artifact_audit")
    return {
        "accepted_decision": None,
        "primary_particle_xmf_render_refs": None,
        "primary_png_refs": None,
        "pending_readiness_source": copy.deepcopy(readiness_ref),
        "source166_case_metadata": copy.deepcopy(ready),
        "native_metadata_refs": [annotate_ref(native, "pending_native_receipt")] if native else [],
        "typed_metadata_refs": [annotate_ref(x, "pending_typed_receipt_or_report") for x in typed],
        "xmf_metadata_refs": [annotate_ref(x, "pending_xmf_receipt_manifest_or_xml") for x in xmf],
        "artifact_audit_metadata_refs": [annotate_ref(x, "pending_artifact_audit") for x in audit],
        "pending_status_boundary": {
            "visual_credit": 0,
            "no_accepted_visual_decision": True,
            "native_typed_xmf_are_pipeline_readiness_evidence_only": True,
            "original_pending154_typed_receipt_not_promoted": bool(ready.get("original_typed_receipt_still_unknown", False)),
            "outer_envelope_stale": ready.get("outer_envelope_stale"),
            "outer_expected_frames": progress.get("expected_frames"),
            "outer_expected_particles": progress.get("expected_particles"),
            "source_plan_condition_field_present": (ready.get("source_scope_roles_preserved") or {}).get("manifest_source_plan_condition_sha256_key_present"),
            "source_plan_condition_sha256": (ready.get("source_scope_roles_preserved") or {}).get("manifest_source_plan_condition_sha256"),
            "current_controller_observation": copy.deepcopy(progress.get("current_controller_observation")),
            "latest_registered_render_request": copy.deepcopy(progress.get("latest_registered_render_request")),
        },
        "scope_roles": {
            "source_scope_roles_preserved": copy.deepcopy(ready.get("source_scope_roles_preserved")),
            "actual_XMF_exact_plan_field_namespaces": copy.deepcopy(ready.get("actual_XMF_exact_plan_field_namespaces")),
            "source_native_scope_roles_preserved": copy.deepcopy(ready.get("source_native_scope_roles_preserved")),
            "declared_actual_converter_scope_sha256": progress.get("declared_actual_converter_scope_sha256"),
            "declared_render_request_condition_sha256": progress.get("declared_render_request_condition_sha256"),
        },
    }


def _sha_json_ref(ref: Any, label: str) -> str | None:
    """Hash only a JSON metadata reference and return its observed SHA."""
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        return None
    path = Path(ref["path"])
    if path.suffix.lower() != ".json" or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _merge_missing(primary: dict[str, Any], fallback: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Fill only genuinely absent metadata from the frozen legacy catalog.

    Current accepted decisions are authoritative.  The old catalog is a
    bounded compatibility source for rows whose current decision does not
    enumerate an otherwise already-published producer reference; it never
    replaces a current path, SHA, status, or role value.
    """
    out = copy.deepcopy(primary)
    for key, value in fallback.items():
        if key in {"accepted_decision", "accepted_decision_metadata", "scope_roles", "native_vs_xmf_role_metadata"}:
            continue
        missing = key not in out or out.get(key) in (None, [], {}, "")
        if missing and value not in (None, [], {}, ""):
            out[key] = copy.deepcopy(value)
            out.setdefault("compatibility_fallbacks", []).append({"field": key, "source": source})
    return out


def _repair_report_digest(visual: dict[str, Any], decision: dict[str, Any]) -> None:
    """Apply only a recorded source209 digest transcription correction.

    A stale report SHA is never silently trusted.  If the decision carries the
    Root1348 correction sidecar, the observed JSON bytes must match that
    sidecar's corrected digest before the ref is replaced in the derived
    metadata product.  The original decision bytes remain untouched.
    """
    ref = visual.get("actual_render_report")
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        return
    path = Path(ref["path"])
    if path.suffix.lower() != ".json" or not path.is_file():
        return
    observed = sha_json(path, f"render report {path}")
    declared = ref.get("sha256")
    if declared in (None, observed):
        if declared is None:
            ref["sha256"] = observed
            ref["digest_source"] = "observed_json_metadata_bytes"
        return
    corrections = decision.get("source_render_report_digest_transcription_corrections")
    if not isinstance(corrections, list):
        raise RuntimeError(f"render report SHA mismatch without correction sidecar: {path}")
    matching = []
    for correction in corrections:
        if not isinstance(correction, dict):
            continue
        if correction.get("path") == str(path) or correction.get("source_file") in {"metadata/upstream-evidence.json", "metadata/actual-render-metadata.json"}:
            matching.append(correction)
    if not any(c.get("actual_report_sha256_from_ownQI_and_atomic_publish") == observed for c in matching):
        raise RuntimeError(f"Root1348 correction does not match observed report SHA: {path}")
    ref["sha256"] = observed
    probe = ref.get("metadata_probe")
    if isinstance(probe, dict):
        probe["declared_sha256"] = observed
        probe["declared_sha256_matches_json"] = True
    ref["digest_correction"] = {
        "role": "Root1348_actual_report_digest_correction",
        "original_declared_sha256": declared,
        "observed_corrected_sha256": observed,
        "source_bytes_preserved": True,
    }



def _json_object(ref: Any, label: str) -> tuple[dict[str, Any] | None, str | None]:
    """Read one JSON metadata ref, never a scientific payload."""
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        return None, "missing_path_ref"
    path = Path(ref["path"])
    if path.suffix.lower() != ".json":
        return None, "not_json_metadata"
    if path.suffix.lower() in FORBIDDEN:
        return None, f"scientific_payload_suffix:{path.suffix.lower()}"
    if not path.is_file():
        return None, "path_not_present"
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"invalid_json:{exc}"
    if not isinstance(obj, dict):
        return None, "json_metadata_not_object"
    declared = ref.get("sha256")
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if declared is not None and declared != observed:
        return None, "declared_json_sha_mismatch"
    return obj, None


def _nested_scalar(obj: Any, key: str) -> Any:
    """Find a case/runtime scalar only in named execution metadata objects."""
    if not isinstance(obj, dict):
        return None
    for source in (obj, obj.get("request"), obj.get("execution"), obj.get("metadata"), obj.get("producer")):
        if isinstance(source, dict) and key in source:
            return source[key]
    return None


def _receipt_binding(obj: dict[str, Any]) -> dict[str, Any]:
    case_id = _nested_scalar(obj, "case_id")
    physical_id = _nested_scalar(obj, "physical_case_id")
    return {
        "case_id": case_id,
        "physical_case_id": physical_id,
        "case_id_field_present": case_id is not None,
        "physical_case_id_field_present": physical_id is not None,
    }


def _execution_receipt_certificate(ref: Any, expected_case_id: str | None = None,
                                   expected_physical_id: str | None = None,
                                   role: str = "execution_receipt") -> dict[str, Any]:
    """Verify a genuine terminal receipt and its case binding.

    A runner request is deliberately rejected even when it says completed in a
    descriptive status string.  This is the role error fixed for the four
    Root1330 rows.
    """
    out: dict[str, Any] = {"role": role, "path": ref.get("path") if isinstance(ref, dict) else None}
    obj, reason = _json_object(ref, role)
    if obj is None:
        out.update({"terminal_completed_returncode_zero": False, "reason": reason})
        return out
    schema = obj.get("schema")
    status = obj.get("status")
    returncode_present = "returncode" in obj
    returncode = obj.get("returncode")
    binding = _receipt_binding(obj)
    request = obj.get("request") if isinstance(obj.get("request"), dict) else {}
    request_schema = request.get("schema") if isinstance(request, dict) else None
    # Execution receipts legitimately embed the schema of the request that
    # launched them.  Reject only a top-level runner-request object (or a
    # non-receipt wrapper), never an embedded request.schema.
    is_request_schema = (isinstance(schema, str) and "runner-request" in schema.lower()) or (schema not in EXECUTION_RECEIPT_SCHEMAS and isinstance(request_schema, str) and "runner-request" in request_schema.lower())
    case_ok = expected_case_id is None or binding["case_id"] == expected_case_id
    physical_ok = expected_physical_id is None or binding["physical_case_id"] == expected_physical_id
    terminal = (
        schema in EXECUTION_RECEIPT_SCHEMAS
        and not is_request_schema
        and status == "completed"
        and returncode_present
        and returncode == 0
        and case_ok
        and physical_ok
    )
    out.update({
        "schema": schema,
        "request_schema": request_schema,
        "status": status,
        "returncode_field_present": returncode_present,
        "returncode": returncode,
        "is_runner_request_schema": is_request_schema,
        "binding": binding,
        "expected_case_id": expected_case_id,
        "expected_physical_case_id": expected_physical_id,
        "case_binding_matches": case_ok,
        "physical_case_binding_matches": physical_ok,
        "terminal_completed_returncode_zero": terminal,
        "reason": None if terminal else "receipt_is_not_a_case-bound_terminal_execution_receipt",
    })
    return out


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _report_certificate(report_ref: Any, expected_case_id: str | None = None,
                         expected_particles: int | None = None) -> dict[str, Any]:
    """Validate producer render metadata without opening any scientific data."""
    out: dict[str, Any] = {"path": report_ref.get("path") if isinstance(report_ref, dict) else None}
    obj, reason = _json_object(report_ref, "render_report")
    if obj is None:
        out.update({"fulltime_metadata_certificate_verified": False, "reasons": [reason]})
        return out
    reasons: list[str] = []
    schema_ok = obj.get("schema") == "ds02.stage1.paraview-full-animation-integrity.v1"
    if not schema_ok:
        reasons.append("render_report_schema_mismatch")
    if expected_case_id is not None and obj.get("case_id") not in (None, expected_case_id):
        reasons.append("render_report_case_id_mismatch")
    if expected_case_id is not None and isinstance(obj.get("request_case_id"), str) and obj.get("request_case_id") != expected_case_id:
        reasons.append("render_report_request_case_id_mismatch")
    if obj.get("frames") != EXPECTED_FRAMES or obj.get("source_frames") != EXPECTED_FRAMES:
        reasons.append("render_report_frame_count_not_401")
    if obj.get("all_frames_rendered") is not True:
        reasons.append("render_report_all_frames_rendered_not_true")
    if obj.get("actual_times_preserved_exactly") is not True:
        reasons.append("render_report_actual_times_not_preserved")
    if obj.get("native_identity_axis_preserved") is not True:
        reasons.append("render_report_identity_axis_not_preserved")
    if obj.get("nonfinite_active_states") not in (0, 0.0):
        reasons.append("render_report_nonfinite_active_states_nonzero")
    selection = obj.get("frame_selection")
    if not isinstance(selection, list) or len(selection) != EXPECTED_FRAMES or selection != list(range(EXPECTED_FRAMES)):
        reasons.append("render_report_frame_selection_not_0_to_400")
    diagnostics = obj.get("frame_diagnostics")
    times: list[float] = []
    missing_total = 0
    if not isinstance(diagnostics, list) or len(diagnostics) != EXPECTED_FRAMES:
        reasons.append("render_report_frame_diagnostics_not_401")
    else:
        for index, diagnostic in enumerate(diagnostics):
            if not isinstance(diagnostic, dict):
                reasons.append(f"frame_diagnostic_{index}_not_object")
                continue
            if diagnostic.get("frame") != index:
                reasons.append(f"frame_diagnostic_{index}_identity_mismatch")
            time_value = diagnostic.get("actual_time_s")
            if not _finite_number(time_value):
                reasons.append(f"frame_diagnostic_{index}_time_not_finite")
            else:
                times.append(float(time_value))
            if diagnostic.get("finite_positions_active") is not True:
                reasons.append(f"frame_diagnostic_{index}_positions_not_finite")
            if diagnostic.get("identity_axis_preserved") is not True:
                reasons.append(f"frame_diagnostic_{index}_identity_axis_not_preserved")
            fields = diagnostic.get("finite_fields")
            if not isinstance(fields, dict):
                reasons.append(f"frame_diagnostic_{index}_finite_fields_missing")
            else:
                for field in ("mass", "velocity", "density", "pressure"):
                    value = fields.get(field)
                    if not isinstance(value, dict) or value.get("finite_active") is not True or value.get("nonfinite_active") not in (0, 0.0):
                        reasons.append(f"frame_diagnostic_{index}_{field}_not_finite")
            missing = diagnostic.get("missing", 0)
            if not isinstance(missing, int) or missing < 0:
                reasons.append(f"frame_diagnostic_{index}_missing_count_invalid")
            else:
                missing_total += missing
            type_counts = diagnostic.get("type_counts_active")
            if not isinstance(type_counts, dict):
                reasons.append(f"frame_diagnostic_{index}_type_counts_missing")
            elif any(not isinstance(type_counts.get(key), (int, float)) or isinstance(type_counts.get(key), bool) or type_counts.get(key) < 0 for key in ("fixed", "moving", "floating", "fluid", "unknown")):
                reasons.append(f"frame_diagnostic_{index}_type_counts_invalid")
            elif expected_particles is not None:
                type_total = sum(type_counts.get(key, 0) for key in ("fixed", "moving", "floating", "fluid", "unknown"))
                if type_total != diagnostic.get("active"):
                    reasons.append(f"frame_diagnostic_{index}_type_counts_do_not_sum_to_active")
                if diagnostic.get("active") + diagnostic.get("missing", 0) != expected_particles:
                    reasons.append(f"frame_diagnostic_{index}_active_plus_missing_not_expected_particles")
        if len(times) == EXPECTED_FRAMES and any(not (times[i] < times[i + 1]) for i in range(len(times) - 1)):
            reasons.append("render_report_times_not_strictly_increasing")
    outputs = obj.get("outputs")
    contact_count = len(outputs.get("contact_sheets", [])) if isinstance(outputs, dict) and isinstance(outputs.get("contact_sheets"), list) else 0
    key_count = len(outputs.get("key_frames", [])) if isinstance(outputs, dict) and isinstance(outputs.get("key_frames"), list) else 0
    if contact_count == 0:
        reasons.append("render_report_contact_sheets_missing")
    out.update({
        "schema": obj.get("schema"),
        "frames": obj.get("frames"),
        "source_frames": obj.get("source_frames"),
        "contact_sheet_count": contact_count,
        "key_frame_count": key_count,
        "actual_times": times,
        "first_time_s": times[0] if times else None,
        "last_time_s": times[-1] if times else None,
        "missing_particle_frame_events": missing_total,
        "fulltime_metadata_certificate_verified": not reasons,
        "reasons": reasons,
    })
    return out


def _manifest_certificate(manifest_ref: Any, expected_case_id: str | None = None,
                          expected_physical_id: str | None = None,
                          expected_particles: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"path": manifest_ref.get("path") if isinstance(manifest_ref, dict) else None}
    obj, reason = _json_object(manifest_ref, "xmf_manifest")
    if obj is None:
        out.update({"verified": False, "reasons": [reason]})
        return out
    reasons: list[str] = []
    for key, expected in (("case_id", expected_case_id), ("physical_case_id", expected_physical_id)):
        if expected is not None and obj.get(key) not in (None, expected):
            reasons.append(f"manifest_{key}_mismatch")
    frame_values = [obj.get(key) for key in ("actual_frame_count", "expected_frames", "frames") if obj.get(key) is not None]
    if not frame_values or any(value != EXPECTED_FRAMES for value in frame_values if isinstance(value, (int, float))):
        reasons.append("manifest_frame_count_not_401")
    dimension_values = [obj.get(key) for key in ("actual_dimension", "expected_dimension", "dimension", "velocity_vector_dimension") if obj.get(key) is not None]
    vector_contract = obj.get("native_vector_contract")
    if not dimension_values or any(value != 3 for value in dimension_values if isinstance(value, (int, float))):
        if not (obj.get("velocity_vector_dimension") == 3 and isinstance(vector_contract, str) and "N3" in vector_contract):
            reasons.append("manifest_dimension_not_3")
    particle_values = [obj.get(key) for key in ("actual_particles", "expected_particles", "particles") if obj.get(key) is not None]
    if expected_particles is not None and (not particle_values or any(value != expected_particles for value in particle_values if isinstance(value, (int, float)))):
        reasons.append("manifest_particle_count_mismatch")
    if obj.get("actual_partvtk_passed") is False:
        reasons.append("manifest_partvtk_not_passed")
    typed_status = obj.get("actual_typed_status")
    if isinstance(typed_status, str) and not typed_status.startswith("completed"):
        reasons.append("manifest_typed_status_not_completed")
    if obj.get("xmf_shape_contract", {}).get("particle_axis_preserved") is False if isinstance(obj.get("xmf_shape_contract"), dict) else False:
        reasons.append("manifest_particle_axis_not_preserved")
    out.update({
        "case_id": obj.get("case_id"),
        "physical_case_id": obj.get("physical_case_id"),
        "actual_frame_count": obj.get("actual_frame_count", obj.get("frames")),
        "actual_dimension": obj.get("actual_dimension", obj.get("dimension")),
        "actual_particles": obj.get("actual_particles", obj.get("particles")),
        "actual_partvtk_passed": obj.get("actual_partvtk_passed"),
        "actual_typed_status": typed_status,
        "verified": not reasons,
        "reasons": reasons,
    })
    return out


def _xml_certificate(xml_ref: Any, expected_case_id: str | None = None,
                     expected_particles: int | None = None,
                     expected_times: list[float] | None = None) -> dict[str, Any]:
    """Parse only XMF/XML metadata; never follows HDF/BI4 payload references."""
    out: dict[str, Any] = {"path": xml_ref.get("path") if isinstance(xml_ref, dict) else None}
    if not isinstance(xml_ref, dict) or not isinstance(xml_ref.get("path"), str):
        out.update({"verified": False, "reasons": ["missing_xml_ref"]})
        return out
    path = Path(xml_ref["path"])
    if path.suffix.lower() not in {".xml", ".xmf"} or path.suffix.lower() in FORBIDDEN or not path.is_file():
        out.update({"verified": False, "reasons": ["xml_missing_or_non_xmf_suffix"]})
        return out
    reasons: list[str] = []
    frame_times: list[float] = []
    frame_count = 0
    vector_shape_count = 0
    topology_count_ok = 0
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        out.update({"verified": False, "reasons": [f"xml_parse_error:{exc}"]})
        return out
    root_name = root.tag.rsplit("}", 1)[-1]
    if root_name != "Xdmf":
        reasons.append("xml_root_not_Xdmf")
    for grid in root.iter():
        if grid.tag.rsplit("}", 1)[-1] != "Grid" or grid.attrib.get("GridType") != "Uniform":
            continue
        frame_count += 1
        time_node = next((node for node in list(grid) if node.tag.rsplit("}", 1)[-1] == "Time"), None)
        value = time_node.attrib.get("Value") if time_node is not None else None
        try:
            frame_times.append(float(value))
        except (TypeError, ValueError):
            reasons.append(f"xml_frame_{frame_count - 1}_time_invalid")
        topology = next((node for node in list(grid) if node.tag.rsplit("}", 1)[-1] == "Topology"), None)
        if topology is None:
            reasons.append(f"xml_frame_{frame_count - 1}_topology_missing")
        elif expected_particles is not None and topology.attrib.get("NumberOfElements") != str(expected_particles):
            reasons.append(f"xml_frame_{frame_count - 1}_topology_count_mismatch")
        else:
            topology_count_ok += 1
        geometry = next((node for node in list(grid) if node.tag.rsplit("}", 1)[-1] == "Geometry"), None)
        if geometry is None:
            reasons.append(f"xml_frame_{frame_count - 1}_geometry_missing")
        else:
            data = next((node for node in list(geometry) if node.tag.rsplit("}", 1)[-1] == "DataItem"), None)
            if geometry.attrib.get("GeometryType") != "XYZ":
                reasons.append(f"xml_frame_{frame_count - 1}_geometry_not_XYZ")
            if data is None or expected_particles is None or data.attrib.get("Dimensions") != f"{expected_particles} 3":
                reasons.append(f"xml_frame_{frame_count - 1}_geometry_not_N3")
            else:
                vector_shape_count += 1
        velocity = next((node for node in grid.iter() if node.tag.rsplit("}", 1)[-1] == "Attribute" and node.attrib.get("Name") == "velocity"), None)
        if velocity is None:
            reasons.append(f"xml_frame_{frame_count - 1}_velocity_missing")
        else:
            if velocity.attrib.get("AttributeType") != "Vector":
                reasons.append(f"xml_frame_{frame_count - 1}_velocity_not_vector")
            data = next((node for node in list(velocity) if node.tag.rsplit("}", 1)[-1] == "DataItem"), None)
            if data is None or expected_particles is None or data.attrib.get("Dimensions") != f"{expected_particles} 3":
                reasons.append(f"xml_frame_{frame_count - 1}_velocity_not_N3")
    if frame_count != EXPECTED_FRAMES:
        reasons.append("xml_frame_count_not_401")
    if topology_count_ok != EXPECTED_FRAMES:
        reasons.append("xml_topology_count_not_verified_for_all_frames")
    if vector_shape_count != EXPECTED_FRAMES:
        reasons.append("xml_geometry_N3_not_verified_for_all_frames")
    if len(frame_times) == EXPECTED_FRAMES and expected_times is not None and len(expected_times) == EXPECTED_FRAMES:
        if any(abs(a - b) > 1e-9 for a, b in zip(frame_times, expected_times)):
            reasons.append("xml_times_do_not_match_render_producer_times")
    elif expected_times is not None:
        reasons.append("xml_time_vector_not_401")
    out.update({
        "xml_root": root_name,
        "frame_count": frame_count,
        "topology_frames_verified": topology_count_ok,
        "geometry_N3_frames_verified": vector_shape_count,
        "first_time_s": frame_times[0] if frame_times else None,
        "last_time_s": frame_times[-1] if frame_times else None,
        "time_count": len(frame_times),
        "verified": not reasons,
        "reasons": reasons,
    })
    return out


def _typed_certificate(typed_refs: list[dict[str, Any]], expected_case_id: str | None = None,
                       expected_physical_id: str | None = None,
                       expected_particles: int | None = None,
                       expected_times: list[float] | None = None) -> dict[str, Any]:
    reasons: list[str] = []
    receipt_certificates: list[dict[str, Any]] = []
    report_seen = False
    report_ok = False
    report_details: dict[str, Any] = {}
    for ref in typed_refs or []:
        obj, _ = _json_object(ref, "typed_ref")
        if obj is None:
            continue
        if "returncode" in obj and "status" in obj:
            receipt_certificates.append(_execution_receipt_certificate(ref, expected_case_id, expected_physical_id, "typed_execution_receipt"))
        if "conversion_status" in obj or "solver_dimension" in obj or "partvtk_validation" in obj:
            report_seen = True
            lifecycle = obj.get("lifecycle") if isinstance(obj.get("lifecycle"), dict) else {}
            frame_summary = lifecycle.get("frame_summary")
            lifecycle_ok = isinstance(frame_summary, list) and len(frame_summary) == EXPECTED_FRAMES
            lifecycle_times: list[float] = []
            if lifecycle_ok:
                for frame_index, frame_item in enumerate(frame_summary):
                    if not isinstance(frame_item, dict) or frame_item.get("frame") != frame_index:
                        lifecycle_ok = False
                        break
                    if not _finite_number(frame_item.get("time")):
                        lifecycle_ok = False
                        break
                    lifecycle_times.append(float(frame_item["time"]))
                    if expected_particles is not None:
                        active = frame_item.get("active_particles")
                        missing = frame_item.get("missing_particles", 0)
                        if not isinstance(active, int) or not isinstance(missing, int) or active + missing != expected_particles:
                            lifecycle_ok = False
                            break
            if lifecycle_ok and expected_times is not None and len(expected_times) == EXPECTED_FRAMES:
                lifecycle_ok = all(abs(a - b) <= 1e-9 for a, b in zip(lifecycle_times, expected_times))
            report_details = {
                "conversion_status": obj.get("conversion_status"),
                "frames": obj.get("frames"),
                "particles": obj.get("particles"),
                "solver_dimension": obj.get("solver_dimension"),
                "partvtk_all_passed": (obj.get("partvtk_validation") or {}).get("all_passed") if isinstance(obj.get("partvtk_validation"), dict) else None,
                "time_evidence": copy.deepcopy(obj.get("time_evidence")) if isinstance(obj.get("time_evidence"), dict) else None,
                "lifecycle_keys": sorted(lifecycle.keys()),
                "lifecycle_frame_summary_count": len(frame_summary) if isinstance(frame_summary, list) else None,
                "lifecycle_identity_contract": lifecycle.get("contract"),
                "lifecycle_frame_times_match_render_report": lifecycle_ok,
                "typed_identity_key": (obj.get("typed_identity") or {}).get("key") if isinstance(obj.get("typed_identity"), dict) else None,
            }
            solver_dimension = obj.get("solver_dimension")
            solver_dimension_value = solver_dimension.get("solver_dimension") if isinstance(solver_dimension, dict) else solver_dimension
            report_ok = (
                obj.get("conversion_status") == "completed"
                and obj.get("frames") == EXPECTED_FRAMES
                and (expected_particles is None or obj.get("particles") == expected_particles)
                and solver_dimension_value == 3
                and isinstance(obj.get("partvtk_validation"), dict)
                and obj["partvtk_validation"].get("all_passed") is True
                and isinstance(obj.get("time_evidence"), dict)
                and obj["time_evidence"].get("strictly_increasing") is True
                and lifecycle_ok
                and isinstance((obj.get("typed_identity") or {}).get("key"), str)
            )
    if not receipt_certificates or not any(item.get("terminal_completed_returncode_zero") for item in receipt_certificates):
        reasons.append("typed_terminal_receipt_not_verified")
    if not report_seen:
        reasons.append("typed_conversion_report_not_found")
    elif not report_ok:
        reasons.append("typed_conversion_report_full401_3D_partvtk_time_gate_failed")
    return {
        "verified": not reasons,
        "receipt_certificates": receipt_certificates,
        "report": report_details,
        "reasons": reasons,
    }


def _native_certificate(native_refs: list[dict[str, Any]], expected_case_id: str | None = None,
                        expected_physical_id: str | None = None) -> dict[str, Any]:
    certificates = [_execution_receipt_certificate(ref, expected_case_id, expected_physical_id, "native_execution_receipt") for ref in native_refs or []]
    reasons = [] if any(item.get("terminal_completed_returncode_zero") for item in certificates) else ["native_terminal_receipt_not_verified"]
    return {"verified": not reasons, "receipt_certificates": certificates, "reasons": reasons}


def _qa_certificate(qa_refs: list[dict[str, Any]], expected_case_id: str | None = None,
                    expected_physical_id: str | None = None) -> dict[str, Any]:
    """Accept only direct QA/audit evidence, never a root-QI summary as QA."""
    receipts: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for ref in qa_refs or []:
        path = str(ref.get("path", ""))
        if "independent-QI" in path or "_QI_" in path or "full-QI" in path:
            continue
        obj, _ = _json_object(ref, "initial_qa_ref")
        if obj is None:
            continue
        if "returncode" in obj and "status" in obj:
            receipt = _execution_receipt_certificate(ref, expected_case_id, expected_physical_id, "initial_qa_execution_receipt")
            request = obj.get("request") if isinstance(obj.get("request"), dict) else {}
            input_files = request.get("input_files")
            task_kind = request.get("cpu_task_kind", request.get("kind"))
            receipt["direct_qa_request_contract"] = {
                "input_files_present": isinstance(input_files, list) and bool(input_files),
                "audit_or_qa_task_kind": task_kind in {"audit", "qa", "initial_qa"},
            }
            if not receipt["direct_qa_request_contract"]["input_files_present"]:
                receipt["reason"] = "initial_qa_receipt_input_files_missing"
                receipt["terminal_completed_returncode_zero"] = False
            if not receipt["direct_qa_request_contract"]["audit_or_qa_task_kind"]:
                receipt["reason"] = "initial_qa_receipt_task_kind_not_audit_or_qa"
                receipt["terminal_completed_returncode_zero"] = False
            receipts.append(receipt)
        checks = obj.get("checks")
        direct_evidence = any(key in obj for key in ("prepared_evidence", "gencase_receipt", "partvtk", "xml_contract", "input_binding"))
        checks_pass = isinstance(checks, dict) and bool(checks) and all(value is True for value in checks.values())
        passed = (
            (obj.get("pass") is True or obj.get("passed") is True or obj.get("all_checks_pass") is True or obj.get("status") in {"pass", "passed"})
            and checks_pass
            and direct_evidence
            and obj.get("case_id") in (None, expected_case_id)
        )
        if passed:
            reports.append({"path": path, "pass": True, "role": "direct_initial_qa_or_audit_report", "checks_all_true": True, "direct_input_evidence": True})
    reasons = []
    if not any(item.get("terminal_completed_returncode_zero") for item in receipts) and not reports:
        reasons.append("direct_initial_qa_or_audit_pass_not_verified")
    return {"verified": not reasons, "receipts": receipts, "reports": reports, "reasons": reasons}


def _xmf_execution_certificate(manifest_ref: Any, expected_case_id: str | None = None,
                               expected_physical_id: str | None = None) -> dict[str, Any]:
    """Require the XMF producer's own terminal receipt and input/output binding.

    A completed render report alone is insufficient: the receipt must be the
    execution receipt for the same attempt root that contains the selected
    manifest.  This keeps a stale request or a report copied from another
    attempt out of the final-primary gate.
    """
    manifest_path = Path(manifest_ref.get("path")) if isinstance(manifest_ref, dict) and isinstance(manifest_ref.get("path"), str) else None
    out: dict[str, Any] = {
        "role": "xmf_execution_receipt",
        "manifest_path": str(manifest_path) if manifest_path else None,
        "receipt_path": None,
        "input_binding_matches_manifest": False,
    }
    if manifest_path is None:
        out.update({"verified": False, "reasons": ["manifest_path_missing"]})
        return out
    attempt_root = manifest_path.parent.parent if manifest_path.parent.name == "xdmf" else manifest_path.parent
    receipt_path = attempt_root / "execution-receipt.json"
    out["receipt_path"] = str(receipt_path)
    receipt_ref = {"path": str(receipt_path), "role": "xmf_execution_receipt"}
    cert = _execution_receipt_certificate(receipt_ref, expected_case_id, expected_physical_id, "xmf_execution_receipt")
    obj, reason = _json_object(receipt_ref, "xmf_execution_receipt")
    reasons = list(cert.get("reason") for _ in [0] if cert.get("reason"))
    if obj is not None:
        output_root = obj.get("output_root")
        request = obj.get("request") if isinstance(obj.get("request"), dict) else {}
        request_root = request.get("attempt_root")
        declared_root = output_root or request_root
        expected_root = str(attempt_root)
        binding_ok = declared_root in {expected_root, str(Path(expected_root).resolve())}
        manifest_in_root = attempt_root / "xdmf" / "manifest.json" if manifest_path.parent.name == "xdmf" else attempt_root / manifest_path.name
        binding_ok = binding_ok and manifest_path.resolve() == manifest_in_root.resolve()
        out["declared_output_root"] = declared_root
        out["request_attempt_root"] = request_root
        out["expected_attempt_root"] = expected_root
        out["manifest_binding_path"] = str(manifest_in_root)
        out["input_binding_matches_manifest"] = binding_ok
        if not binding_ok:
            reasons.append("xmf_receipt_output_root_or_manifest_binding_mismatch")
        input_files = request.get("input_files")
        input_sha = request.get("input_sha256")
        runtime_worktree = request.get("worktree_root")
        runtime_cwd = request.get("cwd")
        input_closure_ok = isinstance(input_files, list) and bool(input_files) and isinstance(input_sha, dict) and set(input_files) == set(input_sha)
        runtime_fields_ok = isinstance(runtime_worktree, str) and bool(runtime_worktree) and isinstance(runtime_cwd, str) and bool(runtime_cwd)
        out["input_files_count"] = len(input_files) if isinstance(input_files, list) else None
        out["input_sha256_count"] = len(input_sha) if isinstance(input_sha, dict) else None
        out["input_files_sha256_keyset_matches"] = input_closure_ok
        out["runtime_worktree_and_cwd_present"] = runtime_fields_ok
        if not input_closure_ok:
            reasons.append("xmf_receipt_input_files_sha256_keyset_not_closed")
        if not runtime_fields_ok:
            reasons.append("xmf_receipt_runtime_worktree_or_cwd_missing")
    else:
        reasons.append(reason or "xmf_receipt_metadata_missing")
    out.update(cert)
    out["input_binding_matches_manifest"] = bool(out.get("input_binding_matches_manifest"))
    if not out["input_binding_matches_manifest"]:
        reasons.append("xmf_receipt_input_binding_not_verified")
    out["verified"] = bool(cert.get("terminal_completed_returncode_zero")) and not reasons
    out["reasons"] = sorted(set(reasons))
    return out


def _p03_recovery_certificate(manifest_ref: Any, expected_case_id: str | None,
                              expected_physical_id: str | None, expected_particles: int | None) -> dict[str, Any]:
    """Verify P03's explicit recovery-aware artifact audit without rewriting
    the original typed135 running/null receipt.
    """
    out: dict[str, Any] = {"verified": False, "reasons": [], "original_runtime_unknown": True}
    obj, reason = _json_object(manifest_ref, "p03_recovery_manifest")
    if obj is None:
        out["reasons"] = [reason or "p03_manifest_missing"]
        return out
    provenance = obj.get("recovery_provenance")
    if not isinstance(provenance, dict) or provenance.get("schema") != "ds02.recovery-aware-xdmf-provenance.v1":
        out["reasons"] = ["p03_recovery_provenance_schema_missing"]
        return out
    original = provenance.get("original_conversion_receipt") if isinstance(provenance.get("original_conversion_receipt"), dict) else {}
    audit = provenance.get("artifact_recovery_audit") if isinstance(provenance.get("artifact_recovery_audit"), dict) else {}
    reasons: list[str] = []
    original_receipt = original.get("receipt") if isinstance(original.get("receipt"), dict) else {}
    if original_receipt.get("status") != "running" or original_receipt.get("returncode") is not None or original.get("conversion_completed_claim") is not False:
        reasons.append("p03_original_typed135_running_null_claim_not_preserved")
    if provenance.get("original_conversion_completed_claim") is not False or provenance.get("independent_artifact_audit_completed") is not True or provenance.get("source_receipt_edited") is not False:
        reasons.append("p03_recovery_provenance_lifecycle_flags_invalid")
    if audit.get("status") != "completed" or audit.get("returncode") != 0 or audit.get("arrays_decoded") is not False or audit.get("opaque_hash_only") is not True:
        reasons.append("p03_recovery_audit_terminal_or_opaque_contract_invalid")
    if audit.get("verified_frames") != EXPECTED_FRAMES or (expected_particles is not None and audit.get("verified_particles") != expected_particles):
        reasons.append("p03_recovery_audit_frame_or_particle_count_mismatch")
    audit_receipt = audit.get("receipt") if isinstance(audit.get("receipt"), dict) else {}
    audit_report = audit.get("report") if isinstance(audit.get("report"), dict) else {}
    original_receipt_ref = original.get("receipt") if isinstance(original.get("receipt"), dict) else {}
    original_report_ref = original.get("report") if isinstance(original.get("report"), dict) else {}
    original_receipt_obj, original_receipt_reason = _json_object({"path": original_receipt_ref.get("path"), "sha256": original_receipt_ref.get("sha256")}, "p03_original_typed135_receipt")
    if original_receipt_obj is None:
        reasons.append(original_receipt_reason or "p03_original_typed135_receipt_unreadable")
    else:
        original_binding = _receipt_binding(original_receipt_obj)
        # The immutable typed135 receipt records status=running while the
        # producer was interrupted before writing a returncode key.  Preserve
        # that field-presence fact: absent and explicit null both mean the
        # original runtime is unknown, while any non-null value would change
        # the historical claim.
        if original_receipt_obj.get("status") != "running" or (
            "returncode" in original_receipt_obj and original_receipt_obj.get("returncode") is not None
        ):
            reasons.append("p03_original_typed135_receipt_actual_status_or_returncode_changed")
        if original_binding.get("case_id") != expected_case_id:
            reasons.append("p03_original_typed135_receipt_actual_case_binding_mismatch")
    original_report_obj, original_report_reason = _json_object({"path": original_report_ref.get("path"), "sha256": original_report_ref.get("sha256")}, "p03_original_typed135_report")
    if original_report_obj is None:
        reasons.append(original_report_reason or "p03_original_typed135_report_unreadable")
    elif original_report_obj.get("schema") != "ds-data-02.bi4-direct-conversion.v1":
        reasons.append("p03_original_typed135_report_schema_mismatch")
    audit_receipt_ref = {"path": audit_receipt.get("path"), "sha256": audit_receipt.get("sha256"), "role": "p03_recovery_audit_receipt"}
    audit_cert = _execution_receipt_certificate(audit_receipt_ref, expected_case_id, None, "p03_recovery_audit_receipt")
    if not audit_cert.get("terminal_completed_returncode_zero"):
        reasons.append("p03_recovery_audit_receipt_not_terminal")
    audit_obj, audit_reason = _json_object(audit_receipt_ref, "p03_recovery_audit_receipt")
    if audit_obj is not None:
        audit_binding = _receipt_binding(audit_obj)
        if audit_binding.get("physical_case_id") not in (None, expected_physical_id):
            reasons.append("p03_recovery_audit_receipt_physical_binding_mismatch")
        if audit_binding.get("case_id") != expected_case_id:
            reasons.append("p03_recovery_audit_receipt_case_binding_mismatch")
    else:
        reasons.append(audit_reason or "p03_recovery_audit_receipt_metadata_missing")
    audit_report_ref = {"path": audit_report.get("path"), "sha256": audit_report.get("sha256"), "role": "p03_recovery_audit_report"}
    audit_report_obj, report_reason = _json_object(audit_report_ref, "p03_recovery_audit_report")
    if audit_report_obj is None:
        reasons.append(report_reason or "p03_recovery_audit_report_missing")
    else:
        if audit_report_obj.get("artifact_integrity_status") != "completed" or audit_report_obj.get("verified_frames") != EXPECTED_FRAMES:
            reasons.append("p03_recovery_audit_report_not_complete")
        if expected_particles is not None and audit_report_obj.get("verified_particles") != expected_particles:
            reasons.append("p03_recovery_audit_report_particle_count_mismatch")
    out.update({
        "manifest_schema": obj.get("schema"),
        "original_conversion_receipt": copy.deepcopy(original),
        "original_receipt_actual": {
            "path": original_receipt_ref.get("path"),
            "sha256": original_receipt_ref.get("sha256"),
            "status": original_receipt_obj.get("status") if isinstance(original_receipt_obj, dict) else None,
            "returncode_field_present": "returncode" in original_receipt_obj if isinstance(original_receipt_obj, dict) else False,
            "returncode": original_receipt_obj.get("returncode") if isinstance(original_receipt_obj, dict) else None,
            "case_id": _receipt_binding(original_receipt_obj).get("case_id") if isinstance(original_receipt_obj, dict) else None,
        },
        "original_report_actual": {
            "path": original_report_ref.get("path"),
            "sha256": original_report_ref.get("sha256"),
            "schema": original_report_obj.get("schema") if isinstance(original_report_obj, dict) else None,
        },
        "artifact_recovery_audit": copy.deepcopy(audit),
        "audit_receipt": audit_cert,
        "audit_report_path": audit_report.get("path"),
        "verified": not reasons,
        "reasons": sorted(set(reasons)),
    })
    return out


def _fulltime_runtime_gate(visual: dict[str, Any], expected_case_id: str | None,
                           expected_physical_id: str | None) -> dict[str, Any]:
    manifest_ref = visual.get("actual_xmf_manifest")
    report_ref = visual.get("actual_render_report")
    xml_ref = visual.get("actual_xmf_xml")
    manifest_obj, _ = _json_object(manifest_ref, "xmf_manifest")
    expected_particles = None
    if isinstance(manifest_obj, dict):
        for key in ("actual_particles", "particles", "expected_particles"):
            if isinstance(manifest_obj.get(key), int):
                expected_particles = manifest_obj[key]
                break
    report_probe = _report_certificate(report_ref, expected_case_id, expected_particles)
    expected_times = report_probe.get("actual_times") if report_probe.get("fulltime_metadata_certificate_verified") else None
    manifest_probe = _manifest_certificate(manifest_ref, expected_case_id, expected_physical_id, expected_particles)
    xml_probe = _xml_certificate(xml_ref, expected_case_id, expected_particles, expected_times)
    render_receipt = _execution_receipt_certificate(visual.get("actual_render_receipt"), expected_case_id, expected_physical_id, "render_execution_receipt")
    xmf_execution_receipt = _xmf_execution_certificate(manifest_ref, expected_case_id, expected_physical_id)
    # Bind the producer report and XML to the same selected manifest.  A
    # report with the right shape but a different attempt is not a primary
    # certificate.
    if isinstance(report_ref, dict) and isinstance(report_ref.get("path"), str):
        report_obj, _ = _json_object(report_ref, "render_report_binding")
        if isinstance(report_obj, dict) and report_obj.get("input_manifest") is not None:
            report_manifest = Path(str(report_obj.get("input_manifest"))).resolve()
            selected_manifest = Path(str(manifest_ref.get("path"))).resolve() if isinstance(manifest_ref, dict) and manifest_ref.get("path") else None
            if selected_manifest is None or report_manifest != selected_manifest:
                report_probe["fulltime_metadata_certificate_verified"] = False
                report_probe.setdefault("reasons", []).append("render_report_input_manifest_binding_mismatch")
        else:
            report_probe["fulltime_metadata_certificate_verified"] = False
            report_probe.setdefault("reasons", []).append("render_report_input_manifest_binding_missing")
    if isinstance(manifest_obj, dict) and isinstance(manifest_obj.get("xdmf"), str) and isinstance(xml_ref, dict) and isinstance(xml_ref.get("path"), str):
        if Path(manifest_obj["xdmf"]).resolve() != Path(xml_ref["path"]).resolve():
            manifest_probe["verified"] = False
            manifest_probe.setdefault("reasons", []).append("manifest_xdmf_xml_binding_mismatch")
    manifest_extra_refs: list[dict[str, Any]] = []
    if isinstance(manifest_obj, dict):
        for key, role in (("native_receipt", "manifest_native_execution_receipt"), ("typed_receipt", "manifest_typed_execution_receipt"), ("qa_execution_receipt", "manifest_initial_qa_execution_receipt"), ("initial_qa_report", "manifest_initial_qa_report")):
            value = manifest_obj.get(key)
            sha_key = f"{key}_sha256"
            if isinstance(value, str) and value.startswith("/"):
                ref = {"path": value, "source_key": f"actual_xmf_manifest.{key}", "role": role}
                if isinstance(manifest_obj.get(sha_key), str):
                    ref["sha256"] = manifest_obj[sha_key]
                manifest_extra_refs.append(ref)
    native_refs = list(visual.get("native_refs") or [])
    typed_refs = list(visual.get("typed_refs") or [])
    qa_refs = list(visual.get("initial_qa_or_audit_refs") or [])
    # Some legacy initial-QA registrations point at the terminal audit
    # receipt and carry the producer report path in the request metadata.  A
    # receipt alone cannot prove QA, so bind the sibling report emitted by
    # that same attempt as an explicit direct-evidence reference.  This is
    # especially important for P03: its original typed135 receipt remains
    # running/unknown, while the recovery-aware XMF and independent initial
    # QA report are real completed artifacts.
    derived_qa_refs: list[dict[str, Any]] = []
    for ref in qa_refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            continue
        receipt_path = Path(ref["path"])
        if receipt_path.name != "execution-receipt.json":
            continue
        sibling_report = receipt_path.parent / "actual-initial-qa.json"
        if sibling_report.is_file():
            derived_qa_refs.append({
                "path": str(sibling_report),
                "sha256": sha_json(sibling_report, "derived_initial_qa_report"),
                "role": "derived_initial_qa_report_from_receipt_output",
                "derived_from_receipt": str(receipt_path),
            })
    qa_refs.extend(derived_qa_refs)
    for ref in manifest_extra_refs:
        if ref.get("role", "").endswith("native_execution_receipt"):
            native_refs.append(ref)
        elif ref.get("role", "").endswith("typed_execution_receipt"):
            typed_refs.append(ref)
        else:
            qa_refs.append(ref)
    native_probe = _native_certificate(native_refs, expected_case_id, expected_physical_id)
    typed_probe = _typed_certificate(typed_refs, expected_case_id, expected_physical_id, expected_particles, report_probe.get("actual_times"))
    qa_probe = _qa_certificate(qa_refs, expected_case_id, expected_physical_id)
    owner_present = bool(visual.get("owner_or_source_refs"))
    gencase_present = bool(visual.get("gencase_or_definition_refs"))
    reasons: list[str] = []
    p03 = expected_physical_id == "F2_STAGE1_OFFSET_P03_OPEN_RIM_RX065_RY014_FILL080"
    p03_recovery = _p03_recovery_certificate(manifest_ref, expected_case_id, expected_physical_id, expected_particles) if p03 else {"verified": False, "reasons": ["not_p03"]}
    for label, probe in (("manifest", manifest_probe), ("render_report", report_probe), ("xml", xml_probe), ("xmf_execution_receipt", xmf_execution_receipt), ("render_receipt", render_receipt), ("native", native_probe), ("typed", typed_probe), ("initial_qa", qa_probe)):
        # P03's normal typed135/initial-QA lineage is intentionally left
        # running/unknown.  Its independent recovery-aware XMF artifact audit
        # is the only permitted substitute for those two roles.
        if p03 and p03_recovery.get("verified") and label == "typed":
            continue
        if not probe.get("verified", probe.get("fulltime_metadata_certificate_verified", False)) and not probe.get("terminal_completed_returncode_zero", False):
            reasons.append(f"{label}_gate_failed")
    if not owner_present:
        reasons.append("owner_or_source_refs_empty")
    # GenCase provenance is retained in the row but is not a terminal-product
    # gate: several accepted legacy rows deliberately have no copied source
    # definition in the visual decision.  Native/typed/XMF/QA/runtime proof
    # still has to pass above.
    runtime_unknown = {
        "original_runtime_unknown": p03,
        "original_typed135_running_or_null_preserved": p03,
        "recovery_aware_chain_required_for_p03": p03,
        "recovery_aware_chain_verified": (not p03) or bool(p03_recovery.get("verified")),
    }
    if p03 and not runtime_unknown["recovery_aware_chain_verified"]:
        reasons.append("P03_original_runtime_unknown_without_verified_recovery_aware_chain")
    return {
        "field_metadata_fulltime_certificate_verified": not reasons,
        "runtime_known_vs_original_unknown": runtime_unknown,
        "reasons": reasons,
        "expected_particles_from_manifest": expected_particles,
        "manifest": manifest_probe,
        "render_report": report_probe,
        "xmf_xml": xml_probe,
        "xmf_execution_receipt": xmf_execution_receipt,
        "render_receipt": render_receipt,
        "native": native_probe,
        "typed": typed_probe,
        "initial_qa": qa_probe,
        "p03_recovery": p03_recovery,
        "owner_or_source_refs_present": owner_present,
        "gencase_or_definition_refs_present": gencase_present,
    }


def _ref_is_complete(ref: Any, *, json_only: bool = False) -> tuple[bool, str | None]:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        return False, "missing_path_ref"
    path = Path(ref["path"])
    if path.suffix.lower() in FORBIDDEN:
        return False, f"scientific_payload_suffix:{path.suffix.lower()}"
    if not path.is_file():
        return False, "path_not_present_at_build"
    if json_only and path.suffix.lower() != ".json":
        return False, "expected_json_metadata"
    if path.suffix.lower() == ".json":
        observed = sha_json(path, f"metadata ref {path}")
        declared = ref.get("sha256")
        if declared is not None and declared != observed:
            return False, "declared_json_sha_mismatch"
    return True, None


def _primary_completeness(visual: dict[str, Any], expected_case_id: str | None = None,
                          expected_physical_id: str | None = None) -> dict[str, Any]:
    """Gate the real producer chain, not merely reference presence.

    The returned object intentionally contains both the historical reference
    checks and the stronger full-time/runtime certificate.  A request-shaped
    JSON, a missing frame, a time mismatch, or an unknown receipt status keeps
    the row in readiness even when all path strings exist.
    """
    reasons: list[str] = []
    checks: dict[str, bool] = {}
    for key, json_only in (
        ("actual_xmf_manifest", True),
        ("actual_render_report", True),
        ("actual_render_receipt", True),
    ):
        ok, reason = _ref_is_complete(visual.get(key), json_only=json_only)
        checks[key] = ok
        if not ok:
            reasons.append(f"{key}:{reason}")
    ok, reason = _ref_is_complete(visual.get("actual_xmf_xml"), json_only=False)
    checks["actual_xmf_xml"] = ok
    if not ok:
        reasons.append(f"actual_xmf_xml:{reason}")
    for group in ("native_refs", "typed_refs"):
        values = visual.get(group)
        ok = isinstance(values, list) and bool(values)
        checks[group] = ok
        if not ok:
            reasons.append(f"{group}:empty")
        else:
            for i, ref in enumerate(values):
                good, why = _ref_is_complete(ref, json_only=True)
                if not good:
                    checks[f"{group}[{i}]"] = False
                    reasons.append(f"{group}[{i}]:{why}")
    contacts = visual.get("contact_png_refs")
    keys = visual.get("key_png_refs")
    checks["contact_png_refs"] = isinstance(contacts, list) and bool(contacts)
    if not checks["contact_png_refs"]:
        reasons.append("contact_png_refs:empty")
    else:
        for i, ref in enumerate(contacts):
            good, why = _ref_is_complete(ref)
            if not good:
                reasons.append(f"contact_png_refs[{i}]:{why}")
    checks["key_png_refs"] = isinstance(keys, list) and bool(keys)

    runtime_gate = _fulltime_runtime_gate(visual, expected_case_id, expected_physical_id)
    if not runtime_gate["field_metadata_fulltime_certificate_verified"]:
        reasons.extend(f"runtime:{item}" for item in runtime_gate["reasons"])
    complete = not reasons
    return {
        "complete_for_final_primary_delivery": complete,
        "checks": checks,
        "reasons": reasons,
        "key_png_paths_enumerated": checks["key_png_refs"],
        "key_png_absence_is_not_inferred_as_missing_render": not checks["key_png_refs"],
        "field_metadata_fulltime_certificate_verified": runtime_gate["field_metadata_fulltime_certificate_verified"],
        "runtime_known_vs_original_unknown": runtime_gate["runtime_known_vs_original_unknown"],
        "runtime_gate": runtime_gate,
        "selected_primary_roles_are_not_reference_presence_only": True,
    }


def _legacy_rows(legacy: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(legacy, dict) or not isinstance(legacy.get("rows"), list):
        raise RuntimeError("legacy catalog must contain a top-level rows list")
    result: dict[str, dict[str, Any]] = {}
    for row in legacy["rows"]:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise RuntimeError("legacy catalog contains a row without physical_case_id")
        physical = row["physical_case_id"]
        if physical in result:
            raise RuntimeError(f"legacy catalog duplicates physical_case_id: {physical}")
        result[physical] = row
    return result



def _legacy_render_corrections(legacy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index Root1330's explicit request-to-receipt role corrections."""
    result: dict[str, dict[str, Any]] = {}
    values = legacy.get("main_corrected_actual_primary_and_published_navigation_sidecars") if isinstance(legacy, dict) else None
    if not isinstance(values, list):
        return result
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("physical_case_id"), str):
            continue
        correction = value.get("source_render_request_role_correction")
        if isinstance(correction, dict):
            result[value["physical_case_id"]] = copy.deepcopy(value)
    return result


def _is_runner_request_role(ref: Any) -> tuple[bool, dict[str, Any] | None]:
    obj, _ = _json_object(ref, "render_role_probe")
    if obj is None:
        return False, None
    schema = obj.get("schema")
    status = obj.get("status")
    request_schema = (obj.get("request") or {}).get("schema") if isinstance(obj.get("request"), dict) else None
    request_role = (isinstance(schema, str) and "runner-request" in schema.lower()) or (isinstance(request_schema, str) and "runner-request" in request_schema.lower())
    pending_status = isinstance(status, str) and ("pending" in status.lower() or "enabled_actual" in status.lower())
    return request_role or pending_status or "returncode" not in obj, obj


def _apply_legacy_render_correction(visual: dict[str, Any], physical_case_id: str,
                                    corrections: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Promote only Root1330's explicit same-attempt receipt correction.

    The old request remains in a historical role.  This function never edits
    source JSON and never silently turns a request's descriptive status into a
    terminal receipt.
    """
    current = visual.get("actual_render_receipt")
    is_request, _ = _is_runner_request_role(current)
    correction_row = corrections.get(physical_case_id)
    if not is_request:
        if correction_row is not None:
            visual.setdefault("render_receipt_role_correction", {"correction_available_but_current_primary_is_terminal": True})
        return visual
    if correction_row is None:
        visual.setdefault("render_receipt_role_correction", {"correction_available": False, "reason": "request_role_without_explicit_root1330_correction"})
        return visual
    correction = correction_row.get("source_render_request_role_correction")
    actual = correction_row.get("actual_render_receipt")
    if not isinstance(correction, dict) or not isinstance(actual, dict):
        visual.setdefault("render_receipt_role_correction", {"correction_available": False, "reason": "malformed_root1330_correction"})
        return visual
    old_ref = correction.get("immutable_source_misclassified_render_request")
    old_matches = isinstance(old_ref, dict) and old_ref.get("path") == current.get("path") and (old_ref.get("sha256") in (None, current.get("sha256")))
    actual_ref = clone_ref(actual, "Root1330.main_corrected_actual_primary_and_published_navigation_sidecars.actual_render_receipt", "corrected_actual_render_execution_receipt")
    if not old_matches or actual_ref is None:
        visual.setdefault("render_receipt_role_correction", {"correction_available": False, "reason": "Root1330_correction_does_not_match_selected_request", "selected_request": copy.deepcopy(current), "correction_old_ref": copy.deepcopy(old_ref)})
        return visual
    # Preserve every old role before deriving the corrected primary chain.
    visual["historical_source_render_request_role"] = copy.deepcopy(current)
    visual["historical_source_render_request_role"]["role"] = "historical_misclassified_render_request_preserved"
    visual["render_receipt_role_correction"] = {
        "source": "Root1330.main_corrected_actual_primary_and_published_navigation_sidecars",
        "source_request_preserved": True,
        "source_request_not_promoted_to_completed_receipt": correction.get("source_request_not_promoted_to_completed_receipt") is True,
        "source_request_role": copy.deepcopy(old_ref),
        "source_status": correction.get("source_status"),
        "source_process_returncode_field_present": correction.get("source_process_returncode_field_present"),
        "source_process_returncode": correction.get("source_process_returncode"),
        "corrected_actual_receipt": copy.deepcopy(actual_ref),
        "role_correction_is_explicit_and_not_silent": True,
    }
    visual["actual_render_receipt"] = annotate_ref(actual_ref, "corrected_actual_render_execution_receipt")
    # The same Root1330 correction supplies the report/manifest/XML from the
    # same completed attempt.  Keep the selected old paths as historical
    # evidence, never merge them into the corrected primary role.
    historical = visual.setdefault("historical_primary_render_chain_refs", {})
    for key in ("actual_xmf_manifest", "actual_xmf_xml", "actual_render_report"):
        if visual.get(key) is not None:
            historical[key] = copy.deepcopy(visual[key])
    for key, role in (("primary_XMF_manifest", "corrected_actual_xmf_manifest"), ("primary_XMF_XML", "corrected_actual_xmf_xml"), ("primary_render_report", "corrected_actual_render_report")):
        value = correction_row.get(key)
        if isinstance(value, dict):
            ref = clone_ref(value, f"Root1330.{key}", role)
            if ref is not None:
                visual_key = {"primary_XMF_manifest": "actual_xmf_manifest", "primary_XMF_XML": "actual_xmf_xml", "primary_render_report": "actual_render_report"}[key]
                visual[visual_key] = annotate_ref(ref, role)
    return visual


def _prepare_output_dir(output_dir: Path) -> None:
    """Allow a new/empty staging directory, never overwrite a product."""
    if output_dir.exists():
        if not output_dir.is_dir():
            die(f"output_dir exists but is not a directory: {output_dir}")
        if any(output_dir.iterdir()):
            die(f"refusing to write into nonempty existing output_dir: {output_dir}")
    else:
        output_dir.mkdir(parents=True, exist_ok=False)


def _membership(first: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    if first.get("family_id") != "F2":
        raise RuntimeError("membership source is not F2")
    frozen8 = first.get("frozen_first8_physical_case_ids")
    actual24 = first.get("actual_first24_physical_case_ids")
    final48 = first.get("registered_final48_physical_case_ids")
    if not all(isinstance(x, list) for x in (frozen8, actual24, final48)):
        raise RuntimeError("membership arrays missing")
    if len(frozen8) != 8 or len(actual24) != 24 or len(final48) != 48:
        raise RuntimeError("membership counts are not 8/24/48")
    if len(set(frozen8)) != 8 or len(set(actual24)) != 24 or len(set(final48)) != 48:
        raise RuntimeError("membership arrays contain duplicate physical IDs")
    if not set(frozen8) <= set(actual24) <= set(final48):
        raise RuntimeError("fixed frozen8 subset actual24 subset registered48 relation is false")
    if first.get("first8_subset_actual24_subset_registered48") is not True:
        raise RuntimeError("membership source did not assert fixed subset relation")
    return copy.deepcopy(frozen8), copy.deepcopy(actual24), copy.deepcopy(final48)


def _source(path: Path, role: str) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha_json(path, role), "role": role}


def build_from_inputs(checkpoint_path: Path, index_path: Path, membership_path: Path, legacy_path: Path, output_dir: Path) -> dict[str, Any]:
    checkpoint = read_json(checkpoint_path, "explicit checkpoint")
    index = read_json(index_path, "explicit current index")
    membership = read_json(membership_path, "explicit Root1276 membership")
    legacy = read_json(legacy_path, "explicit legacy catalog")
    if index.get("schema") != "ds02.stage1.full336.role-aware-progress-index.v6":
        raise RuntimeError("current index schema mismatch")
    expected_checkpoint_ref = {"path": str(checkpoint_path), "sha256": sha_json(checkpoint_path, "explicit checkpoint")}
    if index.get("source_authoritative_checkpoint") != expected_checkpoint_ref:
        raise RuntimeError("current index source_authoritative_checkpoint does not exactly match supplied checkpoint path/SHA")
    if not isinstance(index.get("cases"), list):
        raise RuntimeError("current index cases list is missing")
    frozen8, actual24, final48 = _membership(membership)
    f2 = [row for row in index["cases"] if isinstance(row, dict) and row.get("family_id") == "F2"]
    by_id = {}
    for row in f2:
        physical = row.get("physical_case_id")
        if not isinstance(physical, str) or physical in by_id:
            raise RuntimeError(f"current index has invalid/duplicate F2 physical ID: {physical}")
        by_id[physical] = row
    if set(by_id) != set(final48):
        raise RuntimeError("current F2 physical IDs differ from fixed registered48 membership")
    legacy_by_id = _legacy_rows(legacy)
    legacy_ids = set(legacy_by_id)
    legacy_render_corrections = _legacy_render_corrections(legacy)
    if not legacy_ids <= set(final48):
        raise RuntimeError("legacy catalog contains a physical ID outside fixed registered48")
    accepted = [physical for physical in final48 if isinstance(by_id[physical].get("accepted_decision"), dict)]
    pending = [physical for physical in final48 if physical not in accepted]
    checkpoint_f2 = checkpoint.get("accepted_per_family", {}).get("F2")
    if isinstance(checkpoint_f2, int) and checkpoint_f2 != len(accepted):
        raise RuntimeError(f"checkpoint F2 count {checkpoint_f2} disagrees with current index accepted rows {len(accepted)}")

    first24_by_id = {r.get("physical_case_id"): r for r in membership.get("actual_own_primary_rows", []) if isinstance(r, dict)}
    rows: list[dict[str, Any]] = []
    completeness: dict[str, dict[str, Any]] = {}
    accepted_audit: list[dict[str, Any]] = []
    for order, physical in enumerate(final48, 1):
        progress = by_id[physical]
        member = {
            "frozen_first8_member": physical in set(frozen8),
            "actual_first24_member": physical in set(actual24),
            "registered_final48_member": True,
            "authoritative_order": "Root1276 registered_final48_physical_case_ids order; never sorted or reselected",
        }
        dref = progress.get("accepted_decision")
        if isinstance(dref, dict):
            ok, reason = _ref_is_complete(dref, json_only=True)
            if not ok:
                raise RuntimeError(f"accepted decision ref invalid for {physical}: {reason}")
            decision_path = Path(dref["path"])
            decision_sha = sha_json(decision_path, f"accepted decision {physical}")
            checkpoint_decisions = checkpoint.get("accepted_decisions")
            if not isinstance(checkpoint_decisions, list) or str(decision_path) not in checkpoint_decisions:
                raise RuntimeError(f"accepted decision is not a member of the authoritative checkpoint: {physical}")
            if dref.get("sha256") != decision_sha:
                raise RuntimeError(f"accepted decision SHA mismatch for {physical}: {dref.get('sha256')} != {decision_sha}")
            decision = read_json(decision_path, f"accepted decision {physical}")
            accepted_statuses = {"visual-approved-by-root", "visual-approved-by-delegated-agent"}
            if decision.get("status") not in accepted_statuses:
                raise RuntimeError(f"decision status is not an accepted root/delegated status for {physical}: {decision.get('status')}")
            if decision.get("family_id") != "F2" or decision.get("physical_case_id") != physical:
                raise RuntimeError(f"accepted decision identity mismatch for {physical}")
            if decision.get("case_id") != progress.get("case_id"):
                raise RuntimeError(f"accepted decision case_id mismatch for {physical}")
            visual = select_accepted(decision, copy.deepcopy(dref), first24_by_id.get(physical))
            visual.setdefault("metadata_role_presence", {})["current_index_native_request_scope"] = copy.deepcopy(progress.get("native_request_scope"))
            visual.setdefault("metadata_role_presence", {})["current_index_declared_source_plan_condition_sha256"] = progress.get("declared_source_plan_condition_sha256")
            visual.setdefault("metadata_role_presence", {})["current_index_declared_source_definition_sha256"] = progress.get("declared_source_definition_sha256")
            visual.setdefault("metadata_role_presence", {})["current_index_declared_actual_converter_scope_sha256"] = progress.get("declared_actual_converter_scope_sha256")
            legacy_row = legacy_by_id.get(physical)
            if isinstance(legacy_row, dict) and isinstance(legacy_row.get("accepted_visual_metadata"), dict):
                visual = _merge_missing(visual, legacy_row["accepted_visual_metadata"], source="explicit legacy catalog fallback")
            # Root1330 explicitly corrected four rows where the selected value
            # was a runner request, not a terminal receipt.  Preserve the old
            # request role and derive the same-attempt actual chain only from
            # that immutable correction sidecar.
            visual = _apply_legacy_render_correction(visual, physical, legacy_render_corrections)
            _repair_report_digest(visual, decision)
            corrections = decision.get("source_render_report_digest_transcription_corrections")
            if isinstance(corrections, list) and corrections:
                visual["source_render_report_digest_transcription_corrections"] = copy.deepcopy(corrections)
            completeness[physical] = _primary_completeness(visual, progress.get("case_id"), physical)
            accepted_audit.append({
                "physical_case_id": physical,
                "accepted_decision": copy.deepcopy(dref),
                "actual_xmf_manifest": copy.deepcopy(visual.get("actual_xmf_manifest")),
                "actual_xmf_xml": copy.deepcopy(visual.get("actual_xmf_xml")),
                "actual_render_report": copy.deepcopy(visual.get("actual_render_report")),
                "actual_render_receipt": copy.deepcopy(visual.get("actual_render_receipt")),
                "native_ref_count": len(visual.get("native_refs") or []),
                "typed_ref_count": len(visual.get("typed_refs") or []),
                "contact_png_count": len(visual.get("contact_png_refs") or []),
                "key_png_count": len(visual.get("key_png_refs") or []),
                "native_refs": copy.deepcopy(visual.get("native_refs") or []),
                "typed_refs": copy.deepcopy(visual.get("typed_refs") or []),
                "gencase_or_definition_refs": copy.deepcopy(visual.get("gencase_or_definition_refs") or []),
                "initial_qa_or_audit_refs": copy.deepcopy(visual.get("initial_qa_or_audit_refs") or []),
                "owner_or_source_refs": copy.deepcopy(visual.get("owner_or_source_refs") or []),
                "contact_png_refs": copy.deepcopy(visual.get("contact_png_refs") or []),
                "key_png_refs": copy.deepcopy(visual.get("key_png_refs") or []),
                "metadata_role_presence": copy.deepcopy(visual.get("metadata_role_presence") or {}),
                "primary_ref_completeness": copy.deepcopy(completeness[physical]),
                "scope_roles": copy.deepcopy(visual.get("scope_roles")),
                "native_vs_xmf_role_metadata": copy.deepcopy(visual.get("native_vs_xmf_role_metadata")),
                "historical_source_render_request_role": copy.deepcopy(visual.get("historical_source_render_request_role")),
                "historical_primary_render_chain_refs": copy.deepcopy(visual.get("historical_primary_render_chain_refs")),
                "render_receipt_role_correction": copy.deepcopy(visual.get("render_receipt_role_correction")),
                "field_metadata_fulltime_certificate_verified": completeness[physical].get("field_metadata_fulltime_certificate_verified"),
                "runtime_known_vs_original_unknown": copy.deepcopy(completeness[physical].get("runtime_known_vs_original_unknown")),
            })
            # Preserve actual decision and row roles verbatim.  Unknown runtime
            # return codes, old recovery audits, absent source-plan fields and
            # native/typed/XMF namespace differences are never normalized.
            rows.append({
                "delivery_order": order,
                "family_id": "F2",
                "case_id": progress.get("case_id"),
                "physical_case_id": physical,
                "delivery_status": "accepted_visual_decision",
                "membership": member,
                "accepted_visual_metadata": visual,
                "primary_ref_completeness": completeness[physical],
                "field_metadata_fulltime_certificate_verified": completeness[physical].get("field_metadata_fulltime_certificate_verified"),
                "runtime_known_vs_original_unknown": copy.deepcopy(completeness[physical].get("runtime_known_vs_original_unknown")),
                "progress_index_row": copy.deepcopy(progress),
                "legacy_catalog_row_present": physical in legacy_ids,
                "legacy_catalog_row_role": "historical compatibility fallback only; current accepted decision remains authoritative",
                "root1276_first24_crosscheck": copy.deepcopy(first24_by_id.get(physical)) if physical in set(actual24) else None,
                "scope_roles": {
                    "accepted_decision_top_hash": progress.get("accepted_decision_top_condition_sha256"),
                    "accepted_decision_top_hash_role": progress.get("accepted_decision_top_hash_role"),
                    "declared_source_plan_condition_sha256": progress.get("declared_source_plan_condition_sha256"),
                    "declared_source_definition_sha256": progress.get("declared_source_definition_sha256"),
                    "declared_actual_converter_scope_sha256": progress.get("declared_actual_converter_scope_sha256"),
                    "native_request_scope": copy.deepcopy(progress.get("native_request_scope")),
                    "source_scope_fields_preserved": copy.deepcopy(progress.get("F2_source147_raw_scope_fields_preserved")),
                    "roles_are_not_reconciled": True,
                },
                "credit_boundary": {"case_credit": 0, "new_visual_credit": 0, "Q_N": 0, "Q_E": 0, "numeric_precision_accepted": False},
            })
        else:
            # Pending rows intentionally contain no accepted or primary visual
            # refs.  Readiness metadata is copied only from the current index;
            # an old pending catalog cannot promote an unknown receipt.
            rows.append({
                "delivery_order": order,
                "family_id": "F2",
                "case_id": progress.get("case_id"),
                "physical_case_id": physical,
                "delivery_status": "pending_visual_no_accepted_decision",
                "membership": member,
                "pending_metadata": {
                    "accepted_decision": None,
                    "primary_particle_xmf_render_refs": None,
                    "primary_png_refs": None,
                    "readiness_only_current_index_row": copy.deepcopy(progress),
                    "legacy_catalog_pending_row_preserved": physical in legacy_ids,
                    "original_receipt_or_recovery_status_is_not_promoted": True,
                    "visual_credit": 0,
                    "Q_N": 0,
                    "Q_E": 0,
                },
                "primary_ref_completeness": {
                    "complete_for_final_primary_delivery": False,
                    "checks": {},
                    "reasons": ["no_authoritative_accepted_decision"],
                    "key_png_paths_enumerated": False,
                },
                "progress_index_row": copy.deepcopy(progress),
                "legacy_catalog_row_present": physical in legacy_ids,
                "scope_roles": {
                    "accepted_decision_top_hash": progress.get("accepted_decision_top_condition_sha256"),
                    "declared_source_plan_condition_sha256": progress.get("declared_source_plan_condition_sha256"),
                    "declared_source_definition_sha256": progress.get("declared_source_definition_sha256"),
                    "declared_actual_converter_scope_sha256": progress.get("declared_actual_converter_scope_sha256"),
                    "native_request_scope": copy.deepcopy(progress.get("native_request_scope")),
                    "roles_are_not_reconciled": True,
                },
                "credit_boundary": {"case_credit": 0, "new_visual_credit": 0, "Q_N": 0, "Q_E": 0, "numeric_precision_accepted": False},
            })

    complete = len(pending) == 0 and all(completeness.get(x, {}).get("complete_for_final_primary_delivery") for x in accepted)
    source_refs = {
        "checkpoint": _source(checkpoint_path, "explicit authoritative checkpoint"),
        "current_index": _source(index_path, "explicit authoritative current index"),
        "fixed_membership": _source(membership_path, "Root1276 fixed membership"),
        "legacy_catalog": _source(legacy_path, "legacy primary catalog; compatibility source only"),
    }
    common = {
        "family_id": "F2",
        "assigned_family": "F2",
        "builder_schema": "ds02.f2.fresh195.final48.complete-builder.v1",
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "source_refs": source_refs,
        "membership": {
            "frozen_first8_physical_case_ids": frozen8,
            "actual_first24_physical_case_ids": actual24,
            "registered_final48_physical_case_ids": final48,
            "frozen8_subset_actual24_subset_registered48": True,
            "selection_policy": "explicit Root1276 arrays; physical_case_id join; no sorting, directory selection, alias substitution, or accepted-count redefinition",
        },
        "observed_counts": {"registered_final48": 48, "accepted_visual": len(accepted), "pending_visual": len(pending)},
        "credit_boundary": {"new_case_credit": 0, "Q_N": 0, "Q_E": 0, "numeric_precision_accepted": False, "scientific_payload_read_or_hashed_by_source": False, "new_science_jobs": 0},
        "role_policy": {
            "native_canonical_typed_legacy_xmf_plan_source_plan_and_SourceDef_are_separate": True,
            "old_native_runtime_unknown_and_recovery_audit_are_preserved": True,
            "unknown_receipt_returncode_is_not_rewritten": True,
            "source209_report_digest_uses_root1348_correction_when_present": True,
            "png_refs_are_stat_only_and_not_personally_viewed_claims": True,
            "forbidden_scientific_payload_suffixes": sorted(FORBIDDEN),
        },
    }
    _prepare_output_dir(output_dir)
    final_path = output_dir / "F2-FINAL48-COMPLETE-PRIMARY-DELIVERY.json"
    readiness_path = output_dir / "fresh195-readiness.json"
    if not complete:
        if final_path.exists():
            raise RuntimeError(f"refusing to leave a final48 file while incomplete: {final_path}")
        readiness = {
            **common,
            "schema": "ds02.f2.fresh195.final48.readiness.v1",
            "status": "ready_for_final48_when_all_48_have_authoritative_accepted_decision_and_complete_primary_refs",
            "complete_final48_emitted": False,
            "missing_physical_case_ids": pending + [x for x in accepted if not completeness.get(x, {}).get("complete_for_final_primary_delivery")],
            "accepted_rows_with_ref_gaps": [x for x in accepted if not completeness.get(x, {}).get("complete_for_final_primary_delivery")],
            "accepted_ref_audit": accepted_audit,
            "readiness_rows": [
                {
                    "physical_case_id": x,
                    "accepted_decision_present": x in accepted,
                    "primary_refs_complete": completeness.get(x, {}).get("complete_for_final_primary_delivery", False),
                    "reasons": completeness.get(x, {}).get("reasons", ["no_authoritative_accepted_decision"]),
                    "field_metadata_fulltime_certificate_verified": completeness.get(x, {}).get("field_metadata_fulltime_certificate_verified", False),
                    "runtime_known_vs_original_unknown": copy.deepcopy(completeness.get(x, {}).get("runtime_known_vs_original_unknown", {"original_runtime_unknown": False})),
                }
                for x in final48
            ],
            "pending_are_not_visual_acceptance": True,
            "no_final_catalog_reason": "final48 is emitted only after all48 accepted decisions and each own complete primary refs pass",
        }
        readiness_path.write_text(json.dumps(readiness, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"mode": "readiness", "path": readiness_path, "payload": readiness}
    catalog = {
        **common,
        "schema": "ds02.f2.fresh195.final48.complete-primary-delivery.v1",
        "status": "complete_final48_primary_delivery",
        "complete_final48_emitted": True,
        "delivery": {"registered_final48_count": 48, "accepted_visual_count": 48, "pending_visual_count": 0, "accepted_visual_delivery_complete": True},
        "rows": rows,
    }
    if final_path.exists():
        raise RuntimeError(f"refusing to overwrite an existing final48 file: {final_path}")
    final_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if readiness_path.exists():
        readiness_path.unlink()
    return {"mode": "complete", "path": final_path, "payload": catalog}


def parse_args() -> Any:
    import argparse
    parser = argparse.ArgumentParser(description="Build F2 fresh195 final48 metadata or a readiness-only result.")
    parser.add_argument("--checkpoint", type=Path, required=True, help="explicit ROOT_LIVE checkpoint JSON")
    parser.add_argument("--current-index", type=Path, required=True, help="explicit full336 current progress index JSON")
    parser.add_argument("--membership", type=Path, required=True, help="explicit Root1276 F2 fixed membership JSON")
    parser.add_argument("--legacy-catalog", type=Path, required=True, help="explicit previous F2 primary catalog JSON")
    parser.add_argument("--output-dir", type=Path, required=True, help="new output directory; no shared/index writes")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = build_from_inputs(args.checkpoint, args.current_index, args.membership, args.legacy_catalog, args.output_dir)
    payload = result["payload"]
    print(json.dumps({
        "status": "BUILT_READINESS" if result["mode"] == "readiness" else "BUILT_COMPLETE",
        "mode": result["mode"],
        "path": str(result["path"]),
        "registered_final48": payload["observed_counts"]["registered_final48"],
        "accepted_visual": payload["observed_counts"]["accepted_visual"],
        "pending_visual": payload["observed_counts"]["pending_visual"],
        "complete_final48_emitted": payload["complete_final48_emitted"],
    }, sort_keys=True))
