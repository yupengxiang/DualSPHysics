#!/usr/bin/env python3
"""Metadata-only, completion-only F5 final48 builder.

This program consumes JSON control/receipt/report metadata and filesystem
metadata for XML/XMF/PNG references.  It never opens scientific payloads
(H5/BI4/IBI4/CSV/DAT/VTK and related files), never launches a worker, and
never edits a shared ledger.  With the current checkpoint (35 accepted of
48), it deliberately writes a readiness catalog rather than a final48.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "ds02.f5.fresh218.final48.runtime-bed-primary-gate-repair.v1"
PACKAGE = "root_followup_218_f5_final48_fulltime_runtime_bed_primary_gate_repair_v1"
EXPECTED_FAMILY = "F5"
EXPECTED_COUNTS = (8, 24, 48)
EXPECTED_FRAMES = 801
EXPECTED_PARTICLES = 194427
EXPECTED_CONTACTS = 34
EXPECTED_KEYS = 9
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
FORBIDDEN_SUFFIXES = {
    ".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu",
    ".pvtu", ".pvd", ".raw", ".bin", ".npy", ".npz",
}
JSON_SUFFIXES = {".json"}
XML_SUFFIXES = {".xml", ".xmf", ".xdmf"}
PNG_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class BuildError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise BuildError(message)


def read_json(path: Path, label: str) -> Any:
    if path.suffix.lower() not in JSON_SUFFIXES:
        fail(f"{label} must be JSON: {path}")
    if not path.is_file():
        fail(f"missing {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - diagnostic path
        fail(f"invalid JSON {label}: {path}: {exc}")


def json_sha(path: Path, label: str) -> str:
    if path.suffix.lower() not in JSON_SUFFIXES:
        fail(f"only JSON may be hashed: {label}: {path}")
    if not path.is_file():
        fail(f"missing JSON {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata_sha(path: Path, label: str) -> str:
    """Hash JSON/XML/XMF metadata only; never hash scientific payloads."""
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES or suffix not in JSON_SUFFIXES | XML_SUFFIXES:
        fail(f"metadata_sha may only hash JSON/XML/XMF: {label}: {path}")
    if not path.is_file():
        fail(f"missing metadata {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_hex64(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def source_ref(path: Path, label: str) -> dict[str, Any]:
    return {"path": str(path), "sha256": json_sha(path, label), "role": "authoritative_json"}


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def path_value(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith("/"):
        return value
    if isinstance(value, dict):
        p = value.get("path")
        if isinstance(p, str) and p.startswith("/"):
            return p
    return None


def declared_sha(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("sha256", "SHA256", "json_sha256", "digest"):
            if isinstance(value.get(key), str):
                return value[key]
    return None


def ref(value: Any, *, role: str, source_key: str) -> dict[str, Any] | None:
    p = path_value(value)
    if p is None:
        return None
    out: dict[str, Any] = {"path": p, "role": role, "source_key": source_key}
    d = declared_sha(value)
    if d:
        out["declared_sha256"] = d
    return out


def ref_from_object(obj: Any, keys: Iterable[str], *, role: str, source_key: str) -> dict[str, Any] | None:
    if isinstance(obj, dict) and path_value(obj) is not None:
        return ref(obj, role=role, source_key=source_key)
    if not isinstance(obj, dict):
        return None
    for key in keys:
        if key in obj:
            got = ref(obj[key], role=role, source_key=f"{source_key}.{key}")
            if got is not None:
                return got
            # A role object often has {receipt: {path: ...}} or
            # {report: {path: ...}}.  This is intentionally only one level
            # deep; arbitrary recursive first-match is unsafe for nested
            # historical approvals.
            if isinstance(obj[key], dict):
                for child_key in ("receipt", "report", "execution_receipt", "metadata", "source"):
                    got = ref(obj[key].get(child_key), role=role, source_key=f"{source_key}.{key}.{child_key}")
                    if got is not None:
                        return got
    return None


def metadata_probe(r: dict[str, Any], *, read_json_content: bool = True) -> dict[str, Any]:
    """Probe only approved metadata/reference classes.

    JSON is read and SHA-256 checked. XML/XMF/PNG are stat-only. Scientific
    payloads are represented as deferred and are never stat'ed or opened.
    """
    path = Path(r["path"])
    suffix = path.suffix.lower()
    result: dict[str, Any] = {
        "path": str(path),
        "suffix": suffix,
        "role": r.get("role"),
        "source_key": r.get("source_key"),
        "content_read_or_hashed": False,
    }
    if suffix in FORBIDDEN_SUFFIXES:
        result.update({"access": "scientific_payload_deferred", "path_checked": False})
        return result
    if suffix in JSON_SUFFIXES:
        result["path_exists"] = path.is_file()
        if not path.is_file() or not read_json_content:
            result["access"] = "json_missing_or_deferred"
            return result
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        result.update({
            "access": "json_read_and_hashed",
            "content_read_or_hashed": True,
            "bytes": len(raw),
            "actual_sha256": actual,
        })
        if "declared_sha256" in r:
            result["declared_sha256_matches"] = r["declared_sha256"] == actual
        try:
            obj = json.loads(raw.decode("utf-8"))
            result["json_type"] = "object" if isinstance(obj, dict) else "array" if isinstance(obj, list) else type(obj).__name__
            if isinstance(obj, dict):
                result["top_level_keys"] = sorted(obj.keys())[:80]
                for key in ("status", "returncode", "frames", "source_frames", "particles", "expected_frames", "physical_case_id", "case_id", "schema"):
                    if key in obj and isinstance(obj[key], (str, int, float, bool, type(None))):
                        result[f"top.{key}"] = obj[key]
        except Exception as exc:  # pragma: no cover - diagnostics
            result["json_parse_error"] = str(exc)
        return result
    if suffix in XML_SUFFIXES:
        result["path_exists"] = path.is_file()
        result["access"] = "xml_metadata_read_and_hashed_without_HDF_payload_access"
        if path.is_file():
            result["bytes_stat"] = path.stat().st_size
            result["actual_sha256"] = metadata_sha(path, result["role"] or "XML metadata")
            result["content_read_or_hashed"] = True
        return result
    if suffix in PNG_SUFFIXES:
        result["path_exists"] = path.is_file()
        result["access"] = "stat_only"
        if path.is_file():
            result["bytes_stat"] = path.stat().st_size
        return result
    # Source/Python paths can be provenance references, but are not opened.
    result.update({"access": "path_only", "path_exists": path.is_file()})
    return result


def enrich_ref(r: dict[str, Any] | None) -> dict[str, Any] | None:
    if r is None:
        return None
    out = copy.deepcopy(r)
    out["metadata_probe"] = metadata_probe(out)
    if out.get("metadata_probe", {}).get("actual_sha256"):
        out["actual_sha256"] = out["metadata_probe"]["actual_sha256"]
    if "declared_sha256" in out and "actual_sha256" in out:
        out["declared_sha256_matches"] = out["declared_sha256"] == out["actual_sha256"]
    return out


def direct_ref(obj: dict[str, Any], aliases: tuple[str, ...], role: str, label: str) -> dict[str, Any] | None:
    for key in aliases:
        if key in obj:
            got = ref_from_object(obj[key], ("path", "receipt", "report", "execution_receipt", "manifest", "xml"), role=role, source_key=f"{label}.{key}")
            if got is not None:
                return got
    return None


def role_ref(evidence: dict[str, Any], role_names: tuple[str, ...], aliases: tuple[str, ...], role: str) -> dict[str, Any] | None:
    # Exact evidence keys have precedence over a role object.  A role object
    # named xmf may itself be the XML path; allowing it to satisfy
    # xmf_manifest would silently bind XML as a JSON manifest.
    exact = direct_ref(evidence, aliases, role, "evidence")
    if exact is not None:
        return exact
    for name in role_names:
        role_obj = evidence.get(name)
        if isinstance(role_obj, dict):
            got = ref_from_object(role_obj, aliases, role=role, source_key=f"evidence.{name}")
            if got is not None:
                return got
    return None


def read_ref_json(r: dict[str, Any] | None, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    if r is None:
        return None, [f"missing_{label}_ref"]
    path = Path(r["path"])
    if path.suffix.lower() != ".json":
        return None, [f"{label}_ref_not_json"]
    if not path.is_file():
        return None, [f"{label}_json_missing"]
    obj = read_json(path, label)
    actual = json_sha(path, label)
    gaps: list[str] = []
    if r.get("declared_sha256") and r["declared_sha256"] != actual:
        gaps.append(f"{label}_declared_sha_mismatch")
    r["actual_sha256"] = actual
    r["content_read_or_hashed"] = True
    return obj if isinstance(obj, dict) else None, gaps


def status_gate(obj: dict[str, Any] | None, label: str, row: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    """Require a real execution receipt and an exact case-bound input closure.

    A status/returncode pair is deliberately insufficient: source180's toy
    lookalike receipt demonstrated that a request-shaped object can otherwise
    be promoted without proving that a runtime produced it.
    """
    if not isinstance(obj, dict):
        return False, [f"{label}_receipt_not_object"], {}
    status = obj.get("status")
    rc_present = "returncode" in obj
    rc = obj.get("returncode")
    gaps: list[str] = []
    schema = obj.get("schema")
    if not isinstance(schema, str) or not schema.startswith("ds02.execution-receipt."):
        gaps.append(f"{label}_execution_receipt_schema_missing_or_wrong")
    if status != "completed":
        gaps.append(f"{label}_status_not_completed:{status!r}")
    if not rc_present or rc != 0:
        gaps.append(f"{label}_returncode_not_zero_or_missing:{rc!r}")
    request_sha = obj.get("request_sha256")
    if not is_hex64(request_sha):
        gaps.append(f"{label}_request_sha256_missing_or_invalid")
    launch_hashes = obj.get("input_hashes_at_launch")
    after_hashes = obj.get("input_hashes_after_run")
    if not isinstance(launch_hashes, dict) or not launch_hashes:
        gaps.append(f"{label}_input_hashes_at_launch_missing")
    if not isinstance(after_hashes, dict) or not after_hashes:
        gaps.append(f"{label}_input_hashes_after_run_missing")
    if isinstance(launch_hashes, dict) and isinstance(after_hashes, dict):
        if set(launch_hashes) != set(after_hashes):
            gaps.append(f"{label}_input_hash_key_set_changed")
        for key, value in launch_hashes.items():
            if not is_hex64(value):
                gaps.append(f"{label}_launch_input_hash_invalid")
                break
            if key not in after_hashes or after_hashes.get(key) != value:
                gaps.append(f"{label}_input_hash_transition_not_stable")
                break
        for key, value in after_hashes.items():
            if not is_hex64(value):
                gaps.append(f"{label}_after_input_hash_invalid")
                break
    runner_source = obj.get("runner_source")
    runner_sha = obj.get("runner_sha256")
    if not isinstance(runner_source, str) or not runner_source.startswith("/"):
        gaps.append(f"{label}_runner_source_missing")
    if not is_hex64(runner_sha):
        gaps.append(f"{label}_runner_sha256_missing_or_invalid")
    request = obj.get("request") if isinstance(obj.get("request"), dict) else None
    if request is None:
        gaps.append(f"{label}_request_identity_missing")
    else:
        for field in ("family_id", "case_id", "physical_case_id"):
            expected = row.get(field)
            actual = request.get(field)
            if not isinstance(actual, str):
                gaps.append(f"{label}_{field}_missing")
            elif isinstance(expected, str) and actual != expected:
                gaps.append(f"{label}_{field}_mismatch")
    if isinstance(request, dict):
        request_schema = request.get("schema")
        if request_schema is not None and not isinstance(request_schema, str):
            gaps.append(f"{label}_request_schema_not_string")
        # The producer may use a stage-specific request schema, but an
        # execution receipt must retain its identity-bearing request object.
        if not isinstance(request.get("attempt_id") or request.get("request_id"), str):
            gaps.append(f"{label}_request_attempt_or_id_missing")
    return not gaps, gaps, {
        "schema": schema,
        "status": status,
        "returncode_present": rc_present,
        "returncode": rc,
        "request_identity_present": isinstance(request, dict),
        "request_sha256_present": is_hex64(request_sha),
        "input_hashes_at_launch_present": isinstance(launch_hashes, dict) and bool(launch_hashes),
        "input_hashes_after_run_present": isinstance(after_hashes, dict) and bool(after_hashes),
        "input_hash_transition_stable": isinstance(launch_hashes, dict) and launch_hashes == after_hashes,
        "runner_provenance_present": isinstance(runner_source, str) and is_hex64(runner_sha),
    }


def find_json_value(obj: Any, names: tuple[str, ...], depth: int = 0) -> Any:
    if depth > 5:
        return None
    if isinstance(obj, dict):
        for name in names:
            if name in obj:
                return obj[name]
        for key, value in obj.items():
            if key in {"input_hashes_at_launch", "input_hashes_after_run", "command", "environment"}:
                continue
            got = find_json_value(value, names, depth + 1)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for value in obj[:20]:
            got = find_json_value(value, names, depth + 1)
            if got is not None:
                return got
    return None


def raw_scope_snapshot(native_obj: dict[str, Any] | None, xmf_obj: dict[str, Any] | None) -> dict[str, Any]:
    def values(obj: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(obj, dict):
            return []
        found: list[dict[str, Any]] = []
        def walk(value: Any, path: str, depth: int) -> None:
            if depth > 6:
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    low = key.lower()
                    if "physical_condition" in low or "source_plan" in low or low in {"source_h5", "sourcedef", "source_definition"}:
                        if isinstance(child, (str, int, float, bool)) or child is None:
                            found.append({"path": f"{path}.{key}", "field": key, "value": child, "present": True})
                    if key not in {"input_hashes_at_launch", "input_hashes_after_run", "command"}:
                        walk(child, f"{path}.{key}", depth + 1)
            elif isinstance(value, list):
                for i, child in enumerate(value[:20]):
                    walk(child, f"{path}[{i}]", depth + 1)
        walk(obj, "$", 0)
        return found
    names = (
        "physical_condition_sha256",
        "source_plan_condition_sha256",
        "source_plan_physical_condition_sha256",
        "source_definition_sha256",
        "source_definition",
        "bed_SourceDef_scope_sha256",
        "source_h5_physical_condition_sha256",
    )
    def mask(obj: dict[str, Any] | None) -> dict[str, Any]:
        occurrences: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
        def walk(value: Any, path: str, depth: int) -> None:
            if depth > 7:
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in names:
                        occurrences[key].append({"path": f"{path}.{key}", "present": True, "value": child if isinstance(child, (str, int, float, bool)) or child is None else "<object>"})
                    if key not in {"input_hashes_at_launch", "input_hashes_after_run", "command"}:
                        walk(child, f"{path}.{key}", depth + 1)
            elif isinstance(value, list):
                for i, child in enumerate(value[:20]):
                    walk(child, f"{path}[{i}]", depth + 1)
        walk(obj, "$", 0)
        return {name: {"present": bool(items), "occurrences": items} for name, items in occurrences.items()}
    return {
        "native": values(native_obj),
        "xmf": values(xmf_obj),
        "native_field_presence_mask": mask(native_obj),
        "xmf_field_presence_mask": mask(xmf_obj),
        "raw_field_presence_preserved": True,
        "source_plan_absent_is_not_filled": True,
        "bed_SourceDef_is_independent_role": True,
    }


def png_refs(report_obj: dict[str, Any] | None, report_path: str | None, role: str) -> list[dict[str, Any]]:
    if not isinstance(report_obj, dict):
        return []
    outputs = report_obj.get("outputs")
    if not isinstance(outputs, dict):
        return []
    keys = ("contact_sheets", "contact_pages") if role == "contact_png" else ("keyframes", "key_frames", "key_events")
    found: list[dict[str, Any]] = []
    for key in keys:
        values = outputs.get(key)
        if not isinstance(values, list):
            continue
        for i, value in enumerate(values):
            r = ref(value, role=role, source_key=f"{report_path}:outputs.{key}[{i}]")
            if r:
                found.append(enrich_ref(r) or r)
    return found


def decision_png_refs(decision: dict[str, Any], role: str) -> list[dict[str, Any]]:
    """Use only case-local visual fields from an accepted decision as fallback.

    Historical/source catalogs are deliberately excluded; a missing key list
    remains missing rather than being filled from another case.
    """
    roots = []
    for name in ("source_personal_visual_review", "visual_review", "visual_observations", "actual_source_contacts", "actual_source_keys", "main_actual_published_navigation_keys"):
        if name in decision:
            roots.append((name, decision[name]))
    wanted = {"contact_sheets", "contact_pages", "contacts", "primary_contacts"} if role == "contact_png" else {"keyframes", "key_frames", "key_events", "keys", "primary_keyframes"}
    out: list[dict[str, Any]] = []
    def walk(value: Any, label: str, depth: int) -> None:
        if depth > 4:
            return
        if label in {"actual_source_contacts", "actual_source_keys", "main_actual_published_navigation_keys"} and isinstance(value, list):
            for i, item in enumerate(value):
                rr = ref(item, role=role, source_key=f"decision.{label}[{i}]")
                if rr:
                    out.append(enrich_ref(rr) or rr)
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if key in wanted and isinstance(child, list):
                    for i, item in enumerate(child):
                        rr = ref(item, role=role, source_key=f"decision.{label}.{key}[{i}]")
                        if rr:
                            out.append(enrich_ref(rr) or rr)
                elif key not in {"historical", "legacy", "previous", "source_catalog", "accepted_decisions"}:
                    walk(child, f"{label}.{key}", depth + 1)
        elif isinstance(value, list):
            for i, child in enumerate(value[:100]):
                walk(child, f"{label}[{i}]", depth + 1)
    for label, value in roots:
        walk(value, label, 0)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in out:
        if item["path"] not in seen:
            seen.add(item["path"])
            unique.append(item)
    return unique


def render_fulltime(report_obj: dict[str, Any] | None, decision: dict[str, Any], row: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    """Validate the actual 16 s/801-frame render metadata, never image bytes."""
    gaps: list[str] = []
    if not isinstance(report_obj, dict):
        return False, ["render_report_missing_or_unreadable"], {}
    expected_frames = EXPECTED_FRAMES
    expected_particles = EXPECTED_PARTICLES
    type_counts = {"fixed": 158559, "moving": 4210, "fluid": 31658, "floating": 0}
    declared_counts = decision.get("actual_type_counts") if isinstance(decision.get("actual_type_counts"), dict) else None
    if declared_counts:
        for key in type_counts:
            if isinstance(declared_counts.get(key), (int, float)):
                type_counts[key] = declared_counts[key]
    schema = report_obj.get("schema")
    if not isinstance(schema, str) or not schema.startswith("ds02.stage1.paraview-full-animation-integrity."):
        gaps.append("render_report_schema_missing_or_wrong")
    if report_obj.get("frames") != expected_frames:
        gaps.append(f"render_frames_not_{expected_frames}")
    if report_obj.get("source_frames") != expected_frames:
        gaps.append(f"render_source_frames_not_{expected_frames}")
    if report_obj.get("all_frames_rendered") is not True:
        gaps.append("render_all_frames_rendered_not_true")
    if report_obj.get("actual_times_preserved_exactly") is not True:
        gaps.append("render_actual_times_preserved_flag_missing_or_false")
    if report_obj.get("native_identity_axis_preserved") is not True:
        gaps.append("render_native_identity_axis_not_preserved")
    if report_obj.get("source_h5_read_only") is not True:
        gaps.append("render_source_h5_read_only_flag_missing_or_false")
    if not is_hex64(report_obj.get("source_h5_sha256")):
        gaps.append("render_source_h5_producer_attestation_missing")
    frame_diags = report_obj.get("frame_diagnostics")
    if not isinstance(frame_diags, list) or len(frame_diags) != expected_frames:
        gaps.append("render_frame_diagnostics_missing_or_wrong_count")
        frame_diags = frame_diags if isinstance(frame_diags, list) else []
    selection = report_obj.get("frame_selection")
    if not isinstance(selection, list) or selection != list(range(expected_frames)):
        gaps.append("render_frame_selection_not_exact_0_to_800")
    missing_count = wrong_frame_ids = wrong_counts = nonfinite = missing_required_fields = 0
    missing_active = missing_time = wrong_identity = 0
    actual_times: list[float] = []
    for i, frame in enumerate(frame_diags):
        if not isinstance(frame, dict):
            gaps.append(f"frame_{i}_not_object")
            continue
        if frame.get("frame") != i:
            wrong_frame_ids += 1
        if frame.get("missing") != 0:
            missing_count += 1
        if frame.get("active") != expected_particles:
            missing_active += 1
        t = frame.get("actual_time_s")
        if not finite_number(t):
            missing_time += 1
        else:
            actual_times.append(float(t))
        if frame.get("identity_axis_preserved") is not True:
            wrong_identity += 1
        finite = frame.get("finite_fields")
        if not isinstance(finite, dict):
            missing_required_fields += 4
        else:
            for field_name in ("density", "mass", "pressure", "velocity"):
                field = finite.get(field_name)
                if not isinstance(field, dict) or field.get("finite_active") is not True or field.get("nonfinite_active") != 0:
                    missing_required_fields += 1
                    if isinstance(field, dict) and isinstance(field.get("nonfinite_active"), (int, float)) and field.get("nonfinite_active") > 0:
                        nonfinite += 1
        if frame.get("finite_positions_active") is not True:
            nonfinite += 1
        actual = frame.get("type_counts_active")
        if not isinstance(actual, dict):
            wrong_counts += 1
        else:
            for key, expected in type_counts.items():
                if actual.get(key) != expected:
                    wrong_counts += 1
            if actual.get("unknown") not in (0, None):
                wrong_counts += 1
    if len(actual_times) == expected_frames:
        if any(not math.isfinite(t) for t in actual_times):
            gaps.append("render_actual_time_nonfinite")
        if any(right <= left for left, right in zip(actual_times, actual_times[1:])):
            gaps.append("render_actual_time_not_strictly_increasing")
    else:
        gaps.append("render_actual_time_sequence_incomplete")
    for count, label in ((wrong_frame_ids, "render_frame_ids_wrong"), (missing_count, "render_frames_missing_particles"),
                         (missing_active, "render_active_count_wrong"), (missing_time, "render_actual_time_missing"),
                         (missing_required_fields, "render_required_finite_fields_missing_or_false"),
                         (wrong_counts, "render_frame_counts_wrong"), (nonfinite, "render_nonfinite_or_position_flags"),
                         (wrong_identity, "render_identity_axis_flags_wrong")):
        if count:
            gaps.append(f"{label}:{count}")
    return not gaps, gaps, {
        "schema": schema,
        "frames": report_obj.get("frames"),
        "source_frames": report_obj.get("source_frames"),
        "diagnostic_count": len(frame_diags),
        "missing_frame_count": missing_count,
        "wrong_frame_id_count": wrong_frame_ids,
        "wrong_identity_count": wrong_identity,
        "wrong_count_observations": wrong_counts,
        "missing_actual_time_count": missing_time,
        "nonfinite_observations": nonfinite,
        "expected_frames": expected_frames,
        "expected_particles": expected_particles,
        "expected_type_counts": type_counts,
        "required_finite_fields": ["density", "mass", "pressure", "velocity", "positions"],
        "actual_time_values_read_from_render_metadata": actual_times,
        "diagnostic_only": bool(report_obj.get("diagnostic_only")),
        "precision_not_granted": True,
    }

def xml_metadata(path: Path, expected_frames: int, expected_particles: int | None) -> tuple[dict[str, Any] | None, list[str]]:
    """Read XMF/XML structure only; never follows an HDF/DataItem payload."""
    if not path.is_file():
        return None, ["xmf_xml_missing"]
    if path.suffix.lower() not in XML_SUFFIXES:
        return None, ["xmf_xml_wrong_suffix"]
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        return None, [f"xmf_xml_parse_error:{exc}"]
    uniform: list[ET.Element] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "Grid" and element.attrib.get("GridType") == "Uniform":
            uniform.append(element)
    times: list[float] = []
    particle_counts: list[int] = []
    for grid in uniform:
        time_el = next((child for child in grid if child.tag.rsplit("}", 1)[-1] == "Time"), None)
        if time_el is None or "Value" not in time_el.attrib:
            return {"uniform_grid_count": len(uniform), "time_values": times}, ["xmf_time_metadata_missing"]
        try:
            times.append(float(time_el.attrib["Value"]))
        except ValueError:
            return None, ["xmf_time_value_not_numeric"]
        topo = next((child for child in grid if child.tag.rsplit("}", 1)[-1] == "Topology"), None)
        if topo is None or topo.attrib.get("NumberOfElements") is None:
            particle_counts.append(-1)
        else:
            try:
                particle_counts.append(int(topo.attrib["NumberOfElements"]))
            except ValueError:
                particle_counts.append(-1)
    gaps: list[str] = []
    if len(uniform) != expected_frames:
        gaps.append(f"xmf_uniform_grid_count_not_{expected_frames}")
    if expected_particles is not None and (len(particle_counts) != len(uniform) or any(value != expected_particles for value in particle_counts)):
        gaps.append("xmf_topology_particle_count_mismatch")
    for left, right in zip(times, times[1:]):
        if not (finite_number(left) and finite_number(right)) or right <= left:
            gaps.append("xmf_time_not_strictly_increasing")
            break
    return {
        "uniform_grid_count": len(uniform),
        "time_values": times,
        "particle_counts_observed": particle_counts[:3] + particle_counts[-3:] if len(particle_counts) > 6 else particle_counts,
        "particle_count_unique": sorted(set(particle_counts)) if particle_counts else [],
        "payload_dataitems_not_opened": True,
    }, gaps


def sequence_consistency(
    typed_obj: dict[str, Any] | None,
    xmf_obj: dict[str, Any] | None,
    render_obj: dict[str, Any] | None,
    xmf_xml_summary: dict[str, Any] | None,
    decision: dict[str, Any],
    row: dict[str, Any],
) -> tuple[bool, list[str], dict[str, Any]]:
    """Join typed, XMF and render metadata on the same 801-frame identity axis."""
    gaps: list[str] = []
    expected_frames = EXPECTED_FRAMES
    expected_particles = EXPECTED_PARTICLES
    expected_types = {"0": 158559, "1": 4210, "2": 0, "3": 31658}
    typed_times: list[float] = []
    xmf_times: list[float] = []
    render_times: list[float] = []

    if not isinstance(typed_obj, dict):
        gaps.append("typed_report_unreadable")
    else:
        if typed_obj.get("schema") != "ds-data-02.bi4-direct-conversion.v1":
            gaps.append("typed_report_schema_missing_or_wrong")
        if typed_obj.get("conversion_status") != "completed":
            gaps.append("typed_conversion_status_not_completed")
        if typed_obj.get("frames") != expected_frames:
            gaps.append("typed_frames_mismatch")
        if typed_obj.get("particles") != expected_particles:
            gaps.append("typed_particles_mismatch")
        if not is_hex64(typed_obj.get("output_sha256")):
            gaps.append("typed_output_producer_attestation_missing")
        lifecycle = typed_obj.get("lifecycle")
        summary = lifecycle.get("frame_summary") if isinstance(lifecycle, dict) else None
        if not isinstance(lifecycle, dict) or lifecycle.get("contract") != "closed fixed identity axis":
            gaps.append("typed_identity_lifecycle_contract_missing")
        if not isinstance(summary, list) or len(summary) != expected_frames:
            gaps.append("typed_lifecycle_frame_summary_missing_or_wrong_count")
            summary = summary if isinstance(summary, list) else []
        for i, frame in enumerate(summary):
            if not isinstance(frame, dict):
                gaps.append(f"typed_lifecycle_frame_{i}_not_object")
                continue
            if frame.get("frame") != i:
                gaps.append("typed_lifecycle_frame_ids_mismatch")
            if frame.get("active_particles") != expected_particles:
                gaps.append("typed_lifecycle_active_particles_mismatch")
            if frame.get("missing_particles") != 0:
                gaps.append("typed_lifecycle_missing_particles_nonzero")
            counts = frame.get("type_counts")
            if not isinstance(counts, dict):
                gaps.append("typed_lifecycle_type_counts_missing")
            else:
                normalized = {str(k): v for k, v in counts.items()}
                if any(normalized.get(k) != v for k, v in expected_types.items()):
                    gaps.append("typed_lifecycle_type_counts_mismatch")
                if sum(v for v in normalized.values() if isinstance(v, int)) != expected_particles:
                    gaps.append("typed_lifecycle_type_ledger_does_not_close")
            t = frame.get("time")
            if not finite_number(t):
                gaps.append("typed_lifecycle_time_missing_or_nonfinite")
            else:
                typed_times.append(float(t))
        time_evidence = typed_obj.get("time_evidence")
        if not isinstance(time_evidence, dict) or time_evidence.get("strictly_increasing") is not True:
            gaps.append("typed_time_evidence_not_strictly_increasing")
        if isinstance(lifecycle, dict):
            if lifecycle.get("introduced_ids") != "rejected":
                gaps.append("typed_introduced_id_policy_not_rejected")
            if lifecycle.get("open_birth_adaptive_multi_piece") != "rejected":
                gaps.append("typed_open_birth_policy_not_rejected")
            exclusion = lifecycle.get("initial_exclusion_ledger")
            if isinstance(exclusion, dict) and (exclusion.get("count") != 0 or not is_hex64(exclusion.get("ids_sha256"))):
                gaps.append("typed_initial_exclusion_ledger_nonzero_or_invalid")
        identity = typed_obj.get("typed_identity")
        if not isinstance(identity, dict) or identity.get("key") != "(Zone,Idp)":
            gaps.append("typed_composite_uid_identity_missing")
        else:
            identity_exclusion = identity.get("initial_exclusion_ledger")
            if not isinstance(identity_exclusion, dict) or identity_exclusion.get("count") != 0 or not is_hex64(identity_exclusion.get("ids_sha256")):
                gaps.append("typed_identity_initial_exclusion_missing_or_nonzero")
        provenance = typed_obj.get("source_provenance")
        required_provenance = ("gencase_receipt", "generated_xml", "solver_receipt", "owner_metadata")
        if not isinstance(provenance, dict):
            gaps.append("typed_source_provenance_missing")
        else:
            for name in required_provenance:
                item = provenance.get(name)
                if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not is_hex64(item.get("sha256")):
                    gaps.append(f"typed_source_provenance_{name}_missing_or_invalid")

    if not isinstance(xmf_obj, dict):
        gaps.append("xmf_manifest_unreadable")
    else:
        if xmf_obj.get("frames") != expected_frames:
            gaps.append("xmf_manifest_frames_mismatch")
        if xmf_obj.get("particles") != expected_particles:
            gaps.append("xmf_manifest_particles_mismatch")
        for field_name in ("position", "velocity"):
            field = xmf_obj.get("fields", {}).get(field_name) if isinstance(xmf_obj.get("fields"), dict) else None
            shape = field.get("shape") if isinstance(field, dict) else None
            if shape != [expected_frames, expected_particles, 3]:
                gaps.append(f"xmf_field_{field_name}_n3_shape_mismatch")
        for field_name in ("mass", "density", "pressure", "type"):
            field = xmf_obj.get("fields", {}).get(field_name) if isinstance(xmf_obj.get("fields"), dict) else None
            shape = field.get("shape") if isinstance(field, dict) else None
            if shape != [expected_frames, expected_particles]:
                gaps.append(f"xmf_field_{field_name}_shape_mismatch")
        candidate = xmf_obj.get("actual_time_s") if isinstance(xmf_obj.get("actual_time_s"), list) else xmf_obj.get("time_values")
        if not isinstance(candidate, list) or len(candidate) != expected_frames or not all(finite_number(v) for v in candidate):
            gaps.append("xmf_manifest_time_sequence_missing_or_invalid")
        else:
            xmf_times = [float(v) for v in candidate]
            if any(r <= l for l, r in zip(xmf_times, xmf_times[1:])):
                gaps.append("xmf_manifest_time_not_strictly_increasing")
        for field in ("case_id", "physical_case_id", "family_id"):
            if field in xmf_obj and xmf_obj.get(field) != row.get(field):
                gaps.append(f"xmf_manifest_{field}_mismatch")
        if not is_hex64(xmf_obj.get("conversion_report_sha256")) and not is_hex64(xmf_obj.get("full_typed_conversion_report_sha256")):
            gaps.append("xmf_manifest_conversion_report_attestation_missing")

    if isinstance(render_obj, dict) and isinstance(render_obj.get("frame_diagnostics"), list):
        for frame in render_obj["frame_diagnostics"]:
            if isinstance(frame, dict) and finite_number(frame.get("actual_time_s")):
                render_times.append(float(frame["actual_time_s"]))
    if len(render_times) != expected_frames:
        gaps.append("render_actual_time_count_mismatch")

    if isinstance(xmf_xml_summary, dict):
        xml_times = xmf_xml_summary.get("time_values")
        if not isinstance(xml_times, list) or len(xml_times) != expected_frames or not all(finite_number(v) for v in xml_times):
            gaps.append("xmf_xml_time_count_or_finiteness_mismatch")
        else:
            xml_times = [float(v) for v in xml_times]
            if any(r <= l for l, r in zip(xml_times, xml_times[1:])):
                gaps.append("xmf_xml_time_not_strictly_increasing")
            series = {"typed_to_render": (typed_times, render_times), "xmf_manifest_to_render": (xmf_times, render_times), "xmf_xml_to_render": (xml_times, render_times)}
            for name, (left, right) in series.items():
                if len(left) != expected_frames or len(right) != expected_frames:
                    gaps.append(f"{name}_time_sequence_missing")
                else:
                    delta = max(abs(a - b) for a, b in zip(left, right))
                    if delta > 1e-6:
                        gaps.append(f"{name}_time_delta_over_1e-6:{delta}")
    else:
        gaps.append("xmf_xml_metadata_unreadable")
    return not gaps, list(dict.fromkeys(gaps)), {
        "expected_frames": expected_frames,
        "expected_particles": expected_particles,
        "typed_time_count": len(typed_times),
        "xmf_manifest_time_count": len(xmf_times),
        "render_time_count": len(render_times),
        "xmf_xml_time_count": len(xmf_xml_summary.get("time_values", [])) if isinstance(xmf_xml_summary, dict) else 0,
        "time_tolerance_s": 1e-6,
        "n3_shape_and_lifecycle_identity_checked": True,
        "typed_uid_composite_key_required": "(Zone,Idp)",
        "initial_exclusion_and_introduced_id_policy_required": True,
    }

def bed_fulltime_gate(
    bed_obj: dict[str, Any] | None,
    decision: dict[str, Any],
    row: dict[str, Any] | None = None,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Gate the actual 801-frame bed report as a diagnostic data product.

    The one-DP/two-DP bins are required as evidence, but are explicitly kept
    diagnostic; a zero bin never grants sub-DP containment or precision.
    """
    gaps: list[str] = []
    if not isinstance(bed_obj, dict):
        return False, ["bed_report_unreadable"], {}
    if not isinstance(bed_obj.get("schema"), str) or not bed_obj["schema"].startswith("ds02.f5."):
        gaps.append("bed_report_schema_missing_or_wrong")
    if bed_obj.get("diagnostic_only") is not True:
        gaps.append("bed_diagnostic_only_flag_missing_or_false")
    if bed_obj.get("source_arrays_modified") is not False or bed_obj.get("source_arrays_dropped_or_masked") is not False:
        gaps.append("bed_source_array_mutation_flag_not_false")
    if bed_obj.get("q_n_status") in {"granted", "approved"} or bed_obj.get("production_approval") not in ("none", None):
        gaps.append("bed_report_contains_unallowed_production_approval")
    bound = bed_obj.get("bound_actual_inputs")
    if not isinstance(bound, dict):
        gaps.append("bed_bound_actual_inputs_missing")
    elif row:
        for key in ("case_id", "physical_case_id"):
            if bound.get(key) != row.get(key):
                gaps.append(f"bed_bound_{key}_mismatch")
        native = bound.get("native_conversion")
        if not isinstance(native, dict) or native.get("frames") != EXPECTED_FRAMES or native.get("particles") != EXPECTED_PARTICLES or native.get("native_bed_marker_mk") != 50 or native.get("source_bed_marker_mkbound") != 40:
            gaps.append("bed_native_conversion_identity_missing_or_wrong")
    frames = bed_obj.get("frame_reports")
    if not isinstance(frames, list) or len(frames) != EXPECTED_FRAMES:
        gaps.append("bed_frame_report_count_not_801")
        frames = frames if isinstance(frames, list) else []
    times: list[float] = []
    frame_identity_failures = 0
    missing_or_nonfinite = 0
    footprint_failures = 0
    diagnostic_fields_missing = 0
    for i, frame in enumerate(frames):
        if not isinstance(frame, dict):
            frame_identity_failures += 1
            continue
        if frame.get("frame") != i or not finite_number(frame.get("time_s")):
            frame_identity_failures += 1
        else:
            times.append(float(frame["time_s"]))
        if frame.get("particle_axis_count") != EXPECTED_PARTICLES or frame.get("initial_fluid_uid_count") != 31658:
            frame_identity_failures += 1
        if frame.get("finite_position_current_fluid_count") != 31658 or frame.get("finite_mass_current_fluid_count") != 31658:
            missing_or_nonfinite += 1
        if frame.get("nonfinite_position_current_fluid_count") != 0 or frame.get("nonfinite_mass_current_fluid_count") != 0:
            missing_or_nonfinite += 1
        uid = frame.get("uid_tracking")
        if not isinstance(uid, dict):
            missing_or_nonfinite += 1
        else:
            mi = uid.get("missing_initial_uid", {})
            ui = uid.get("unexpected_current_uid", {})
            if not isinstance(mi, dict) or mi.get("count") != 0 or not isinstance(ui, dict) or ui.get("count") != 0 or uid.get("unexplained") is not False:
                missing_or_nonfinite += 1
        domain = frame.get("bed_domain")
        pen = frame.get("penetration")
        if not isinstance(domain, dict) or not isinstance(pen, dict):
            footprint_failures += 1
        else:
            if domain.get("finite_bed_footprint_evaluable_count") != 31658 or domain.get("x_in_exact_profile_domain_count") != 31658 or domain.get("y_in_actual_bed_footprint_count") != 31658:
                footprint_failures += 1
            for key in ("one_dp", "two_dp"):
                item = pen.get(key)
                if not isinstance(item, dict) or "count" not in item or "fraction_of_initial_fluid_uid_set" not in item or item.get("threshold_interpretation") != "diagnostic bin; not an acceptance threshold":
                    diagnostic_fields_missing += 1
    if len(times) == EXPECTED_FRAMES and any(r <= l for l, r in zip(times, times[1:])):
        gaps.append("bed_times_not_strictly_increasing")
    if frame_identity_failures:
        gaps.append(f"bed_frame_identity_or_time_failures:{frame_identity_failures}")
    if missing_or_nonfinite:
        gaps.append(f"bed_uid_or_finite_failures:{missing_or_nonfinite}")
    if footprint_failures:
        gaps.append(f"bed_footprint_failures:{footprint_failures}")
    if diagnostic_fields_missing:
        gaps.append(f"bed_diagnostic_one_two_dp_fields_missing:{diagnostic_fields_missing}")
    time_provenance = bed_obj.get("time_provenance")
    if not isinstance(time_provenance, dict) or time_provenance.get("frame_count") != EXPECTED_FRAMES or time_provenance.get("strictly_increasing") is not True or time_provenance.get("match") is not True or time_provenance.get("uniform_spacing_assumption") is not False:
        gaps.append("bed_time_provenance_missing_or_invalid")
    else:
        if not finite_number(time_provenance.get("first_s")) or not finite_number(time_provenance.get("last_s")):
            gaps.append("bed_time_provenance_nonfinite_bounds")
    contract = bed_obj.get("native_identity_contract")
    expected_contract = {"total_particles": 194427, "fixed_particles": 158559, "moving_particles": 4210, "fluid_particles": 31658, "native_bed_marker_mk": 50, "source_bed_marker_mkbound": 40}
    if not isinstance(contract, dict) or any(contract.get(k) != v for k, v in expected_contract.items()):
        gaps.append("bed_native_identity_contract_missing_or_wrong")
    if not is_hex64(bed_obj.get("physical_condition_sha256")):
        gaps.append("bed_physical_condition_attestation_missing")
    return not gaps, list(dict.fromkeys(gaps)), {
        "schema": bed_obj.get("schema"),
        "frame_count": len(frames),
        "time_count": len(times),
        "diagnostic_only": bed_obj.get("diagnostic_only"),
        "frames_with_missing_or_nonfinite": missing_or_nonfinite,
        "frames_with_footprint_failure": footprint_failures,
        "frames_missing_diagnostic_bins": diagnostic_fields_missing,
        "thresholds_are_diagnostic_only": True,
        "precision_granted": False,
        "sub_dp_containment_granted": False,
    }


