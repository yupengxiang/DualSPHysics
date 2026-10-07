#!/usr/bin/env python3
"""Metadata-only F1/F6 normalized physical-tuple audit.

This module reads JSON metadata plus one explicitly selected F6 baseline
GenCase source-definition XML.  It never opens BI4/H5/CSV/DAT/VTK/XMF/science
payloads and never computes producer hashes.  The source receipts are used only
to pin the native request and its launch/after-run metadata; all tuple values
come from JSON request/owner/source-plan metadata or the named baseline XML
definition.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_INDEX = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_full336_actual336_user_delivery_direct_XMF_N3_times_navigation_physical_difference_and_goal_audit_unproven_1451/"
    "DS-DATA-02-ACTUAL-USER-DELIVERY-INDEX.json"
)

# Deliberately excludes all scientific payload suffixes.  A JSON source path may
# attest a payload but this worker never opens the payload itself.
JSON_SUFFIX = ".json"
XML_SUFFIX = ".xml"
SOURCE_METADATA_SUFFIXES = {JSON_SUFFIX, XML_SUFFIX}
F6_BASELINE_SOURCE_XML_NAME = "F6_ANGULAR_RELEASE_DP025.xml"
FORBIDDEN_PAYLOAD_SUFFIXES = {".bi4", ".h5", ".csv", ".dat", ".vtk", ".xmf"}

_CACHE: dict[Path, Any] = {}
_XML_CACHE: dict[Path, dict[str, Any]] = {}


def fail(message: str) -> None:
    raise RuntimeError(message)


def xml_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def read_json(path: str | Path) -> Any:
    p = Path(path)
    if p.suffix.lower() != JSON_SUFFIX:
        fail(f"refused non-JSON metadata input: {p}")
    if p.suffix.lower() in FORBIDDEN_PAYLOAD_SUFFIXES:
        fail(f"refused scientific payload input: {p}")
    p = p.resolve()
    if p not in _CACHE:
        with p.open("r", encoding="utf-8") as fh:
            _CACHE[p] = json.load(fh)
    return _CACHE[p]


def read_f6_baseline_source_xml(path: str | Path) -> dict[str, Any]:
    """Read only the named F6 baseline source-definition XML.

    This is a definition file explicitly supplied by the actual native request,
    not a solver output or a particle payload.  Restricting the basename keeps
    the exception narrow: no other XML, XMF, or generated scientific file can
    enter this audit.
    """
    p = Path(path)
    if p.suffix.lower() != XML_SUFFIX or p.name != F6_BASELINE_SOURCE_XML_NAME:
        fail(f"refused non-baseline XML metadata input: {p}")
    p = p.resolve()
    if p not in _XML_CACHE:
        root = ET.parse(p).getroot()
        floating = root.find("./casedef/floatings/floating")
        if floating is None:
            fail(f"F6 baseline XML floating definition missing: {p}")
        mass_attr = floating.find("massbody")
        angular_attr = floating.find("angularvelini")
        mass_value = xml_number(mass_attr.get("value")) if mass_attr is not None else None
        if mass_attr is None or mass_value is None:
            fail(f"F6 baseline XML massbody missing: {p}")
        if angular_attr is None:
            fail(f"F6 baseline XML angularvelini missing: {p}")
        angular = [angular_attr.get(axis) for axis in ("x", "y", "z")]
        angular_values = [xml_number(value) for value in angular]
        if not all(value is not None for value in angular_values):
            fail(f"F6 baseline XML angularvelini is not finite: {p}")
        body_box = None
        for drawbox in root.findall("./casedef/geometry/commands/mainlist/drawbox"):
            comment = drawbox.get("cmt", "")
            if "Native floatingtype=2 body" not in comment:
                continue
            point = drawbox.find("point")
            size = drawbox.find("size")
            if point is None or size is None:
                fail(f"F6 baseline XML native body drawbox incomplete: {p}")
            low = [point.get(axis) for axis in ("x", "y", "z")]
            extent = [size.get(axis) for axis in ("x", "y", "z")]
            low_values = [xml_number(value) for value in low]
            extent_values = [xml_number(value) for value in extent]
            if not all(value is not None for value in low_values + extent_values):
                fail(f"F6 baseline XML native body drawbox is not finite: {p}")
            body_box = {
                "low_m": [float(value) for value in low_values],
                "size_m": [float(value) for value in extent_values],
            }
            break
        if body_box is None:
            fail(f"F6 baseline XML native body drawbox missing: {p}")
        _XML_CACHE[p] = {
            "body_mass_kg": float(mass_value),
            "initial_angular_velocity_rad_s": [float(value) for value in angular_values],
            "initial_orientation_yaw_deg": None,
            "rigid_body_low_m": body_box["low_m"],
            "rigid_body_size_m": body_box["size_m"],
            "source_field_presence": {
                "massbody": True,
                "angularvelini": True,
                "rotation_yaw": False,
            },
        }
    return _XML_CACHE[p]


def as_path(value: Any) -> Path | None:
    if isinstance(value, str) and value.endswith(JSON_SUFFIX):
        return Path(value)
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        p = value["path"]
        if p.endswith(JSON_SUFFIX):
            return Path(p)
    return None


def f6_baseline_source_xml_path(q: dict[str, Any]) -> Path | None:
    """Return the actual baseline XML named by the native request only."""
    candidates: list[Any] = [q.get("gencase_xml")]
    input_files = q.get("input_files")
    if isinstance(input_files, list):
        candidates.extend(input_files)
    for value in candidates:
        if isinstance(value, str):
            candidate = Path(value)
            if candidate.name == F6_BASELINE_SOURCE_XML_NAME and candidate.suffix.lower() == XML_SUFFIX:
                return candidate
    return None


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def copy_numeric(value: Any) -> Any:
    if isinstance(value, list):
        return [copy_numeric(x) for x in value]
    if finite_number(value):
        return float(value) if isinstance(value, float) else int(value)
    return value


def vec3(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 3 or not all(finite_number(x) for x in value):
        return None
    return [float(x) for x in value]


def nested(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def first_value(candidates: list[tuple[str, Any]]) -> tuple[Any, str | None]:
    for field, value in candidates:
        if value is not None:
            return value, field
    return None, None


def first_vec(candidates: list[tuple[str, Any]]) -> tuple[list[float] | None, str | None]:
    for field, value in candidates:
        v = vec3(value)
        if v is not None:
            return v, field
    return None, None


def recursive_path_values(obj: Any, wanted: set[str], prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in wanted:
                out.append((path, value))
            out.extend(recursive_path_values(value, wanted, path))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            out.extend(recursive_path_values(value, f"{prefix}[{i}]"))
    return out


def find_physical_binding(obj: Any, prefix: str = "") -> tuple[dict[str, Any] | None, str | None]:
    """Find a physical binding object without walking any non-JSON source."""
    if isinstance(obj, dict):
        pb = obj.get("physical_binding")
        if isinstance(pb, dict):
            return pb, f"{prefix}.physical_binding" if prefix else "physical_binding"
        # Fallback F1 binding uses a wrapper with a direct geometry object.
        if isinstance(obj.get("geometry"), dict) and (
            "geometry_family_id" in obj or "family_id" in obj or "schema" in obj
        ):
            return obj, prefix or "$"
        if "tank_low_m" in obj and "fluid_reservoir_size_m" in obj:
            return obj, prefix or "$"
        for key, value in obj.items():
            found, path = find_physical_binding(value, f"{prefix}.{key}" if prefix else key)
            if found is not None:
                return found, path
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found, path = find_physical_binding(value, f"{prefix}[{i}]")
            if found is not None:
                return found, path
    return None, None


def collect_json_refs(obj: Any, keys: set[str], out: list[Path]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys:
                p = as_path(value)
                if p is not None:
                    out.append(p)
                elif isinstance(value, dict):
                    p = as_path(value)
                    if p is not None:
                        out.append(p)
            collect_json_refs(value, keys, out)
    elif isinstance(obj, list):
        for value in obj:
            collect_json_refs(value, keys, out)


def ref(path: str | Path, field: str, value: Any, role: str) -> dict[str, Any]:
    return {"path": str(path), "field": field, "value": copy_numeric(value), "role": role}


def geometry_parts(pb: dict[str, Any]) -> dict[str, list[float] | None]:
    g = pb.get("geometry") if isinstance(pb.get("geometry"), dict) else pb
    def part(name: str, flat_prefix: str) -> tuple[list[float] | None, list[float] | None]:
        item = g.get(name) if isinstance(g, dict) else None
        if isinstance(item, dict):
            return vec3(item.get("low_m")), vec3(item.get("size_m"))
        return vec3(g.get(f"{flat_prefix}_low_m")), vec3(g.get(f"{flat_prefix}_size_m"))
    tank_low, tank_size = part("tank", "tank")
    obstacle_low, obstacle_size = part("obstacle_or_divider", "obstacle_or_divider")
    fluid_low, fluid_size = part("initial_fluid", "fluid_reservoir")
    if fluid_low is None:
        fluid_low, fluid_size = part("fluid_reservoir", "fluid_reservoir")
    return {
        "tank_low_m": tank_low,
        "tank_size_m": tank_size,
        "obstacle_or_divider_low_m": obstacle_low,
        "obstacle_or_divider_size_m": obstacle_size,
        "fluid_reservoir_low_m": fluid_low,
        "fluid_reservoir_size_m": fluid_size,
    }


def geometry_family(pb: dict[str, Any], q: dict[str, Any]) -> str | None:
    raw = str(pb.get("geometry_family_id") or q.get("geometry_family_id") or "")
    if "ECC" in raw.upper() or "ECCENTRIC" in raw.upper():
        return "ECC"
    if "DUAL" in raw.upper() or "ASYMMETRIC" in raw.upper():
        return "DUAL"
    return raw or None


def native_receipt_path(family: str, product_row: dict[str, Any]) -> Path | None:
    if family == "F1":
        obs = nested(product_row, "actual_native_condition_observation", "observations")
        if isinstance(obs, list):
            for item in obs:
                p = as_path(nested(item, "receipt"))
                if p is not None and p.name == "execution-receipt.json":
                    return p
    else:
        refs = nested(product_row, "primary_refs", "native")
        if isinstance(refs, list):
            for item in refs:
                p = as_path(item)
                if p is not None and p.name == "execution-receipt.json":
                    return p
    # Conservative fallback: only select a path labelled native, never a CSV/
    # BI4/H5/etc. path.
    found: list[Path] = []
    def walk(x: Any) -> None:
        if isinstance(x, dict):
            p = as_path(x)
            if p is not None and p.name == "execution-receipt.json":
                found.append(p)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(product_row)
    for p in found:
        if "native" in str(p).lower() or "qualification" in str(p).lower():
            return p
    return found[0] if found else None


def pin_receipt(path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    launch = receipt.get("input_hashes_at_launch")
    after = receipt.get("input_hashes_after_run")
    present = isinstance(launch, dict) and isinstance(after, dict)
    equal = bool(present and launch == after)
    return {
        "receipt_path": str(path),
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "completed0": receipt.get("status") == "completed" and receipt.get("returncode") == 0,
        "input_hashes_at_launch_present": isinstance(launch, dict),
        "input_hashes_after_run_present": isinstance(after, dict),
        "launch_after_metadata_equal": equal,
        "native_pin_verified": bool(receipt.get("status") == "completed" and receipt.get("returncode") == 0 and equal),
        "launch_hash_key_count": len(launch) if isinstance(launch, dict) else None,
        "after_hash_key_count": len(after) if isinstance(after, dict) else None,
    }


def f1_source_docs(q: dict[str, Any], receipt_path: Path) -> tuple[list[tuple[Path, Any]], list[str]]:
    paths: list[Path] = []
    # These are metadata roles, not payload paths.  We intentionally do not
    # use input_files because that list contains BI4/CSV/XML payload entries.
    for key in ("actual_continuum_binding", "binding", "owner_provenance", "owner", "source_plan"):
        p = as_path(q.get(key))
        if p is not None and p not in paths:
            paths.append(p)
    docs: list[tuple[Path, Any]] = []
    errors: list[str] = []
    for p in paths:
        try:
            docs.append((p, read_json(p)))
        except Exception as exc:
            errors.append(f"{p}: {exc}")
    return docs, errors


def f1_tuple(product_row: dict[str, Any], q: dict[str, Any], receipt_path: Path, family_parent: tuple[dict[str, Any], str] | None) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    docs, errors = f1_source_docs(q, receipt_path)
    binding: dict[str, Any] | None = None
    binding_source: str | None = None
    for p, doc in docs:
        candidate, loc = find_physical_binding(doc)
        if candidate is not None:
            binding, binding_source = candidate, f"{p}::{loc}"
            break
    # Newer F1 requests carry their own geometry in the native request.
    if binding is None and isinstance(q.get("geometry"), dict):
        binding = {"geometry": q["geometry"], "geometry_family_id": q.get("geometry_family_id")}
        binding_source = f"{receipt_path}::request.geometry"
    inherited = False
    if binding is None and family_parent is not None:
        binding, binding_source = family_parent
        inherited = True
    if binding is None:
        errors.append("no physical binding metadata")
        binding = {}

    parts = geometry_parts(binding)
    family = geometry_family(binding, q)
    plan_doc: dict[str, Any] | None = None
    plan_path: Path | None = None
    for p, doc in docs:
        if isinstance(doc, dict) and isinstance(doc.get("grid"), dict):
            plan_doc, plan_path = doc, p
            break
        nested_plan = doc.get("source_plan") if isinstance(doc, dict) else None
        if isinstance(nested_plan, str) and nested_plan.endswith(".json"):
            candidate_path = Path(nested_plan)
            try:
                candidate = read_json(candidate_path)
                if isinstance(candidate, dict) and isinstance(candidate.get("grid"), dict):
                    plan_doc, plan_path = candidate, candidate_path
                    break
            except Exception as exc:
                errors.append(f"{candidate_path}: {exc}")
    # The request itself can name the plan even if binding docs were absent.
    direct_plan = as_path(q.get("source_plan"))
    if plan_doc is None and direct_plan is not None:
        try:
            plan_doc, plan_path = read_json(direct_plan), direct_plan
        except Exception as exc:
            errors.append(f"{direct_plan}: {exc}")

    grid = plan_doc.get("grid", {}) if isinstance(plan_doc, dict) else {}
    depth_candidates = [
        # A Root283/090 source plan is the physical height and velocity
        # mutation for these rows.  It must outrank the shared fallback
        # binding still present in the native request input list.
        ("source_plan.grid.nominal_physical_fluid_depth_m", grid.get("nominal_physical_fluid_depth_m")),
        ("request.parameter_tuple.fluid_depth_m", nested(q, "parameter_tuple", "fluid_depth_m")),
        ("request.fluid_depth_m", q.get("fluid_depth_m")),
        ("request.geometry.fluid_reservoir.size_m[2]", nested(q, "geometry", "fluid_reservoir", "size_m",)),
        ("binding.parameters.fluid_depth_m", nested(binding, "parameters", "fluid_depth_m")),
        ("binding.geometry.fluid_reservoir_size_m[2]", (parts["fluid_reservoir_size_m"] or [None, None, None])[2] if parts["fluid_reservoir_size_m"] else None),
        ("binding.geometry.initial_fluid.size_m[2]", nested(binding, "geometry", "initial_fluid", "size_m",)),
    ]
    depth, depth_field = first_value(depth_candidates)
    if not finite_number(depth):
        depth, depth_field = None, None
    drawbox = grid.get("xml_fluid_drawbox_size_z_m") if isinstance(grid, dict) else None
    if not finite_number(drawbox):
        drawbox = None
    if drawbox is not None and parts["fluid_reservoir_size_m"] is not None:
        # Root283/090 materializes the source-plan XML drawbox one DP below
        # the nominal physical depth.  Keep the nominal depth as its own
        # tuple field and make the geometry size describe that materialized
        # source, rather than the parent endpoint's height.
        parts["fluid_reservoir_size_m"] = [parts["fluid_reservoir_size_m"][0], parts["fluid_reservoir_size_m"][1], float(drawbox)]
    vx, vx_field = first_vec([
        ("source_plan.initial_velocity_declaration_m_per_s", plan_doc.get("initial_velocity_declaration_m_per_s") if plan_doc else None),
        ("request.initial_velocity_declaration_m_per_s", q.get("initial_velocity_declaration_m_per_s")),
        ("request.motion.initial_velocities_m_per_s.fluid", nested(q, "motion", "initial_velocities_m_per_s", "fluid")),
        ("request.initial_velocity_m_per_s", q.get("initial_velocity_m_per_s")),
        ("binding.initialization.velocity_m_s", nested(binding, "initialization", "velocity_m_s")),
        ("binding.parameters.initial_velocity_m_per_s", nested(binding, "parameters", "initial_velocity_m_per_s")),
        ("binding.initial_state.velocities_m_per_s.fluid", nested(binding, "initial_state", "velocities_m_per_s", "fluid")),
    ])
    if vx is None:
        errors.append("initial fluid vx/vector missing")
    refs: list[dict[str, Any]] = []
    refs.append(ref(receipt_path, "request", {"physical_binding": binding_source}, "native request / binding source"))
    if binding_source:
        refs.append(ref(binding_source.split("::", 1)[0], binding_source.split("::", 1)[1] if "::" in binding_source else "$", {
            "geometry_family_id": binding.get("geometry_family_id"),
            "geometry": parts,
        }, "physical geometry source"))
    if depth_field:
        depth_path = plan_path if depth_field.startswith("source_plan.") and plan_path is not None else receipt_path
        if depth_field.startswith("binding.") and binding_source and "::" in binding_source:
            depth_path = Path(binding_source.split("::", 1)[0])
        refs.append(ref(depth_path, depth_field, depth, "fluid depth"))
    if vx_field:
        vx_path = plan_path if vx_field.startswith("source_plan.") and plan_path is not None else receipt_path
        if vx_field.startswith("binding.") and binding_source and "::" in binding_source:
            vx_path = Path(binding_source.split("::", 1)[0])
        refs.append(ref(vx_path, vx_field, vx, "initial fluid velocity"))
    if plan_path is not None:
        refs.append(ref(plan_path, "grid", {"nominal_physical_fluid_depth_m": grid.get("nominal_physical_fluid_depth_m"), "xml_fluid_drawbox_size_z_m": grid.get("xml_fluid_drawbox_size_z_m")}, "source-plan materialization metadata"))
    normalized = {
        "geometry_family": family,
        "fluid_depth_m": float(depth) if depth is not None else None,
        "materialized_fluid_drawbox_size_z_m": float(drawbox) if drawbox is not None else None,
        "initial_fluid_vx_m_s": float(vx[0]) if vx is not None else None,
        "fluid_reservoir_low_m": parts["fluid_reservoir_low_m"],
        "fluid_reservoir_size_m": parts["fluid_reservoir_size_m"],
        "obstacle_or_divider_low_m": parts["obstacle_or_divider_low_m"],
        "obstacle_or_divider_size_m": parts["obstacle_or_divider_size_m"],
        "tank_low_m": parts["tank_low_m"],
        "tank_size_m": parts["tank_size_m"],
    }
    return normalized, refs, errors


def f6_source_paths(product_row: dict[str, Any], q: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for value in (q.get("canonical_owner"), q.get("binding"), q.get("actual_initial_qa"), q.get("actual_initial_qa_report")):
        p = as_path(value)
        if p is not None and p not in paths:
            paths.append(p)
    refs = nested(product_row, "primary_refs", "owner_or_source")
    if isinstance(refs, list):
        for item in refs:
            p = as_path(item)
            if p is not None and p not in paths:
                paths.append(p)
    qa_refs = nested(product_row, "primary_refs", "initial_qa_or_audit")
    if isinstance(qa_refs, list):
        for item in qa_refs:
            p = as_path(item)
            if p is not None and p not in paths:
                paths.append(p)
    return paths


def f6_tuple(product_row: dict[str, Any], q: dict[str, Any], receipt_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], dict[str, Any]]:
    paths = f6_source_paths(product_row, q)
    docs: list[tuple[Path, Any]] = []
    errors: list[str] = []
    for p in paths:
        try:
            docs.append((p, read_json(p)))
        except Exception as exc:
            errors.append(f"{p}: {exc}")
    owner_path: Path | None = None
    owner_doc: dict[str, Any] | None = None
    # Prefer explicit canonical owner; otherwise first JSON containing a binding.
    explicit = as_path(q.get("canonical_owner"))
    if explicit is not None:
        for p, doc in docs:
            if p == explicit:
                owner_path, owner_doc = p, doc
                break
    if owner_doc is None:
        for p, doc in docs:
            candidate, _ = find_physical_binding(doc)
            if candidate is not None:
                owner_path, owner_doc = p, doc
                break
    pb: dict[str, Any] | None = None
    pb_loc: str | None = None
    if owner_doc is not None:
        pb, pb_loc = find_physical_binding(owner_doc)
    if pb is None:
        candidate, loc = find_physical_binding(q)
        if candidate is not None:
            pb, pb_loc = candidate, f"{receipt_path}::{loc}"
    if pb is None:
        errors.append("no F6 physical_binding owner metadata")
        pb = {}
    parts = geometry_parts(pb)
    baseline_xml_path: Path | None = None
    baseline_xml: dict[str, Any] | None = None
    if product_row.get("physical_case_id") == "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE":
        baseline_xml_path = f6_baseline_source_xml_path(q)
        if baseline_xml_path is None:
            errors.append("baseline F6 GenCase source-definition XML pointer missing")
        else:
            try:
                baseline_xml = read_f6_baseline_source_xml(baseline_xml_path)
            except Exception as exc:
                errors.append(f"{baseline_xml_path}: {exc}")
    params = pb.get("parameters", {}) if isinstance(pb.get("parameters"), dict) else {}
    mass_policy = q.get("mass_policy") if isinstance(q.get("mass_policy"), dict) else {}
    body_mass, mass_field = first_value([
        ("request.mass_policy.physical_rigid_mass_kg", mass_policy.get("physical_rigid_mass_kg")),
        ("request.initial_body_mass_semantics.declared_rigid_mass_kg", nested(q, "initial_body_mass_semantics", "declared_rigid_mass_kg")),
        ("owner.physical_binding.parameters.body_mass_kg", params.get("body_mass_kg")),
    ])
    if not finite_number(body_mass):
        body_mass, mass_field = None, None
        errors.append("rigid body mass missing")
    angular, angular_field = first_vec([
        ("request.initial_angular_velocity_rad_s", q.get("initial_angular_velocity_rad_s")),
        ("owner.physical_binding.parameters.initial_angular_velocity_rad_s", params.get("initial_angular_velocity_rad_s")),
    ])
    if angular is None:
        errors.append("initial angular velocity missing")
    # The thin baseline request does not carry these native fields.  Its actual
    # GenCase definition is the authoritative source for the native mass and
    # angular release values, while the request-field absence remains recorded
    # below.  This also supplies the baseline's actual native body geometry.
    if baseline_xml is not None:
        body_mass = baseline_xml["body_mass_kg"]
        mass_field = "casedef.floatings.floating.massbody@value"
        angular = list(baseline_xml["initial_angular_velocity_rad_s"])
        angular_field = "casedef.floatings.floating.angularvelini@x/y/z"
    orient = q.get("initial_orientation_axis_angle") if isinstance(q.get("initial_orientation_axis_angle"), dict) else None
    orient_field = "request.initial_orientation_axis_angle"
    if orient is None and isinstance(params.get("initial_orientation_axis_angle"), dict):
        orient = params["initial_orientation_axis_angle"]
        orient_field = "owner.physical_binding.parameters.initial_orientation_axis_angle"
    yaw = orient.get("angle_deg") if isinstance(orient, dict) else None
    if not finite_number(yaw):
        yaw = None
        errors.append("initial orientation yaw missing")
    refs: list[dict[str, Any]] = []
    refs.append(ref(receipt_path, "request", {
        "initial_angular_velocity_rad_s_present": isinstance(q.get("initial_angular_velocity_rad_s"), list),
        "initial_orientation_axis_angle_present": isinstance(q.get("initial_orientation_axis_angle"), dict),
        "mass_policy_present": isinstance(q.get("mass_policy"), dict),
        "initial_body_mass_semantics_present": isinstance(q.get("initial_body_mass_semantics"), dict),
        "physical_binding_present": isinstance(q.get("physical_binding"), dict),
    }, "native request field presence"))
    if owner_path is not None:
        refs.append(ref(owner_path, pb_loc or "physical_binding", {
            "geometry_family_id": pb.get("geometry_family_id"),
            "geometry": parts,
            "parameters": {"body_mass_kg": params.get("body_mass_kg"), "initial_angular_velocity_rad_s": params.get("initial_angular_velocity_rad_s"), "initial_orientation_axis_angle": params.get("initial_orientation_axis_angle")},
        }, "canonical owner/source geometry"))
    if mass_field:
        mass_path = (
            baseline_xml_path
            if baseline_xml is not None and baseline_xml_path is not None and mass_field.startswith("casedef.")
            else owner_path if mass_field.startswith("owner.") and owner_path is not None else receipt_path
        )
        refs.append(ref(mass_path, mass_field, body_mass, "physical rigid mass"))
    if angular_field:
        angular_path = (
            baseline_xml_path
            if baseline_xml is not None and baseline_xml_path is not None and angular_field.startswith("casedef.")
            else owner_path if angular_field.startswith("owner.") and owner_path is not None else receipt_path
        )
        refs.append(ref(angular_path, angular_field, angular, "initial angular velocity"))
    if orient is not None:
        orient_path = owner_path if orient_field.startswith("owner.") and owner_path is not None else receipt_path
        refs.append(ref(orient_path, orient_field, orient, "initial orientation"))
    # Baseline explicitly retains a separate initial-QA metadata source.  We do
    # not infer missing native request fields from this source; it is only a
    # provenance note for the declared owner parameters.
    qa_refs = nested(product_row, "primary_refs", "initial_qa_or_audit")
    if isinstance(qa_refs, list):
        for item in qa_refs:
            p = as_path(item)
            if p is not None:
                refs.append(ref(p, "$", "JSON metadata source (not native-field backfill)", "initial QA metadata"))
                break
    rigid_body_low = None
    rigid_body_size = None
    paddle_low = None
    paddle_size = None
    g = pb.get("geometry") if isinstance(pb.get("geometry"), dict) else {}
    for key, dst in (("rigid_body", "rigid_body"), ("paddle", "paddle")):
        item = g.get(key) if isinstance(g.get(key), dict) else {}
        if dst == "rigid_body":
            rigid_body_low = vec3(item.get("low_m"))
            rigid_body_size = vec3(item.get("size_m"))
        else:
            paddle_low = vec3(item.get("low_m"))
            paddle_size = vec3(item.get("size_m"))
    if baseline_xml is not None:
        rigid_body_low = list(baseline_xml["rigid_body_low_m"])
        rigid_body_size = list(baseline_xml["rigid_body_size_m"])
        if baseline_xml_path is not None:
            refs.append(ref(
                baseline_xml_path,
                "casedef.geometry.commands.mainlist.drawbox[cmt='Native floatingtype=2 body']",
                {
                    "low_m": rigid_body_low,
                    "size_m": rigid_body_size,
                },
                "native source-definition rigid geometry",
            ))
    normalized = {
        "rigid_body_mass_kg": float(body_mass) if body_mass is not None else None,
        "initial_angular_velocity_rad_s": angular,
        "initial_orientation_yaw_deg": float(yaw) if yaw is not None else None,
        "tank_low_m": parts["tank_low_m"],
        "tank_size_m": parts["tank_size_m"],
        "initial_fluid_low_m": parts["fluid_reservoir_low_m"],
        "initial_fluid_size_m": parts["fluid_reservoir_size_m"],
        "rigid_body_low_m": rigid_body_low,
        "rigid_body_size_m": rigid_body_size,
        "paddle_low_m": paddle_low,
        "paddle_size_m": paddle_size,
    }
    normalized["geometry_family"] = "F6_RECTANGULAR_TANK" if normalized.get("tank_size_m") else None
    presence = {
        "request_initial_angular_velocity_rad_s": isinstance(q.get("initial_angular_velocity_rad_s"), list),
        "request_initial_orientation_axis_angle": isinstance(q.get("initial_orientation_axis_angle"), dict),
        "request_mass_policy_physical_rigid_mass_kg": finite_number(nested(q, "mass_policy", "physical_rigid_mass_kg")),
        "request_initial_body_mass_semantics_declared_rigid_mass_kg": finite_number(nested(q, "initial_body_mass_semantics", "declared_rigid_mass_kg")),
        "request_physical_binding": isinstance(q.get("physical_binding"), dict),
        "owner_physical_binding": pb_loc is not None,
        "source_definition_gencase_xml": baseline_xml_path is not None,
        "source_definition_massbody": bool(baseline_xml and baseline_xml["source_field_presence"]["massbody"]),
        "source_definition_angularvelini": bool(baseline_xml and baseline_xml["source_field_presence"]["angularvelini"]),
        "source_definition_rotation_yaw": bool(baseline_xml and baseline_xml["source_field_presence"]["rotation_yaw"]),
    }
    # A baseline owner commonly carries the angular/yaw declaration while the
    # native request is thin.  Preserve this distinction in the row metadata.
    return normalized, refs, errors, presence


def build(index_path: Path) -> dict[str, Any]:
    index = read_json(index_path)
    if not isinstance(index, dict):
        fail("authoritative index is not an object")
    family_meta = index.get("families", {})
    result_rows: list[dict[str, Any]] = []
    # Product rows are authoritative for native receipt pointers; index rows
    # provide current membership and primary physical IDs.
    product_rows: dict[str, dict[str, dict[str, Any]]] = {}
    for family in ("F1", "F6"):
        product_path = Path(family_meta[family]["product"]["path"])
        product_doc = read_json(product_path)
        key = "cases" if family == "F1" else "rows"
        product_rows[family] = {r["physical_case_id"]: r for r in product_doc[key]}
    # Parent actual bindings for F1 root-283 source-plan rows.
    parent_pb: dict[str, tuple[dict[str, Any], str]] = {}
    f1_receipts: dict[str, tuple[Path, dict[str, Any]]] = {}
    for idx_row in index.get("cases", []):
        if idx_row.get("family_id") != "F1":
            continue
        cid = idx_row["physical_case_id"]
        pr = product_rows["F1"].get(cid)
        if pr is None:
            continue
        rp = native_receipt_path("F1", pr)
        if rp is None:
            continue
        receipt = read_json(rp)
        f1_receipts[cid] = (rp, receipt)
        q = receipt.get("request", {})
        docs, _ = f1_source_docs(q, rp)
        for p, doc in docs:
            pb, _loc = find_physical_binding(doc)
            if pb is not None:
                fam = geometry_family(pb, q)
                if fam:
                    candidate_source = f"{p}::{_loc}"
                    current = parent_pb.get(fam)
                    # Prefer an actual endpoint owner over the older coarse
                    # fallback binding when both are available.  The source
                    # plans mutate that endpoint geometry; they must not
                    # inherit the unrelated fallback drawbox height.
                    if current is None or ("root_actual_fallback_full_native_032" in current[1] and "root_actual_fallback_full_native_032" not in candidate_source):
                        parent_pb[fam] = (pb, candidate_source)
        if isinstance(q.get("geometry"), dict):
            pb = {"geometry": q["geometry"], "geometry_family_id": q.get("geometry_family_id")}
            fam = geometry_family(pb, q)
            if fam and fam not in parent_pb:
                parent_pb[fam] = (pb, f"{rp}::request.geometry")
    missing: list[dict[str, Any]] = []
    for family in ("F1", "F6"):
        for idx_row in index.get("cases", []):
            if idx_row.get("family_id") != family:
                continue
            cid = idx_row["physical_case_id"]
            pr = product_rows[family].get(cid)
            if pr is None:
                missing.append({"family": family, "physical_case_id": cid, "reason": "product row missing"})
                continue
            receipt_path = native_receipt_path(family, pr)
            if receipt_path is None:
                missing.append({"family": family, "physical_case_id": cid, "reason": "native receipt pointer missing"})
                continue
            receipt = read_json(receipt_path)
            q = receipt.get("request")
            if not isinstance(q, dict):
                missing.append({"family": family, "physical_case_id": cid, "reason": "receipt request missing"})
                continue
            pin = pin_receipt(receipt_path, receipt)
            if family == "F1":
                normalized, refs, errors = f1_tuple(pr, q, receipt_path, parent_pb.get("ECC" if "ECC" in cid else "DUAL"))
                presence = None
            else:
                normalized, refs, errors, presence = f6_tuple(pr, q, receipt_path)
            row = {
                "family_id": family,
                "physical_case_id": cid,
                "native_receipt": pin,
                "native_request_field_presence": presence,
                "source_refs": refs,
                "normalized_physical_tuple": normalized,
                "metadata_errors": errors,
                "lifecycle_evidence": {
                    "authoritative_index_row": f"/cases/{index.get('cases', []).index(idx_row)}",
                    "current_membership": {k: idx_row.get(k) for k in ("first8_member", "first24_member", "final48_member")},
                },
            }
            result_rows.append(row)
            if errors or not pin["native_pin_verified"]:
                missing.append({"family": family, "physical_case_id": cid, "reason": errors or ["native pin failed"]})
    groups: dict[str, list[str]] = defaultdict(list)
    for row in result_rows:
        key = json.dumps(row["normalized_physical_tuple"], sort_keys=True, separators=(",", ":"))
        groups[f"tuple:{key}"].append(row["physical_case_id"])
    duplicates = [ids for ids in groups.values() if len(ids) > 1]
    return {
        "schema": "ds02.fresh232.normalized-physical-tuple-audit.v1",
        "generated_by": "F5 metadata-only source worker; GPT-5.6 Luna/max",
        "read_policy": {
            "allowed": ["JSON metadata", "the explicitly named F6 baseline GenCase source-definition XML"],
            "refused": ["BI4", "H5", "CSV", "DAT", "VTK", "XMF", "science arrays", "new jobs"],
            "producer_hashes": "attested values are not recomputed here",
        },
        "authoritative_sources": {
            "index": str(index_path),
            "checkpoint": index.get("authoritative_checkpoint"),
            "families": {f: str(family_meta[f]["product"]["path"]) for f in ("F1", "F6")},
        },
        "scope_note": "F1 normalized tuple uses actual request/physical-binding or its same-family source-plan parent geometry. F6 baseline preserves thin native-request field absence while reporting owner/initial-QA metadata separately. Root1453 reports small unknown-cause fluid omissions across all F6; this audit does not turn them into zero-loss or QN/QE evidence.",
        "summary": {
            "row_count": len(result_rows),
            "F1_count": sum(r["family_id"] == "F1" for r in result_rows),
            "F6_count": sum(r["family_id"] == "F6" for r in result_rows),
            "native_pin_verified_count": sum(bool(r["native_receipt"]["native_pin_verified"]) for r in result_rows),
            "duplicate_normalized_tuple_group_count": len(duplicates),
            "missing_or_ambiguous_count": len(missing),
        },
        "duplicate_normalized_tuple_groups": duplicates,
        "missing_or_ambiguous": missing,
        "rows": result_rows,
    }


def validate_report(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) != 96:
        errors.append(f"expected 96 rows, got {len(rows) if isinstance(rows, list) else type(rows).__name__}")
        return errors
    counts = {f: sum(r.get("family_id") == f for r in rows) for f in ("F1", "F6")}
    if counts != {"F1": 48, "F6": 48}:
        errors.append(f"family counts are {counts}")
    allowed_f1 = {"geometry_family", "fluid_depth_m", "materialized_fluid_drawbox_size_z_m", "initial_fluid_vx_m_s", "fluid_reservoir_low_m", "fluid_reservoir_size_m", "obstacle_or_divider_low_m", "obstacle_or_divider_size_m", "tank_low_m", "tank_size_m"}
    allowed_f6 = {"geometry_family", "rigid_body_mass_kg", "initial_angular_velocity_rad_s", "initial_orientation_yaw_deg", "tank_low_m", "tank_size_m", "initial_fluid_low_m", "initial_fluid_size_m", "rigid_body_low_m", "rigid_body_size_m", "paddle_low_m", "paddle_size_m"}
    for row in rows:
        fam = row.get("family_id")
        tup = row.get("normalized_physical_tuple")
        if not isinstance(tup, dict):
            errors.append(f"{row.get('physical_case_id')}: tuple is not object")
            continue
        allowed = allowed_f1 if fam == "F1" else allowed_f6
        extra = set(tup) - allowed
        if extra:
            errors.append(f"{row.get('physical_case_id')}: tuple has forbidden keys {sorted(extra)}")
        # A normalized tuple must not encode case/path/hash/DP/window identity.
        for key, value in tup.items():
            low = key.lower()
            if "case" in low or "path" in low or "hash" in low or low in {"dp", "window"} or low.endswith("_id") or low.endswith("_hash"):
                errors.append(f"{row.get('physical_case_id')}: identity key leaked into tuple: {key}")
            if isinstance(value, str) and any(token in value.lower() for token in ("/", "sha", "case", "dp", "window")):
                errors.append(f"{row.get('physical_case_id')}: identity text leaked into tuple: {key}")
        pin = row.get("native_receipt", {})
        if not pin.get("native_pin_verified"):
            errors.append(f"{row.get('physical_case_id')}: native pin not verified")
        for key, value in tup.items():
            if key == "materialized_fluid_drawbox_size_z_m" and fam == "F1" and value is None:
                continue
            if key == "geometry_family" and value:
                continue
            if value is None:
                errors.append(f"{row.get('physical_case_id')}: missing tuple value {key}")
            elif isinstance(value, list):
                if not value or not all((isinstance(x, list) and len(x) == 3 and all(finite_number(y) for y in x)) or finite_number(x) for x in value):
                    errors.append(f"{row.get('physical_case_id')}: malformed vector/list {key}")
            elif not finite_number(value) and not isinstance(value, str):
                errors.append(f"{row.get('physical_case_id')}: non-finite tuple value {key}")
        if not isinstance(row.get("source_refs"), list) or not row["source_refs"]:
            errors.append(f"{row.get('physical_case_id')}: no metadata source refs")
        for src in row.get("source_refs", []):
            p = str(src.get("path", ""))
            suffix = Path(p).suffix.lower()
            if suffix not in SOURCE_METADATA_SUFFIXES:
                errors.append(f"{row.get('physical_case_id')}: non-metadata source ref {p}")
            elif suffix == XML_SUFFIX and Path(p).name != F6_BASELINE_SOURCE_XML_NAME:
                errors.append(f"{row.get('physical_case_id')}: unapproved XML source ref {p}")
    if report.get("summary", {}).get("row_count") != 96:
        errors.append("summary row count mismatch")
    if report.get("summary", {}).get("native_pin_verified_count") != 96:
        errors.append("summary native pin count mismatch")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args(argv)
    if args.validate:
        report = read_json(args.validate)
        errors = validate_report(report)
        if errors:
            for error in errors:
                print("ERROR:", error, file=sys.stderr)
            return 1
        print(f"VALID {args.validate}: 96 rows, F1=48, F6=48, native pins=96")
        return 0
    report = build(args.index.resolve())
    errors = validate_report(report)
    if errors:
        for error in errors:
            print("ERROR:", error, file=sys.stderr)
        return 1
    if args.output is None:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        print(f"WROTE {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
