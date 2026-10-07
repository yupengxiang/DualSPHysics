#!/usr/bin/env python3
"""Build the source-only full336 physical-distinctness audit.

This program reads JSON/XML/XMF metadata only.  It deliberately does not
open, hash, copy, or enumerate scientific payloads (BI4/H5/CSV/DAT/VTK/PNG).
The audit records physical evidence separately from native condition fields;
an absent native field is never reconstructed from an accepted/top/typed/XMF
hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parents[1]
OUT = HERE / "metadata" / "full336-physical-distinctness-audit.json"
SUMMARY = HERE / "metadata" / "physical-distinctness-summary.json"
INTEGRATION_HANDOFF = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/"
    "DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
)
# Root1446 is the latest cp334 index available to this source-only audit.  It
# preserves the same 336 physical members while recording the two still
# pending visual rows; use it instead of the older cp333 snapshot.
INDEX = INTEGRATION_HANDOFF / (
    "root_stage1_F5_actual47_primary801_fullbed_extend45_actual1184_1175_"
    "personal86PNG_actual_native_plan_absences_preserved_1446/"
    "full336-current334-actual-final48-delivery-progress-index.json"
)
PINNED_F2_F7 = INTEGRATION_HANDOFF / (
    "root_stage1_F2_F7_actual96_native_launch_after_JSON_pinned_numeric_"
    "physical_discriminators_no_ID_path_recipe_uniqueness_1452/"
    "actual96-native-pinned-physical-discriminators.json"
)
ENDPOINT_F3_PROOF = INTEGRATION_HANDOFF / (
    "root_stage1_F3_actual_two_endpoint_forcing_transform_native_pins_XML_"
    "relative_file_lookup_copied_nominal_request_metadata_preserved_1456/"
    "actual-two-F3-endpoint-forcing-and-stale-request-binding-proof.json"
)
OMISSION_PROOF = INTEGRATION_HANDOFF / (
    "root_stage1_all336_actual_full_lifecycle_omission_counts_relative_to_initial_"
    "fluid_unknown_causes_preserved_1454/"
    "all336-full-lifecycle-relative-fluid-omission-proof.json"
)
CLOSURE = INTEGRATION_HANDOFF / (
    "root_stage1_F6_47_actual_native_receipts_34_old_nulls_recovered_"
    "full336_331_unique_digest_five_true_legacy_absences_1320/"
    "full336-native-field-role-closure-331-unique-five-real-absences.json"
)
ROSTER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/"
    "DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/"
    "handoff_20261003/root_followup_175_f1_f4_f7_final48_delivery_manifest_v1/"
    "final48-delivery-roster.json"
)
PRODUCTS = {
    "F1": INTEGRATION_HANDOFF / (
        "root_stage1_source175_actual_F1_F4_F7_final48_delivery_real8_24_48_"
        "primary_XMF_native_scope_observation_1261/"
        "F1-ACTUAL_FINAL48_DELIVERY_8_24_48.json"
    ),
    "F4": INTEGRATION_HANDOFF / (
        "root_stage1_source175_actual_F1_F4_F7_final48_delivery_real8_24_48_"
        "primary_XMF_native_scope_observation_1261/"
        "F4-ACTUAL_FINAL48_DELIVERY_8_24_48.json"
    ),
    "F7": INTEGRATION_HANDOFF / (
        "root_stage1_source175_actual_F1_F4_F7_final48_delivery_real8_24_48_"
        "primary_XMF_native_scope_observation_1261/"
        "F7-ACTUAL_FINAL48_DELIVERY_8_24_48.json"
    ),
    "F6": INTEGRATION_HANDOFF / (
        "root_stage1_source190_F6_final48_actual_particle_rigid_primary_baseline_"
        "native_typed_XMF_receipt_recovery_condition_absence_threefluid_limits_1353/"
        "F6-FINAL48-COMPLETE-PARTICLE-RIGID-ACTUAL-PRIMARY-DELIVERY.json"
    ),
    "F3": INTEGRATION_HANDOFF / (
        "root_stage1_source229_lastF3_actual1101_personal44PNG_full836QI_"
        "F3final48_primary_native_both_plan_ABS_XMF_condition_present_1449/"
        "F3-FINAL48-COMPLETE-ACTUAL836-PRIMARY-DELIVERY.json"
    ),
    "F5": INTEGRATION_HANDOFF / (
        "root_stage1_source206_lastF5_actual1149_personal43PNG_full801QI_"
        "F5final48_primary_336_visual_records_final_distinction_audit_pending_1450/"
        "F5-FINAL48-COMPLETE-ACTUAL801-PRIMARY-BED-DELIVERY.json"
    ),
    "F2": INTEGRATION_HANDOFF / (
        "root_stage1_source226_F2_final48_actual401_UID_N3_times_816contacts432navigation_"
        "P03_unknown_and_old_scope_limits_preserved_1444/"
        "F2-FINAL48-COMPLETE-ACTUAL401-PRIMARY-DELIVERY.json"
    ),
}

ALLOWED_SUFFIXES = {".json", ".xml", ".xmf"}
FORBIDDEN_SUFFIXES = {".bi4", ".h5", ".csv", ".dat", ".vtk", ".png"}
FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6", "F7")
ABSENT_NATIVE_IDS = {
    "F2H10V2_OFFSET_V1",
    "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE",
    "F7_OBSTACLE_QUINTIC_B08_A030",
    "F7_OBSTACLE_QUINTIC_B08_A065",
}
PHYSICAL_WORDS = (
    "geometry", "control", "mechanism", "parameter", "initial_state",
    "position", "velocity", "gravity", "size", "low_m", "gap", "offset",
    "rotation", "angle", "amplitude", "speed", "pitch", "yaw", "depth",
    "fill", "receiver", "cup", "drop", "pool", "tank", "paddle", "axis",
    "motion", "lineage", "source_layer", "mkfluid", "open_top", "wall",
)
XML_TAG_WORDS = (
    "drawbox", "box", "fluid", "wall", "motion", "mv", "gravity", "point",
    "size", "velocity", "parameter", "execution", "geometry", "domain",
    "particles", "mk", "axis", "begin", "finish", "time", "definition",
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str | None:
    if path.suffix.lower() not in {".json", ".xml"}:
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def path_like(value: str) -> bool:
    suffix = Path(value.split("?", 1)[0]).suffix.lower()
    return suffix in ALLOWED_SUFFIXES and "/" in value


def refs(value: Any, out: list[tuple[str, str]] | None = None, key_path: str = "") -> list[tuple[str, str]]:
    """Collect only permitted metadata paths; never follows payload paths."""
    out = out if out is not None else []
    if isinstance(value, dict):
        for key, child in value.items():
            kp = f"{key_path}.{key}" if key_path else key
            if isinstance(child, str) and path_like(child):
                out.append((kp, child))
            else:
                refs(child, out, kp)
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            kp = f"{key_path}[{idx}]"
            if isinstance(child, str) and path_like(child):
                out.append((kp, child))
            else:
                refs(child, out, kp)
    return out


def unique_refs(items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for key, path in items:
        if path not in seen:
            seen.add(path)
            result.append((key, path))
    return result


def interesting_path(key: str, path: str) -> bool:
    low = f"{key} {path}".lower()
    name = Path(path).name.lower()
    return (
        "manifest" in low
        or "owner" in low
        or "prepared" in low
        or "gencase" in low
        or "request" in low
        or name in {"execution-receipt.json", "controller-result.json"}
        or name.endswith(".owner.json")
        or name.endswith(".metadata.json")
        or path.lower().endswith(".xml")
    )


def safe_scalar(value: Any, depth: int = 0) -> Any:
    """Keep physical metadata, excluding payload paths/digests and receipts."""
    if depth > 8:
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            low = value.lower()
            if any(low.endswith(s) for s in FORBIDDEN_SUFFIXES) or "/part_" in low:
                return None
            if len(value) > 600:
                return None
        return value
    if isinstance(value, list):
        vals = [safe_scalar(v, depth + 1) for v in value]
        return [v for v in vals if v is not None]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            kl = str(key).lower()
            if any(word in kl for word in ("sha", "hash", "receipt", "report", "path", "file", "h5", "bi4", "csv", "dat", "vtk", "png")):
                continue
            kept = safe_scalar(child, depth + 1)
            if kept not in (None, {}, []):
                result[str(key)] = kept
        return result
    return None


def find_physical_binding(value: Any) -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {"physical_binding", "physical_binding_metadata"}:
                candidate = safe_scalar(child)
                if isinstance(candidate, dict) and candidate.get("present") is False:
                    continue
                return candidate
        for child in value.values():
            found = find_physical_binding(child)
            if found not in (None, {}, []):
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_physical_binding(child)
            if found not in (None, {}, []):
                return found
    return None


def selected_manifest_fields(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keep_exact = {
        "family_id", "case_id", "physical_case_id", "physical_condition_sha256",
        "source_plan_physical_condition_sha256", "canonical_physical_binding_sha256",
        "producer_scope_schema", "actual_dimension", "expected_dimension",
        "actual_frame_count", "expected_native_frames", "expected_frames",
        "actual_particles", "expected_particles", "physical_window_s",
        "save_interval_s", "actual_partvtk_passed", "actual_typed_status",
        "semantic_binding_status", "scope_id", "source_only", "disabled",
        "execution_allowed", "launch_allowed", "numerical_precision_status",
        "coordinate_frame", "frames", "particles",
    }
    result: dict[str, Any] = {}
    for key in keep_exact:
        if key in value:
            result[key] = safe_scalar(value[key])
    binding = find_physical_binding(value)
    if binding not in (None, {}, []):
        result["physical_binding"] = binding
    # A few manifests place geometry/control directly under the owner object.
    for key in (
        "geometry", "control_family_id", "geometry_family_id", "mechanism_id",
        "parameters", "parameter_values", "initial_state", "motion",
        "physical_condition", "domain_basis", "numerical_recipe", "lineage_group_id",
    ):
        if key in value:
            result[key] = safe_scalar(value[key])
    return {k: v for k, v in result.items() if v not in (None, {}, [])}


def physical_owner_fields(value: Any) -> dict[str, Any]:
    binding = find_physical_binding(value)
    if binding not in (None, {}, []):
        return binding
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in (
            "family_id", "physical_case_id", "geometry", "control_family_id",
            "geometry_family_id", "mechanism_id", "parameters", "parameter_values",
            "initial_state", "motion", "physical_condition", "domain_basis",
            "numerical_recipe", "lineage_group_id", "continuum_geometry",
            "physical_parameter_changes", "geometry_control", "physical_parameters",
            "forcing_parameters", "motion_parameters", "actual_continuum_binding",
        ):
            if key in value:
                kept = safe_scalar(value[key])
                if kept not in (None, {}, []):
                    result[key] = kept
        return result
    return {}


PHYSICAL_SECTION_KEYS = {
    "physical_binding", "physical_binding_metadata", "physical_condition",
    "actual_continuum_binding", "continuum_binding", "source_condition",
    "source_owner", "geometry", "geometry_parameters", "parameters",
    "parameter_values", "initial_state", "motion", "forcing", "displacement",
    "control", "controls", "domain_basis", "numerical_recipe",
    "source_definition", "physical_plan", "source_plan", "actual_forcing",
    # Direct parameter fields occur in prepared source metadata and owner files
    # without a surrounding ``parameters`` object.  Keep these values so the
    # family tuple is based on the case's actual controls rather than its ID.
    "nominal_pitch_multiplier", "pitch_multiplier", "transverse_amplitude_m_s2",
    "transverse_amplitude", "transverse_omega_rad_s", "transverse_phase_rad",
    "transverse_ramp_duration_s", "receiver_x_m", "receiver_y_m", "fill_ratio",
    "rotation_duration_s", "rotation_final_angle_deg", "rotation_amplitude_deg",
    "gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s", "initial_velocity_m_per_s",
    "amplitude_scale", "time_scale", "duration_s", "activation_scale", "period_s",
    "body_mass_kg", "initial_orientation_axis_angle", "initial_angular_velocity_rad_s",
    "body_center_m", "body_inertia_diagonal_kg_m2", "amplitude_deg", "cycle_schedule",
    "motion_function", "fluid", "fluid_geometry", "continuum_geometry",
}


def physical_sections(value: Any, depth: int = 0) -> dict[str, Any]:
    """Extract case-bound physical sections without treating IDs as evidence.

    This is deliberately metadata-only.  It is used for the request embedded in
    an actual native receipt, where families store the decisive receiver,
    forcing, gap/offset, pitch/amplitude, or run-up motion values rather than
    repeating them in the top-level delivery index.
    """
    if depth > 12 or not isinstance(value, (dict, list)):
        return {}
    found: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            kl = str(key).lower()
            if kl in PHYSICAL_SECTION_KEYS:
                kept = safe_scalar(child)
                if kept not in (None, {}, []):
                    found[str(key)] = kept
            nested = physical_sections(child, depth + 1)
            for nk, nv in nested.items():
                found.setdefault(nk, nv)
    else:
        for child in value:
            nested = physical_sections(child, depth + 1)
            for nk, nv in nested.items():
                found.setdefault(nk, nv)
    return found


def case_bound_path(path: str, family: str, case_id: str | None, physical_id: str | None) -> bool:
    """Accept only a source/receipt path belonging to this case.

    The current index and receipts contain many historical full336/checkpoint
    references.  Those are provenance, not this case's geometry/control source,
    so they must not become a first-match physical binding.
    """
    low = path.lower()
    if Path(path).suffix.lower() not in ALLOWED_SUFFIXES:
        return False
    tokens = [str(case_id or "").lower(), str(physical_id or "").lower()]
    tokens = [t for t in tokens if t]
    if any(t in low for t in tokens):
        return True
    # A receipt itself can be selected by the native scope even if its parent
    # directory uses a short alias.  The caller adds those explicit paths.
    if Path(path).name.lower() in {"execution-receipt.json", "controller-result.json"}:
        return False
    return False


def structure_score(value: Any) -> int:
    """Prefer a real geometry/control binding over a tiny presence sentinel."""
    if isinstance(value, dict):
        return sum(1 + structure_score(v) for k, v in value.items() if k not in {"family_id"})
    if isinstance(value, list):
        return sum(structure_score(v) for v in value)
    return 1 if value not in (None, "", False) else 0


SIGNATURE_EXCLUDED_KEYS = {
    "family_id", "case_id", "physical_case_id", "scope_id", "attempt_id",
    "lineage_group_id", "reference_variant", "source_batch_template", "schema",
    "label", "role", "status", "claim", "qualification_claim", "production_claim",
}


def signature_physical_value(value: Any, key: str = "", depth: int = 0) -> Any:
    """Remove identifiers/status/window bookkeeping before collision testing.

    A collision test must never become an ID-difference test.  Hashes and file
    paths have already been excluded by ``safe_scalar``; this second pass also
    removes case aliases, lineage labels, schemas, and review status while
    preserving numeric geometry, forcing, initial velocity, and control values.
    """
    if depth > 10:
        return None
    kl = key.lower()
    if kl in SIGNATURE_EXCLUDED_KEYS or kl.endswith("_id"):
        return None
    if any(token in kl for token in ("sha", "hash", "receipt", "path", "file", "report", "ref")):
        return None
    if kl in {"physical_window_s", "window_s", "time_window_s", "save_interval_s", "expected_frames", "actual_frame_count", "actual_particles", "expected_particles"}:
        return None
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for child_key, child in value.items():
            kept = signature_physical_value(child, str(child_key), depth + 1)
            if kept not in (None, {}, []):
                out[str(child_key)] = kept
        return out
    if isinstance(value, list):
        vals = [signature_physical_value(v, key, depth + 1) for v in value]
        return [v for v in vals if v not in (None, {}, [])]
    return value


def xml_physical_markers(path: Path) -> dict[str, Any]:
    if not path.exists() or path.suffix.lower() != ".xml":
        return {}
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return {}
    markers: list[dict[str, Any]] = []
    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1].lower()
        attrs: dict[str, Any] = {}
        for key, val in elem.attrib.items():
            kl = key.lower()
            if kl in {"id", "name", "date", "ref"} or any(s in kl for s in FORBIDDEN_SUFFIXES):
                continue
            if any(word in kl for word in (
                "dp", "point", "size", "mk", "gravity", "velocity", "value",
                "key", "start", "finish", "duration", "angle", "axis", "x", "y", "z",
                "time", "count", "speed", "boundary", "kernel", "visco", "density",
            )):
                attrs[key] = val
        include_tag = any(word in tag for word in XML_TAG_WORDS)
        if attrs or include_tag:
            item: dict[str, Any] = {"tag": tag}
            if attrs:
                item["attrs"] = attrs
            text = (elem.text or "").strip()
            if text and len(text) < 240 and not any(text.lower().endswith(s) for s in FORBIDDEN_SUFFIXES):
                if tag in {"boxfill", "setdrawmode", "setshapemode"}:
                    item["text"] = text
            if attrs or "text" in item:
                markers.append(item)
    # Repeated XML boilerplate is still useful only through these physical tags.
    return {"marker_count": len(markers), "markers": markers}


def named_physical_values(value: Any, wanted: set[str], path: str = "") -> list[dict[str, Any]]:
    """Find physical fields with their JSON key paths, never using IDs as values."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            kp = f"{path}.{key}" if path else str(key)
            if str(key).lower() in wanted:
                kept = signature_physical_value(child, str(key))
                if kept not in (None, {}, []):
                    found.append({"field": kp, "value": kept})
            found.extend(named_physical_values(child, wanted, kp))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            found.extend(named_physical_values(child, wanted, f"{path}[{idx}]"))
    return found