def primary_visual_gate(
    contacts: list[dict[str, Any]],
    keys: list[dict[str, Any]],
    expected_frames: int = EXPECTED_FRAMES,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Require exactly the published navigation inventory; inspect PNGs only by stat."""
    gaps: list[str] = []
    if len(contacts) != EXPECTED_CONTACTS:
        gaps.append(f"primary_contact_sheet_count_not_{EXPECTED_CONTACTS}")
    if len(keys) != EXPECTED_KEYS:
        gaps.append(f"primary_keyframe_count_not_{EXPECTED_KEYS}")
    def check(items: list[dict[str, Any]], label: str) -> int:
        missing = 0
        for item in items:
            path = Path(item.get("path", ""))
            if path.suffix.lower() not in PNG_SUFFIXES or not path.is_file():
                missing += 1
            else:
                # stat is intentional; the source builder never reads/hashes PNG bytes.
                item["stat_bytes"] = path.stat().st_size
                item["stat_only"] = True
        if missing:
            gaps.append(f"{label}_missing_or_not_png:{missing}")
        return missing
    missing_contacts = check(contacts, "primary_contact_sheets")
    missing_keys = check(keys, "primary_keyframes")
    return not gaps, gaps, {
        "contacts": len(contacts),
        "keys": len(keys),
        "expected_contacts": EXPECTED_CONTACTS,
        "expected_keys": EXPECTED_KEYS,
        "missing_contact_files": missing_contacts,
        "missing_key_files": missing_keys,
        "png_content_read_or_hashed": False,
        "navigation_inventory_role": "actual published manifest/receipt/decision sidecar; no synthetic frame labels",
    }


def provenance_gate(
    decision: dict[str, Any],
    evidence: dict[str, Any],
    receipt_objects: dict[str, dict[str, Any] | None],
    typed_obj: dict[str, Any] | None,
    row: dict[str, Any],
) -> tuple[bool, list[str], dict[str, Any]]:
    """Require the actual GenCase→QA→native→typed→XMF→bed→render chain."""
    gaps: list[str] = []
    required = (
        "gencase_receipt", "initial_qa_receipt", "initial_qa_report", "generated_xml",
        "native_receipt", "typed_receipt", "typed_report", "xmf_receipt", "xmf_manifest", "xmf_xml",
        "bed_receipt", "bed_report", "render_receipt", "render_report", "render_publish_receipt",
    )
    for name in required:
        item = evidence.get(name)
        if not isinstance(item, dict) or not Path(item.get("path", "")).exists():
            gaps.append(f"provenance_missing:{name}")
    for name in ("gencase_receipt", "initial_qa_receipt", "native_receipt", "typed_receipt", "xmf_receipt", "bed_receipt", "render_receipt"):
        obj = receipt_objects.get(name)
        if not isinstance(obj, dict):
            gaps.append(f"provenance_receipt_unreadable:{name}")
        elif not isinstance(obj.get("schema"), str) or not obj.get("schema", "").startswith("ds02.execution-receipt."):
            gaps.append(f"provenance_receipt_schema_missing:{name}")
    publish = receipt_objects.get("render_publish_receipt")
    if not isinstance(publish, dict):
        gaps.append("provenance_publish_receipt_unreadable")
    else:
        if not isinstance(publish.get("schema"), str) or "render-publish-receipt" not in publish.get("schema", ""):
            gaps.append("provenance_publish_receipt_schema_missing")
        if publish.get("status") != "published_after_atomic_rename":
            gaps.append("provenance_publish_receipt_not_atomic_published")
        if not isinstance(publish.get("published_output_root"), str) or not isinstance(publish.get("published_bytes_total"), int):
            gaps.append("provenance_publish_receipt_output_missing")
        publish_case = publish.get("case_id")
        if isinstance(publish_case, str) and publish_case not in {row.get("case_id"), row.get("physical_case_id")} and row.get("physical_case_id") not in publish_case:
            gaps.append("provenance_publish_receipt_case_identity_mismatch")
    if not isinstance(typed_obj, dict):
        gaps.append("provenance_typed_source_provenance_unreadable")
    else:
        source = typed_obj.get("source_provenance")
        if not isinstance(source, dict):
            gaps.append("provenance_typed_source_provenance_missing")
        else:
            for name in ("gencase_receipt", "generated_xml", "solver_receipt", "owner_metadata"):
                item = source.get(name)
                if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not is_hex64(item.get("sha256")):
                    gaps.append(f"provenance_typed_source_provenance_missing:{name}")
    # An accepted decision must expose the main full-time QI/visual closure;
    # its absence is a readiness gap even if the stage receipts exist.
    for name in ("source_review_closure", "independent_full801_QI_previsual_proof"):
        item = decision.get(name)
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not is_hex64(item.get("sha256")):
            gaps.append(f"provenance_decision_{name}_missing_or_invalid")
    return not gaps, list(dict.fromkeys(gaps)), {
        "required_actual_roles": list(required),
        "receipt_schema_required": "ds02.execution-receipt.v1",
        "source_provenance_owner_refs_required": True,
        "decision_QI_and_closure_refs_required": True,
        "payload_hashes_recomputed_by_source": False,
    }

def membership(checkpoint: dict[str, Any], index: dict[str, Any], first: dict[str, Any], legacy: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    first8 = first.get("frozen_first8_physical_case_ids")
    first24 = first.get("actual_first24_physical_case_ids")
    final48 = first.get("registered_final48_physical_case_ids")
    require(all(isinstance(x, list) for x in (first8, first24, final48)), "Root1293 membership arrays missing")
    require(tuple(map(len, (first8, first24, final48))) == EXPECTED_COUNTS, "Root1293 membership counts are not 8/24/48")
    require(len(set(first8)) == 8 and len(set(first24)) == 24 and len(set(final48)) == 48, "Root1293 membership duplicate physical IDs")
    require(set(first8) <= set(first24) <= set(final48), "Root1293 frozen8/actual24/final48 subset relation failed")
    require(first.get("family_id") == EXPECTED_FAMILY, "Root1293 family is not F5")
    f5_rows = [r for r in index.get("cases", []) if isinstance(r, dict) and r.get("family_id") == EXPECTED_FAMILY]
    require({r.get("physical_case_id") for r in f5_rows} == set(final48), "current cp295 F5 set differs from Root1293 final48")
    require(first.get("first8_subset_actual24_subset_registered48") is True, "Root1293 explicit subset flag is not true")
    lm = legacy.get("membership") if isinstance(legacy.get("membership"), dict) else {}
    require(legacy.get("schema") == "ds02.main.F5.final48.current30accepted18pending.actual801.primary-bed-delivery.v1", "Root1344 legacy schema mismatch")
    require(legacy.get("current_accepted_count") == 30 and legacy.get("current_pending_count") == 18, "Root1344 legacy 30/18 role snapshot mismatch")
    require(lm.get("registered_final48_physical_case_ids") == final48, "Root1344 legacy membership differs from Root1293")
    return {
        "frozen_first8_physical_case_ids": first8,
        "actual_first24_physical_case_ids": first24,
        "registered_final48_physical_case_ids": final48,
        "first8_subset_actual24_subset_registered48": True,
        "membership_source": source_ref(paths["membership"], "Root1293 membership"),
        "legacy_catalog_membership_role": "historical Root1344 role snapshot; current acceptance comes only from cp295/index",
    }


def validate_source_audit(path: Path) -> dict[str, Any]:
    audit = read_json(path, "source180 audit")
    require(audit.get("schema") == "ds02.main.source180.F5.assembly-only-final-gate-defect-audit.v1", "source180 audit schema mismatch")
    require(audit.get("source_commit") == "1e82b35a62f60828a64e2030cae11923870ba1ca", "source180 immutable commit mismatch")
    require(audit.get("source180_approved_only_as_readiness_assembly") is True, "source180 readiness-only approval missing")
    require(audit.get("source180_not_approved_as_standalone_final48_builder") is True, "source180 standalone-final prohibition missing")
    require(audit.get("source180_completed_source_bytes_immutable") is True, "source180 immutable-byte declaration missing")
    require(audit.get("main_scientific_payload_IO") is False and audit.get("PNG_payload_IO") is False, "source180 audit payload IO flags are unsafe")
    require(audit.get("new_case_credit") == 0 and audit.get("Q_N") == 0 and audit.get("Q_E") == 0, "source180 audit grants credit")
    toys = audit.get("toy_only_false_positive_gate_evidence")
    require(isinstance(toys, dict), "source180 toy evidence missing")
    for key in ("non_execution_schema_with_lookalike_fields_status_gate_accepted", "missing_N3_shapes_and_nonfinite_time_sequence_accepted", "empty801_bed_frame_objects_and_empty_time_provenance_accepted"):
        require(toys.get(key) is True, f"source180 toy evidence missing: {key}")
    return audit


def validate_control_inputs(checkpoint_path: Path, index_path: Path, membership_path: Path, legacy_path: Path, source_audit_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Path]]:
    cp = read_json(checkpoint_path, "checkpoint")
    index = read_json(index_path, "current index")
    first = read_json(membership_path, "Root1293 membership")
    legacy = read_json(legacy_path, "Root1344 legacy catalog")
    audit = validate_source_audit(source_audit_path)
    require(cp.get("schema") == "ds02.root.live-resumption-checkpoint.v1", "checkpoint schema mismatch")
    require(isinstance(cp.get("checkpoint"), int) and cp.get("checkpoint") >= 0, "checkpoint number is not an integer")
    require(isinstance(cp.get("at_utc"), str) and cp.get("at_utc"), "checkpoint timestamp is missing")
    require(index.get("schema") == "ds02.stage1.full336.role-aware-progress-index.v6", "current index schema mismatch")
    require(index.get("at_utc") == cp.get("at_utc"), "current index/checkpoint at_utc mismatch")
    source_cp = index.get("source_authoritative_checkpoint")
    require(isinstance(source_cp, dict), "current index has no source_authoritative_checkpoint")
    require(Path(source_cp.get("path", "")).resolve() == checkpoint_path.resolve(), "current index points at a different checkpoint")
    actual_cp_sha = json_sha(checkpoint_path, "checkpoint")
    require(source_cp.get("sha256") == actual_cp_sha, "current index checkpoint SHA does not match checkpoint bytes")
    accepted_global = cp.get("stage1_visual_accepted_complete_independent_cases")
    require(isinstance(accepted_global, int), "checkpoint accepted count is missing")
    require(index.get("accepted_independent_physical_cases") == accepted_global, "current index/checkpoint accepted counts disagree")
    pending_global = index.get("registered_pending_independent_physical_cases")
    union_global = index.get("union_distinct_physical_case_ids")
    require(isinstance(pending_global, int) and isinstance(union_global, int), "current index pending/union counts are missing")
    require(accepted_global + pending_global == union_global, "current index accepted/pending/union counts do not close")
    f5_rows = [r for r in index.get("cases", []) if isinstance(r, dict) and r.get("family_id") == EXPECTED_FAMILY]
    require(len(f5_rows) == 48, "current index does not contain 48 F5 rows")
    accepted_paths = set(cp.get("accepted_decisions", []))
    accepted = 0
    for row in f5_rows:
        dref = row.get("accepted_decision")
        if isinstance(dref, dict) and isinstance(dref.get("path"), str):
            if dref["path"] in accepted_paths:
                accepted += 1
    require(accepted == cp.get("accepted_per_family", {}).get("F5"), "current F5 decision/checkpoint intersection disagrees with checkpoint")
    paths = {"checkpoint": checkpoint_path, "index": index_path, "membership": membership_path, "legacy": legacy_path, "source_audit": source_audit_path}
    mem = membership(cp, index, first, legacy, paths)
    return cp, index, first, legacy, audit, paths


def evidence_map(decision: dict[str, Any]) -> dict[str, dict[str, Any] | None]:
    ev = decision.get("actual_completed_metadata_evidence")
    if not isinstance(ev, dict):
        return {key: None for key in (
            "native_receipt", "typed_receipt", "typed_report", "xmf_receipt", "xmf_manifest", "xmf_xml",
            "render_receipt", "render_report", "render_publish_receipt", "bed_receipt", "bed_report",
            "gencase_receipt", "initial_qa_receipt", "initial_qa_report", "generated_xml")}
    out: dict[str, dict[str, Any] | None] = {}
    aliases = {
        "native_receipt": ("native_receipt", "full_native_receipt", "actual_native_receipt", "execution_receipt"),
        "typed_receipt": ("typed_receipt", "typed_conversion_receipt", "root753_receipt", "full_typed_receipt", "execution_receipt"),
        "typed_report": ("typed_report", "conversion_report", "typed_conversion_report", "report"),
        "xmf_receipt": ("xmf_receipt", "actual_xmf_receipt", "full_xmf_receipt", "execution_receipt"),
        "xmf_manifest": ("xmf_manifest", "actual_xmf_manifest", "manifest"),
        "xmf_xml": ("xmf_xml", "xmf", "actual_xmf_xml", "case_xmf", "normal_xdmf"),
        "render_receipt": ("render_receipt", "actual_render_receipt", "render_execution_receipt", "execution_receipt"),
        "render_report": ("render_report", "actual_render_report", "full_render_report", "animation_integrity_report", "report"),
        "render_publish_receipt": ("render_publish_receipt", "actual_render_publish_receipt", "publish_receipt"),
        "bed_receipt": ("bed_receipt", "actual_bed_receipt", "execution_receipt"),
        "bed_report": ("bed_report", "actual_bed_report", "bed_audit_report", "audit_report", "report"),
        "gencase_receipt": ("gencase_receipt", "execution_receipt"),
        "initial_qa_receipt": ("initial_qa_receipt", "initial_native_qa_receipt", "execution_receipt"),
        "initial_qa_report": ("initial_qa_report", "initial_native_qa_report", "report"),
        "generated_xml": ("generated_xml", "prepared_xml", "xml"),
    }
    role_names = {
        "native_receipt": ("native", "native_full", "full_native"),
        "typed_receipt": ("typed", "typed_conversion", "full_typed", "root753"),
        "typed_report": ("typed", "typed_conversion"),
        "xmf_receipt": ("xmf", "actual_xmf", "full_xmf"),
        "xmf_manifest": ("xmf", "actual_xmf"),
        "xmf_xml": ("xmf", "actual_xmf"),
        "render_receipt": ("render", "actual_render"),
        "render_report": ("render", "actual_render"),
        "render_publish_receipt": ("render", "actual_render"),
        "bed_receipt": ("bed", "actual_bed"),
        "bed_report": ("bed", "actual_bed", "bed_audit"),
        "gencase_receipt": ("gencase",),
        "initial_qa_receipt": ("initial_qa", "basic_initial_qa"),
        "initial_qa_report": ("initial_qa", "basic_initial_qa"),
        "generated_xml": ("gencase",),
    }
    for name, keys in aliases.items():
        out[name] = role_ref(ev, role_names[name], keys, name)
        if out[name] is None:
            # Current accepted decisions use direct evidence keys.  This
            # bounded fallback handles a role object with a different name,
            # while avoiding a recursive historical first-match.
            out[name] = direct_ref(ev, keys, name, "evidence")
    return out


def case_catalog(row: dict[str, Any], cp: dict[str, Any], legacy_row: dict[str, Any] | None = None) -> dict[str, Any]:
    physical = row.get("physical_case_id")
    dref = row.get("accepted_decision") if isinstance(row.get("accepted_decision"), dict) else None
    accepted_paths = set(cp.get("accepted_decisions", []))
    accepted = bool(dref and dref.get("path") in accepted_paths)
    base: dict[str, Any] = {
        "family_id": row.get("family_id"),
        "case_id": row.get("case_id"),
        "physical_case_id": physical,
        "index_status": row.get("status"),
        "accepted": accepted,
        "case_credit": 0,
        "decision": None,
        "actual_evidence": {},
        "fulltime_gate": {"pass": False, "reasons": []},
        "scope_roles": {},
        "primary_contacts": [],
        "primary_keyframes": [],
        "publication_receipt": None,
        "publication_receipt_absent": False,
    }
    if not accepted:
        base["fulltime_gate"]["reasons"] = ["accepted_decision_missing_or_not_in_checkpoint"]
        return base
    if dref is None or not Path(dref["path"]).is_file():
        base["fulltime_gate"]["reasons"] = ["accepted_decision_json_missing"]
        return base
    decision_path = Path(dref["path"])
    decision = read_json(decision_path, f"decision {physical}")
    decision_actual_sha = json_sha(decision_path, f"decision {physical}")
    reasons: list[str] = []
    if dref.get("sha256") != decision_actual_sha:
        reasons.append("accepted_decision_sha_mismatch")
    for key in ("family_id", "case_id", "physical_case_id"):
        if isinstance(decision, dict) and decision.get(key) is not None and decision.get(key) != row.get(key):
            reasons.append(f"decision_{key}_mismatch")
    if not isinstance(decision, dict) or decision.get("status") not in {"visual-approved-by-delegated-agent", "visual-approved-in-checkpoint", "accepted", "visual-approved"} and not str(decision.get("status", "")).startswith("visual-approved"):
        reasons.append("decision_status_not_accepted")
    base["decision"] = {"path": str(decision_path), "declared_sha256": dref.get("sha256"), "actual_sha256": decision_actual_sha, "status": decision.get("status") if isinstance(decision, dict) else None}
    base["decision_summary"] = {
        "precision_status": decision.get("precision_status") if isinstance(decision, dict) else None,
        "full_native_frames": decision.get("full_native_frames") if isinstance(decision, dict) else None,
        "particle_count": decision.get("particle_count") if isinstance(decision, dict) else None,
        "actual_type_counts": decision.get("actual_type_counts") if isinstance(decision, dict) else None,
        "actual_physical_window_s": decision.get("actual_physical_window_s") if isinstance(decision, dict) else None,
        "historical_negative_flags": decision.get("historical_negative_flags") if isinstance(decision, dict) else None,
    }
    emap = evidence_map(decision if isinstance(decision, dict) else {})
    # Root1344 is a historical actual-primary sidecar, not a replacement
    # checkpoint.  It is used only to recover a missing/missing-on-disk
    # primary reference (not to turn a planning request into a receipt).
    legacy_fallbacks: dict[str, str] = {
        "native_receipt": "actual_native_receipt",
        "typed_report": "primary_typed_report",
        "xmf_manifest": "primary_XMF_manifest",
        "xmf_xml": "primary_XMF_XML",
        "render_report": "primary_render_report",
        "render_receipt": "actual_render_execution_receipt",
        "render_publish_receipt": "actual_atomic_publish_receipt",
        "bed_receipt": "actual_full801_bed_receipt",
        "bed_report": "actual_full801_bed_report",
    }
    fallback_used: dict[str, dict[str, Any]] = {}
    if isinstance(legacy_row, dict):
        for name, legacy_key in legacy_fallbacks.items():
            current = emap.get(name)
            current_path = Path(current["path"]) if isinstance(current, dict) and isinstance(current.get("path"), str) else None
            candidate = ref(legacy_row.get(legacy_key), role=f"root1344_fallback_{name}", source_key=f"legacy.{legacy_key}")
            expected_suffixes = {
                "native_receipt": {".json"}, "typed_receipt": {".json"}, "typed_report": {".json"},
                "xmf_receipt": {".json"}, "xmf_manifest": {".json"}, "xmf_xml": {".xml", ".xmf", ".xdmf"},
                "render_receipt": {".json"}, "render_report": {".json"}, "render_publish_receipt": {".json"},
                "bed_receipt": {".json"}, "bed_report": {".json"},
            }.get(name, {".json"})
            wrong_class = current_path is not None and current_path.suffix.lower() not in expected_suffixes
            if current is None or current_path is None or not current_path.exists() or wrong_class:
                if candidate is not None:
                    emap[name] = candidate
                    fallback_used[name] = candidate
    evidence_out: dict[str, Any] = {}
    receipt_objects: dict[str, dict[str, Any] | None] = {}
    for name, r in emap.items():
        er = enrich_ref(r)
        evidence_out[name] = er
        if er and Path(er["path"]).suffix.lower() == ".json":
            obj, errors = read_ref_json(er, f"{physical}:{name}")
            receipt_objects[name] = obj
            if errors:
                reasons.extend(errors)
        else:
            receipt_objects[name] = None
    base["actual_evidence"] = evidence_out
    base["legacy_fallback_refs"] = {key: enrich_ref(value) for key, value in fallback_used.items()}
    base["legacy_fallback_role"] = "Root1344 actual-primary sidecar only; never a replacement for current cp/index acceptance" if fallback_used else None
    for required in ("gencase_receipt", "initial_qa_receipt", "initial_qa_report", "generated_xml", "native_receipt", "typed_receipt", "xmf_receipt", "render_receipt", "bed_receipt", "typed_report", "xmf_manifest", "xmf_xml", "render_report"):
        if emap.get(required) is None:
            reasons.append(f"missing_required_ref:{required}")
    for receipt_name in ("gencase_receipt", "initial_qa_receipt", "native_receipt", "typed_receipt", "xmf_receipt", "render_receipt", "bed_receipt"):
        if emap.get(receipt_name) is not None:
            ok, rerrors, summary = status_gate(receipt_objects.get(receipt_name), receipt_name, row)
            if not ok:
                reasons.extend(rerrors)
            evidence_out[receipt_name]["receipt_gate"] = summary
        else:
            evidence_out[receipt_name] = None
    pub = evidence_out.get("render_publish_receipt")
    if pub is None:
        base["publication_receipt_absent"] = True
        base["publication_receipt"] = None
    elif receipt_objects.get("render_publish_receipt") is not None:
        base["publication_receipt"] = {"ref": pub, "status": receipt_objects["render_publish_receipt"].get("status"), "returncode": receipt_objects["render_publish_receipt"].get("returncode")}
    render_obj = receipt_objects.get("render_report")
    full_ok, render_reasons, render_summary = render_fulltime(render_obj, decision if isinstance(decision, dict) else {}, row)
    if not full_ok:
        reasons.extend(render_reasons)
    base["render_fulltime_summary"] = render_summary
    report_path = evidence_out.get("render_report", {}).get("path") if isinstance(evidence_out.get("render_report"), dict) else None
    base["primary_contacts"] = png_refs(render_obj, report_path, "contact_png")
    base["primary_keyframes"] = png_refs(render_obj, report_path, "key_png")
    if not base["primary_contacts"] and isinstance(decision, dict):
        base["primary_contacts"] = decision_png_refs(decision, "contact_png")
    if not base["primary_keyframes"] and isinstance(decision, dict):
        base["primary_keyframes"] = decision_png_refs(decision, "key_png")
    if isinstance(legacy_row, dict):
        if not base["primary_contacts"]:
            base["primary_contacts"] = decision_png_refs({"actual_source_contacts": legacy_row.get("actual_source_contacts")}, "contact_png")
        if not base["primary_keyframes"]:
            base["primary_keyframes"] = decision_png_refs({"actual_source_keys": legacy_row.get("actual_source_keys"), "main_actual_published_navigation_keys": legacy_row.get("main_actual_published_navigation_keys")}, "key_png")
    if not base["primary_contacts"]:
        reasons.append("primary_contact_refs_missing_or_unenumerated")
    # Key-frame enumeration is historically incomplete for some accepted
    # decisions.  It is a visible readiness gap, never silently filled.
    if not base["primary_keyframes"]:
        reasons.append("primary_key_refs_missing_or_unenumerated")
    visual_ok, visual_reasons, visual_summary = primary_visual_gate(base["primary_contacts"], base["primary_keyframes"])
    if not visual_ok:
        reasons.extend(visual_reasons)
    base["primary_visual_gate"] = visual_summary
    native_obj = receipt_objects.get("native_receipt")
    xmf_obj = None
    xmf_manifest_ref = evidence_out.get("xmf_manifest")
    if isinstance(xmf_manifest_ref, dict):
        xmf_obj, xmf_errors = read_ref_json(xmf_manifest_ref, f"{physical}:xmf_manifest")
        if xmf_errors:
            reasons.extend(xmf_errors)
        receipt_objects["xmf_manifest"] = xmf_obj
    typed_obj = receipt_objects.get("typed_report")
    xmf_xml_summary = None
    xmf_xml_ref = evidence_out.get("xmf_xml")
    if isinstance(xmf_xml_ref, dict):
        expected_frames = decision.get("full_native_frames") or decision.get("expected_frames") or 801
        expected_particles = decision.get("particle_count")
        xmf_xml_summary, xml_errors = xml_metadata(Path(xmf_xml_ref["path"]), expected_frames, expected_particles)
        if isinstance(evidence_out.get("xmf_xml"), dict):
            evidence_out["xmf_xml"].setdefault("metadata_probe", {})["access"] = "xml_metadata_read_without_HDF_payload_access"
            evidence_out["xmf_xml"]["metadata_probe"]["content_read_or_hashed"] = False
            evidence_out["xmf_xml"]["metadata_probe"]["xml_structure_summary"] = xmf_xml_summary
        if xml_errors:
            reasons.extend(xml_errors)
    sequence_ok, sequence_reasons, sequence_summary = sequence_consistency(
        typed_obj, xmf_obj, render_obj, xmf_xml_summary, decision if isinstance(decision, dict) else {}, row
    )
    if not sequence_ok:
        reasons.extend(sequence_reasons)
    base["frame_time_shape_consistency"] = sequence_summary
    bed_obj = receipt_objects.get("bed_report")
    bed_ok, bed_reasons, bed_summary = bed_fulltime_gate(bed_obj, decision if isinstance(decision, dict) else {}, row)
    if not bed_ok:
        reasons.extend(bed_reasons)
    base["bed_fulltime_summary"] = bed_summary
    provenance_ok, provenance_reasons, provenance_summary = provenance_gate(
        decision if isinstance(decision, dict) else {}, evidence_out, receipt_objects, typed_obj, row
    )
    if not provenance_ok:
        reasons.extend(provenance_reasons)
    base["provenance_gate"] = provenance_summary
    raw_masks = raw_scope_snapshot(native_obj, xmf_obj)
    if not raw_masks.get("native"):
        reasons.append("raw_native_scope_fields_missing")
    if not raw_masks.get("xmf"):
        reasons.append("raw_xmf_scope_fields_missing")
    for xml_name in ("generated_xml", "xmf_xml"):
        xml_ref = evidence_out.get(xml_name)
        if isinstance(xml_ref, dict) and xml_ref.get("declared_sha256") and xml_ref.get("actual_sha256") != xml_ref.get("declared_sha256"):
            reasons.append(f"{xml_name}_declared_sha_mismatch")
    base["scope_roles"] = {
        "decision_top_condition_sha256": decision.get("physical_condition_sha256") if isinstance(decision, dict) else None,
        "decision_actual_converter_scope_sha256": decision.get("actual_converter_scope_sha256") if isinstance(decision, dict) else None,
        "decision_bed_SourceDef_scope_sha256": decision.get("bed_SourceDef_scope_sha256") if isinstance(decision, dict) else None,
        "native_vs_xmf_raw_field_presence": raw_masks,
        "source_plan_absence_is_preserved": True,
        "canonical_legacy_SourceDef_roles_are_distinct": decision.get("canonical_legacy_SourceDef_roles_are_distinct") if isinstance(decision, dict) else None,
        "bed_SourceDef_raw_role_mask_from_legacy_sidecar": legacy_row.get("actual_native_typed_XMF_bed_raw_role_masks") if isinstance(legacy_row, dict) else None,
        "legacy_role_masks_are_historical_sidecar_not_new_receipts": isinstance(legacy_row, dict),
    }
    base["fulltime_gate"] = {"pass": not reasons, "reasons": list(dict.fromkeys(reasons))}
    return base


def build_catalog(cp: dict[str, Any], index: dict[str, Any], first: dict[str, Any], legacy: dict[str, Any], audit: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    f5_rows = {row["physical_case_id"]: row for row in index["cases"] if row.get("family_id") == EXPECTED_FAMILY}
    membership_obj = membership(cp, index, first, legacy, paths)
    legacy_rows = {}
    for key in ("main_current_accepted30_actual_primary_rows", "main_current_pending18_readiness_rows"):
        for item in legacy.get(key, []) if isinstance(legacy.get(key), list) else []:
            if isinstance(item, dict) and isinstance(item.get("physical_case_id"), str):
                legacy_rows[item["physical_case_id"]] = item
    cases = [case_catalog(f5_rows[physical], cp, legacy_rows.get(physical)) for physical in membership_obj["registered_final48_physical_case_ids"]]
    accepted = sum(1 for c in cases if c["accepted"])
    pending = len(cases) - accepted
    all_pass = accepted == 48 and pending == 0 and all(c["fulltime_gate"]["pass"] for c in cases)
    return {
        "schema": SCHEMA,
        "status": "complete" if all_pass else "readiness",
        "complete": bool(all_pass),
        "package": PACKAGE,
        "generated_by": "build_fresh218.py",
        "source_checkpoint": source_ref(paths["checkpoint"], "checkpoint"),
        "source_current_index": source_ref(paths["index"], "current index"),
        "source_membership": source_ref(paths["membership"], "Root1293 membership"),
        "source_legacy_catalog": source_ref(paths["legacy"], "Root1344 legacy catalog"),
        "source180_gate_defect_audit": source_ref(paths["source_audit"], "Root1390 source180 audit"),
        "source180_audit_summary": {
            "source_commit": audit.get("source_commit"),
            "approved_as_readiness_only": audit.get("source180_approved_only_as_readiness_assembly"),
            "toy_false_positive_cases_preserved": audit.get("toy_only_false_positive_gate_evidence"),
            "repair_scope": audit.get("fresh182_repair_required_after_current_personal_visual181"),
        },
        "checkpoint": cp.get("checkpoint"),
        "at_utc": cp.get("at_utc"),
        "family_id": EXPECTED_FAMILY,
        "accepted_count": accepted,
        "pending_count": pending,
        "registered_count": len(cases),
        "membership": membership_obj,
        "cases": cases,
        "legacy_publication_absences": legacy.get("four_legacy_atomic_publish_receipt_absences", []),
        "new_case_credit": 0,
        "Q_N": 0,
        "Q_E": 0,
        "scientific_payload_IO": False,
        "readiness_gaps": sorted({reason for c in cases for reason in c["fulltime_gate"]["reasons"]}),
        "completion_gate": {
            "requires_all_48_current_cp295_accepted": True,
            "requires_genuine_completed0_receipts": ["native_receipt", "typed_receipt", "xmf_receipt", "render_receipt", "bed_receipt"],
            "requires_execution_receipt_schema": "ds02.execution-receipt.v1",
            "requires_exact_case_bound_request_identity": ["family_id", "case_id", "physical_case_id"],
            "requires_launch_after_input_hash_join": True,
            "requires_typed_composite_uid_initial_exclusion_introduced_rejection_type_ledger": True,
            "requires_exact_801_n3_shape_and_strict_time_join": True,
            "requires_bed_801_frame_reports_and_time_provenance": True,
            "requires_fulltime_render_report": True,
            "requires_bed_fulltime_report": True,
            "requires_case_bound_native_typed_xmf_render": True,
            "requires_primary_contact_and_key_refs": True,
            "missing_or_unknown_is_failure": True,
            "current_result": "readiness_only" if not all_pass else "final48_allowed",
        },
    }


def write_outputs(catalog: dict[str, Any], output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        fail(f"refuse overwrite existing output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    name = "final48.json" if catalog["complete"] else "readiness.json"
    (output_dir / name).write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = (
        "# Fresh218 completion-only F5 builder\n\n"
        f"Status: **{catalog['status']}**. Accepted {catalog['accepted_count']}/48; pending {catalog['pending_count']}.\n\n"
        "This output is metadata-only. It does not grant case credit, Q-N, Q-E, numerical precision, or production acceptance. "
        "A final48 is emitted only when every membership row has a case-bound completed/0 native, typed, XMF, render, and bed chain, full-time frame metadata, and primary visual references.\n"
    )
    (output_dir / "README.md").write_text(summary, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", required=True, type=Path)
    p.add_argument("--current-index", required=True, type=Path)
    p.add_argument("--membership", required=True, type=Path)
    p.add_argument("--legacy-catalog", required=True, type=Path)
    p.add_argument("--source-audit", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        cp, index, first, legacy, audit, paths = validate_control_inputs(args.checkpoint.resolve(), args.current_index.resolve(), args.membership.resolve(), args.legacy_catalog.resolve(), args.source_audit.resolve())
        catalog = build_catalog(cp, index, first, legacy, audit, paths)
        write_outputs(catalog, args.output_dir.resolve())
        print(json.dumps({"status": catalog["status"], "accepted_count": catalog["accepted_count"], "pending_count": catalog["pending_count"], "output_dir": str(args.output_dir.resolve())}, sort_keys=True))
        return 0
    except BuildError as exc:
        print(f"fresh218 build rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
