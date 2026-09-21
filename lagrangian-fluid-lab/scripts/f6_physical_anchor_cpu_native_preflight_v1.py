#!/usr/bin/env python3
"""Run one hash-bound F6 CPU GenCase/native preflight.

The preflight consumes exactly one already-reviewed physical-anchor Definition.
It may invoke the CPU GenCase binary once and the native BI4 decoder once.  It
never invokes a solver, CUDA/GPU path, queue, registry, ledger or matrix
submission path.  A lock is written before either binary is called; any later
invocation with the same output directory is rejected as a same-input retry.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd  # noqa: E402
from scripts import f6_physical_anchor_root_review as physical  # noqa: E402


AUTHORIZATION_SCHEMA = "core.f6.physical_anchor.cpu_native_preflight_authorization.v1"
PREFLIGHT_SCHEMA = "core.f6.physical_anchor.cpu_native_preflight.v1"
LOCK_SCHEMA = "core.f6.physical_anchor.cpu_native_preflight_lock.v1"
DEFINITION_ID = physical.IDENTITY
BODY_ID = physical.BODY_ID
CASE_ID = "F6_physical_anchor_cpu_native_preflight_20260921"
AUTHORIZATION_ID = "F6_physical_anchor_cpu_native_preflight_authorization_20260921"
OUTPUT_DIR = LAB_ROOT / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cpu-native-preflight-v1-20260921"
SOURCE_DIR = LAB_ROOT / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-root-review-v1-20260921"
DEFINITION = SOURCE_DIR / f"{DEFINITION_ID}_Def.xml"
CONTRACT = SOURCE_DIR / "definition-contract.json"
SIDECAR = SOURCE_DIR / "body-state-force-torque-sidecar-schema.json"
EVENT = SOURCE_DIR / "event-window-contract.json"
STATIC_PREFLIGHT = SOURCE_DIR / "preflight.json"
PROPOSAL = SOURCE_DIR / "proposal.json"
GENCASE = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
DECODER = LAB_ROOT / "campaigns/l1-resume/artifacts/bi4_dump"
MASS_RELATIVE_ERROR_MAX = 0.05
GEOMETRY_TOLERANCE_M = 1.0e-8


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def resolve_ref(item: dict[str, Any], label: str) -> Path:
    raw = item.get("path")
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label}: path is missing")
    path = Path(raw)
    if not path.is_absolute():
        path = LAB_ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    observed = sha256(path)
    if item.get("sha256") != observed:
        raise ValueError(f"{label}: SHA-256 mismatch")
    if item.get("bytes") is not None and int(item["bytes"]) != path.stat().st_size:
        raise ValueError(f"{label}: byte count mismatch")
    return path


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        display = path.relative_to(LAB_ROOT.resolve()).as_posix()
    except ValueError:
        display = str(path)
    return {"path": display, "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def _static_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = load_json(CONTRACT)
    sidecar = load_json(SIDECAR)
    event = load_json(EVENT)
    static = load_json(STATIC_PREFLIGHT)
    proposal = load_json(PROPOSAL)
    if static.get("status") != "cpu_physical_anchor_preflight_pass" or static.get("gate_passed") is not True:
        raise ValueError("physical-anchor static CPU preflight is not passed")
    if static.get("qualification_claim") != "none" or static.get("qualification_credit") != 0:
        raise ValueError("physical-anchor static preflight has qualification credit")
    if static.get("solver_canary_authorized_in_this_receipt") is not False:
        raise ValueError("physical-anchor static preflight opens solver authorization")
    if proposal.get("qualification_claim") != "none" or proposal.get("qualification_credit") != 0 or proposal.get("T1") is not False:
        raise ValueError("physical-anchor proposal is qualified")
    decision = proposal.get("root_review_decision", {})
    if decision.get("solver_canary_authorized_now") is not False:
        raise ValueError("physical-anchor proposal opens immediate solver authorization")
    return contract, sidecar, event, static, proposal


def build_authorization() -> dict[str, Any]:
    contract, sidecar, event, static, proposal = _static_inputs()
    if contract.get("case_id") != DEFINITION_ID or contract.get("body", {}).get("body_id") != BODY_ID:
        raise ValueError("physical-anchor identity mismatch")
    definition_ref = contract.get("fresh_input", {}).get("definition", {})
    if resolve_ref(definition_ref, "physical-anchor Definition") != DEFINITION.resolve():
        raise ValueError("physical-anchor Definition binding mismatch")
    if contract.get("fresh_input", {}).get("old_assets_reused") is not False:
        raise ValueError("legacy asset reuse is not closed")
    if contract.get("fresh_input", {}).get("old_hdf5_reused") is not False:
        raise ValueError("legacy HDF5 reuse is not closed")
    for path in (DEFINITION, CONTRACT, SIDECAR, EVENT, STATIC_PREFLIGHT, PROPOSAL, GENCASE, DECODER):
        if not path.is_file():
            raise FileNotFoundError(path)
    return {
        "schema": AUTHORIZATION_SCHEMA,
        "authorization_id": AUTHORIZATION_ID,
        "created_at_utc": stamp(),
        "status": "authorized_for_exactly_one_cpu_native_preflight",
        "family": "F6",
        "scope_id": "F6_fluid_rigid_body_physical_anchor_v1",
        "case_id": CASE_ID,
        "definition_id": DEFINITION_ID,
        "body_id": BODY_ID,
        "root_authorized_for_cpu_native_preflight": True,
        "authorization_basis": "F6 physical-anchor root review plus passed static CPU preflight; CPU GenCase/native entry only",
        "single_input": {
            "simulation_input_count": 1,
            "definition": ref(DEFINITION, "single fresh physical-anchor Definition input"),
            "old_xml_bi4_hdf5_reused_as_input": False,
            "trajectory_input": None,
        },
        "read_only_contract_inputs": {
            "definition_contract": ref(CONTRACT, "physical-anchor Definition contract"),
            "sidecar_schema": ref(SIDECAR, "body-state/force/torque sidecar schema"),
            "event_window_contract": ref(EVENT, "physical-anchor event-window contract"),
            "static_preflight": ref(STATIC_PREFLIGHT, "passed static physical-anchor preflight"),
            "proposal": ref(PROPOSAL, "physical-anchor root-review proposal"),
        },
        "cpu_native_entry": {
            "gencase_binary": ref(GENCASE, "pinned CPU GenCase entry"),
            "native_decoder": ref(DECODER, "pinned native BI4 decoder entry"),
            "gencase_invocation_limit": 1,
            "native_decode_invocation_limit": 1,
            "output_interval_s": physical.OUTPUT_INTERVAL_S,
            "event_window_s": [physical.TIME_START_S, physical.TIME_END_S],
        },
        "permissions": {
            "definition_read": True,
            "cpu_gencase": True,
            "native_decode": True,
            "solver_launch": False,
            "gpu_launch": False,
            "job_spec_creation": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
            "qualification_credit": 0,
        },
        "execution_policy": {
            "exactly_one_definition_input": True,
            "exactly_one_cpu_gencase_invocation": True,
            "exactly_one_native_decode_invocation": True,
            "same_input_retry": False,
            "retry_after_gencase_failure": False,
            "retry_after_native_decode_failure": False,
            "solver_or_gpu_product_not_allowed": True,
            "runtime_sidecar_is_contract_only_until_solver": True,
            "event_window_complete_in_this_preflight": False,
        },
        "qualification_claim": "none",
        "qualification_credit": 0,
    }


def _float_attr(node: ET.Element, attr: str) -> float:
    raw = node.get(attr)
    if raw is None:
        raise ValueError(f"missing XML attribute {attr}")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"non-finite XML attribute {attr}")
    return value


def _close_vector(actual: list[float], expected: list[float], tolerance: float = 1.0e-12) -> bool:
    return len(actual) == len(expected) and all(abs(a - b) <= tolerance for a, b in zip(actual, expected))


def validate_definition(contract: dict[str, Any], sidecar: dict[str, Any], event: dict[str, Any], static: dict[str, Any]) -> dict[str, Any]:
    root = ET.parse(DEFINITION).getroot()
    if root.tag != "case":
        raise ValueError("physical Definition root is not <case>")
    xml_text = DEFINITION.read_text(encoding="utf-8")
    forbidden = ("F6_floating_box", "F6_heavy_box_entry", "F6_twin_floaters", ".bi4", ".h5")
    checks: dict[str, bool] = {
        "xml_root_case": True,
        "fresh_xml_no_legacy_input": not any(token in xml_text for token in forbidden),
    }
    gravity_node = root.find("./casedef/constantsdef/gravity")
    gravity = [_float_attr(gravity_node, axis) for axis in ("x", "y", "z")] if gravity_node is not None else []
    checks["gravity_exact"] = _close_vector(gravity, list(physical.GRAVITY))
    geometry_definition = root.find("./casedef/geometry/definition")
    dp = _float_attr(geometry_definition, "dp") if geometry_definition is not None else float("nan")
    checks["dp_exact"] = math.isclose(dp, physical.DP_M, rel_tol=0.0, abs_tol=1.0e-12)
    floating = root.find("./casedef/floatings/floating")
    massbody_node = floating.find("massbody") if floating is not None else None
    density_binding = floating is not None and math.isclose(float(floating.get("rhopbody", "nan")), physical.RHO_BODY, rel_tol=0.0, abs_tol=1.0e-12)
    # The explicit-body revision intentionally omits rhopbody.  Its mass is
    # checked against the immutable contract below; the density-only route
    # remains valid for the earlier form.
    expected_body_mass = float(json.loads(CONTRACT.read_text(encoding="utf-8"))["body"]["mass_kg"])
    mass_binding = massbody_node is not None and math.isclose(float(massbody_node.get("value", "nan")), expected_body_mass, rel_tol=0.0, abs_tol=1.0e-12)
    checks["single_floating_binding"] = bool(floating is not None and floating.get("mkbound") == str(physical.MKBOUND) and (density_binding or mass_binding))
    params = {node.get("key"): node.get("value") for node in root.findall("./execution/parameters/parameter")}
    checks["runtime_cadence"] = params.get("TimeMax") == str(physical.TIME_END_S) and params.get("TimeOut") == str(physical.OUTPUT_INTERVAL_S)

    body = contract["body"]
    fluid = contract["fluid"]
    tank = contract["tank"]
    drawboxes = root.findall("./casedef/geometry/commands/mainlist/drawbox")
    fluid_boxes = []
    body_boxes = []
    for node in drawboxes:
        fill = (node.findtext("boxfill") or "").strip()
        point = node.find("point")
        size = node.find("size")
        if point is None or size is None:
            continue
        value = {
            "fill": fill,
            "point": [_float_attr(point, axis) for axis in "xyz"],
            "size": [_float_attr(size, axis) for axis in "xyz"],
        }
        parent_index = drawboxes.index(node)
        # The writer emits fluid first, tank second, then the mkbound=8 body.
        if parent_index == 0:
            fluid_boxes.append(value)
        if parent_index == 2:
            body_boxes.append(value)
    expected_body_low = body["bbox_low_m"]
    sampling = fluid.get("sampling_contract", {})
    registered_drawbox_size = sampling.get("drawbox_size_m") if isinstance(sampling, dict) else None
    expected_drawbox_size = registered_drawbox_size if registered_drawbox_size is not None else fluid["size_m"]
    checks["fresh_fluid_drawbox"] = bool(
        fluid_boxes
        and _close_vector(fluid_boxes[0]["point"], fluid["low_m"])
        and _close_vector(fluid_boxes[0]["size"], expected_drawbox_size)
    )
    checks["fresh_tank_faces"] = any("bottom" in item["fill"] and "left" in item["fill"] and "right" in item["fill"] for item in ({"fill": (node.findtext("boxfill") or "")} for node in drawboxes))
    checks["fresh_body_drawbox"] = bool(body_boxes and _close_vector(body_boxes[0]["point"], expected_body_low) and _close_vector(body_boxes[0]["size"], body["size_m"]))
    checks["contract_static_pass"] = static.get("gate_passed") is True
    checks["sidecar_schema_binding"] = sidecar.get("schema") == physical.SIDECAR_SCHEMA and sidecar.get("body_id") == BODY_ID
    required_sidecar = {"time_s", "body_position_m", "body_quaternion_xyzw", "linear_velocity_m_s", "angular_velocity_rad_s", "fluid_force_N", "fluid_torque_Nm", "contact_count", "penetration_depth_m", "boundary_contact_count", "open_face_mass_flux_kg_s", "event_status", "valid"}
    checks["sidecar_fields_complete"] = {field.get("name") for field in sidecar.get("required_fields", [])} == required_sidecar
    window = event.get("window", {})
    checks["event_contract_binding"] = bool(
        event.get("schema") == physical.EVENT_SCHEMA
        and event.get("body_id") == BODY_ID
        and event.get("physical_f6_qualification") is False
        and window.get("start_s") == physical.TIME_START_S
        and window.get("end_s") == physical.TIME_END_S
        and window.get("output_interval_s") == physical.OUTPUT_INTERVAL_S
        and window.get("expected_frame_count") == 301
        and event.get("uncensored_required") is True
    )
    if not all(checks.values()):
        raise ValueError(f"physical Definition/native entry contract failed: {checks}")
    return {
        "checks": checks,
        "gravity_m_s2": gravity,
        "dp_m": dp,
        "runtime_parameters": params,
        "drawbox_count": len(drawboxes),
        "fluid_contract": {
            "low_m": fluid["low_m"],
            "size_m": fluid["size_m"],
            "drawbox_size_m": expected_drawbox_size,
            "sampling_contract": sampling,
        },
        "body_contract": {"body_id": BODY_ID, "low_m": expected_body_low, "size_m": body["size_m"]},
        "tank_contract": tank,
        "runtime_sidecar_present": False,
        "event_window_complete": False,
    }


def _group_items(generated_xml: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = ET.parse(generated_xml).getroot()
    fixed: list[dict[str, Any]] = []
    fluids: list[dict[str, Any]] = []
    for node in root.findall(".//particles/*"):
        if node.tag not in {"fixed", "moving", "floating", "fluid"}:
            continue
        value: dict[str, Any] = {"kind": node.tag}
        for key, raw in node.attrib.items():
            try:
                value[key] = int(raw) if key in {"begin", "count", "mk", "mkbound", "mkfluid"} else raw
            except (TypeError, ValueError):
                value[key] = raw
        for child in node:
            if child.tag == "massbody":
                value["massbody_kg"] = float(child.get("value"))
            elif child.tag == "masspart":
                value["masspart_kg"] = float(child.get("value"))
            elif child.tag == "center":
                value["center_m"] = [float(child.get(axis)) for axis in "xyz"]
            elif child.tag == "inertia" and all(child.get(axis) is not None for axis in "xyz"):
                value["inertia_diag_kg_m2"] = [float(child.get(axis)) for axis in "xyz"]
            elif child.tag == "inertiafull":
                rows = child.findall("values")
                value["inertia_matrix_kg_m2"] = [[float(row.get(f"v{i}{j}")) for j in (1, 2, 3)] for i, row in enumerate(rows, 1)]
        (fluids if node.tag == "fluid" else fixed).append(value)
    return fixed, fluids


def _select(ids: np.ndarray, group: dict[str, Any]) -> np.ndarray:
    begin = int(group["begin"])
    count = int(group["count"])
    return (ids >= begin) & (ids < begin + count)


def _run_gencase(output: Path) -> tuple[Path, Path, dict[str, Any]]:
    generated = output / "generated"
    generated.mkdir(parents=True, exist_ok=False)
    prefix = generated / CASE_ID
    log_path = output / "gencase.log"
    command = [str(GENCASE), str(DEFINITION.with_suffix("")), str(prefix), "-save:all"]
    receipt: dict[str, Any] = {
        "command": command,
        "started_at_utc": stamp(),
        "cpu_gencase_invoked": True,
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "matrix_submission": False,
    }
    try:
        with log_path.open("w", encoding="utf-8") as stream:
            process = subprocess.run(command, cwd=output, env=core_cfd.environment(LAB_ROOT), stdout=stream, stderr=subprocess.STDOUT, check=False, timeout=1800)
        receipt["returncode"] = int(process.returncode)
    except subprocess.TimeoutExpired:
        receipt["returncode"] = 124
        receipt["timeout"] = True
    receipt["finished_at_utc"] = stamp()
    xml_path = prefix.with_suffix(".xml")
    bi4_path = prefix.with_suffix(".bi4")
    receipt["generated_xml"] = ref(xml_path, "GenCase generated XML") if xml_path.is_file() else None
    receipt["native_bi4"] = ref(bi4_path, "GenCase native BI4") if bi4_path.is_file() else None
    return xml_path, bi4_path, receipt


def _decode_and_check(generated_xml: Path, bi4: Path, output: Path, contract: dict[str, Any]) -> dict[str, Any]:
    fixed, fluids = _group_items(generated_xml)
    generated_root = ET.parse(generated_xml).getroot()
    metadata_nodes = generated_root.findall(".//particles/*")
    groups_cover_all = bool(metadata_nodes and all(int(item.get("count", -1)) > 0 for item in fluids + fixed))
    generated_checks = {
        "generated_xml_case": generated_root.tag == "case",
        "one_fluid_group": len(fluids) == 1 and int(fluids[0].get("mkfluid", -1)) == 0,
        "one_body_group": sum(int(item.get("mkbound", -1)) == physical.MKBOUND for item in fixed) == 1,
        "generated_groups_nonempty": groups_cover_all,
    }
    if not all(generated_checks.values()):
        return {"checks": generated_checks, "preflight_pass": False, "failure": "generated particle group contract failed", "generated_groups": {"fixed": fixed, "fluid": fluids}}
    decoded_root = output / "decoded" / "native"
    decoded_root.parent.mkdir(parents=True, exist_ok=False)
    native: dict[str, Any] = {"native_decoder_invoked": True}
    try:
        ids, positions, velocities, density, metadata, info, arrays = core_cfd.native_frame(bi4, decoded_root, DECODER)
    except Exception as error:
        native.update({"preflight_pass": False, "failure": f"native decoder failed: {error!r}", "checks": generated_checks})
        return native
    ids = np.asarray(ids)
    positions = np.asarray(positions)
    velocities = np.asarray(velocities)
    density = np.asarray(density)
    fluid_mask = _select(ids, fluids[0])
    body_groups = [item for item in fixed if int(item.get("mkbound", -1)) == physical.MKBOUND]
    body_mask = np.zeros(len(ids), dtype=bool)
    for item in body_groups:
        body_mask |= _select(ids, item)
    tank_mask = ~(fluid_mask | body_mask)
    body = contract["body"]
    fluid = contract["fluid"]
    tank = contract["tank"]
    fluid_position = positions[fluid_mask]
    body_position = positions[body_mask]
    fluid_velocity = velocities[fluid_mask]
    body_velocity = velocities[body_mask]
    fluid_low = np.asarray(fluid["low_m"], dtype=float)
    fluid_high = fluid_low + np.asarray(fluid["size_m"], dtype=float)
    body_low = np.asarray(body["bbox_low_m"], dtype=float)
    body_high = np.asarray(body["bbox_high_m"], dtype=float)
    tank_low = np.asarray(tank["low_m"], dtype=float)
    tank_high = tank_low + np.asarray(tank["size_m"], dtype=float)
    finite = bool(np.isfinite(ids).all() and np.isfinite(positions).all() and np.isfinite(velocities).all() and np.isfinite(density).all())
    metadata_fluid = int(round(float(metadata.get("CaseNfluid", "nan"))))
    native_dp = float(metadata.get("Dp", "nan"))
    mass_particle = float(metadata.get("MassFluid", "nan"))
    native_fluid_mass = mass_particle * int(fluid_mask.sum())
    continuum_fluid_mass = float(np.prod(fluid["size_m"])) * float(fluid["density_kg_m3"])
    mass_error = native_fluid_mass / continuum_fluid_mass - 1.0
    boundary_normals_path = Path(arrays) / "BoundNor.bin"
    boundary_normals = np.fromfile(boundary_normals_path, np.float32).reshape(-1, 3) if boundary_normals_path.is_file() else np.empty((0, 3), dtype=np.float32)
    expected_boundary = int(sum(int(item.get("count", 0)) for item in fixed if item not in body_groups))
    body_contract = contract["body"]
    generated_body = body_groups[0] if body_groups else {}
    generated_mass = float(generated_body.get("massbody_kg", "nan"))
    expected_mass = float(body_contract["mass_kg"])
    mass_relative_error = generated_mass / expected_mass - 1.0 if expected_mass else float("inf")
    generated_center = generated_body.get("center_m", [])
    center_error = max((abs(float(a) - float(b)) for a, b in zip(generated_center, body_contract["com_m"])), default=float("inf"))
    expected_inertia = np.asarray(body_contract["inertia_about_com_kg_m2"], dtype=float)
    if "inertia_matrix_kg_m2" in generated_body:
        generated_inertia = np.asarray(generated_body["inertia_matrix_kg_m2"], dtype=float)
    elif "inertia_diag_kg_m2" in generated_body:
        generated_inertia = np.diag(np.asarray(generated_body["inertia_diag_kg_m2"], dtype=float))
    else:
        generated_inertia = np.full((3, 3), float("nan"))
    inertia_relative_error = float(np.max(np.abs(generated_inertia - expected_inertia) / np.maximum(np.abs(expected_inertia), 1.0e-12)))
    checks = {
        **generated_checks,
        "native_ids_unique": len(np.unique(ids)) == len(ids),
        "native_arrays_finite": finite,
        "native_fluid_count": metadata_fluid == int(fluid_mask.sum()) == int(fluids[0]["count"]),
        "native_body_count": int(body_mask.sum()) == int(sum(int(item["count"]) for item in body_groups)),
        "native_dp_matches": math.isclose(native_dp, physical.DP_M, rel_tol=0.0, abs_tol=1.0e-12),
        "fluid_inside_declared_box": bool(len(fluid_position) and np.all(fluid_position >= fluid_low - GEOMETRY_TOLERANCE_M) and np.all(fluid_position <= fluid_high + GEOMETRY_TOLERANCE_M)),
        "body_inside_declared_box": bool(len(body_position) and np.all(body_position >= body_low - physical.DP_M - GEOMETRY_TOLERANCE_M) and np.all(body_position <= body_high + physical.DP_M + GEOMETRY_TOLERANCE_M)),
        "all_particles_inside_tank": bool(len(positions) and np.all(positions >= tank_low - physical.DP_M - GEOMETRY_TOLERANCE_M) and np.all(positions <= tank_high + physical.DP_M + GEOMETRY_TOLERANCE_M)),
        "native_fluid_initial_zero_velocity": bool(len(fluid_velocity) and np.max(np.linalg.norm(fluid_velocity, axis=1)) <= 1.0e-12),
        "native_body_initial_zero_velocity": bool(len(body_velocity) and np.max(np.linalg.norm(body_velocity, axis=1)) <= 1.0e-12),
        "mass_relative_gate": math.isfinite(mass_error) and abs(mass_error) <= MASS_RELATIVE_ERROR_MAX,
        "no_solver_product": not any(path.name in {"trajectory.h5", "result.json", "audit.json"} for path in output.rglob("*")),
        "boundnor_finite_if_present": bool(len(boundary_normals) == 0 or np.isfinite(boundary_normals).all()),
        "boundnor_count_if_present": bool(len(boundary_normals) == 0 or len(boundary_normals) == expected_boundary),
        "generated_body_mass_matches_contract": math.isfinite(mass_relative_error) and abs(mass_relative_error) <= 0.01,
        "generated_body_center_matches_contract": math.isfinite(center_error) and center_error <= 0.5 * physical.DP_M,
        "generated_body_inertia_matches_contract": math.isfinite(inertia_relative_error) and inertia_relative_error <= 0.01,
    }
    return {
        "checks": checks,
        "preflight_pass": bool(all(checks.values())),
        "generated_groups": {"fixed": fixed, "fluid": fluids},
        "native": {
            "total_particles": int(len(ids)),
            "fluid_particles": int(fluid_mask.sum()),
            "body_particles": int(body_mask.sum()),
            "boundary_particles": int(tank_mask.sum()),
            "metadata_case_nfluid": metadata_fluid,
            "native_dp_m": native_dp,
            "mass_per_particle_kg": mass_particle,
            "native_fluid_mass_kg": native_fluid_mass,
            "continuum_fluid_mass_kg": continuum_fluid_mass,
            "mass_error_relative": mass_error,
            "max_fluid_initial_speed_m_s": float(np.max(np.linalg.norm(fluid_velocity, axis=1))) if len(fluid_velocity) else None,
            "max_body_initial_speed_m_s": float(np.max(np.linalg.norm(body_velocity, axis=1))) if len(body_velocity) else None,
            "metadata": {str(key): str(value) for key, value in metadata.items()},
            "info": {str(key): str(value) for key, value in info.items()},
        },
        "boundnor": {
            "path": str(boundary_normals_path.resolve()),
            "sha256": sha256(boundary_normals_path) if boundary_normals_path.is_file() else None,
            "count": int(len(boundary_normals)),
            "expected_if_present": expected_boundary,
        },
        "generated_body": {
            "massbody_kg": generated_mass,
            "massbody_relative_error": mass_relative_error,
            "center_m": generated_center,
            "center_max_abs_error_m": center_error,
            "inertia_matrix_kg_m2": generated_inertia.tolist(),
            "inertia_max_relative_error": inertia_relative_error,
        },
        "decoded_xml": ref(Path(str(decoded_root) + ".xml"), "native decoder XML") if Path(str(decoded_root) + ".xml").is_file() else None,
        "trajectory_or_solver_checked": False,
    }


def _base_receipt(auth: dict[str, Any], output: Path) -> dict[str, Any]:
    return {
        "schema": PREFLIGHT_SCHEMA,
        "receipt_id": "F6_physical_anchor_cpu_native_preflight_receipt_20260921",
        "created_at_utc": stamp(),
        "status": "cpu_native_preflight_pending",
        "family": "F6",
        "scope_id": "F6_fluid_rigid_body_physical_anchor_v1",
        "case_id": CASE_ID,
        "definition_id": DEFINITION_ID,
        "body_id": BODY_ID,
        "authorization": ref(output / "authorization.json", "root authorization for exactly one CPU/native preflight"),
        "definition": ref(DEFINITION, "single fresh physical-anchor Definition"),
        "definition_contract": ref(CONTRACT, "physical-anchor Definition contract"),
        "sidecar_schema": ref(SIDECAR, "body-state/force/torque sidecar schema"),
        "event_window_contract": ref(EVENT, "physical-anchor event-window contract"),
        "root_review_proposal": ref(PROPOSAL, "physical-anchor root-review proposal"),
        "static_preflight": ref(STATIC_PREFLIGHT, "passed static physical-anchor preflight"),
        "single_input": auth["single_input"],
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "event_window_complete": False,
        "runtime_sidecar_present": False,
        "execution_controls": {
            "definition_read": True,
            "cpu_gencase_invoked": False,
            "cpu_native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "job_created": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
            "qualification_credit": 0,
        },
        "same_input_retry": False,
        "failure_policy": "Any failure is retained in this receipt; the same Definition hash cannot be retried by this contract.",
    }


def run(output: Path = OUTPUT_DIR) -> dict[str, Any]:
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"one-shot output is not fresh; refusing same-input retry: {output}")
    auth = build_authorization()
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "authorization.json", auth)
    lock = {
        "schema": LOCK_SCHEMA,
        "created_at_utc": stamp(),
        "authorization_id": AUTHORIZATION_ID,
        "authorization_sha256": sha256(output / "authorization.json"),
        "definition_sha256": sha256(DEFINITION),
        "gencase_invocation_budget": 1,
        "native_decode_invocation_budget": 1,
        "same_input_retry": False,
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "matrix_submission": False,
    }
    write_json(output / "one-shot-lock.json", lock)
    contract, sidecar, event, static, _proposal = _static_inputs()
    receipt = _base_receipt(auth, output)
    receipt["one_shot_lock"] = ref(output / "one-shot-lock.json", "pre-execution same-input retry lock")
    try:
        receipt["definition_audit"] = validate_definition(contract, sidecar, event, static)
        generated_xml, bi4, gencase = _run_gencase(output)
        receipt["gencase"] = gencase
        receipt["execution_controls"]["cpu_gencase_invoked"] = True
        if gencase.get("returncode") != 0 or not generated_xml.is_file() or not bi4.is_file():
            receipt["status"] = "cpu_gencase_failed_hard"
            receipt["failure"] = "GenCase did not produce both generated XML and BI4"
        else:
            native = _decode_and_check(generated_xml, bi4, output, contract)
            receipt.update(native)
            receipt["execution_controls"]["cpu_native_decode_invoked"] = True
            receipt["gencase_generated_xml"] = ref(generated_xml, "GenCase generated XML")
            receipt["native_bi4"] = ref(bi4, "GenCase native BI4")
            receipt["status"] = "cpu_native_preflight_pass_exact_one" if native.get("preflight_pass") else "cpu_native_preflight_failed_hard"
    except Exception as error:
        receipt["status"] = "cpu_native_preflight_failed_hard"
        receipt["failure"] = repr(error)
    receipt["finished_at_utc"] = stamp()
    write_json(output / "preflight.json", receipt)
    return receipt


def verify_receipt(path: Path = OUTPUT_DIR / "preflight.json") -> dict[str, Any]:
    receipt = load_json(path)
    if receipt.get("schema") != PREFLIGHT_SCHEMA:
        raise ValueError("unexpected F6 CPU/native preflight schema")
    if receipt.get("qualification_claim") != "none" or receipt.get("qualification_credit") != 0:
        raise ValueError("F6 CPU/native preflight carries qualification credit")
    if receipt.get("same_input_retry") is not False:
        raise ValueError("same-input retry policy is open")
    controls = receipt.get("execution_controls", {})
    for key in ("solver_invoked", "gpu_invoked", "job_created"):
        if controls.get(key) is not False:
            raise ValueError(f"forbidden execution control opened: {key}")
    for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "qualification_credit"):
        if controls.get(key) != 0:
            raise ValueError(f"forbidden mutation opened: {key}")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    try:
        receipt = run(args.output)
    except Exception as error:
        print(json.dumps({"status": "preflight_not_started", "error": str(error)}, ensure_ascii=False))
        return 2
    receipt_path = Path(args.output).resolve() / "preflight.json"
    verify_receipt(receipt_path)
    print(json.dumps({"status": receipt["status"], "preflight_pass": receipt.get("preflight_pass", False), "output": str(receipt_path)}, ensure_ascii=False))
    return 0 if receipt.get("status") == "cpu_native_preflight_pass_exact_one" else 1


if __name__ == "__main__":
    raise SystemExit(main())