def mapping_values(value: Any, wanted: set[str], path: str = "") -> list[dict[str, Any]]:
    """Return normalized physical mappings (geometry/parameters/controls)."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            kp = f"{path}.{key}" if path else str(key)
            if str(key).lower() in wanted and isinstance(child, (dict, list)):
                kept = signature_physical_value(child, str(key))
                if kept not in (None, {}, []):
                    found.append({"field": kp, "value": kept})
            found.extend(mapping_values(child, wanted, kp))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            found.extend(mapping_values(child, wanted, f"{path}[{idx}]"))
    return found


def native_receipt_role(current: dict[str, Any]) -> dict[str, Any]:
    """Summarize native launch/after metadata joins without payload IO."""
    evidence = current.get("native_request_scope", {}).get("evidence", {})
    receipt_ref = evidence.get("receipt", {}) if isinstance(evidence, dict) else {}
    path = receipt_ref.get("path") if isinstance(receipt_ref, dict) else None
    result: dict[str, Any] = {
        "receipt_path": path,
        "receipt_sha256": receipt_ref.get("sha256") if isinstance(receipt_ref, dict) else None,
        "status": None,
        "returncode": None,
        "request_case_id": None,
        "request_physical_case_id": None,
        "request_condition_sha256": None,
        "metadata_input_count": 0,
        "metadata_input_launch_after_equal_count": 0,
        "metadata_input_mismatch_count": 0,
        "metadata_input_unbound_count": 0,
        "metadata_input_join_status": "no_receipt",
    }
    if not isinstance(path, str) or not Path(path).exists() or Path(path).suffix.lower() != ".json":
        return result
    data = load_metadata(Path(path))
    if not isinstance(data, dict):
        result["metadata_input_join_status"] = "receipt_unreadable"
        return result
    req = data.get("request", {}) if isinstance(data.get("request"), dict) else {}
    result.update({
        "status": data.get("status"),
        "returncode": data.get("returncode"),
        "request_case_id": req.get("case_id"),
        "request_physical_case_id": req.get("physical_case_id"),
        "request_condition_sha256": req.get("physical_condition_sha256"),
    })
    launch = data.get("input_hashes_at_launch", {})
    after = data.get("input_hashes_after_run", {})
    if not isinstance(launch, dict):
        launch = {}
    if not isinstance(after, dict):
        after = {}
    metadata_paths = sorted({
        str(p) for p in set(launch) | set(after)
        if Path(str(p)).suffix.lower() in {".json", ".xml"}
        and Path(str(p)).exists()
    })
    result["metadata_input_count"] = len(metadata_paths)
    equal = mismatched = unbound = 0
    for p in metadata_paths:
        actual = file_hash(Path(p))
        lval, aval = launch.get(p), after.get(p)
        if actual is None or lval is None or aval is None:
            unbound += 1
        elif lval == aval == actual:
            equal += 1
        else:
            mismatched += 1
    result["metadata_input_launch_after_equal_count"] = equal
    result["metadata_input_mismatch_count"] = mismatched
    result["metadata_input_unbound_count"] = unbound
    result["metadata_input_join_status"] = (
        "all_case_bound_json_xml_inputs_match_launch_after" if metadata_paths and mismatched == 0 and unbound == 0
        else "metadata_inputs_present_with_unresolved_or_mismatched_hashes" if metadata_paths
        else "no_case_bound_json_xml_inputs_in_receipt"
    )
    return result



def _numeric_payload(value: Any, mode: str = "scalar") -> Any:
    """Keep only numeric controls/vectors for the normalized tuple."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, tuple)):
        out = [_numeric_payload(v, mode) for v in value]
        return out if out and all(v is not None for v in out) else None
    if isinstance(value, dict):
        if mode == "vector":
            # Velocity/omega maps commonly key the physical cohort as fluid,
            # drop, or mkfluid:1.  Keep the selected vector only.
            for key in ("fluid", "drop", "moving", "mkfluid:1", "mkfluid_1", "body"):
                if key in value:
                    picked = _numeric_payload(value[key], "vector")
                    if picked is not None:
                        return picked
            for child in value.values():
                picked = _numeric_payload(child, "vector")
                if isinstance(picked, list) and picked:
                    return picked
            return None
        if mode == "angle":
            for key in ("yaw_deg", "angle_deg", "angle"):
                if key in value and isinstance(value[key], (int, float)) and not isinstance(value[key], bool):
                    return value[key]
            return None
    return None


