#!/usr/bin/env python3
"""Build fresh172 from F3 JSON metadata only.

The builder opens and hashes JSON metadata only.  XMF/XML/PNG references are
stat checked; H5/BI4/IBI4/CSV/DAT/VTK scientific payloads are never opened or
hashed.  The catalog is a frozen metadata product and performs no launches.
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
CP247 = HANDOFF / (
    "root_stage1_F6_47_actual_native_receipts_34_old_nulls_recovered_full336_331_unique_digest_"
    "five_true_legacy_absences_1320/full336-current298-actual-final48-delivery-progress-index.json"
)
ROOT247 = HANDOFF / "ROOT_LIVE_RESUMPTION_CHECKPOINT_247.json"
FIRST24 = HANDOFF / (
    "root_stage1_sources178164_actual_F2_F3_F6_first24_delivery72_correct_own_primary_XMF_PNG_8_"
    "subset24_subset48_1276/F3-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json"
)
READINESS = HANDOFF / (
    "root_stage1_source166_remaining9_actualF3_full836_own_metadata_UID_N3_unknown154_"
    "audit_recovery_scope_discrepancies_readiness_1287/remaining9-F3-full836-own-metadata-readiness-adoption.json"
)
CATALOG = HERE / "F3-FINAL48-PRIMARY-DELIVERY-39ACCEPTED-NINE-PENDING.json"
SCHEMA = "ds02.f3.fresh172.final48.primary-delivery.39accepted-nine-pending.v1"
FORBIDDEN = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}


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

    Several historical F3 decisions intentionally have different native and
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

    return {
        "accepted_decision": copy.deepcopy(decision_ref),
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


def build() -> dict[str, Any]:
    cp = read_json(CP247, "cp247 current full336 index")
    checkpoint = read_json(ROOT247, "ROOT_LIVE_RESUMPTION_CHECKPOINT_247")
    first = read_json(FIRST24, "Root1276 F3 first24 product")
    readiness = read_json(READINESS, "Root1287 remaining9 readiness")
    require = lambda cond, msg: die(msg) if not cond else None
    require(cp.get("schema") == "ds02.stage1.full336.role-aware-progress-index.v6", "current full336 schema mismatch")
    require(checkpoint.get("checkpoint") == 247, "ROOT_LIVE checkpoint is not 247")
    require(first.get("family_id") == "F3" and first.get("actual_first24_count") == 24, "Root1276 F3 membership mismatch")
    require(readiness.get("schema") == "ds02.main.f3.remaining9.metadata-readiness.v1", "Root1287 readiness schema mismatch")
    f3_rows = [row for row in cp.get("cases", []) if row.get("family_id") == "F3"]
    require(len(f3_rows) == 48, f"expected 48 F3 rows, got {len(f3_rows)}")
    first8 = copy.deepcopy(first.get("frozen_first8_physical_case_ids", []))
    first24 = copy.deepcopy(first.get("actual_first24_physical_case_ids", []))
    final48 = copy.deepcopy(first.get("registered_final48_physical_case_ids", []))
    require(len(first8) == 8 and len(first24) == 24 and len(final48) == 48, "Root1276 membership counts mismatch")
    require(set(first8) <= set(first24) <= set(final48), "Root1276 membership subset relation missing")
    require({r.get("physical_case_id") for r in f3_rows} == set(final48), "current F3 set differs from Root1276 final48")
    require(checkpoint.get("accepted_per_family", {}).get("F3") == 39, "cp247 F3 accepted count is not 39")
    ready_map = {c.get("physical_case_id"): c for c in readiness.get("cases", [])}
    pending = [row for row in f3_rows if not isinstance(row.get("accepted_decision"), dict)]
    accepted = [row for row in f3_rows if isinstance(row.get("accepted_decision"), dict)]
    require(len(accepted) == 39 and len(pending) == 9, "current F3 is not 39 accepted + 9 pending")
    require(set(ready_map) == {r.get("physical_case_id") for r in pending}, "Root1287 readiness does not exactly cover current pending9")
    first_rows = {row.get("physical_case_id"): row for row in first.get("actual_own_primary_rows", [])}
    rows: list[dict[str, Any]] = []
    for order, progress in enumerate(f3_rows, 1):
        physical = progress["physical_case_id"]
        member = {
            "frozen_first8_member": physical in first8,
            "actual_first24_member": physical in first24,
            "registered_final48_member": physical in final48,
            "authoritative_order": "cp247 current full336 F3 row order; first8/first24 membership copied from Root1276, never redefined by accepted count",
        }
        if isinstance(progress.get("accepted_decision"), dict):
            dref = copy.deepcopy(progress["accepted_decision"])
            dpath = Path(dref["path"])
            decision = read_json(dpath, f"accepted F3 decision {physical}")
            require(decision.get("family_id") == "F3", f"accepted decision family mismatch: {physical}")
            require(decision.get("physical_case_id") == physical, f"accepted decision physical ID mismatch: {physical}")
            require(sha_json(dpath, f"accepted decision {physical}") == dref.get("sha256"), f"accepted decision SHA mismatch: {physical}")
            visual = select_accepted(decision, dref, first_rows.get(physical))
            rows.append({
                "delivery_order": order,
                "family_id": "F3",
                "case_id": progress.get("case_id"),
                "physical_case_id": physical,
                "delivery_status": "accepted_visual_decision_in_cp247",
                "membership": member,
                "accepted_visual_metadata": visual,
                "progress_index_row": copy.deepcopy(progress),
                "root1276_first24_crosscheck": copy.deepcopy(first_rows.get(physical)) if physical in first24 else None,
                "scope_roles": {
                    "cp247_declared": {
                        "accepted_decision_top_condition_sha256": progress.get("accepted_decision_top_condition_sha256"),
                        "accepted_decision_top_hash_role": progress.get("accepted_decision_top_hash_role"),
                        "declared_source_plan_condition_sha256": progress.get("declared_source_plan_condition_sha256"),
                        "declared_source_definition_sha256": progress.get("declared_source_definition_sha256"),
                        "declared_actual_converter_scope_sha256": progress.get("declared_actual_converter_scope_sha256"),
                        "native_request_scope": copy.deepcopy(progress.get("native_request_scope")),
                    },
                    "decision_scope_roles": copy.deepcopy(decision.get("scope_separation")),
                    "roles_must_remain_distinct": True,
                },
                "credit_boundary": {"case_credit": 0, "new_visual_credit": 0, "Q_N": 0, "Q_E": 0, "numeric_precision_accepted": False},
            })
        else:
            ready = ready_map[physical]
            rref = {"path": str(READINESS), "sha256": sha_json(READINESS, "Root1287 readiness"), "role": "Root1287 remaining9 readiness source"}
            rows.append({
                "delivery_order": order,
                "family_id": "F3",
                "case_id": progress.get("case_id"),
                "physical_case_id": physical,
                "delivery_status": "pending_visual_pipeline_readiness_no_accepted_decision",
                "membership": member,
                "pending_metadata": select_pending(progress, ready, rref),
                "progress_index_row": copy.deepcopy(progress),
                "root1276_first24_crosscheck": None,
                "scope_roles": {
                    "cp247_declared": {
                        "declared_render_request_condition_sha256": progress.get("declared_render_request_condition_sha256"),
                        "declared_actual_converter_scope_sha256": progress.get("declared_actual_converter_scope_sha256"),
                        "native_request_scope": copy.deepcopy(progress.get("native_request_scope")),
                    },
                    "roles_must_remain_distinct": True,
                },
                "credit_boundary": {"case_credit": 0, "new_visual_credit": 0, "Q_N": 0, "Q_E": 0, "numeric_precision_accepted": False},
            })
    catalog = {
        "schema": SCHEMA,
        "status": "metadata_complete_39_accepted_nine_pending",
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "assignment": {
            "assigned_family": "F3",
            "actual_family": "F3",
            "source_package_role": "final48 primary particle/XMF delivery; accepted metadata plus nine pending pipeline-readiness boundaries",
            "package_name": HERE.name,
            "scientific_payload_read_or_hashed_by_source": False,
            "new_science_jobs": 0,
            "new_case_credit": 0,
            "Q_N": 0,
            "Q_E": 0,
            "numeric_precision_accepted": False,
        },
        "authoritative_sources": {
            "cp247_current_full336_index": source_ref(CP247, "cp247 current full336 index"),
            "root_live_resumption_checkpoint_247": source_ref(ROOT247, "ROOT_LIVE checkpoint247"),
            "root1276_f3_fixed_membership_and_first24": source_ref(FIRST24, "Root1276 F3 first24 product"),
            "root1287_f3_remaining9_readiness": source_ref(READINESS, "Root1287 remaining9 readiness"),
        },
        "membership": {
            "frozen_first8_physical_case_ids": first8,
            "actual_first24_physical_case_ids": first24,
            "registered_final48_physical_case_ids": final48,
            "frozen8_subset_actual24_subset_registered48": True,
            "membership_source_is_root1276": True,
            "accepted_count_does_not_redefine_first24": True,
            "membership_selection": "copied from Root1276 explicit arrays; no directory or lexical selection",
        },
        "delivery": {
            "registered_final48_count": 48,
            "accepted_visual_count": 39,
            "pending_visual_count": 9,
            "accepted_visual_delivery_complete": False,
            "pending_case_ids": [r["physical_case_id"] for r in rows if r["delivery_status"].startswith("pending")],
            "pending_are_not_visual_acceptance": True,
            "pending_native_typed_xmf_are_readiness_metadata_only": True,
        },
        "pending_boundary": {
            "source166_root1287_is_pipeline_readiness_not_visual_decision": True,
            "outer_p0800_envelope_801_frames_194427_particles_is_preserved_when_present": True,
            "source_plan_condition_sha256_key_absence_is_preserved": True,
            "original_pending154_typed_receipt_is_not_promoted": True,
            "live_original1141_ay0640_and_original1135_ay0570_are_not_restarted": True,
        },
        "scope_policy": {
            "physical_case_id_is_the_join_key": True,
            "primary_refs_must_be_case_local": True,
            "native_typed_xmf_render_source_plan_and_legacy_roles_remain_separate": True,
            "missing_key_paths_are_disclosed_not_inferred": True,
            "PNG_refs_are_stat_only_and_not_personal_view_claims": True,
            "declared_visual_digest_policy": "builder does not read visual bytes; validator checks a producer-declared PNG/XMF/XML digest when present",
            "scientific_payload_boundary": "JSON metadata is read/hashed; XMF/XML/PNG are stat-only references while building; H5/BI4/IBI4/CSV/DAT/VTK are never opened or hashed",
            "no_jobs_or_shared_state": True,
        },
        "rows": rows,
    }
    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return catalog


if __name__ == "__main__":
    out = build()
    print(json.dumps({"status": "BUILT", "catalog": str(CATALOG), "rows": len(out["rows"]), "accepted": out["delivery"]["accepted_visual_count"], "pending": out["delivery"]["pending_visual_count"]}, sort_keys=True))
