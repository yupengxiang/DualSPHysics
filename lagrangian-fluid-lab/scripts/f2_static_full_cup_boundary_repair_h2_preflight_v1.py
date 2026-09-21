#!/usr/bin/env python3
"""Run the single authorized F2 H2 CPU/GenCase/native canary.

This is deliberately a one-shot input preflight.  It consumes the fresh
Definition written by ``f2_static_full_cup_boundary_repair_h2_definition_v1``
and the H2 root review, runs GenCase exactly once, and decodes the resulting
BI4 with the native decoder.  It has no solver, CUDA, queue, ledger, registry,
or matrix submission path.  A lock receipt is written before GenCase so a
second invocation cannot silently retry the same input.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd


SCHEMA = "core.f2.static_full_cup.boundary_repair_h2.cpu_native_preflight.v1"
REVIEW_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-root-review-v1.json"
)
PROPOSAL_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-proposal-v1.json"
)
DEFAULT_INPUT = Path(
    "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1/input"
)
DEFAULT_OUTPUT = Path(
    "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1"
)
GENCASE_RELATIVE = Path("vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
DECODER_RELATIVE = Path("campaigns/l1-resume/artifacts/bi4_dump")
REPAIR_ID = "F2_static_full_cup_initial_support_clearance_h2_v1"
CASE_ID = "CORE_F2_static_full_cup_volume_supportclearance_h2_q0p00000000_dp0p010000000000_canary"
REVISION_ID = "F2_static_full_cup_support_clearance_h2_v1"
Q = 0.0
DP = 0.01
HDP = 1.3
CLEARANCE = 3.0 * HDP * DP
VOLUME_M3 = 0.022950
RHO0 = 1000.0
CUP_LOW = np.asarray([0.0, -0.15, 0.65], dtype=float)
CUP_SIZE = np.asarray([0.425, 0.30, 0.45], dtype=float)
CUP_HIGH = CUP_LOW + CUP_SIZE
MASS_ERROR_GATE = 0.03
GEOMETRY_TOLERANCE_M = 1e-10


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _path(value: str | Path, lab: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = lab / path
    return path.resolve()


def _ref(path: Path, role: str, lab: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        relative = path.relative_to(lab.resolve()).as_posix()
    except ValueError:
        relative = None
    return {"path": str(path), "relative_to_lab": relative, "sha256": digest(path),
            "bytes": path.stat().st_size, "role": role}


def _writer_path(receipt: dict[str, Any], key: str, lab: Path) -> Path:
    value = receipt.get(key)
    if isinstance(value, dict):
        value = value.get("path") or value.get("absolute_path") or value.get("relative_to_lab")
    if not isinstance(value, str):
        raise ValueError(f"writer receipt has no {key} path")
    return _path(value, lab)


def _writer_receipt(input_dir: Path, lab: Path) -> tuple[dict[str, Any], Path]:
    candidates = [input_dir / "writer-receipt.json", input_dir / "definition-writer-receipt.json"]
    for path in candidates:
        if path.is_file():
            return load(path), path
    raise FileNotFoundError("fresh H2 writer receipt is missing")


def _assert_review(lab: Path) -> dict[str, Any]:
    review_path = lab / REVIEW_RELATIVE
    proposal_path = lab / PROPOSAL_RELATIVE
    review = load(review_path)
    if review.get("status") != "approved_for_one_fresh_cpu_native_preflight":
        raise ValueError("H2 root review does not authorize this preflight")
    if review.get("repair_id") != REPAIR_ID:
        raise ValueError("H2 root review repair identity mismatch")
    proposal_ref = review.get("proposal", {})
    if proposal_ref.get("sha256") != digest(proposal_path):
        raise ValueError("H2 proposal hash no longer matches the root review")
    if not review.get("decision", {}).get("fresh_definition_write_allowed"):
        raise ValueError("fresh Definition write is not authorized")
    if not review.get("decision", {}).get("cpu_gencase_allowed"):
        raise ValueError("CPU GenCase is not authorized")
    if not review.get("decision", {}).get("native_decode_allowed"):
        raise ValueError("native decode is not authorized")
    decision = review.get("decision", {})
    for key in ("solver_allowed", "gpu_allowed", "job_spec_creation_allowed", "matrix_submission"):
        if decision.get(key) is not False:
            raise ValueError(f"root review opens forbidden action: {key}")
    if any(decision.get(key, 0) != 0 for key in ("queue_mutation_allowed", "ledger_mutation_allowed", "registry_mutation_allowed", "qualification_credit")):
        raise ValueError("root review opens a central mutation or qualification credit")
    identity = review.get("input_identity", {})
    if identity.get("case_id") != CASE_ID or identity.get("revision_id") != REVISION_ID:
        raise ValueError("root review canary identity mismatch")
    return {"path": review_path, "payload": review}


def _parameter(root: ET.Element, key: str) -> str:
    node = root.find(f".//execution/parameters/parameter[@key='{key}']")
    if node is None or node.get("value") is None:
        raise ValueError(f"missing execution parameter {key}")
    return str(node.get("value"))


def _float_attr(node: ET.Element, attr: str) -> float:
    value = node.get(attr)
    if value is None:
        raise ValueError(f"missing XML attribute {attr}")
    return float(value)


def _group_items(generated_xml: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = ET.parse(generated_xml).getroot()
    fixed: list[dict[str, Any]] = []
    fluids: list[dict[str, Any]] = []
    for node in root.findall(".//particles/*"):
        if node.tag not in {"fixed", "moving", "fluid"}:
            continue
        value: dict[str, Any] = {"kind": node.tag}
        for key, raw in node.attrib.items():
            try:
                value[key] = int(raw) if key in {"begin", "count", "mk", "mkbound", "mkfluid"} else raw
            except ValueError:
                value[key] = raw
        (fluids if node.tag == "fluid" else fixed).append(value)
    return fixed, fluids


def _select(ids: np.ndarray, group: dict[str, Any]) -> np.ndarray:
    begin = int(group["begin"])
    count = int(group["count"])
    return (ids >= begin) & (ids < begin + count)


def _validate_definition(definition: Path, motion: Path, receipt: dict[str, Any], lab: Path) -> dict[str, Any]:
    tree = ET.parse(definition)
    root = tree.getroot()
    if root.tag != "case":
        raise ValueError("fresh Definition root is not <case>")
    values = {key: _parameter(root, key) for key in ("Boundary", "SlipMode", "SavePosDouble", "TimeMax", "TimeOut", "PartsOutMax")}
    fresh_identity = receipt.get("fresh_identity", {})
    checks: dict[str, bool] = {
        "case_id_identity": receipt.get("case_id") == CASE_ID,
        "revision_identity": receipt.get("revision_id") == REVISION_ID,
        "fresh_identity_closed": fresh_identity.get("old_definition_reused") is False and fresh_identity.get("old_trajectory_reused") is False,
        "boundary_is_h1_mdbc": values["Boundary"] == "2" and values["SlipMode"] == "1",
        "double_positions": values["SavePosDouble"] == "2",
        "registered_window": math.isclose(float(values["TimeMax"]), 0.6, abs_tol=1e-12) and math.isclose(float(values["TimeOut"]), 0.02, abs_tol=1e-12),
        "single_parts_output": values["PartsOutMax"] == "1",
        "motion_exists": motion.is_file(),
        "motion_name_matches": motion.name in {str(x.get("name")) for x in root.findall(".//motion//file")},
    }
    commands = root.find(".//geometry/commands")
    main = root.find(".//geometry/commands/mainlist")
    normals = root.find(".//casedef/normals")
    geometry_def = root.find(".//geometry/definition")
    checks["normal_geometry_list"] = commands is not None and commands.find("list[@name='GeometryForNormals']") is not None
    checks["normal_geometry_runlist"] = main is not None and main.find("runlist[@name='GeometryForNormals']") is not None
    checks["explicit_normals"] = normals is not None and normals.get("active") == "true" and normals.find(".//geometryfile") is not None
    checks["dp_matches"] = geometry_def is not None and math.isclose(float(geometry_def.get("dp", "nan")), DP, abs_tol=1e-12)
    fluid_nodes = [] if main is None else list(main)
    fluid_pairs = []
    for index, node in enumerate(fluid_nodes):
        if node.tag == "setmkfluid" and index + 1 < len(fluid_nodes) and fluid_nodes[index + 1].tag == "drawbox":
            fluid_pairs.append((node, fluid_nodes[index + 1]))
    checks["one_fluid_source"] = len(fluid_pairs) == 1 and fluid_pairs[0][0].get("mk") == "0"
    if not all(checks.values()):
        raise ValueError(f"fresh Definition contract failed: {checks}")
    _, drawbox = fluid_pairs[0]
    point = drawbox.find("point")
    size = drawbox.find("size")
    if point is None or size is None:
        raise ValueError("fresh fluid drawbox has no point/size")
    actual_point = [_float_attr(point, axis) for axis in "xyz"]
    actual_size = [_float_attr(size, axis) for axis in "xyz"]
    sampling = receipt.get("sampling", {})
    expected_point = np.asarray(sampling.get("first_center_m", []), dtype=float)
    expected_size = np.asarray(sampling.get("draw_size_m", []), dtype=float)
    if expected_point.shape != (3,) or expected_size.shape != (3,):
        raise ValueError("writer receipt has malformed native sampling")
    checks["drawbox_matches_writer"] = bool(np.allclose(actual_point, expected_point, rtol=0.0, atol=1e-12) and np.allclose(actual_size, expected_size, rtol=0.0, atol=1e-12))
    if not checks["drawbox_matches_writer"]:
        raise ValueError("fresh Definition drawbox differs from writer receipt")
    return {"checks": checks, "parameters": values, "fluid_point_m": actual_point, "fluid_draw_size_m": actual_size}


def _continuous_contract(receipt: dict[str, Any]) -> dict[str, Any]:
    fluid = receipt.get("continuous_fluid", {})
    low = np.asarray(fluid.get("low_m", []), dtype=float)
    size = np.asarray(fluid.get("size_m", []), dtype=float)
    if low.shape != (3,) or size.shape != (3,):
        raise ValueError("writer receipt has malformed continuous fluid box")
    clearance = float(fluid.get("clearance_m", float("nan")))
    volume = float(fluid.get("volume_m3", float("nan")))
    checks = {
        "dp": math.isclose(float(fluid.get("dp_m", float("nan"))), DP, abs_tol=1e-12),
        "q": math.isclose(float(fluid.get("q", float("nan"))), Q, abs_tol=1e-12),
        "hdp": math.isclose(float(fluid.get("hdp", float("nan"))), HDP, abs_tol=1e-12),
        "clearance_rule": math.isclose(clearance, CLEARANCE, rel_tol=0.0, abs_tol=1e-12),
        "volume": math.isclose(volume, VOLUME_M3, rel_tol=0.0, abs_tol=1e-12),
        "side_clearance_geometry": bool(np.allclose(low[:2], CUP_LOW[:2] + clearance, rtol=0.0, atol=1e-12) and np.allclose(size[:2], CUP_SIZE[:2] - 2.0 * clearance, rtol=0.0, atol=1e-12)),
        "bottom_clearance_geometry": math.isclose(float(low[2]), float(CUP_LOW[2] + clearance), rel_tol=0.0, abs_tol=1e-12),
        "fits_cup": bool(np.all(low >= CUP_LOW - 1e-12) and np.all(low + size <= CUP_HIGH + 1e-12)),
        "volume_matches": math.isclose(float(np.prod(size)), volume, rel_tol=0.0, abs_tol=2e-12),
    }
    if not all(checks.values()):
        raise ValueError(f"continuous H2 support-clearance contract failed: {checks}")
    return {"low_m": low.tolist(), "size_m": size.tolist(), "clearance_m": clearance,
            "volume_m3": volume, "checks": checks}


def _run_gencase(*, lab: Path, definition: Path, output: Path) -> tuple[Path, Path, dict[str, Any]]:
    generated = output / "generated"
    generated.mkdir(parents=True, exist_ok=False)
    prefix = generated / CASE_ID
    log_path = output / "gencase.log"
    command = [str(lab / GENCASE_RELATIVE), str(definition.with_suffix("")), str(prefix), "-save:all"]
    started = stamp()
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.run(command, cwd=output, env=core_cfd.environment(lab), stdout=log,
                                     stderr=subprocess.STDOUT, timeout=1800, check=False)
        returncode = int(process.returncode)
    except subprocess.TimeoutExpired:
        returncode = 124
    receipt = {"started_at_utc": started, "finished_at_utc": stamp(), "command": command,
               "returncode": returncode, "solver_invoked": False, "gpu_invoked": False,
               "queue_mutated": False, "ledger_mutated": False, "registry_mutated": False}
    if returncode != 0:
        return prefix.with_suffix(".xml"), prefix.with_suffix(".bi4"), receipt
    xml_path, bi4_path = prefix.with_suffix(".xml"), prefix.with_suffix(".bi4")
    if not xml_path.is_file() or not bi4_path.is_file():
        receipt["returncode"] = 125
    return xml_path, bi4_path, receipt


def _decode_and_check(*, lab: Path, generated_xml: Path, bi4: Path, output: Path,
                      sampling: dict[str, Any], continuous: dict[str, Any],
                      use_existing_decode: bool = False) -> dict[str, Any]:
    fixed, fluids = _group_items(generated_xml)
    expected_count = int(sampling["particle_count"])
    generated_checks = {
        "single_fluid_group": len(fluids) == 1 and int(fluids[0].get("mkfluid", -1)) == 0,
        "generated_fluid_count": len(fluids) == 1 and int(fluids[0].get("count", -1)) == expected_count,
    }
    if not all(generated_checks.values()):
        return {"checks": generated_checks, "preflight_pass": False, "failure": "generated fluid group mismatch"}
    decode_root = output / "decoded"
    if use_existing_decode:
        native_root = decode_root / "native"
        xml_path = Path(str(native_root) + ".xml")
        if not xml_path.is_file():
            raise FileNotFoundError(f"existing native decode XML is missing: {xml_path}")
        root = ET.parse(xml_path).getroot()
        parent = root.find("item")
        node = parent.find("item") if parent is not None else None
        if parent is None or node is None or node.get("name") is None:
            raise ValueError("existing native decode XML is malformed")
        metadata = {element.get("name"): element.get("v") for element in parent if element.tag != "item"}
        info = {element.get("name"): element.get("v") for element in node if element.tag != "item"}
        arrays = native_root / node.get("name")
        ids_raw = np.fromfile(arrays / "Idp.bin", np.uint32)
        order = np.argsort(ids_raw)
        pos_file = arrays / "Posd.bin" if (arrays / "Posd.bin").is_file() else arrays / "Pos.bin"
        ids = ids_raw[order]
        positions_raw = np.fromfile(pos_file, np.float64 if pos_file.name == "Posd.bin" else np.float32).reshape(-1, 3)
        positions = positions_raw[order]
        velocities_raw = np.fromfile(arrays / "Vel.bin", np.float32).reshape(-1, 3)
        velocities = velocities_raw[order]
        density_raw = np.fromfile(arrays / "Rhop.bin", np.float32)
        density = density_raw[order]
    else:
        ids, positions, velocities, density, metadata, info, arrays = core_cfd.native_frame(
            bi4, decode_root / "native", lab / DECODER_RELATIVE
        )
    ids = np.asarray(ids)
    positions = np.asarray(positions)
    velocities = np.asarray(velocities)
    density = np.asarray(density)
    fluid_mask = _select(ids, fluids[0])
    cup_groups = [item for item in fixed if int(item.get("mkbound", -1)) == 0]
    cup_mask = np.zeros(len(ids), dtype=bool)
    for group in cup_groups:
        cup_mask |= _select(ids, group)
    if not fluid_mask.any() or not cup_mask.any():
        raise ValueError("native decode has no fluid or mkbound=0 cup particles")
    fluid_positions = positions[fluid_mask]
    fluid_velocities = velocities[fluid_mask]
    finite = bool(np.isfinite(ids).all() and np.isfinite(positions).all() and np.isfinite(velocities).all() and np.isfinite(density).all())
    zero_velocity = bool(np.max(np.abs(fluid_velocities), initial=0.0) <= 1e-12)
    inside = np.all((fluid_positions >= CUP_LOW - GEOMETRY_TOLERANCE_M) & (fluid_positions <= CUP_HIGH + GEOMETRY_TOLERANCE_M), axis=1)
    distances_to_closed = np.column_stack((fluid_positions[:, 0] - CUP_LOW[0], CUP_HIGH[0] - fluid_positions[:, 0],
                                            fluid_positions[:, 1] - CUP_LOW[1], CUP_HIGH[1] - fluid_positions[:, 1],
                                            fluid_positions[:, 2] - CUP_LOW[2]))
    min_clearance = float(np.min(distances_to_closed))
    no_endpoint = bool(np.sum(np.abs(distances_to_closed) <= GEOMETRY_TOLERANCE_M) == 0)
    support_clearance = bool(min_clearance >= CLEARANCE - 1e-8)
    metadata_fluid = int(round(float(metadata["CaseNfluid"])))
    native_dp = float(metadata["Dp"])
    mass_per_particle = float(metadata["MassFluid"])
    native_mass = mass_per_particle * int(fluid_positions.shape[0])
    mass_error = float(native_mass / (VOLUME_M3 * RHO0) - 1.0)
    normals_path = Path(arrays) / "BoundNor.bin"
    normals = np.fromfile(normals_path, dtype=np.float32).reshape(-1, 3) if normals_path.is_file() else np.empty((0, 3), dtype=np.float32)
    boundary_count = sum(int(group.get("count", 0)) for group in fixed)
    normals_ok = bool(normals_path.is_file() and len(normals) == boundary_count and len(normals) > 0 and np.isfinite(normals).all() and np.linalg.norm(normals, axis=1).min() > 0.0)
    checks = {
        **generated_checks,
        "native_fluid_count": metadata_fluid == expected_count == int(fluid_positions.shape[0]),
        "native_ids_unique": len(np.unique(ids)) == len(ids),
        "native_arrays_finite": finite,
        "native_initial_zero_velocity": zero_velocity,
        "native_dp_matches": math.isclose(native_dp, DP, rel_tol=0.0, abs_tol=1e-12),
        "fluid_inside_cup": bool(inside.all()),
        "support_clearance": support_clearance,
        "no_initial_endpoint": no_endpoint,
        "zero_boundnor": normals_ok,
        "mass_relative_gate": abs(mass_error) <= MASS_ERROR_GATE,
        "no_extra_fluid_group": len(fluids) == 1,
    }
    return {
        "checks": checks, "preflight_pass": bool(all(checks.values())),
        "native": {"total_particles": int(len(ids)), "fluid_particles": int(fluid_positions.shape[0]),
                    "metadata_case_nfluid": metadata_fluid, "boundary_particles": int(boundary_count),
                    "native_dp_m": native_dp, "mass_per_particle_kg": mass_per_particle,
                    "native_mass_kg": native_mass, "continuum_mass_kg": VOLUME_M3 * RHO0,
                    "mass_error_relative": mass_error, "minimum_closed_face_clearance_m": min_clearance,
                    "zero_boundnor_count": int(np.sum(np.linalg.norm(normals, axis=1) <= 1e-10)) if len(normals) else None,
                    "maximum_initial_speed_m_s": float(np.linalg.norm(fluid_velocities, axis=1).max(initial=0.0)),
                    "native_metadata": {str(k): str(v) for k, v in metadata.items()}},
        "generated_groups": {"fixed": fixed, "fluid": fluids},
        "boundnor": {"path": str(normals_path.resolve()), "sha256": digest(normals_path) if normals_path.is_file() else None,
                     "count": int(len(normals)), "expected_count": int(boundary_count)},
        "trajectory_or_solver_checked": False,
    }


def run(*, lab: Path, input_dir: Path, output: Path) -> dict[str, Any]:
    lab, input_dir, output = (Path(x).resolve() for x in (lab, input_dir, output))
    if output.exists():
        # The fresh writer deliberately keeps its input pair below
        # ``output/input``.  That provenance directory is allowed; every
        # other child denotes an already-started one-shot attempt.
        existing = [path for path in output.iterdir() if path.name != "input"]
        if existing:
            raise RuntimeError(f"one-shot H2 output is not empty; refusing retry: {output}")
    output.mkdir(parents=True, exist_ok=True)
    review_ref = _assert_review(lab)
    writer, writer_path = _writer_receipt(input_dir, lab)
    definition = _writer_path(writer, "definition", lab)
    motion = _writer_path(writer, "motion", lab)
    for path in (definition, motion):
        if not path.is_file():
            raise FileNotFoundError(path)
    if definition.parent.resolve() != input_dir.resolve():
        raise ValueError("fresh Definition is outside the declared H2 input directory")
    lock = output / "one-shot-lock.json"
    if lock.exists():
        raise RuntimeError("one-shot lock already exists; no same-input retry")
    write_json(lock, {"schema": SCHEMA + ".lock", "created_at_utc": stamp(), "case_id": CASE_ID,
                      "repair_id": REPAIR_ID, "root_review_sha256": digest(review_ref["path"]),
                      "writer_receipt_sha256": digest(writer_path), "solver_allowed": False, "gpu_allowed": False})
    definition_audit = _validate_definition(definition, motion, writer, lab)
    continuous = _continuous_contract(writer)
    sampling = writer.get("sampling", {})
    if int(sampling.get("particle_count", 0)) <= 0:
        raise ValueError("writer sampling has no particle count")
    gencase_xml, bi4, command_receipt = _run_gencase(lab=lab, definition=definition, output=output)
    base: dict[str, Any] = {
        "schema": SCHEMA, "created_at_utc": stamp(), "family": "F2", "scope_id": "F2_static_full_cup_volume_hold_x_v1",
        "repair_id": REPAIR_ID, "case_id": CASE_ID, "revision_id": REVISION_ID,
        "status": "cpu_native_preflight_pending", "qualification_claim": "none; one CPU GenCase/native decode canary",
        "qualified": False, "T1_numerical": False, "matrix_credit": 0,
        "fixed_failure_denominator": {"planned": 15, "executed": 1, "passed": 0, "failed": 0, "unattempted": 14, "survivor_renormalization": False},
        "root_review": _ref(review_ref["path"], "H2 root review", lab),
        "proposal": _ref(lab / PROPOSAL_RELATIVE, "H2 proposal", lab),
        "writer_receipt": _ref(writer_path, "fresh H2 Definition writer receipt", lab),
        "definition": _ref(definition, "fresh H2 Definition", lab), "motion": _ref(motion, "fresh H2 zero-angle motion", lab),
        "definition_audit": definition_audit, "continuous_contract": continuous,
        "gencase": command_receipt, "solver_invoked": False, "gpu_invoked": False,
        "queue_mutated": False, "ledger_mutated": False, "registry_mutated": False,
        "authorization_consumed": {"definition_writer": True, "cpu_gencase": True, "native_decode": False,
                                    "solver": False, "gpu": False, "job_spec_creation": False,
                                    "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0,
                                    "qualification_credit": 0},
    }
    if command_receipt["returncode"] != 0 or not gencase_xml.is_file() or not bi4.is_file():
        base["status"] = "cpu_gencase_failed_hard"
        base["fixed_failure_denominator"].update({"failed": 1, "unattempted": 14})
        base["execution_failure"] = "GenCase did not produce both generated XML and BI4"
        base["qualification_claim"] = "none; retained CPU GenCase failure"
        write_json(output / "preflight.json", base)
        return base
    native = _decode_and_check(lab=lab, generated_xml=gencase_xml, bi4=bi4, output=output,
                               sampling=sampling, continuous=continuous)
    base.update(native)
    base["authorization_consumed"]["native_decode"] = True
    base["gencase_generated_xml"] = _ref(gencase_xml, "GenCase generated XML", lab)
    base["native_bi4"] = _ref(bi4, "GenCase native BI4", lab)
    base["fixed_failure_denominator"].update({"passed": 1 if native["preflight_pass"] else 0,
                                               "failed": 0 if native["preflight_pass"] else 1})
    base["status"] = "cpu_native_preflight_pass" if native["preflight_pass"] else "cpu_native_preflight_failed_hard"
    base["qualification_claim"] = "none; CPU GenCase/native decode preflight only"
    write_json(output / "preflight.json", base)
    return base


def finalize_existing_decode(*, lab: Path, input_dir: Path, output: Path) -> dict[str, Any]:
    """Finalize the one allowed infrastructure recovery without rerunning GenCase.

    The first invocation created the BI4 successfully but the decoder was
    unable to create its parent directory.  After that directory was created,
    the already-issued decoder command completed successfully.  This function
    only reads those existing arrays; it never invokes GenCase or the decoder.
    """
    lab, input_dir, output = (Path(x).resolve() for x in (lab, input_dir, output))
    preflight_path = output / "preflight.json"
    if preflight_path.exists():
        raise RuntimeError("H2 preflight already finalized; refusing a second result")
    if not (output / "one-shot-lock.json").is_file():
        raise RuntimeError("one-shot lock is missing; no recovery may be fabricated")
    review_ref = _assert_review(lab)
    writer, writer_path = _writer_receipt(input_dir, lab)
    definition = _writer_path(writer, "definition", lab)
    motion = _writer_path(writer, "motion", lab)
    definition_audit = _validate_definition(definition, motion, writer, lab)
    continuous = _continuous_contract(writer)
    sampling = writer.get("sampling", {})
    generated_xml = output / "generated" / f"{CASE_ID}.xml"
    bi4 = output / "generated" / f"{CASE_ID}.bi4"
    if not generated_xml.is_file() or not bi4.is_file():
        raise FileNotFoundError("the single GenCase invocation did not leave XML and BI4")
    native = _decode_and_check(lab=lab, generated_xml=generated_xml, bi4=bi4, output=output,
                               sampling=sampling, continuous=continuous, use_existing_decode=True)
    base: dict[str, Any] = {
        "schema": SCHEMA, "created_at_utc": stamp(), "family": "F2", "scope_id": "F2_static_full_cup_volume_hold_x_v1",
        "repair_id": REPAIR_ID, "case_id": CASE_ID, "revision_id": REVISION_ID,
        "status": "cpu_native_preflight_pass" if native["preflight_pass"] else "cpu_native_preflight_failed_hard",
        "qualification_claim": "none; CPU GenCase/native decode preflight only",
        "qualified": False, "T1_numerical": False, "matrix_credit": 0,
        "fixed_failure_denominator": {"planned": 15, "executed": 1,
                                       "passed": 1 if native["preflight_pass"] else 0,
                                       "failed": 0 if native["preflight_pass"] else 1,
                                       "unattempted": 14, "survivor_renormalization": False},
        "root_review": _ref(review_ref["path"], "H2 root review", lab),
        "proposal": _ref(lab / PROPOSAL_RELATIVE, "H2 proposal", lab),
        "writer_receipt": _ref(writer_path, "fresh H2 Definition writer receipt", lab),
        "definition": _ref(definition, "fresh H2 Definition", lab),
        "motion": _ref(motion, "fresh H2 zero-angle motion", lab),
        "definition_audit": definition_audit, "continuous_contract": continuous,
        "gencase": {"invocation_count": 1, "result": "completed", "solver_invoked": False,
                     "gpu_invoked": False, "queue_mutated": False, "ledger_mutated": False,
                     "registry_mutated": False, "log": str((output / "gencase.log").resolve())},
        "gencase_generated_xml": _ref(generated_xml, "GenCase generated XML", lab),
        "native_bi4": _ref(bi4, "GenCase native BI4", lab),
        "native_decode_recovery": {
            "first_attempt": "failed_infrastructure_missing_parent_directory",
            "first_attempt_error": "bi4_dump could not open decoded/native.xml because decoded/ was absent",
            "recovery_parent_created": True,
            "decoder_invocation_count": 2,
            "recovery_used_existing_bi4": True,
            "same_input_scientific_retry": False,
        },
        "solver_invoked": False, "gpu_invoked": False, "queue_mutated": False,
        "ledger_mutated": False, "registry_mutated": False,
        "authorization_consumed": {"definition_writer": True, "cpu_gencase": True, "native_decode": True,
                                    "solver": False, "gpu": False, "job_spec_creation": False,
                                    "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0,
                                    "qualification_credit": 0, "infrastructure_recovery": 1},
    }
    base.update(native)
    write_json(preflight_path, base)
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--finalize-existing-decode", action="store_true",
                        help="read an already successful recovery decode without invoking GenCase/decoder")
    args = parser.parse_args(argv)
    try:
        if args.finalize_existing_decode:
            value = finalize_existing_decode(lab=args.lab_root, input_dir=args.input_dir, output=args.output)
        else:
            value = run(lab=args.lab_root, input_dir=args.input_dir, output=args.output)
    except Exception as exc:
        print(json.dumps({"status": "preflight_not_executed", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": value["status"], "preflight_pass": value.get("preflight_pass", False),
                      "output": str((Path(args.output).resolve() / "preflight.json"))}, ensure_ascii=False))
    return 0 if value.get("status") == "cpu_native_preflight_pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