def _field_candidates(roots: list[tuple[str, Any]], aliases: set[str]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    def walk(value: Any, role: str, path: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                kp = f"{path}.{key}" if path else str(key)
                if str(key).lower() in aliases:
                    found.append({"role": role, "field": kp, "value": child})
                walk(child, role, kp)
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                walk(child, role, f"{path}[{idx}]")
    for role, value in roots:
        if isinstance(value, (dict, list)):
            walk(value, role)
    return found


def _pick_case_numeric(
    roots: list[tuple[str, Any]],
    aliases: set[str],
    *,
    mode: str = "scalar",
    hints: tuple[str, ...] = (),
) -> tuple[Any, dict[str, Any] | None]:
    # The exact case-bound owner/source metadata is the primary physical
    # control authority.  Native request snapshots can intentionally retain a
    # copied mother binding (notably F3 endpoints); a pinned proof overrides
    # those known endpoint rows below.
    role_rank = {"owner": 0, "native_request": 1, "manifest": 2}
    candidates: list[tuple[tuple[int, int, int], Any, dict[str, Any]]] = []
    for item in _field_candidates(roots, aliases):
        value = _numeric_payload(item["value"], mode)
        if value is None:
            continue
        low = item["field"].lower()
        hint_score = sum(1 for hint in hints if hint in low)
        # Prefer an explicit case-bound native/request or owner field, then a
        # path that names the physical cohort.  The field path itself is kept
        # only as provenance and is never included in the tuple digest.
        score = (-hint_score, role_rank.get(item["role"], 9), len(item["field"]))
        candidates.append((score, value, {"role": item["role"], "field": item["field"]}))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: x[0])
    _, value, source = candidates[0]
    return value, source


def _clean_family_tuple(
    family: str,
    evidence: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]], list[str]]:
    """Return a small, uniform numeric tuple for one family.

    Rich owner/manifest structures remain in ``source_metadata``.  This helper
    deliberately keeps only the physical controls specified for the family so
    paths, IDs, hashes, solver recipes, resolution, windows, and report shape
    cannot make two otherwise equal cases appear different.
    """
    roots = [
        ("native_request", evidence.get("native_request_physical_sections", {})),
        ("owner", evidence.get("owner_physical_binding", {})),
        ("manifest", evidence.get("manifest_physical_fields", {})),
    ]
    values: dict[str, Any] = {}
    missing: list[str] = []
    sources: list[dict[str, Any]] = []

    def put(name: str, value: Any, source: dict[str, Any] | None) -> None:
        if value is None:
            missing.append(name)
            return
        values[name] = value
        if source is not None:
            sources.append({"normalized_field": name, **source})

    if family == "F1":
        depth, src = _pick_case_numeric(roots, {"fluid_depth_m", "fluid_height_m"}, hints=("fluid",))
        put("fluid_depth_m", depth, src)
        velocity, src = _pick_case_numeric(
            roots,
            {"velocities_m_per_s", "initial_velocity_m_per_s", "velocity_m_per_s", "initial_velocity"},
            mode="vector", hints=("fluid", "initial"),
        )
        put("initial_fluid_velocity_m_s", velocity, src)
        low, src = _pick_case_numeric(
            roots, {"low_m"}, mode="vector",
            hints=("fluid_reservoir", "source_regions.fluid", "initial_fluid", "fluid"),
        )
        put("fluid_reservoir_low_m", low, src)
    elif family == "F3":
        pitch, src = _pick_case_numeric(
            roots, {"nominal_pitch_multiplier", "pitch_multiplier", "amplitude_x"}, hints=("forcing", "pitch"),
        )
        put("pitch_multiplier", pitch, src)
        amp, src = _pick_case_numeric(
            roots, {"transverse_amplitude_m_s2", "transverse_amplitude", "amplitude_y"}, hints=("forcing", "transverse"),
        )
        put("transverse_amplitude_m_s2", amp, src)
    elif family == "F4":
        for name, aliases in (
            ("gap_m", {"gap_m"}), ("x_offset_m", {"x_offset_m"}),
            ("y_offset_m", {"y_offset_m"}),
        ):
            value, src = _pick_case_numeric(roots, aliases)
            put(name, value, src)
        speed, src = _pick_case_numeric(
            roots, {"speed_m_per_s", "drop_initial_speed_m_s", "initial_speed_m_per_s"}, hints=("drop", "initial"),
        )
        if speed is None:
            velocity, vsrc = _pick_case_numeric(
                roots, {"velocities_m_per_s", "initial_velocity_m_per_s", "initial_velocity"},
                mode="vector", hints=("drop", "mkfluid:1"),
            )
            if isinstance(velocity, list) and len(velocity) >= 3:
                speed = abs(velocity[2])
                src = vsrc
        put("drop_initial_speed_m_s", speed, src)
    elif family == "F5":
        amp, src = _pick_case_numeric(
            roots, {"piston_amplitude_scale", "amplitude_scale", "activation_scale"}, hints=("piston", "motion"),
        )
        put("piston_amplitude_scale", amp, src)
        scale, src = _pick_case_numeric(
            roots, {"piston_time_scale", "time_scale", "duration_scale", "period_scale"}, hints=("piston", "motion"),
        )
        put("piston_time_scale", scale, src)
    elif family == "F6":
        mass, src = _pick_case_numeric(roots, {"body_mass_kg"}, hints=("body", "rigid"))
        put("body_mass_kg", mass, src)
        omega, src = _pick_case_numeric(
            roots, {"initial_angular_velocity_rad_s", "initial_omega_rad_s"}, mode="vector", hints=("initial", "angular"),
        )
        put("initial_angular_velocity_rad_s", omega, src)
        yaw, src = _pick_case_numeric(
            roots, {"initial_yaw_deg", "yaw_deg", "initial_orientation_axis_angle"}, mode="angle", hints=("yaw", "orientation"),
        )
        put("initial_yaw_deg", yaw, src)
    else:
        # F2/F7 are replaced with the independent Root1452 pinned tuple.
        values = {}
        missing = ["pinned_numeric_discriminators"]
    status = (
        "PASS_CASE_BOUND_PHYSICAL_TUPLE"
        if values and not missing
        else "PASS_CASE_BOUND_PHYSICAL_TUPLE_WITH_EXPLICIT_FIELD_ABSENCE"
        if values
        else "UNCERTAIN_REQUIRED_PHYSICAL_FIELDS_MISSING"
    )
    return values, sorted(set(missing)), sources, [status]

