#!/usr/bin/env python3
"""Build fresh174 from F5 JSON metadata only.

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
CP254 = HANDOFF / "root_stage1_source186_actualF3_P1200AY0570_original1135_full836QI_personal44PNG_exact_native_XMF_plan_absence_visual_acceptance_1335/full336-current302-actual-final48-delivery-progress-index.json"
ROOT254 = HANDOFF / "ROOT_LIVE_RESUMPTION_CHECKPOINT_254.json"
FIRST24 = HANDOFF / "root_stage1_F5_actual24_dynamic_delivery_own801_XMF_primary1032PNG_frozen8_subset24_subset48_1293/F5-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json"
CATALOG = HERE / "F5-FINAL48-PRIMARY-DELIVERY-28ACCEPTED-TWENTY-PENDING.json"
SCHEMA = "ds02.f5.fresh174.final48.primary-delivery.28accepted-twenty-pending.v1"
FORBIDDEN = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}

# Root1293 explicitly preserves four historical render products whose
# atomic-publish receipt was absent.  Their render reports and PNG references
# are still useful, but a request/planning JSON must never be promoted to a
# terminal receipt in their place.
LEGACY_PUBLISH_RECEIPT_ABSENT_IDS = {
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_A080",
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_A120",
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_M085_T080",
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_M115_T100",
}


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


def is_terminal_receipt_path(path: Path) -> bool:
    """Accept only receipt filenames, never enabled/request/planning JSON."""
    name = path.name.lower()
    return (
        path.suffix.lower() == ".json"
        and (
            "execution-receipt" in name
            or "render-publish-receipt" in name
            or name in {"conversion-receipt.json", "native-receipt.json"}
        )
        and not name.endswith("request.json")
        and "enabled" not in name
    )


def sanitize_receipt(ref: dict[str, Any] | None, role: str) -> dict[str, Any] | None:
    """Return a case-local terminal receipt ref or None.

    A path named ``*-request.json`` can contain status-like fields, so it is
    deliberately rejected even when a producer decision used it under a
    misleading ``*_receipt`` key.  Missing returncode/status fields remain
    metadata facts on an actual receipt; they are not filled here.
    """
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        return None
    path = Path(ref["path"])
    if not is_terminal_receipt_path(path) or not path.is_file():
        return None
    obj = read_json(path, f"{role} candidate {path}")
    if not isinstance(obj, dict):
        return None
    if not any(key in obj for key in ("status", "returncode", "execution_status", "schema")):
        return None
    out = copy.deepcopy(ref)
    out["role"] = role
    out["receipt_filename_contract"] = "terminal execution/render-publish receipt; request JSON rejected"
    out["receipt_metadata_presence"] = {
        "status_field_present": "status" in obj,
        "returncode_field_present": "returncode" in obj,
        "execution_status_field_present": "execution_status" in obj,
        "schema_field_present": "schema" in obj,
        "status": obj.get("status"),
        "returncode": obj.get("returncode"),
    }
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

    Several historical F5 decisions intentionally have different native and
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


def refs_in_named_containers(
    sources: list[tuple[str, Any]],
    container_keys: tuple[str, ...],
    leaf_keys: tuple[str, ...],
    role: str,
) -> list[dict[str, Any]]:
    """Resolve refs below explicitly named bed/source containers only.

    This avoids treating every native/gencase ``execution_receipt`` in a
    decision as a bed receipt merely because the leaf key has the same name.
    """
    found: list[dict[str, Any]] = []

    def visit(value: Any, label: str, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                child_label = f"{label}.{key}"
                if key in container_keys:
                    direct = clone_ref(child, child_label, role)
                    if direct is not None:
                        found.append(direct)
                    else:
                        found.extend(find_all_named(child, leaf_keys, child_label, role))
                    continue
                if key in {"path", "sha256", "SHA256", "command", "input_hashes_at_launch", "input_hashes_after_run"}:
                    continue
                visit(child, child_label, depth + 1)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{label}[{index}]", depth + 1)

    for label, source in sources:
        visit(source, label)
    return dedup(found)


def fallback_ref(row: dict[str, Any] | None, key: str, role: str) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    value = row.get(key)
    if isinstance(value, list):
        value = value[0] if value else None
    return clone_ref(value, f"Root1293.actual_own_primary_rows.{key}", role)


def fallback_list(row: dict[str, Any] | None, key: str, role: str) -> list[dict[str, Any]]:
    if not isinstance(row, dict) or not isinstance(row.get(key), list):
        return []
    out: list[dict[str, Any]] = []
    for i, value in enumerate(row[key]):
        ref = clone_ref(value, f"Root1293.actual_own_primary_rows.{key}[{i}]", role)
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
    receipt = sanitize_receipt(receipt, "output_derivation_receipt")
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


def own_output_metadata(ref: dict[str, Any] | None, label: str) -> dict[str, Any]:
    """Read scalar metadata from the selected case-local JSON output only.

    This deliberately does not open XMF/XML/PNG or any scientific payload.  A
    missing scalar remains absent; the builder never fills F5 baseline values
    from another case or from a nominal envelope.
    """
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        return {"path": None, "json_read": False}
    path = Path(ref["path"])
    if path.suffix.lower() != ".json" or not path.is_file():
        return {"path": str(path), "json_read": False}
    obj = read_json(path, label)
    if not isinstance(obj, dict):
        return {"path": str(path), "json_read": True, "json_type": type(obj).__name__}
    scalar_keys = (
        "frames", "expected_frames", "frame_count", "particles", "expected_particles",
        "total_particles", "time_window_s", "times_s", "last_time_s", "duration_s",
        "status", "returncode", "published_status", "all_frames_rendered",
        "full_animation", "n3", "dimensions", "uid_missing_count", "nonfinite_count",
        "physical_case_id", "physical_condition_sha256", "xmf", "xdmf",
    )
    summary: dict[str, Any] = {"path": str(path), "json_read": True}
    for key in scalar_keys:
        if key in obj and isinstance(obj[key], (str, int, float, bool, type(None), list)):
            summary[key] = copy.deepcopy(obj[key])
    outputs = obj.get("outputs")
    if isinstance(outputs, dict):
        for key in ("contact_sheets", "contact_pages", "key_frames", "keyframes", "key_events"):
            values = outputs.get(key)
            if isinstance(values, list):
                summary[f"{key}_count"] = len(values)
    return summary


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
    # A compact legacy decision may put an ordered list of producer receipts
    # under bindings.actual_completed_receipts.  Classify those receipts by
    # their own JSON request task kind; never choose by a global path search.
    binding_receipts = bindings.get("actual_completed_receipts") if isinstance(bindings.get("actual_completed_receipts"), list) else []
    binding_native_receipt: dict[str, Any] | None = None
    binding_typed_receipt: dict[str, Any] | None = None
    for index, candidate in enumerate(binding_receipts):
        ref = clone_ref(candidate, f"decision.bindings.actual_completed_receipts[{index}]", "role_receipt_candidate")
        ref = sanitize_receipt(ref, "role_receipt_candidate")
        if ref is None or not Path(ref["path"]).is_file():
            continue
        receipt_obj = read_json(Path(ref["path"]), f"role receipt candidate {ref['path']}")
        request_obj = receipt_obj.get("request") if isinstance(receipt_obj, dict) and isinstance(receipt_obj.get("request"), dict) else {}
        task_kind = request_obj.get("cpu_task_kind")
        if task_kind == "solver" and binding_native_receipt is None:
            binding_native_receipt = ref
        elif task_kind == "conversion" and binding_typed_receipt is None:
            binding_typed_receipt = ref
    native_role = next((evidence.get(key) for key in ("native", "native_full", "full_native_solver") if isinstance(evidence.get(key), dict)), None)
    if native_role is None:
        native_role = actual_receipts.get("native") or ({"receipt": binding_native_receipt} if binding_native_receipt else None)
    typed_role = next((evidence.get(key) for key in ("typed", "typed_conversion") if isinstance(evidence.get(key), dict)), None)
    if typed_role is None:
        typed_role = actual_receipts.get("typed") or ({"receipt": binding_typed_receipt} if binding_typed_receipt else None)
    xmf_role = next((evidence.get(key) for key in ("xmf", "n3_xmf") if isinstance(evidence.get(key), dict)), None)
    if xmf_role is None:
        xmf_role = actual_receipts.get("xmf")
    render_role = next((evidence.get(key) for key in ("render", "full_render_root1066") if isinstance(evidence.get(key), dict)), None)
    if render_role is None:
        render_role = next((value for key, value in evidence.items() if key.startswith("full_render_") and isinstance(value, dict)), None)
    if render_role is None:
        render_role = actual_receipts.get("render")

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
        manifest = first_ref(sources, ("manifest", "xmf_manifest", "actual_xmf_manifest", "dynamic_xdmf_manifest", "normal_manifest"), "primary_xmf_manifest")
    if manifest is None:
        manifest = fallback_ref(first24_row, "actual_xmf_manifest", "primary_xmf_manifest")
    if manifest is None:
        manifest = fallback_ref(first24_row, "xmf_manifest", "primary_xmf_manifest")
    manifest = annotate_ref(manifest, "primary_xmf_manifest")

    xml = role_first(
        "decision.actual_completed_metadata_evidence.xmf",
        xmf_role,
        ("xmf_xml", "xdmf", "actual_xmf_xml", "dynamic_xdmf", "normal_xdmf", "case_xmf"),
        "primary_xmf_xml",
    )
    if xml is None:
        xml = first_ref(sources, ("xmf_xml", "xdmf", "actual_xmf_xml", "dynamic_xdmf", "normal_xdmf", "case_xmf", "XMF_XML"), "primary_xmf_xml")
    if xml is None:
        xml = fallback_ref(first24_row, "actual_xmf_xml", "primary_xmf_xml")
    if xml is None:
        xml = fallback_ref(first24_row, "xdmf", "primary_xmf_xml")
    xml = annotate_ref(xml, "primary_xmf_xml")
    if xml is None:
        xml = derive_xml_from_manifest(manifest)

    report = role_first(
        "decision.actual_completed_metadata_evidence.render",
        render_role,
        ("report", "animation_report", "render_report", "actual_render_report", "animation_integrity_report", "full_render_report"),
        "primary_render_report",
    )
    if report is None:
        report = first_ref(sources, ("render_report", "actual_render_report", "animation_integrity_report", "full_render_report", "native_full_render_report"), "primary_render_report")
    if report is None:
        report = fallback_ref(first24_row, "actual_render_report", "primary_render_report")
    if report is None:
        report = fallback_ref(first24_row, "render_report", "primary_render_report")
    report = annotate_ref(report, "primary_render_report")

    receipt = role_first(
        "decision.actual_completed_metadata_evidence.render",
        render_role,
        ("execution_receipt", "receipt", "render_receipt", "actual_render_receipt", "animation_receipt", "full_render_receipt", "render_publish_receipt", "publish_receipt"),
        "primary_render_receipt",
    )
    if receipt is None:
        receipt = first_ref(sources, ("render_receipt", "actual_render_receipt", "animation_receipt", "full_render_receipt", "publish_receipt", "render"), "primary_render_receipt")
    if receipt is None:
        receipt = fallback_ref(first24_row, "render_receipt_refs", "primary_render_receipt")
    if receipt is None:
        receipt = fallback_ref(first24_row, "atomic_publish_receipt", "primary_render_receipt")
    receipt = sanitize_receipt(receipt, "primary_render_receipt")

    # Preserve uppercase compact schemas used by several accepted decisions,
    # then derive the fixed worker outputs from the own terminal receipts if
    # the decision stored only those receipts.
    if manifest is None:
        manifest = first_ref(
            [("decision.actual_completed_metadata_evidence", evidence)],
            ("XMF_manifest", "manifest", "xmf_manifest", "actual_xmf_manifest", "dynamic_xdmf_manifest", "normal_manifest"),
            "primary_xmf_manifest",
        )
        manifest = annotate_ref(manifest, "primary_xmf_manifest")
    if xml is None:
        xml = first_ref(
            [("decision.actual_completed_metadata_evidence", evidence)],
            ("XMF_XML", "xmf_xml", "xdmf", "actual_xmf_xml", "dynamic_xdmf", "normal_xdmf", "case_xmf"),
            "primary_xmf_xml",
        )
        xml = annotate_ref(xml, "primary_xmf_xml")

    xmf_receipt_for_outputs = role_first(
        "decision.actual_completed_metadata_evidence.xmf",
        xmf_role,
        ("execution_receipt", "receipt", "xmf_receipt"),
        "xmf_receipt",
    )
    xmf_receipt_for_outputs = sanitize_receipt(xmf_receipt_for_outputs, "xmf_receipt")
    render_receipt_for_outputs = role_first(
        "decision.actual_completed_metadata_evidence.render",
        render_role,
        ("execution_receipt", "receipt", "render_receipt", "render_publish_receipt", "publish_receipt"),
        "render_receipt",
    )
    render_receipt_for_outputs = sanitize_receipt(render_receipt_for_outputs, "render_receipt")
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
            ("animation_report", "render_report", "actual_render_report", "animation_integrity_report", "full_render_report", "native_full_render_report"),
            "primary_render_report",
        )
        report = annotate_ref(report, "primary_render_report")
    if report is None:
        report = annotate_ref(render_outputs.get("render_report"), "primary_render_report")
    if receipt is None:
        receipt = annotate_ref(render_outputs.get("receipt"), "primary_render_receipt")
        receipt = sanitize_receipt(receipt, "primary_render_receipt")

    native = []
    native_role_ref = role_first(
        "decision.actual_completed_metadata_evidence.native",
        native_role,
        ("execution_receipt", "receipt", "native_receipt", "full_native_receipt"),
        "native_receipt",
    )
    if native_role_ref is not None:
        native.append(native_role_ref)
    native.extend(all_refs(sources, ("native_receipt", "full_native_receipt"), "native_receipt"))
    native += all_refs(sources, ("native",), "native_receipt")
    if not native and isinstance(first24_row, dict):
        native_scope = first24_row.get("canonical_actual_native_request_scope")
        if isinstance(native_scope, dict):
            native_candidate = native_scope.get("actual_native_receipt")
            if native_candidate is not None:
                native.append(clone_ref(native_candidate, "Root1293.actual_own_primary_rows.canonical_actual_native_request_scope.actual_native_receipt", "native_receipt"))
    if not native:
        native = fallback_list(first24_row, "native_refs", "native_receipt")
    native = [annotate_ref(sanitize_receipt(x, "native_receipt"), "native_receipt") for x in dedup(native)]
    native = [x for x in native if x is not None]

    typed = []
    typed_role_receipt = role_first(
        "decision.actual_completed_metadata_evidence.typed",
        typed_role,
        ("execution_receipt", "receipt", "typed_receipt", "typed_conversion_receipt"),
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
    if not typed and isinstance(first24_row, dict):
        typed_scope = first24_row.get("typed_report_authority")
        if typed_scope is not None:
            typed.append(clone_ref(typed_scope, "Root1293.actual_own_primary_rows.typed_report_authority", "typed_report"))
    if not typed:
        typed = fallback_list(first24_row, "typed_refs", "typed_receipt_or_report")
    typed_receipts: list[dict[str, Any]] = []
    typed_reports: list[dict[str, Any]] = []
    for x in dedup(typed):
        if x.get("source_key", "").endswith("conversion_report") or "report" in x.get("role", ""):
            typed_reports.append(annotate_ref(x, "typed_report"))
        else:
            clean = sanitize_receipt(x, "typed_receipt")
            if clean is not None:
                typed_receipts.append(annotate_ref(clean, "typed_receipt"))
    typed = [x for x in typed_receipts + typed_reports if x is not None]

    gencase = all_refs(sources, ("gencase_receipt", "generated_xml", "generated_definition_xml", "prepared_input_report", "genuine_gencase"), "gencase_or_definition")
    if not gencase:
        gencase = fallback_list(first24_row, "gencase_or_definition_refs", "gencase_or_definition")
    gencase = [annotate_ref(x, "gencase_or_definition") for x in dedup(gencase)]

    qa = all_refs(sources, ("initial_native_qa", "native_initial_qa", "initial_qa", "initial_qa_report", "initial_qa_receipt", "artifact_audit_receipt", "audit_report", "chain_audit"), "initial_qa_or_audit")
    if not qa:
        qa = fallback_list(first24_row, "initial_qa_or_audit_refs", "initial_qa_or_audit")
    qa = [annotate_ref(x, "initial_qa_or_audit") for x in dedup(qa)]

    owners = all_refs(sources, ("owner_metadata", "physical_binding_semantic_source", "source_definition", "source_plan_path", "source_condition_template"), "owner_or_source")
    if not owners:
        owners = fallback_list(first24_row, "owner_or_source_refs", "owner_or_source")
    owners = [annotate_ref(x, "owner_or_source") for x in dedup(owners)]

    bed_refs = refs_in_named_containers(
        sources,
        (
            "bed_receipt", "bed_report", "bed_audit", "bed_audit_report", "bed_review",
            "bed_source_definition", "bed_SourceDef", "source_definition",
            "actual_full801_bed_independent_review", "bed_independent_review",
        ),
        ("execution_receipt", "report", "generated_definition_xml", "generated_def_xml"),
        "bed_or_source_definition",
    )
    if not bed_refs and isinstance(first24_row, dict):
        bed_refs = fallback_list(first24_row, "bed_refs", "bed_or_source_definition")
    bed_refs = [annotate_ref(x, "bed_or_source_definition") for x in dedup(bed_refs)]

    def role_field_presence(objects: list[tuple[str, Any]], keys: tuple[str, ...]) -> dict[str, Any]:
        for label, obj in objects:
            if not isinstance(obj, dict):
                continue
            for key in keys:
                if key in obj:
                    return {"present": True, "source": label, "key": key, "value": copy.deepcopy(obj[key])}
        return {"present": False, "source": None, "key": None, "value": None}

    role_objects: list[tuple[str, Any]] = [
        ("decision", decision),
        ("decision.scope_separation", decision.get("scope_separation")),
        ("decision.actual_completed_metadata_evidence", evidence),
        ("decision.actual_completed_metadata_evidence.native", native_role),
        ("decision.actual_completed_metadata_evidence.typed", typed_role),
        ("decision.actual_completed_metadata_evidence.xmf", xmf_role),
        ("decision.actual_completed_metadata_evidence.render", render_role),
    ]
    role_presence = {
        "native_canonical": role_field_presence(role_objects, ("canonical_scope_sha256", "canonical_physical_scope_sha256", "native_canonical_scope_sha256", "physical_condition_sha256")),
        "native_source_plan": role_field_presence(role_objects, ("actual_native_plan_field_present", "actual_native_plan_field_value", "native_plan", "native_source_plan", "source_plan_condition_sha256")),
        "typed_legacy": role_field_presence(role_objects, ("typed_h5_sha256_producer_attested", "source_h5_legacy_scope_sha256", "actual_converter_scope_sha256", "legacy_scope_sha256")),
        "xmf_declared_canonical": role_field_presence(role_objects, ("physical_condition_sha256", "declared_physical_condition_sha256", "canonical_physical_scope_sha256")),
        "xmf_source_h5": role_field_presence(role_objects, ("source_h5_sha256", "source_h5_physical_condition_sha256", "trajectory_h5_sha256", "source_h5_legacy_scope_sha256")),
        "xmf_source_plan": role_field_presence(role_objects, ("source_plan_condition_sha256", "declared_source_plan_condition_sha256", "fresh130_source_plan_sha256")),
        "bed_source_def": role_field_presence(role_objects, ("bed_SourceDef_scope_sha256", "bed_XMF_SourceDef_scope_sha256", "source_definition_sha256", "source_definition")),
    }

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
        fallback_contacts = []
        if isinstance(first24_row, dict):
            fallback_contacts = first24_row.get("contact_png_refs", []) or first24_row.get("contact_sheets", [])
        contacts = [normalize_png(v, f"Root1293.actual_own_primary_rows.contact_sheets[{i}]", "contact_png") for i, v in enumerate(fallback_contacts)]
        contacts = [v for v in contacts if v]
    if not keys and isinstance(first24_row, dict):
        fallback_keys = first24_row.get("key_png_refs", []) or first24_row.get("navigation_keyframes", [])
        keys = [normalize_png(v, f"Root1293.actual_own_primary_rows.navigation_keyframes[{i}]", "key_png") for i, v in enumerate(fallback_keys)]
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
        "actual_result_metadata": {
            "source": "selected case-local XMF manifest and render report JSON; no nominal values substituted",
            "xmf_manifest": own_output_metadata(manifest, f"own XMF manifest metadata {decision.get('physical_case_id') or decision.get('case_id')}"),
            "render_report": own_output_metadata(report, f"own render report metadata {decision.get('physical_case_id') or decision.get('case_id')}"),
        },
        "native_refs": native,
        "typed_refs": typed,
        "gencase_or_definition_refs": gencase,
        "initial_qa_or_audit_refs": qa,
        "owner_or_source_refs": owners,
        "bed_refs": bed_refs,
        "role_field_presence": role_presence,
        "render_receipt_boundary": {
            "terminal_receipt_present": receipt is not None,
            "terminal_receipt_absent": receipt is None,
            "absence_is_explicit_legacy_publish_boundary": receipt is None and decision.get("physical_case_id") in LEGACY_PUBLISH_RECEIPT_ABSENT_IDS,
            "request_json_was_not_promoted_to_terminal_receipt": True,
        },
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


def select_pending(progress: dict[str, Any], readiness_ref: dict[str, Any]) -> dict[str, Any]:
    """Copy only this pending row's bounded readiness metadata.

    The current-index rows are the available authority for these twenty cases.
    No not-yet-submitted W6/source187 readiness package is substituted.  The
    native receipt and loaded XMF manifest are explicit nested fields in the
    row; a render receipt remains an observation (usually null) and is never
    promoted to a visual decision.
    """
    native_scope = progress.get("native_request_scope") if isinstance(progress.get("native_request_scope"), dict) else {}
    native_evidence = native_scope.get("evidence") if isinstance(native_scope.get("evidence"), dict) else {}
    native_receipt = native_evidence.get("receipt")
    if native_receipt is None:
        observation = native_scope.get("actual_native_receipt_observation")
        if isinstance(observation, dict):
            native_receipt = observation.get("actual_native_receipt")
    wrapper = progress.get("actual_wrapper_contract_and_live_observation")
    wrapper = wrapper if isinstance(wrapper, dict) else {}
    actual_manifest = wrapper.get("actual_manifest")
    loaded_wrapper = wrapper.get("actual_loaded_wrapper")
    native_ref = clone_ref(native_receipt, "cp254.current_index.native_request_scope.evidence.receipt", "pending_native_receipt")
    xmf_refs: list[dict[str, Any]] = []
    manifest_ref = clone_ref(actual_manifest, "cp254.current_index.actual_wrapper_contract.actual_manifest", "pending_xmf_manifest")
    if manifest_ref:
        xmf_refs.append(manifest_ref)
    wrapper_ref = clone_ref(loaded_wrapper, "cp254.current_index.actual_wrapper_contract.actual_loaded_wrapper", "pending_loaded_wrapper")
    actual_native_completed = (
        native_evidence.get("status") == "completed"
        and native_evidence.get("returncode") == 0
    )
    serialized_row = json.dumps(progress, ensure_ascii=False, sort_keys=True)
    historical_attempts = [label for label in ("1181", "1191") if label in serialized_row]
    return {
        "accepted_decision": None,
        "primary_particle_xmf_render_refs": None,
        "primary_png_refs": None,
        "pending_readiness_source": copy.deepcopy(readiness_ref),
        "cp254_current_index_case_metadata": copy.deepcopy(progress),
        "native_metadata_refs": [annotate_ref(native_ref, "pending_native_receipt")] if native_ref else [],
        "typed_metadata_refs": [],
        "xmf_metadata_refs": [annotate_ref(x, "pending_xmf_receipt_manifest_or_xml") for x in xmf_refs],
        "loaded_wrapper_metadata_refs": [annotate_ref(wrapper_ref, "pending_loaded_wrapper") ] if wrapper_ref else [],
        "artifact_audit_metadata_refs": [],
        "historical_render_observation_snapshot": {
            "source": "cp254 current-index pending row only",
            "attempt_labels_observed_in_frozen_row": historical_attempts,
            "status": "historical_snapshot_only",
            "not_a_terminal_receipt": True,
            "not_a_visual_decision": True,
            "visual_credit": 0,
        },
        "pending_status_boundary": {
            "visual_credit": 0,
            "no_accepted_visual_decision": True,
            "native_typed_xmf_are_pipeline_readiness_evidence_only": True,
            "native_completed0_observed_in_current_index": actual_native_completed,
            "render_receipt_not_observed_as_terminal": True,
            "render_published0_observed": bool(wrapper.get("published0", False)),
            "outer_envelope_stale": progress.get("original_index_expected_fields_preserved"),
            "outer_expected_frames": progress.get("expected_frames"),
            "outer_expected_particles": progress.get("expected_particles"),
            "source_plan_condition_field_present": None,
            "source_plan_condition_sha256": None,
            "current_controller_observation": copy.deepcopy(progress.get("current_controller_observation")),
            "latest_registered_render_request": copy.deepcopy(progress.get("latest_registered_render_request")),
        },
        "scope_roles": {
            "source_scope_roles_preserved": None,
            "actual_XMF_exact_plan_field_namespaces": None,
            "source_native_scope_roles_preserved": copy.deepcopy(progress.get("native_request_scope")),
            "declared_actual_converter_scope_sha256": progress.get("declared_actual_converter_scope_sha256"),
            "declared_render_request_condition_sha256": progress.get("declared_render_request_condition_sha256"),
        },
    }


def build() -> dict[str, Any]:
    cp = read_json(CP254, "cp254 current full336 index")
    checkpoint = read_json(ROOT254, "ROOT_LIVE_RESUMPTION_CHECKPOINT_254")
    first = read_json(FIRST24, "Root1293 F5 first24 product")
    require = lambda cond, msg: die(msg) if not cond else None
    require(cp.get("schema") == "ds02.stage1.full336.role-aware-progress-index.v6", "current full336 schema mismatch")
    require(checkpoint.get("checkpoint") == 254, "ROOT_LIVE checkpoint is not 254")
    require(first.get("family_id") == "F5" and first.get("actual_first24_count") == 24, "Root1293 F5 membership mismatch")
    f5_rows = [row for row in cp.get("cases", []) if row.get("family_id") == "F5"]
    require(len(f5_rows) == 48, f"expected 48 F5 rows, got {len(f5_rows)}")
    first8 = copy.deepcopy(first.get("frozen_first8_physical_case_ids", []))
    first24 = copy.deepcopy(first.get("actual_first24_physical_case_ids", []))
    final48 = copy.deepcopy(first.get("registered_final48_physical_case_ids", []))
    require(len(first8) == 8 and len(first24) == 24 and len(final48) == 48, "Root1293 membership counts mismatch")
    require(set(first8) <= set(first24) <= set(final48), "Root1293 membership subset relation missing")
    require({r.get("physical_case_id") for r in f5_rows} == set(final48), "current F5 set differs from Root1293 final48")
    require(checkpoint.get("accepted_per_family", {}).get("F5") == 28, "cp254 F5 accepted count is not 28")
    pending = [row for row in f5_rows if not isinstance(row.get("accepted_decision"), dict)]
    accepted = [row for row in f5_rows if isinstance(row.get("accepted_decision"), dict)]
    require(len(accepted) == 28 and len(pending) == 20, "current F5 is not 28 accepted + 20 pending")
    first_rows = {row.get("physical_case_id"): row for row in first.get("actual_own_primary_rows", [])}
    rows: list[dict[str, Any]] = []
    for order, progress in enumerate(f5_rows, 1):
        physical = progress["physical_case_id"]
        member = {
            "frozen_first8_member": physical in first8,
            "actual_first24_member": physical in first24,
            "registered_final48_member": physical in final48,
            "authoritative_order": "cp254 current full336 F5 row order; first8/first24 membership copied from Root1293, never redefined by accepted count",
        }
        if isinstance(progress.get("accepted_decision"), dict):
            dref = copy.deepcopy(progress["accepted_decision"])
            dpath = Path(dref["path"])
            decision = read_json(dpath, f"accepted F5 decision {physical}")
            require(decision.get("family_id") == "F5", f"accepted decision family mismatch: {physical}")
            require(decision.get("physical_case_id") == physical, f"accepted decision physical ID mismatch: {physical}")
            require(sha_json(dpath, f"accepted decision {physical}") == dref.get("sha256"), f"accepted decision SHA mismatch: {physical}")
            visual = select_accepted(decision, dref, first_rows.get(physical))
            rows.append({
                "delivery_order": order,
                "family_id": "F5",
                "case_id": progress.get("case_id"),
                "physical_case_id": physical,
                "delivery_status": "accepted_visual_decision_in_cp254",
                "membership": member,
                "accepted_visual_metadata": visual,
                "progress_index_row": copy.deepcopy(progress),
                "root1293_first24_crosscheck": copy.deepcopy(first_rows.get(physical)) if physical in first24 else None,
                "scope_roles": {
                    "cp254_declared": {
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
            rref = {"path": str(CP254), "sha256": sha_json(CP254, "cp254 current-index pending row readiness source"), "role": "cp254 current-index pending row readiness source"}
            rows.append({
                "delivery_order": order,
                "family_id": "F5",
                "case_id": progress.get("case_id"),
                "physical_case_id": physical,
                "delivery_status": "pending_visual_pipeline_readiness_no_accepted_decision",
                "membership": member,
                "pending_metadata": select_pending(progress, rref),
                "progress_index_row": copy.deepcopy(progress),
                "root1293_first24_crosscheck": None,
                "scope_roles": {
                    "cp254_declared": {
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
        "status": "metadata_complete_28_accepted_twenty_pending",
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "assignment": {
            "assigned_family": "F3",
            "actual_family": "F5",
            "source_package_role": "F3-isolated source package carrying F5 final48 primary particle/XMF delivery; accepted metadata plus twenty pending pipeline-readiness boundaries",
            "package_name": HERE.name,
            "scientific_payload_read_or_hashed_by_source": False,
            "new_science_jobs": 0,
            "new_case_credit": 0,
            "Q_N": 0,
            "Q_E": 0,
            "numeric_precision_accepted": False,
        },
        "authoritative_sources": {
            "cp254_current_full336_index": source_ref(CP254, "cp254 current full336 index"),
            "root_live_resumption_checkpoint_254": source_ref(ROOT254, "ROOT_LIVE checkpoint254"),
            "root1293_f5_fixed_membership_and_first24": source_ref(FIRST24, "Root1293 F5 first24 product"),
        },
        "membership": {
            "frozen_first8_physical_case_ids": first8,
            "actual_first24_physical_case_ids": first24,
            "registered_final48_physical_case_ids": final48,
            "frozen8_subset_actual24_subset_registered48": True,
            "membership_source_is_root1293": True,
            "accepted_count_does_not_redefine_first24": True,
            "membership_selection": "copied from Root1293 explicit arrays; no directory or lexical selection",
        },
        "delivery": {
            "registered_final48_count": 48,
            "accepted_visual_count": 28,
            "pending_visual_count": 20,
            "accepted_visual_delivery_complete": False,
            "pending_case_ids": [r["physical_case_id"] for r in rows if r["delivery_status"].startswith("pending")],
            "pending_are_not_visual_acceptance": True,
            "pending_native_typed_xmf_are_readiness_metadata_only": True,
        },
        "pending_boundary": {
            "cp254_current_index_pending_rows_are_pipeline_readiness_not_visual_decision": True,
            "outer_envelope_fields_are_preserved_when_present": True,
            "source_plan_condition_sha256_key_absence_is_preserved": True,
            "original_pending154_typed_receipt_is_not_promoted": True,
            "live_or_pending_original_render_requests_are_not_restarted": True,
            "legacy_render_publish_receipt_absent_physical_case_ids": sorted(LEGACY_PUBLISH_RECEIPT_ABSENT_IDS),
            "request_json_never_promoted_to_terminal_receipt": True,
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