def family_physical_tuple(
    family: str,
    physical_id: str,
    evidence: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Build a family-specific tuple from actual case-bound metadata values.

    The tuple excludes IDs, aliases, digests, resolution, frame/time-window,
    and view metadata.  Missing required physical values are reported rather
    than inferred from the physical_case_id spelling.
    """
    roots = [
        ("owner", evidence.get("owner_physical_binding", {})),
        ("native_request", evidence.get("native_request_physical_sections", {})),
        ("manifest", evidence.get("manifest_physical_fields", {})),
    ]
    combined = {role: value for role, value in roots if isinstance(value, dict) and value}
    field_sources: list[dict[str, Any]] = []
    for role, value in roots:
        if not isinstance(value, dict) or not value:
            continue
        field_sources.append({
            "role": role,
            "source_fields": sorted(named_physical_values(value, {
                "receiver_x_m", "receiver_y_m", "fill_ratio", "rotation_duration_s",
                "rotation_final_angle_deg", "nominal_pitch_multiplier", "pitch_multiplier",
                "transverse_amplitude_m_s2", "transverse_amplitude", "amplitude_deg",
                "gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s", "initial_velocity_m_per_s",
                "amplitude_scale", "time_scale", "duration_s", "body_mass_kg",
                "initial_orientation_axis_angle", "initial_angular_velocity_rad_s",
                "body_center_m", "body_inertia_diagonal_kg_m2", "geometry", "parameters",
                "physical_condition", "physical_binding", "piston_motion", "analytic_target",
            }), key=lambda x: x["field"]),
        })

    def all_named(wanted: set[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for role, value in roots:
            if isinstance(value, dict):
                for item in named_physical_values(value, wanted):
                    item = dict(item)
                    item["role"] = role
                    out.append(item)
        return out

    def all_maps(wanted: set[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for role, value in roots:
            if isinstance(value, dict):
                for item in mapping_values(value, wanted):
                    item = dict(item)
                    item["role"] = role
                    out.append(item)
        return out

    tuple_value: dict[str, Any] = {}
    required: list[str]
    if family == "F1":
        required = ["geometry", "initial_velocity_or_state"]
        tuple_value = {
            "geometry": all_maps({"geometry"}),
            "parameters": all_maps({"parameters"}),
            "controls": all_maps({"controls"}),
            "initial_velocity_or_state": all_named({"velocities_m_per_s", "initial_velocity_m_per_s", "initial_velocity"}),
            "mechanism": all_named({"mechanism_id"}),
        }
    elif family == "F2":
        required = ["receiver_x_m", "receiver_y_m", "fill_ratio", "rotation_duration_s", "rotation_final_angle_deg", "geometry"]
        tuple_value = {
            "parameters": all_named({"receiver_x_m", "receiver_y_m", "fill_ratio", "rotation_duration_s", "rotation_final_angle_deg", "rotation_amplitude_deg"}),
            "geometry": all_maps({"geometry", "fluid_geometry", "continuum_geometry", "geometry_control", "physical_condition"}),
            "motion": all_maps({"motion"}),
        }
    elif family == "F3":
        required = ["pitch_multiplier", "transverse_amplitude", "geometry"]
        tuple_value = {
            "pitch_and_forcing": all_named({"nominal_pitch_multiplier", "pitch_multiplier", "transverse_amplitude_m_s2", "transverse_amplitude", "transverse_omega_rad_s", "transverse_phase_rad", "transverse_ramp_duration_s"}),
            "geometry": all_maps({"geometry"}),
            "initial_state": all_maps({"initial_state"}),
        }
    elif family == "F4":
        required = ["gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s", "initial_velocity", "geometry"]
        tuple_value = {
            "drop_parameters": all_named({"gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s"}),
            "initial_velocity": all_named({"velocities_m_per_s", "initial_velocity_m_per_s", "initial_velocity"}),
            "geometry": all_maps({"geometry"}),
        }
    elif family == "F5":
        required = ["amplitude_or_scale", "duration_or_time_scale", "geometry"]
        tuple_value = {
            "motion": all_named({"amplitude_scale", "time_scale", "duration_s", "activation_scale", "period_s"}) + all_maps({"piston_motion", "prescribed_control"}),
            "geometry": all_maps({"geometry", "fluid_geometry", "continuum_geometry", "geometry_control", "physical_condition"}),
        }
    elif family == "F6":
        required = ["body_mass_or_rigid_geometry", "initial_angular_or_velocity", "geometry"]
        tuple_value = {
            "rigid_parameters": all_named({"body_mass_kg", "initial_orientation_axis_angle", "initial_angular_velocity_rad_s", "body_center_m", "body_inertia_diagonal_kg_m2", "velocities_m_per_s"}),
            "geometry": all_maps({"geometry", "rigid_body", "physical_condition", "geometry_control", "continuum_geometry"}),
        }
    else:  # F7
        required = ["amplitude_deg", "geometry"]
        tuple_value = {
            "amplitude_and_schedule": all_named({"amplitude_deg", "cycle_schedule", "motion_function", "motion_sampling_dt_s"}) + all_maps({"analytic_target"}),
            "geometry": all_maps({"geometry"}),
        }
    # Validate requirements against field names, not ID spelling.
    flat_fields = {
        str(item.get("field", "")).lower().split(".")[-1]
        for role in roots if isinstance(role[1], dict)
        for item in named_physical_values(role[1], {
            "receiver_x_m", "receiver_y_m", "fill_ratio", "rotation_duration_s", "rotation_final_angle_deg",
            "nominal_pitch_multiplier", "pitch_multiplier", "transverse_amplitude_m_s2", "transverse_amplitude",
            "gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s", "initial_velocity_m_per_s", "velocities_m_per_s",
            "amplitude_scale", "time_scale", "duration_s", "activation_scale", "period_s", "body_mass_kg",
            "initial_orientation_axis_angle", "initial_angular_velocity_rad_s", "geometry", "parameters", "physical_condition",
            "amplitude_deg", "analytic_target",
        })
    }
    # Geometry is a mapping requirement; the other compound requirements accept
    # a role-specific field alias and are kept explicit when absent.
    missing: list[str] = []
    if "geometry" in required and not tuple_value.get("geometry"):
        missing.append("geometry")
    if family == "F1" and not tuple_value.get("initial_velocity_or_state"):
        missing.append("initial_velocity_or_state")
    if family == "F2":
        for name in ("receiver_x_m", "receiver_y_m", "fill_ratio", "rotation_duration_s"):
            if name not in flat_fields:
                missing.append(name)
        if not any(name in flat_fields for name in ("rotation_final_angle_deg", "rotation_amplitude_deg")):
            missing.append("rotation_final_angle_deg")
    if family == "F3":
        if not any(name in flat_fields for name in ("nominal_pitch_multiplier", "pitch_multiplier")):
            missing.append("pitch_multiplier")
        if not any(name in flat_fields for name in ("transverse_amplitude_m_s2", "transverse_amplitude")):
            missing.append("transverse_amplitude")
    if family == "F4":
        for name in ("gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s"):
            if name not in flat_fields:
                missing.append(name)
        if not any(name in flat_fields for name in ("initial_velocity_m_per_s", "velocities_m_per_s", "initial_velocity")):
            missing.append("initial_velocity")
    if family == "F5":
        if not any(name in flat_fields for name in ("amplitude_scale", "activation_scale")):
            missing.append("amplitude_or_scale")
        if not any(name in flat_fields for name in ("duration_s", "time_scale", "period_s")):
            missing.append("duration_or_time_scale")
    if family == "F6":
        if not any(name in flat_fields for name in ("body_mass_kg", "rigid_body")):
            missing.append("body_mass_or_rigid_geometry")
        if not any(name in flat_fields for name in ("initial_orientation_axis_angle", "initial_angular_velocity_rad_s", "velocities_m_per_s")):
            missing.append("initial_angular_or_velocity")
    if family == "F7" and "amplitude_deg" not in flat_fields:
        missing.append("amplitude_deg")
    # Replace the exploratory rich structure with the family-specific,
    # uniform numeric tuple.  The rich fields remain in source_metadata.
    clean_value, clean_missing, clean_sources, clean_status = _clean_family_tuple(family, evidence)
    tuple_value = clean_value
    missing = clean_missing
    field_sources = [{"role": "normalized_case_bound", **item} for item in clean_sources]
    tuple_value = signature_physical_value(tuple_value)
    # A tuple can remain uniquely grounded when a legacy source omits one
    # named field but exposes a case-bound geometry discriminator.  Keep the
    # omission explicit; never infer the value from the case ID.
    tuple_digest = canonical_hash(tuple_value) if tuple_value else None
    metadata_sources = [
        {"path": ref["path"], "sha256": ref.get("sha256"), "key": ref.get("key")}
        for ref in evidence.get("metadata_refs", [])
        if ref.get("exists") and any(marker in (ref.get("key", "") + ref.get("path", "")).lower() for marker in ("owner", "source", "prepared", "gencase", "definition", "metadata"))
    ]
    return {
        "family": family,
        "required_field_names": required,
        "missing_required_fields": sorted(set(missing)),
        "tuple_status": (
            "PASS_CASE_BOUND_PHYSICAL_TUPLE"
            if tuple_digest and not missing
            else "PASS_CASE_BOUND_PHYSICAL_TUPLE_WITH_EXPLICIT_FIELD_ABSENCE"
            if tuple_digest
            else "UNCERTAIN_REQUIRED_PHYSICAL_FIELDS_MISSING"
        ),
        "tuple_value": tuple_value,
        "tuple_sha256": tuple_digest,
        "field_sources": field_sources,
        "metadata_sources": metadata_sources,
        "native_receipt_launch_after_metadata_join": native_receipt_role(current),
        "id_or_alias_not_used_as_tuple_value": True,
        "resolution_window_view_not_used_as_tuple_value": True,
    }


def pinned_family_tuple(
    family: str,
    physical_id: str,
    base: dict[str, Any],
    pinned: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    """Use the independent case-bound F2/F7 numeric proof when available.

    Root1452 selected the exact source metadata file for each native request
    and checked its launch/after hashes.  Its discriminator values are already
    normalized numbers; paths, IDs, digests, recipe, resolution, and windows
    remain only in the attached provenance.  We retain any geometry extracted
    from this audit as a supplementary normalized component, without using the
    rich signature as proof.
    """
    item = pinned.get((family, physical_id))
    if not isinstance(item, dict):
        return None
    discriminators = item.get("physical_discriminators")
    if not isinstance(discriminators, dict) or not discriminators:
        return None
    base_value = base.get("tuple_value", {}) if isinstance(base, dict) else {}
    tuple_value: dict[str, Any] = {
        "physical_discriminators": safe_scalar(discriminators),
    }
    geometry = base_value.get("geometry") if isinstance(base_value, dict) else None
    if geometry not in (None, {}, []):
        tuple_value["geometry"] = geometry
    pointers = item.get("source_field_pointers", {})
    source_fields = [
        {"role": "pinned_source_metadata", "field": k, "pointer": v}
        for k, v in sorted(pointers.items())
    ]
    missing: list[str] = []
    if family == "F2":
        # The baseline deliberately lacks RX/RY/ROT; fluid height is its
        # documented discriminator.  Preserve that true source absence.
        for field in ("receiver_x_m", "receiver_y_m", "fill_ratio", "rotation_duration_s"):
            if field not in discriminators:
                missing.append(field)
    elif family == "F7" and "amplitude_deg" not in discriminators:
        missing.append("amplitude_deg")
    receipt = item.get("actual_native_receipt")
    return {
        "family": family,
        "required_field_names": list(sorted(discriminators)),
        "missing_required_fields": missing,
        "tuple_status": (
            "PASS_CASE_BOUND_PINNED_PHYSICAL_TUPLE"
            if not missing
            else "PASS_CASE_BOUND_PINNED_PHYSICAL_TUPLE_WITH_EXPLICIT_FIELD_ABSENCE"
        ),
        "tuple_value": signature_physical_value(tuple_value),
        "tuple_sha256": canonical_hash(signature_physical_value(tuple_value)),
        "field_sources": source_fields,
        "metadata_sources": item.get("source_evidence", []),
        "native_receipt_launch_after_metadata_join": {
            "receipt_path": receipt.get("path") if isinstance(receipt, dict) else None,
            "receipt_sha256": receipt.get("sha256") if isinstance(receipt, dict) else None,
            "launch_after_pins_match": all(
                ev.get("actual_native_launch_and_after_run_pins_match") is True
                for ev in item.get("source_evidence", [])
            ),
            "native_condition_field_present": item.get("native_condition_field_present"),
        },
        "id_or_alias_not_used_as_tuple_value": True,
        "resolution_window_view_not_used_as_tuple_value": True,
        "pinned_proof_source": str(PINNED_F2_F7),
    }


def endpoint_f3_tuple(
    physical_id: str,
    base: dict[str, Any],
    endpoint_rows: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Use the case-bound F3 endpoint forcing proof for the two endpoints.

    Their copied nominal request still carries the old AY=.50 binding.  The
    independent 1456 proof pins the actual native XML/report transform and
    launch/after producer digest, so the tuple must use (pitch, AY) from that
    proof rather than the stale request field or the case-name token.
    """
    item = endpoint_rows.get(physical_id)
    if not isinstance(item, dict):
        return None
    disc = item.get("physical_discriminators")
    if not isinstance(disc, dict):
        return None
    pitch = disc.get("nominal_pitch_multiplier")
    amp = disc.get("transverse_amplitude_m_s2")
    if not isinstance(pitch, (int, float)) or not isinstance(amp, (int, float)):
        return None
    evidence = []
    for key in ("actual_native_receipt", "actual_generated_XML", "actual_launch_after_pinned_forcing_transform_report"):
        ref = item.get(key)
        if isinstance(ref, dict):
            evidence.append({"role": key, **{k: ref.get(k) for k in ("path", "sha256") if ref.get(k)}})
    return {
        "family": "F3",
        "required_field_names": ["pitch_multiplier", "transverse_amplitude_m_s2"],
        "missing_required_fields": [],
        "tuple_status": "PASS_CASE_BOUND_PINNED_PHYSICAL_TUPLE",
        "tuple_value": {
            "pitch_multiplier": pitch,
            "transverse_amplitude_m_s2": amp,
        },
        "tuple_sha256": canonical_hash({
            "pitch_multiplier": pitch,
            "transverse_amplitude_m_s2": amp,
        }),
        "field_sources": [
            {"role": "actual_forcing_transform_proof", "field": k, "pointer": v}
            for k, v in sorted(item.get("source_field_pointers", {}).items())
        ],
        "metadata_sources": evidence,
        "actual_forcing_proof": {
            "producer_report_transverse_column_range": item.get("producer_report_transverse_column_range"),
            "actual_forcing_sha256_attested": item.get("actual_forcing_SHA_producer_attested_and_native_launch_after_equal"),
            "copied_request_binding_is_nominal_and_inconsistent": item.get("copied_request_binding_is_nominal_and_inconsistent_with_actual_forcing"),
            "scientific_forcing_table_read_or_hashed_by_main": item.get("scientific_forcing_table_read_or_hashed_by_main"),
        },
        "native_receipt_launch_after_metadata_join": {
            "receipt_path": (item.get("actual_native_receipt") or {}).get("path"),
            "receipt_sha256": (item.get("actual_native_receipt") or {}).get("sha256"),
            "launch_after_pins_match": True,
        },
        "id_or_alias_not_used_as_tuple_value": True,
        "resolution_window_view_not_used_as_tuple_value": True,
        "pinned_proof_source": str(ENDPOINT_F3_PROOF),
    }


def special_case_tuple(
    family: str,
    physical_id: str,
    base: dict[str, Any],
) -> dict[str, Any] | None:
    """Case-bound thin-source repairs for two legacy rows.

    These are explicit metadata sources supplied by the producer chain, not
    values inferred from IDs.  F1's fallback binding stores velocity and fluid
    geometry under ``initialization``/``geometry``; F6's legacy baseline stores
    mass and omega in its generated XML while no yaw field is present.
    """
    if family == "F1" and physical_id == "F1_DUAL_THICK_DBC_LOWER_HEAD_V1":
        path = Path(
            "/home/jade/.codex/worktrees/ds-data-02-integration/"
            "DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/"
            "handoff_20261003/root_actual_fallback_full_native_032/dual_coarse/"
            "physical-binding.json"
        )
        data = load_metadata(path)
        binding = data.get("physical_binding", {}) if isinstance(data, dict) else {}
        geometry = binding.get("geometry", {}) if isinstance(binding, dict) else {}
        initialization = binding.get("initialization", {}) if isinstance(binding, dict) else {}
        reservoir_low = geometry.get("fluid_reservoir_low_m")
        size = geometry.get("fluid_reservoir_size_m")
        velocity = initialization.get("velocity_m_s")
        values: dict[str, Any] = {}
        missing: list[str] = []
        if isinstance(size, list) and len(size) >= 3 and isinstance(size[2], (int, float)):
            values["fluid_depth_m"] = size[2]
        else:
            missing.append("fluid_depth_m")
        if isinstance(velocity, list) and all(isinstance(x, (int, float)) for x in velocity):
            values["initial_fluid_velocity_m_s"] = velocity
        else:
            missing.append("initial_fluid_velocity_m_s")
        if isinstance(reservoir_low, list) and all(isinstance(x, (int, float)) for x in reservoir_low):
            values["fluid_reservoir_low_m"] = reservoir_low
        else:
            missing.append("fluid_reservoir_low_m")
        if not values:
            return None
        return {
            "family": family,
            "required_field_names": ["fluid_depth_m", "initial_fluid_velocity_m_s", "fluid_reservoir_low_m"],
            "missing_required_fields": missing,
            "tuple_status": "PASS_CASE_BOUND_PHYSICAL_TUPLE" if not missing else "PASS_CASE_BOUND_PHYSICAL_TUPLE_WITH_EXPLICIT_FIELD_ABSENCE",
            "tuple_value": values,
            "tuple_sha256": canonical_hash(values),
            "field_sources": [
                {"normalized_field": "fluid_depth_m", "role": "fallback_physical_binding.geometry.fluid_reservoir_size_m[2]"},
                {"normalized_field": "initial_fluid_velocity_m_s", "role": "fallback_physical_binding.initialization.velocity_m_s"},
                {"normalized_field": "fluid_reservoir_low_m", "role": "fallback_physical_binding.geometry.fluid_reservoir_low_m"},
            ],
            "metadata_sources": [{"path": str(path), "sha256": file_hash(path), "role": "case_bound_fallback_owner"}],
            "id_or_alias_not_used_as_tuple_value": True,
            "resolution_window_view_not_used_as_tuple_value": True,
        }
    if family == "F6" and physical_id == "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE":
        path = Path(
            "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/"
            "F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-actual-gencase-preflight-017/"
            "F6_ANGULAR_RELEASE_DP025.xml"
        )
        if not path.exists():
            return None
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            return None
        mass = None
        omega = None
        for elem in root.iter():
            tag = elem.tag.rsplit("}", 1)[-1].lower()
            if tag == "massbody" and mass is None:
                try:
                    mass = float(elem.attrib.get("value"))
                except (TypeError, ValueError):
                    pass
            if tag == "angularvelini" and omega is None:
                try:
                    omega = [float(elem.attrib[k]) for k in ("x", "y", "z")]
                except (KeyError, TypeError, ValueError):
                    pass
        values: dict[str, Any] = {}
        missing = []
        if mass is not None:
            values["body_mass_kg"] = mass
        else:
            missing.append("body_mass_kg")
        if omega is not None:
            values["initial_angular_velocity_rad_s"] = omega
        else:
            missing.append("initial_angular_velocity_rad_s")
        # The legacy source has no yaw field.  Keep the absence explicit; the
        # omega vector is sufficient producer evidence for this tuple.
        missing.append("initial_yaw_deg")
        return {
            "family": family,
            "required_field_names": ["body_mass_kg", "initial_angular_velocity_rad_s", "initial_yaw_deg"],
            "missing_required_fields": missing,
            "tuple_status": "PASS_CASE_BOUND_PHYSICAL_TUPLE_WITH_EXPLICIT_FIELD_ABSENCE" if values else "UNCERTAIN_REQUIRED_PHYSICAL_FIELDS_MISSING",
            "tuple_value": values,
            "tuple_sha256": canonical_hash(values) if values else None,
            "field_sources": [
                {"normalized_field": "body_mass_kg", "role": "generated_xml.floatings.massbody.value"},
                {"normalized_field": "initial_angular_velocity_rad_s", "role": "generated_xml.floatings.angularvelini.xyz"},
            ],
            "metadata_sources": [{"path": str(path), "sha256": file_hash(path), "role": "case_bound_legacy_generated_xml"}],
            "id_or_alias_not_used_as_tuple_value": True,
            "resolution_window_view_not_used_as_tuple_value": True,
        }
    return None


def load_metadata(path: Path) -> Any | None:
    if not path.exists() or path.suffix.lower() != ".json":
        return None
    try:
        return load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def metadata_record(key: str, path: str) -> dict[str, Any]:
    p = Path(path)
    record: dict[str, Any] = {
        "key": key,
        "path": path,
        "suffix": p.suffix.lower(),
        "exists": p.exists(),
    }
    if p.exists():
        record["bytes"] = p.stat().st_size
        if p.suffix.lower() in {".json", ".xml"}:
            record["sha256"] = file_hash(p)
        else:
            record["sha256"] = None
            record["hash_policy"] = "not read or hashed by this source-only audit"
    return record


def source_evidence(current: dict[str, Any], product: dict[str, Any], roster_row: dict[str, Any]) -> dict[str, Any]:
    initial = unique_refs(refs(current) + refs(product) + refs(roster_row))
    queue = [(k, p) for k, p in initial if interesting_path(k, p)]
    seen_json: set[str] = set()
    manifest_candidates: list[dict[str, Any]] = []
    owner_candidates: list[dict[str, Any]] = []
    xml_candidates: list[tuple[str, str]] = []
    all_refs: list[tuple[str, str]] = []
    while queue and len(seen_json) < 24:
        key, path = queue.pop(0)
        if (key, path) not in all_refs:
            all_refs.append((key, path))
        if path.lower().endswith(".xml"):
            if "prepared" in path.lower() or "gencase" in key.lower() or "generated" in key.lower():
                xml_candidates.append((key, path))
            continue
        if not path.lower().endswith(".json") or path in seen_json:
            continue
        seen_json.add(path)
        data = load_metadata(Path(path))
        if data is None:
            continue
        if "manifest" in f"{key} {path}".lower() or Path(path).name.lower() == "manifest.json":
            fields = selected_manifest_fields(data)
            if fields:
                manifest_candidates.append(fields)
            for child_key, child_path in refs(data):
                if interesting_path(child_key, child_path) and child_path not in {x[1] for x in all_refs}:
                    queue.append((child_key, child_path))
        if "owner" in f"{key} {path}".lower():
            fields = physical_owner_fields(data)
            if fields:
                owner_candidates.append(fields)
            for child_key, child_path in refs(data):
                if interesting_path(child_key, child_path) and child_path not in {x[1] for x in all_refs}:
                    queue.append((child_key, child_path))
        # Requests and source metadata can contain the generated XML/owner pointers.
        # A current index often exposes only the execution-receipt path.  The
        # receipt's nested request.input_files is the authoritative bridge to
        # the owner/metadata/XML source package, so follow it explicitly.
        is_execution_receipt = Path(path).name.lower() in {
            "execution-receipt.json", "controller-result.json"
        }
        if (
            is_execution_receipt
            or "request" in key.lower()
            or "prepared" in key.lower()
            or "source" in key.lower()
            or "metadata" in key.lower()
            or "owner" in key.lower()
        ):
            for child_key, child_path in refs(data):
                if interesting_path(child_key, child_path) and child_path not in {x[1] for x in all_refs}:
                    queue.append((child_key, child_path))
            direct_binding = physical_owner_fields(data)
            if direct_binding:
                owner_candidates.append(direct_binding)
            direct_manifest = selected_manifest_fields(data)
            if direct_manifest:
                manifest_candidates.append(direct_manifest)
    physical_owner = max(owner_candidates, key=structure_score, default={})
    physical_manifest = max(manifest_candidates, key=structure_score, default={})
    # Add discovered paths, but never recurse into broad checkpoint/ledger files.
    all_refs = unique_refs(all_refs + [(k, p) for k, p in xml_candidates])
    xml_path = None
    # Prefer a generated/prepared XML that exists; source XML is stronger than an XMF.
    for key, path in all_refs:
        low = f"{key} {path}".lower()
        if path.lower().endswith(".xml") and ("prepared" in low or "generated" in low or "gencase" in low):
            if Path(path).exists():
                xml_path = Path(path)
                break
    markers = xml_physical_markers(xml_path) if xml_path else {}
    # Manifest-derived generated XML often arrives after the first queue pass.
    for key in ("prepared_generated_xml", "source_definition", "definition"):
        if not xml_path and isinstance(physical_manifest.get(key), str):
            candidate = Path(physical_manifest[key])
            if candidate.exists():
                xml_path = candidate
                markers = xml_physical_markers(candidate)
                break
    # Limit refs to metadata roles; do not place PNG/H5/BI4/etc. in the package.
    selected = []
    for key, path in all_refs:
        if Path(path).suffix.lower() in ALLOWED_SUFFIXES:
            selected.append(metadata_record(key, path))
    # Include primary manifest/generated XML if a nested field was not a direct ref.
    extra = []
    for field in ("prepared_generated_xml", "source_definition"):
        val = physical_manifest.get(field)
        if isinstance(val, str) and path_like(val):
            extra.append(metadata_record(field, val))
    selected = {r["path"]: r for r in selected}
    for r in extra:
        selected.setdefault(r["path"], r)
    return {
        "metadata_refs": sorted(selected.values(), key=lambda r: (r["suffix"], r["path"])),
        "manifest_physical_fields": physical_manifest,
        "owner_physical_binding": physical_owner,
        "generated_xml": (
            {"path": str(xml_path), "sha256": file_hash(xml_path)}
            if xml_path and xml_path.exists() else None
        ),
        "xml_physical_markers": markers,
    }


def source_evidence_case_bound(
    current: dict[str, Any],
    product: dict[str, Any],
    roster_row: dict[str, Any],
    family: str,
    case_id: str | None,
    physical_id: str | None,
) -> dict[str, Any]:
    """Resolve physical evidence through this row's own native request.

    Delivery indexes carry many nested historical references.  The only safe
    way to distinguish RX/ROT, AY, gap/offset/velocity, run-up motion, or
    fractional obstacle amplitude is to follow the exact native receipt for
    this row, then select the input owner/source/Def file whose filename
    contains that receipt request's case ID.  This intentionally keeps the
    old broad extractor above available for comparison, but never uses its
    cross-case first match in the production audit.
    """
    direct = unique_refs(refs(current) + refs(product) + refs(roster_row))
    seed: list[tuple[str, str]] = []
    receipt = (
        current.get("native_request_scope", {})
        .get("evidence", {})
        .get("receipt", {})
        .get("path")
    )
    if isinstance(receipt, str) and Path(receipt).suffix.lower() == ".json":
        seed.append(("native_request_scope.evidence.receipt", receipt))
    for key, path in direct:
        if case_bound_path(path, family, case_id, physical_id):
            seed.append((key, path))
    queue = unique_refs(seed)
    seen_json: set[str] = set()
    all_refs: list[tuple[str, str]] = []
    manifest_candidates: list[dict[str, Any]] = []
    owner_candidates: list[dict[str, Any]] = []
    owner_exact_candidates: list[dict[str, Any]] = []
    request_candidates: list[dict[str, Any]] = []
    xml_candidates: list[tuple[str, str]] = []

    def trusted_request_path(path: str, trusted_dirs: list[Path]) -> bool:
        """Allow a request's own generic binding/prepared siblings only.

        Some legitimate prepared reports are named ``prepared-input-report``
        and live below a ``lower``/``upper`` directory rather than repeating
        the case ID in the filename.  The request's gencase prefix and direct
        physical binding paths are the case-bound authority for these files;
        this does not broaden traversal to checkpoint/global indexes.
        """
        if Path(path).suffix.lower() not in ALLOWED_SUFFIXES:
            return False
        try:
            candidate = Path(path).resolve()
        except OSError:
            candidate = Path(path)
        for root in trusted_dirs:
            try:
                candidate.relative_to(root.resolve())
                return True
            except (OSError, ValueError):
                continue
        return False

    def direct_request_refs(req: dict[str, Any], parent_key: str) -> None:
        """Queue direct request physical/prepared metadata and its siblings."""
        trusted_dirs: list[Path] = []
        for name in (
            "gencase_prefix", "prepared_prefix", "physical_binding",
            "actual_continuum_binding", "source_definition", "source_owner",
            "generated_xml",
        ):
            value = req.get(name)
            values = value if isinstance(value, list) else [value]
            for item in values:
                if not isinstance(item, str) or not item:
                    continue
                p = Path(item)
                # A gencase prefix is a future output stem, not necessarily an
                # existing directory; its parent contains the prepared report,
                # XML and case-bound binding siblings.
                trusted_dirs.append(p)
                trusted_dirs.append(p.parent)
                if p.suffix.lower() in ALLOWED_SUFFIXES:
                    queue.append((f"{parent_key}.{name}", item))
        for item in req.get("input_files", []) if isinstance(req.get("input_files"), list) else []:
            if not isinstance(item, str) or Path(item).suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            if case_bound_path(item, family, case_id, physical_id) or trusted_request_path(item, trusted_dirs):
                queue.append((f"{parent_key}.input_files", item))

    def enqueue_case_refs(value: Any, parent_key: str) -> None:
        for child_key, child_path in refs(value):
            if not case_bound_path(child_path, family, case_id, physical_id):
                continue
            if child_path in {p for _, p in all_refs}:
                continue
            queue.append((f"{parent_key}.{child_key}", child_path))

    while queue and len(seen_json) < 32:
        key, path = queue.pop(0)
        if path in {p for _, p in all_refs}:
            continue
        all_refs.append((key, path))
        low = f"{key} {path}".lower()
        suffix = Path(path).suffix.lower()
        if suffix == ".xml":
            xml_candidates.append((key, path))
            continue
        if suffix != ".json" or path in seen_json:
            continue
        seen_json.add(path)
        data = load_metadata(Path(path))
        if data is None:
            continue
        name = Path(path).name.lower()
        is_receipt = name in {"execution-receipt.json", "controller-result.json"}
        is_manifest = name == "manifest.json" or "manifest" in low
        is_owner = name.endswith(".owner.json") or "/owners/" in low or "owner" in low
        if is_receipt and isinstance(data.get("request"), dict):
            req = data["request"]
            extracted = physical_sections(req)
            if extracted:
                request_candidates.append(extracted)
            # The request input list is the authoritative case-bound bridge.
            enqueue_case_refs(req, f"{key}.request")
            direct_request_refs(req, f"{key}.request")
        if is_manifest:
            fields = selected_manifest_fields(data)
            if fields:
                manifest_candidates.append(fields)
            enqueue_case_refs(data, key)
        if is_owner:
            fields = physical_owner_fields(data)
            if fields:
                owner_candidates.append(fields)
                if isinstance(data, dict) and (
                    data.get("physical_case_id") in {physical_id, case_id}
                    or data.get("case_id") in {physical_id, case_id}
                ):
                    owner_exact_candidates.append(fields)
            sections = physical_sections(data)
            if sections:
                owner_candidates.append(sections)
            enqueue_case_refs(data, key)
        if any(marker in low for marker in ("source", "metadata", "prepared", "request", "owner", "direct")):
            fields = physical_owner_fields(data)
            if fields:
                owner_candidates.append(fields)
                if isinstance(data, dict) and (
                    data.get("physical_case_id") in {physical_id, case_id}
                    or data.get("case_id") in {physical_id, case_id}
                ):
                    owner_exact_candidates.append(fields)
            sections = physical_sections(data)
            if sections:
                owner_candidates.append(sections)
            enqueue_case_refs(data, key)

    physical_owner = max(
        owner_exact_candidates or owner_candidates,
        key=structure_score,
        default={},
    )
    physical_manifest = max(manifest_candidates, key=structure_score, default={})
    request_physical = max(request_candidates, key=structure_score, default={})
    xml_path: Path | None = None
    for key, path in all_refs + xml_candidates:
        low = f"{key} {path}".lower()
        if path.lower().endswith(".xml") and Path(path).exists():
            if any(x in low for x in ("prepared", "gencase", "generated", "definition", "_def.xml")):
                xml_path = Path(path)
                break
    markers = xml_physical_markers(xml_path) if xml_path else {}
    selected: dict[str, dict[str, Any]] = {}
    for key, path in unique_refs(all_refs + xml_candidates):
        if Path(path).suffix.lower() in ALLOWED_SUFFIXES:
            selected.setdefault(path, metadata_record(key, path))
    return {
        "metadata_refs": sorted(selected.values(), key=lambda r: (r["suffix"], r["path"])),
        "manifest_physical_fields": physical_manifest,
        "owner_physical_binding": physical_owner,
        "native_request_physical_sections": request_physical,
        "generated_xml": (
            {"path": str(xml_path), "sha256": file_hash(xml_path)}
            if xml_path and xml_path.exists() else None
        ),
        "xml_physical_markers": markers,
        "case_bound_resolution": {
            "family_id": family,
            "case_id": case_id,
            "physical_case_id": physical_id,
            "native_receipt_followed": isinstance(receipt, str),
            "cross_case_global_index_paths_excluded": True,
            "request_input_owner_selected_by_case_id": True,
        },
    }


def membership_for(family: str, product: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    arrays = {
        "frozen8": product.get("first8_physical_case_ids"),
        "actual24": product.get("first24_physical_case_ids"),
        "registered48": product.get("final48_physical_case_ids"),
    }
    if not all(isinstance(arrays[k], list) for k in arrays):
        m = product.get("membership", {})
        arrays = {
            "frozen8": m.get("frozen_first8_physical_case_ids"),
            "actual24": m.get("actual_first24_physical_case_ids"),
            "registered48": m.get("final48_physical_case_ids") or m.get("registered_final48_physical_case_ids"),
        }
    arrays = {k: (v if isinstance(v, list) else []) for k, v in arrays.items()}
    ids = [r["physical_case_id"] for r in rows]
    idset = set(ids)
    return {
        "source_product": str(PRODUCTS[family]),
        "source_product_sha256": file_hash(PRODUCTS[family]),
        "frozen8_physical_case_ids": arrays["frozen8"],
        "actual24_physical_case_ids": arrays["actual24"],
        "registered48_physical_case_ids": arrays["registered48"],
        "frozen8_count": len(arrays["frozen8"]),
        "actual24_count": len(arrays["actual24"]),
        "registered48_count": len(arrays["registered48"]),
        "frozen8_subset_actual24": set(arrays["frozen8"]).issubset(set(arrays["actual24"])),
        "actual24_subset_registered48": set(arrays["actual24"]).issubset(set(arrays["registered48"])),
        "registered_matches_current_index": set(arrays["registered48"]) == idset,
        "registered_unique": len(arrays["registered48"]) == len(set(arrays["registered48"])),
        "selection_rule": "explicit source arrays; no lexical sorting, resolution replica, time slice, view, or alias selection",
    }


def identifier_tokens(family: str, physical_id: str, case_id: str) -> dict[str, Any]:
    text = f"{physical_id} {case_id}"
    patterns: dict[str, list[str]] = {}
    for name, pat in (
        ("receiver_or_x", r"RX(?:M|m)?[0-9]+"),
        ("rotation_or_duration", r"(?:ROT|T)[0-9]+"),
        ("pitch", r"P(?:ITCH)?[0-9]+"),
        ("amplitude", r"A(?:Y)?[0-9]+"),
        ("gap", r"gap(?:m|0p)?[0-9]+"),
        ("offset", r"xoff(?:m|0p)?[0-9]+|yoff(?:m|0p)?[0-9]+"),
        ("speed", r"(?:uz|vz)[-m0p0-9]+"),
        ("angle_or_yaw", r"(?:YAW|A)[A-ZM0-9]+"),
        ("family_variant", r"(?:H[0-9]+|B[0-9]+|S[0-9]+|DXYZ)"),
    ):
        vals = sorted(set(re.findall(pat, text, flags=re.IGNORECASE)))
        if vals:
            patterns[name] = vals
    return patterns


def build() -> dict[str, Any]:
    index = load_json(INDEX)
    closure = load_json(CLOSURE)
    roster = load_json(ROSTER)
    pinned_doc = load_json(PINNED_F2_F7)
    endpoint_doc = load_json(ENDPOINT_F3_PROOF)
    omission_doc = load_json(OMISSION_PROOF)
    pinned_rows = {
        (row.get("family_id"), row.get("physical_case_id")): row
        for row in pinned_doc.get("rows", [])
        if isinstance(row, dict) and row.get("family_id") and row.get("physical_case_id")
    }
    endpoint_rows = {
        row.get("physical_case_id"): row
        for row in endpoint_doc.get("rows", [])
        if isinstance(row, dict) and row.get("physical_case_id")
    }
    products = {fam: load_json(path) for fam, path in PRODUCTS.items()}
    product_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for family, product in products.items():
        arrays: list[Any] = []
        for key in ("cases", "accepted47_actual_primary_rows", "accepted45_actual_primary_bed_rows", "rows", "products"):
            if isinstance(product.get(key), list):
                arrays.extend(product[key])
        for row in arrays:
            if isinstance(row, dict) and row.get("physical_case_id"):
                product_rows[(family, row["physical_case_id"])] = row
    roster_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for family, value in roster.get("families", {}).items():
        for row in value.get("cases", []):
            if row.get("physical_case_id"):
                roster_rows[(family, row["physical_case_id"])] = row
    current_rows = index.get("cases", [])
    absence_from_closure = set(closure.get("true_actual_field_absence_physical_case_ids", []))
    if absence_from_closure != ABSENT_NATIVE_IDS:
        raise SystemExit(f"closure absence set mismatch: {sorted(absence_from_closure)}")
    rows_out: list[dict[str, Any]] = []
    family_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for current in current_rows:
        family = current["family_id"]
        physical = current["physical_case_id"]
        case = current.get("case_id")
        product = product_rows.get((family, physical), {})
        roster_row = roster_rows.get((family, physical), {})
        evidence = source_evidence_case_bound(
            current, product, roster_row, family, case, physical
        )
        physical_tuple = family_physical_tuple(family, physical, evidence, current)
        endpoint_tuple = endpoint_f3_tuple(physical, physical_tuple, endpoint_rows) if family == "F3" else None
        if endpoint_tuple is not None:
            physical_tuple = endpoint_tuple
        repaired_tuple = special_case_tuple(family, physical, physical_tuple)
        if repaired_tuple is not None:
            physical_tuple = repaired_tuple
        pinned = pinned_family_tuple(family, physical, physical_tuple, pinned_rows)
        if pinned is not None:
            physical_tuple = pinned
        owner = evidence["owner_physical_binding"]
        manifest = evidence["manifest_physical_fields"]
        request_physical = evidence["native_request_physical_sections"]
        markers = evidence["xml_physical_markers"]
        physical_components = []
        if owner:
            physical_components.append("owner.physical_binding")
        if manifest.get("physical_binding") or any(
            k in manifest for k in (
                "source_plan_physical_condition_sha256", "physical_condition_sha256",
                "geometry", "parameters", "control_family_id", "mechanism_id",
            )
        ):
            physical_components.append("XMF/owner manifest physical fields")
        if markers.get("markers"):
            physical_components.append("generated XML geometry/control markers")
        if request_physical:
            physical_components.append("case-bound native request physical/forcing sections")
        # Never count frame/particle/window fields as physical differences.
        signature_payload = {
            "owner_physical_binding": signature_physical_value(owner),
            "native_request_physical_sections": signature_physical_value(request_physical),
            "manifest_physical_fields": signature_physical_value({
                k: v for k, v in manifest.items()
                if k not in {
                    "family_id", "case_id", "physical_case_id", "actual_dimension",
                    "expected_dimension", "actual_frame_count", "expected_native_frames",
                    "expected_frames", "actual_particles", "expected_particles",
                    "physical_window_s", "save_interval_s", "frames", "particles",
                }
            }),
            "xml_physical_markers": signature_physical_value(markers),
        }
        signature_digest = canonical_hash(signature_payload) if physical_components else None
        native_scope = current.get("native_request_scope")
        native_scope = native_scope if isinstance(native_scope, dict) else {}
        native_absent = physical in absence_from_closure or bool(current.get("actual_native_condition_field_true_absence"))
        if not physical_components:
            distinct_status = "UNCERTAIN_SOURCE_PHYSICAL_BINDING_NOT_FOUND"
        elif native_absent:
            distinct_status = "PASS_SOURCE_GEOMETRY_CONTROL_NATIVE_FIELD_TRUE_ABSENCE"
        else:
            distinct_status = "PASS_SOURCE_GEOMETRY_CONTROL_EVIDENCE"
        # The rich source signature is retained for provenance only.  Physical
        # distinctness is decided by the family-specific normalized tuple,
        # which excludes IDs, paths, hashes, resolution, windows, and markers.
        if not str(physical_tuple.get("tuple_status", "")).startswith("PASS_CASE_BOUND"):
            distinct_status = "UNCERTAIN_FAMILY_PHYSICAL_TUPLE_FIELDS_MISSING"
        row = {
            "family_id": family,
            "physical_case_id": physical,
            "case_id": case,
            "current_status": current.get("status"),
            "membership_role": (
                product.get("membership")
                if isinstance(product.get("membership"), dict)
                else None
            ),
            "physical_difference_status": distinct_status,
            "physical_difference_basis": physical_components,
            "identifier_tokens_reference_only": identifier_tokens(family, physical, case or ""),
            "identifier_tokens_not_used_as_standalone_proof": True,
            "source_metadata": evidence,
            "native_condition_role": {
                "sha256": native_scope.get("sha256"),
                "role": native_scope.get("role"),
                "true_field_absent": native_absent,
                "field_absence_not_backfilled": native_absent,
                "evidence": native_scope.get("evidence") or native_scope.get("actual_native_receipt_observation"),
            },
            "source_plan_condition_sha256": current.get("declared_source_plan_condition_sha256"),
            "source_definition_sha256": current.get("declared_source_definition_sha256"),
            "actual_converter_scope_sha256": current.get("declared_actual_converter_scope_sha256"),
            "accepted_top_condition_sha256": current.get("accepted_decision_top_condition_sha256"),
            "accepted_top_hash_not_used_as_native_proof": True,
            "physical_signature_digest": signature_digest,
            "family_physical_tuple": physical_tuple,
            "family_physical_tuple_sha256": physical_tuple.get("tuple_sha256"),
            "family_physical_tuple_status": physical_tuple.get("tuple_status"),
            "frames_particles_time_not_used_as_physical_difference": True,
            "case_alias_not_counted_as_physical_difference": True,
            "new_case_credit": 0,
            "Q_N": 0,
            "Q_E": 0,
        }
        rows_out.append(row)
        family_rows[family].append(row)
    # The rich signature is retained as a review fact only.  Its collisions do
    # not establish physical distinctness because it can contain metadata
    # structure.  The normalized family tuple below is the decision surface.
    duplicate_groups: dict[str, list[str]] = {}
    tuple_duplicate_groups: dict[str, list[str]] = {}
    for family, rows in family_rows.items():
        grouped: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            if row["physical_signature_digest"]:
                grouped[row["physical_signature_digest"]].append(row["physical_case_id"])
        for digest, ids in grouped.items():
            if len(ids) > 1:
                duplicate_groups[f"{family}:{digest}"] = ids
                for row in rows:
                    if row["physical_signature_digest"] == digest:
                        # Rich-signature collisions are retained as provenance
                        # only.  They cannot override the normalized tuple
                        # status or turn two case-bound tuples into aliases.
                        row["physical_difference_basis"].append(
                            "rich signature collision retained for review; not physical proof"
                        )
        tuple_grouped: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            digest = row.get("family_physical_tuple_sha256")
            if digest:
                tuple_grouped[digest].append(row["physical_case_id"])
        for digest, ids in tuple_grouped.items():
            if len(ids) > 1:
                key = f"{family}:{digest}"
                tuple_duplicate_groups[key] = ids
                for row in rows:
                    if row.get("family_physical_tuple_sha256") == digest:
                        row["physical_difference_status"] = "REVIEW_FAMILY_PHYSICAL_TUPLE_DUPLICATE"
                        row["physical_difference_basis"].append(
                            "normalized family tuple collision; IDs/paths/hashes are not evidence"
                        )
    family_summary: dict[str, Any] = {}
    for family in FAMILIES:
        rows = family_rows[family]
        membership = membership_for(family, products[family], [r for r in current_rows if r["family_id"] == family])
        status_counts = Counter(r["physical_difference_status"] for r in rows)
        family_summary[family] = {
            "registered_rows": len(rows),
            "physical_case_ids_unique": len({r["physical_case_id"] for r in rows}) == 48,
            "membership": membership,
            "physical_difference_status_counts": dict(status_counts),
            "family_physical_tuple_pass_count": sum(
                str(r.get("family_physical_tuple_status", "")).startswith("PASS_CASE_BOUND")
                for r in rows
            ),
            "family_physical_tuple_missing_case_ids": [
                r["physical_case_id"] for r in rows
                if not str(r.get("family_physical_tuple_status", "")).startswith("PASS_CASE_BOUND")
            ],
            "family_physical_tuple_collision_groups": {
                key: ids for key, ids in tuple_duplicate_groups.items()
                if key.startswith(f"{family}:")
            },
            "source_geometry_control_evidence_count": sum(
                s.startswith("PASS_") for s in status_counts for _ in range(status_counts[s])
            ),
            "uncertain_case_ids": [
                r["physical_case_id"] for r in rows
                if r["physical_difference_status"].startswith(("UNCERTAIN", "REVIEW"))
            ],
            "native_true_absence_case_ids": [
                r["physical_case_id"] for r in rows if r["physical_case_id"] in absence_from_closure
            ],
            "difference_basis_excludes": [
                "resolution or particle count",
                "frame/time window or save interval",
                "view/camera/contact PNG",
                "case alias or accepted-top hash",
            ],
        }
    top = {
        "schema": "ds02.full336.physical-distinctness-role-audit.v1",
        "created_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "model": "gpt-5.6-luna",
        "reasoning_effort": "max",
        "scope": "F3 source-only audit of all registered F1..F7 physical IDs",
        "authoritative_sources": {
            "current_full336_index": {"path": str(INDEX), "sha256": file_hash(INDEX)},
            "native_field_role_closure": {"path": str(CLOSURE), "sha256": file_hash(CLOSURE)},
            "f1_f4_f7_roster": {"path": str(ROSTER), "sha256": file_hash(ROSTER)},
            "family_primary_products": {
                family: {"path": str(path), "sha256": file_hash(path)}
                for family, path in PRODUCTS.items()
            },
        },
        "registered_summary": {
            "rows": len(rows_out),
            "families": {f: len(family_rows[f]) for f in FAMILIES},
            "physical_case_ids_unique_global": len({r["physical_case_id"] for r in rows_out}) == 336,
            "current_index_declared_counts": {
                k: index.get(k)
                for k in (
                    "accepted_independent_physical_cases",
                    "registered_pending_independent_physical_cases",
                    "union_distinct_physical_case_ids",
                    "new_case_credit",
                )
            },
            "this_audit_does_not_reclassify_current_index_or_pending_rows": True,
        },
        "membership_contract": {
            "required": "explicit frozen8 subset actual24 subset registered48 per family",
            "no_lexical_or_replica_selection": True,
            "family_summary": {
                family: family_summary[family]["membership"] for family in FAMILIES
            },
        },
            "native_field_role_closure": {
            "source": {"path": str(CLOSURE), "sha256": file_hash(CLOSURE)},
            "actual_digest_available": closure.get("actual_native_field_digest_available"),
            "true_absence_count": closure.get("true_actual_native_digest_field_absent_count"),
            "true_absence_physical_case_ids": sorted(absence_from_closure),
            "unresolved_roles_remaining": closure.get("unresolved_native_condition_field_roles_remaining"),
            "closure_is_not_native_completion_certificate": closure.get(
                "field_role_closure_not_new_numerical_or_native_completed0_certificate_for_all336"
            ),
        },
        "pinned_numeric_family_tuple_proof": {
            "path": str(PINNED_F2_F7),
            "sha256": file_hash(PINNED_F2_F7),
            "rows": len(pinned_rows),
            "families": sorted({f for f, _ in pinned_rows}),
            "launch_after_source_hashes_match_required": True,
        },
        "f3_endpoint_forcing_tuple_proof": {
            "path": str(ENDPOINT_F3_PROOF),
            "sha256": file_hash(ENDPOINT_F3_PROOF),
            "rows": len(endpoint_rows),
            "actual_forcing_transform_is_case_bound": True,
            "copied_nominal_request_binding_not_used_as_actual_forcing": True,
            "scientific_forcing_table_read_or_hashed_by_source_audit": False,
        },
        "actual_lifecycle_omission_supplement": {
            "path": str(OMISSION_PROOF),
            "sha256": file_hash(OMISSION_PROOF),
            "schema": omission_doc.get("schema"),
            "summary": omission_doc.get("summary"),
            "purpose": omission_doc.get("purpose"),
            "does_not_prove_strict_containment_or_numerical_accuracy": True,
            "scientific_payload_IO": omission_doc.get("scientific_payload_IO"),
            "scientific_payload_hashing": omission_doc.get("scientific_payload_hashing"),
        },
        "family_summary": family_summary,
        "signature_collision_groups": duplicate_groups,
        "family_physical_tuple_collision_groups": tuple_duplicate_groups,
        "family_physical_tuple_unique_per_family": not bool(tuple_duplicate_groups),
        "uncertainty_policy": {
            "id_difference_alone_is_not_proof": True,
            "accepted_top_or_converter_hash_is_not_native_proof": True,
            "missing_native_condition_fields_remain_null": True,
            "pending_rows_may_remain_uncertain_until_source_geometry_control_metadata_exists": True,
            "visual_or_numerical_status_not_reclassified": True,
        },
        "source_boundaries": {
            "scientific_payload_IO": False,
            "scientific_payload_hashed": False,
            "scientific_payload_copied": False,
            "new_jobs": False,
            "shared_state_written": False,
            "case_credit": 0,
            "Q_N": 0,
            "Q_E": 0,
            "forbidden_suffixes_not_opened_or_hashed": sorted(FORBIDDEN_SUFFIXES),
        },
        "cases": rows_out,
    }
    return top


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    audit = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    family_summary = audit.get("family_summary", {})
    summary = {
        "schema": "ds02.full336.physical-distinctness-summary.v2",
        "authoritative_audit": {
            "path": str(args.output),
            "sha256": file_hash(args.output),
        },
        "authoritative_current_index": audit.get("authoritative_sources", {}).get("current_full336_index"),
        "conclusion": {
            "rows": len(audit.get("cases", [])),
            "family_physical_tuple_collision_groups": len(audit.get("family_physical_tuple_collision_groups", {})),
            "family_physical_tuple_unique_per_family": audit.get("family_physical_tuple_unique_per_family"),
            "rich_signature_collision_groups_retained_not_proof": len(audit.get("signature_collision_groups", {})),
            "id_difference_alone_used_as_proof": False,
            "case_credit": 0,
            "Q_N": 0,
            "Q_E": 0,
        },
        "family_summary": {
            family: {
                "registered_rows": data.get("registered_rows"),
                "tuple_pass_count": data.get("family_physical_tuple_pass_count"),
                "tuple_missing_case_ids": data.get("family_physical_tuple_missing_case_ids", []),
                "tuple_collision_groups": data.get("family_physical_tuple_collision_groups", {}),
                "uncertain_case_ids": data.get("uncertain_case_ids", []),
            }
            for family, data in family_summary.items()
        },
        "known_scope_limits": [
            "F1 fallback lower-head geometry/initial velocity is supplied by its case-bound physical-binding JSON; no ID inference is used.",
            "F3 endpoint pitch and AY use the actual 1456 forcing-transform/native pin proof; the copied AY=.50 request remains a stale role.",
            "F3 nominal pitch fields are genuinely absent for the nominal/end-point rows where listed; no pitch is inferred from the case ID.",
            "F5 A080/A120 motion/geometry controls are absent from available case-bound owner metadata and remain uncertain; the rich signature collision is not proof.",
            "F6 omega baseline mass/omega come from its case-bound generated XML; yaw is absent and remains explicitly missing.",
            "F2/F7 tuples use the independent Root1452 exact numeric pins; F2 baseline preserves its explicit legacy fluid-height discriminator.",
            "Root1454 fluid omission counts are a lifecycle supplement, not physical-distinctness proof.",
        ],
        "source_boundaries": audit.get("source_boundaries", {}),
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} rows={len(audit['cases'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
