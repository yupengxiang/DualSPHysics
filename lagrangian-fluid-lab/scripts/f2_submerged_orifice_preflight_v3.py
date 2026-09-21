#!/usr/bin/env python3
"""Run the exact-one v3 CPU/native preflight and audit its fresh output.

``write-contract`` and ``verify-contract`` are static commands.  They only
read the v3 authorization receipt and its fresh Definition, and they never
materialize GenCase products.  ``run-preflight`` is the explicit execution
command: after rechecking the receipt it runs the pinned CPU GenCase binary
once, decodes the resulting BI4 with the pinned native decoder, and writes a
hard-audit receipt under the new v3 output prefix.

The worker has no solver, GPU, job, queue, ledger, registry, or matrix
submission path.  The normal-size audit is computed from the decoded
``BoundNor`` vectors when the native decoder does not emit a separate
``NormalSize.bin`` field; an emitted field is checked instead when present.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Mapping

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_cfd import native_frame  # noqa: E402
from scripts.finite_wall_audit import wall_penetration  # noqa: E402
from scripts.f2_submerged_orifice_normal_remediation_root_review_v3 import (  # noqa: E402
    DEFAULT_RECEIPT,
    verify_receipt,
)
from scripts.f2_submerged_orifice_normal_remediation_v3 import (  # noqa: E402
    CASE_ID,
    DEFAULT_BASE,
    DEFAULT_DEFINITION as V3_DEFINITION,
    DEFAULT_OUTPUT_PREFIX,
    DP_M,
    MASS_RELATIVE_ERROR_MAX,
    Q,
    REVISION_ID,
    SCOPE_ID,
    ZERO_NORMAL_TOLERANCE_M,
    inspect_definition,
    ref,
    sha256,
    verify_ref,
    write_json,
)


PREFLIGHT_SCHEMA = "core.f2.submerged_orifice_transfer.cpu_native_preflight.v3"
CONTRACT_SCHEMA = "core.f2.submerged_orifice_transfer.cpu_native_preflight_contract.v3"
CONTRACT_ID = "F2_SUBMERGED_ORIFICE_CPU_NATIVE_PREFLIGHT_CONTRACT_V3"
CREATED_AT = "2026-09-21T00:00:00+00:00"
MATRIX_INDEX = 4
CONTINUOUS_SOURCE_VOLUME_M3 = 0.64 * 0.42 * 0.36
SOURCE_DENSITY_KG_M3 = 1000.0
ENDPOINT_TOLERANCE_M = 1.0e-8

DEFAULT_DEFINITION = V3_DEFINITION
DEFAULT_CONTRACT = DEFAULT_BASE / "normal-remediation-v3/preflight-contract-v3.json"
DEFAULT_GENERATED_PREFIX = DEFAULT_OUTPUT_PREFIX
DEFAULT_OUTPUT = DEFAULT_GENERATED_PREFIX.parent / "preflight.json"
GENCASE_BINARY = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
NATIVE_DECODER = LAB_ROOT / "campaigns/l1-resume/artifacts/bi4_dump"
OLD_V4_OUTPUT_ROOT = DEFAULT_BASE / "normal-remediation-v2/preflight-v4"
TEST_PATH = LAB_ROOT / "tests/test_f2_submerged_orifice_preflight_v3.py"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _assert_closed_runtime(value: Mapping[str, Any], label: str) -> None:
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if value.get(key) is not False:
            raise ValueError(f"{label} opened permission: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if value.get(key) != 0:
            raise ValueError(f"{label} opened mutation: {key}")


def _parse_attrs(node: ET.Element, *keys: str) -> tuple[float, ...]:
    try:
        return tuple(float(node.get(key, "nan")) for key in keys)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid geometry attributes on {node.tag}") from exc


def _definition_contract(path: Path) -> dict[str, Any]:
    """Read only the fresh literal Definition required by this runner."""
    path = Path(path).resolve()
    if path.name != f"{CASE_ID}_Def.xml":
        raise ValueError("runner Definition path is not the exact authorized case")
    root = ET.parse(path).getroot()
    if root.tag != "case":
        raise ValueError("fresh Definition root must be <case>")
    definition = root.find("./casedef/geometry/definition")
    if definition is None or not math.isclose(float(definition.get("dp", "nan")), DP_M, rel_tol=0.0, abs_tol=1e-15):
        raise ValueError("fresh Definition dp mismatch")
    commands = root.find("./casedef/geometry/commands")
    if commands is None:
        raise ValueError("fresh Definition has no geometry commands")
    normal_list = commands.find("list[@name='GeometryForNormals']")
    main = commands.find("mainlist")
    if normal_list is None or main is None:
        raise ValueError("fresh Definition normal/main lists are missing")
    normal_boxes = normal_list.findall("drawbox")
    if len(normal_boxes) != 2:
        raise ValueError("fresh Definition normal list is not the v3 two-role recipe")
    normal_layers = [box.find("layers") for box in normal_boxes]
    if [node.get("vdp") if node is not None else None for node in normal_layers] != ["0,1,2", "0,-1,-2"]:
        raise ValueError("fresh Definition normal layers do not mirror v3 shells")
    normal_fills = [(box.findtext("boxfill") or "").strip() for box in normal_boxes]
    if normal_fills != [
        "bottom | left | right | front | back",
        "bottom | top | left | right | front | back",
    ]:
        raise ValueError("fresh Definition v3 normal face recipe changed")
    runlist = main.find("runlist")
    if runlist is None or runlist.get("name") != "GeometryForNormals" or list(main).index(runlist) != 0:
        raise ValueError("fresh Definition must run GeometryForNormals first")
    main_boxes = main.findall("drawbox")
    if len(main_boxes) != 4:
        raise ValueError("fresh Definition main list is not the expected four drawboxes")
    outer_layers = main_boxes[0].find("layers")
    gate_layers = main_boxes[2].find("layers")
    if outer_layers is None or outer_layers.get("vdp") != "0,1,2":
        raise ValueError("fresh Definition outer boundary layers changed")
    if gate_layers is None or gate_layers.get("vdp") != "0,-1,-2":
        raise ValueError("fresh Definition gate boundary layers changed")
    source_box = main_boxes[3]
    source_low = _parse_attrs(source_box.find("point"), "x", "y", "z")
    source_draw_size = _parse_attrs(source_box.find("size"), "x", "y", "z")
    if (source_box.findtext("boxfill") or "").strip() != "solid":
        raise ValueError("fresh Definition source is not a solid drawbox")
    if source_low != (0.04125, 0.04125, 0.04125) or source_draw_size != (0.63, 0.405, 0.345):
        raise ValueError("fresh Definition v3 source lattice box changed")
    normals = root.find("./casedef/normals")
    if normals is None or normals.get("active") != "true":
        raise ValueError("fresh Definition mDBC normals are inactive")
    norgeometry = normals.find("norgeometry")
    if norgeometry is None:
        raise ValueError("fresh Definition has no norgeometry block")
    if norgeometry.find("geometryfile").get("file") != "[CaseName]_hdp_Actual.vtk":
        raise ValueError("fresh Definition normal geometry source changed")
    # The source box is encoded by the writer as first cell centre plus the
    # inclusive draw extent.  Keep the frozen continuum volume as an explicit
    # contract, while exposing the literal box for audit/reporting.
    return {
        "definition_sha256": sha256(path),
        "definition_bytes": path.stat().st_size,
        "case_id": CASE_ID,
        "dp_m": DP_M,
        "source_draw_low_m": list(source_low),
        "source_draw_size_m": list(source_draw_size),
        "continuous_source_volume_m3": CONTINUOUS_SOURCE_VOLUME_M3,
        "continuous_source_mass_kg": CONTINUOUS_SOURCE_VOLUME_M3 * SOURCE_DENSITY_KG_M3,
        "expected_source_counts_xyz": [86, 56, 48],
        "expected_source_particles": 231168,
        "normal_geometry": {
            "outer_boxfill": normal_fills[0],
            "gate_boxfill": normal_fills[1],
            "outer_vdp": normal_layers[0].get("vdp"),
            "gate_vdp": normal_layers[1].get("vdp"),
        },
        "runtime_invoked": False,
    }


def _receipt_definition(receipt_path: Path, definition_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt_path = Path(receipt_path).resolve()
    if receipt_path != DEFAULT_RECEIPT.resolve():
        raise ValueError("runner must use the exact v3 root-review receipt")
    receipt = verify_receipt(receipt_path, DEFAULT_BASE)
    definition_path = Path(definition_path).resolve()
    case = receipt["case"]
    if case.get("fresh_definition") != str(definition_path):
        raise ValueError("runner Definition differs from v3 receipt")
    binding = receipt.get("hash_bindings", {}).get("v3_fresh_definition", {})
    verify_ref(binding, "runner fresh Definition", definition_path)
    if case.get("fresh_definition_sha256") != sha256(definition_path):
        raise ValueError("runner Definition SHA differs from v3 receipt")
    contract = _definition_contract(definition_path)
    return receipt, contract


def _output_identity(receipt: Mapping[str, Any], generated_prefix: Path | None = None) -> dict[str, Path]:
    expected = Path(receipt["case"]["generated_prefix"]).resolve()
    prefix = expected if generated_prefix is None else Path(generated_prefix).resolve()
    if prefix != expected:
        raise ValueError("runner output prefix differs from v4 receipt")
    if prefix.name != CASE_ID:
        raise ValueError("runner output prefix case identity mismatch")
    if OLD_V4_OUTPUT_ROOT.resolve() == prefix or OLD_V4_OUTPUT_ROOT.resolve() in prefix.parents:
        raise ValueError("runner output prefix is under the failed v4 output root")
    return {
        "prefix": prefix,
        "root": prefix.parent,
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
        "gencase_log": prefix.parent / "gencase.log",
        "preflight": prefix.parent / "preflight.json",
    }


def _generated_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    particles = root.find(".//particles")
    if particles is None:
        raise ValueError("generated XML has no particles section")
    try:
        total = int(particles.get("np", "-1"))
        boundary = int(particles.get("nb", "-1"))
    except ValueError as exc:
        raise ValueError("generated XML particle counts are invalid") from exc
    fixed = particles.findall("fixed")
    fluids = particles.findall("fluid")
    if len(fixed) != 2 or len(fluids) != 1:
        raise ValueError("generated XML must contain two boundary blocks and one fluid block")
    blocks = [*fixed, *fluids]
    ids: list[np.ndarray] = []
    result: dict[str, int] = {
        "total_particles": total,
        "boundary_particles": boundary,
        "fluid_particles": int(fluids[0].get("count", "-1")),
        "fluid_begin": int(fluids[0].get("begin", "-1")),
        "outer_boundary_particles": int(fixed[0].get("count", "-1")),
        "gate_boundary_particles": int(fixed[1].get("count", "-1")),
    }
    for block in blocks:
        begin = int(block.get("begin", "-1"))
        count = int(block.get("count", "-1"))
        if begin < 0 or count < 0:
            raise ValueError("generated XML has invalid particle block identity")
        ids.append(np.arange(begin, begin + count, dtype=np.uint32))
    expected_ids = np.concatenate(ids) if ids else np.empty(0, dtype=np.uint32)
    if len(expected_ids) != total or boundary != sum(result[key] for key in ("outer_boundary_particles", "gate_boundary_particles")):
        raise ValueError("generated XML particle block counts are inconsistent")
    if not np.array_equal(expected_ids, np.arange(total, dtype=np.uint32)):
        raise ValueError("generated XML particle IDs are not contiguous")
    result["xml_id_count"] = int(len(expected_ids))
    return result


def _wall_spec() -> dict[str, Any]:
    return {
        "container_interior": {
            "xmin": 0.0,
            "xmax": 1.6,
            "ymin": 0.0,
            "ymax": 0.5,
            "zmin": 0.0,
            "zmax": 0.8,
        },
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
        "obstacles": [
            {
                "id": "upper_gate_slab",
                "xmin": 0.72,
                "xmax": 0.78,
                "ymin": 0.04,
                "ymax": 0.46,
                "zmin": 0.18,
                "zmax": 0.8,
            }
        ],
        "runtime_domain": {
            "xmin": -0.30,
            "xmax": 1.90,
            "ymin": -0.15,
            "ymax": 0.65,
            "zmin": -0.15,
            "zmax": 1.20,
        },
    }


def audit_decoded(
    *,
    ids: np.ndarray,
    positions: np.ndarray,
    velocities: np.ndarray,
    density: np.ndarray,
    boundnor: np.ndarray,
    normal_size: np.ndarray,
    counts: Mapping[str, int],
    mass_fluid_kg: float,
) -> dict[str, Any]:
    """Run the v4 native hard audit on decoded arrays without side effects."""
    ids = np.asarray(ids)
    positions = np.asarray(positions)
    velocities = np.asarray(velocities)
    density = np.asarray(density)
    boundnor = np.asarray(boundnor)
    normal_size = np.asarray(normal_size)
    total = int(counts["total_particles"])
    boundary = int(counts["boundary_particles"])
    fluid = int(counts["fluid_particles"])
    fluid_begin = int(counts["fluid_begin"])

    expected_ids = np.arange(total, dtype=np.uint32)
    ids_unique = len(np.unique(ids)) == len(ids)
    ids_match_xml = bool(len(ids) == total and np.array_equal(ids, expected_ids))
    fluid_ids = np.arange(fluid_begin, fluid_begin + fluid, dtype=np.uint32)
    fluid_ids_match = bool(ids_match_xml and np.array_equal(ids[fluid_begin:fluid_begin + fluid], fluid_ids))

    arrays = (positions, velocities, density, boundnor, normal_size)
    arrays_finite = bool(all(np.isfinite(array).all() for array in arrays))
    boundnor_shape_ok = bool(boundnor.ndim == 2 and boundnor.shape == (boundary, 3))
    normal_size_shape_ok = bool(normal_size.ndim == 1 and len(normal_size) == boundary)
    boundnor_norm = np.linalg.norm(boundnor, axis=1) if boundnor_shape_ok else np.empty(0, dtype=float)
    zero_boundnor = int(np.sum(boundnor_norm <= ZERO_NORMAL_TOLERANCE_M)) if boundnor_shape_ok else boundary
    zero_normal_size = int(np.sum(normal_size <= ZERO_NORMAL_TOLERANCE_M)) if normal_size_shape_ok else boundary

    fluid_positions = positions[fluid_begin:fluid_begin + fluid] if len(positions) >= fluid_begin + fluid else np.empty((0, 3))
    try:
        geometry = wall_penetration(
            fluid_positions,
            np.ones(len(fluid_positions), dtype=float),
            _wall_spec(),
            ENDPOINT_TOLERANCE_M,
        )
        outer_endpoint_count = int(geometry["outside_closed_container_count"])
        gate_endpoint_count = int(geometry["obstacle_penetration_count"])
    except (KeyError, ValueError, IndexError):
        outer_endpoint_count = fluid
        gate_endpoint_count = fluid

    continuous_mass = CONTINUOUS_SOURCE_VOLUME_M3 * SOURCE_DENSITY_KG_M3
    discrete_mass = float(mass_fluid_kg) * fluid
    mass_error = discrete_mass / continuous_mass - 1.0 if continuous_mass else math.inf
    mass_pass = bool(math.isfinite(mass_error) and abs(mass_error) <= MASS_RELATIVE_ERROR_MAX)
    ids_pass = bool(ids_unique and ids_match_xml and fluid_ids_match)
    finite_pass = bool(arrays_finite and boundnor_shape_ok and normal_size_shape_ok)
    endpoint_pass = outer_endpoint_count == 0 and gate_endpoint_count == 0
    normal_pass = bool(zero_boundnor == 0 and zero_normal_size == 0)
    hard_gates = {
        "zero_boundnor": {
            "observed": zero_boundnor,
            "required": 0,
            "threshold_m": ZERO_NORMAL_TOLERANCE_M,
            "pass": zero_boundnor == 0,
        },
        "normal_size": {
            "observed": zero_normal_size,
            "required": 0,
            "threshold_m": ZERO_NORMAL_TOLERANCE_M,
            "pass": zero_normal_size == 0,
        },
        "ids": {
            "ids_unique": bool(ids_unique),
            "ids_match_generated_xml": bool(ids_match_xml),
            "fluid_ids_match_generated_xml": bool(fluid_ids_match),
            "pass": ids_pass,
        },
        "finite": {
            "positions": bool(np.isfinite(positions).all()),
            "velocities": bool(np.isfinite(velocities).all()),
            "density": bool(np.isfinite(density).all()),
            "boundnor": bool(np.isfinite(boundnor).all()),
            "normal_size": bool(np.isfinite(normal_size).all()),
            "pass": finite_pass,
        },
        "mass": {
            "continuous_source_mass_kg": continuous_mass,
            "discrete_native_mass_kg": discrete_mass,
            "relative_error": mass_error,
            "max_relative_error": MASS_RELATIVE_ERROR_MAX,
            "pass": mass_pass,
        },
        "endpoints": {
            "outer_wall_endpoint_count": outer_endpoint_count,
            "gate_endpoint_penetration_count": gate_endpoint_count,
            "tolerance_m": ENDPOINT_TOLERANCE_M,
            "pass": endpoint_pass,
        },
    }
    return {
        "ids_unique": bool(ids_unique),
        "ids_match_generated_xml": bool(ids_match_xml),
        "fluid_ids_match_generated_xml": bool(fluid_ids_match),
        "native_particle_count": int(len(ids)),
        "generated_total_particles": total,
        "boundnor_file_present": bool(len(boundnor) > 0),
        "boundnor_count": int(len(boundnor)),
        "normal_size_count": int(len(normal_size)),
        "zero_boundnor_count": zero_boundnor,
        "zero_normal_size_count": zero_normal_size,
        "normal_size_min_m": float(np.min(normal_size)) if len(normal_size) else math.nan,
        "normal_size_max_m": float(np.max(normal_size)) if len(normal_size) else math.nan,
        "arrays_finite": bool(arrays_finite),
        "fluid_particles_decoded": int(len(fluid_positions)),
        "boundary_particles_decoded": boundary,
        "wall_endpoint_outer_count": outer_endpoint_count,
        "gate_endpoint_penetration_count": gate_endpoint_count,
        "normal_size_source": "decoded_NormalSize.bin_or_norm_BoundNor",
        "hard_gates": hard_gates,
        "all_hard_gates_pass": bool(all(item["pass"] for item in hard_gates.values())),
    }


def _read_normal_arrays(arrays: Path, boundary_count: int) -> tuple[np.ndarray, np.ndarray, str]:
    normal_file = arrays / "BoundNor.bin"
    boundnor = (
        np.fromfile(normal_file, np.float32).reshape(-1, 3)
        if normal_file.is_file()
        else np.empty((0, 3), dtype=np.float32)
    )
    normal_size_file = arrays / "NormalSize.bin"
    if normal_size_file.is_file():
        normal_size = np.fromfile(normal_size_file, np.float32)
        source = "native_NormalSize.bin"
    elif len(boundnor) == boundary_count:
        normal_size = np.linalg.norm(boundnor, axis=1).astype(np.float32)
        source = "derived_from_BoundNor"
    else:
        normal_size = np.empty(0, dtype=np.float32)
        source = "missing"
    if len(boundnor) and len(boundnor) != boundary_count:
        # Keep the shape explicit so audit_decoded records a hard failure.
        boundnor = boundnor.reshape(-1, 3)
    return boundnor, normal_size, source


def _fresh_output_guard(identity: Mapping[str, Path], *, allow_materialized: bool = False) -> None:
    """Guard the one-shot execution path.

    Contract verification is also used after the one-shot preflight has
    produced its immutable evidence.  That read-only path must be able to
    rebuild and compare the contract without opening a second execution
    attempt, while builders and ``run_preflight`` keep the strict freshness
    guard.
    """
    if allow_materialized:
        return
    root = identity["root"]
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"v3 output prefix is not fresh: {root}")
    if identity["preflight"].exists():
        raise ValueError("v3 preflight receipt already exists; same-input retry is forbidden")


def build_contract(
    receipt_path: Path = DEFAULT_RECEIPT,
    definition_path: Path = DEFAULT_DEFINITION,
    output: Path = DEFAULT_CONTRACT,
    generated_prefix: Path | None = None,
    *,
    allow_materialized: bool = False,
) -> dict[str, Any]:
    receipt, definition = _receipt_definition(Path(receipt_path), Path(definition_path))
    identity = _output_identity(receipt, generated_prefix)
    _fresh_output_guard(identity, allow_materialized=allow_materialized)
    permissions = {
        "cpu_gencase": True,
        "native_decode": True,
        "solver_launch": False,
        "gpu_launch": False,
        "job_spec_creation": False,
        "matrix_submission": False,
        "queue_mutation": 0,
        "ledger_mutation": 0,
        "registry_mutation": 0,
        "qualification_numerator_credit": 0,
    }
    contract = {
        "schema": CONTRACT_SCHEMA,
        "contract_id": CONTRACT_ID,
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "case_id": CASE_ID,
        "matrix_index": MATRIX_INDEX,
        "q": Q,
        "dp_m": DP_M,
        "status": "authorized_one_cpu_native_preflight_pending",
        "decision": "exact_one_case_cpu_gencase_native_decode_only",
        "authorized_now": True,
        "proposal_only": False,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "input_bindings": {
            "v3_root_review_receipt": ref(Path(receipt_path), "v3 exact-one authorization receipt"),
            "fresh_definition": ref(Path(definition_path), "fresh v3 literal Definition"),
            "runner": ref(Path(__file__).resolve(), "v3 preflight runner"),
            "gencase_binary": ref(GENCASE_BINARY, "pinned CPU GenCase executable"),
            "native_decoder": ref(NATIVE_DECODER, "pinned native BI4 decoder"),
            "v3_preflight_test": ref(TEST_PATH, "v3 preflight contract/audit test"),
        },
        "fresh_output": {
            "generated_prefix": str(identity["prefix"]),
            "expected_generated_xml": str(identity["xml"]),
            "expected_native_bi4": str(identity["bi4"]),
            "output_materialized": False,
            "old_anchor_definition_reused": False,
            "v4_failed_definition_reused": False,
            "v4_failed_native_input_reused": False,
            "old_preflight_receipt_reused": False,
        },
        "definition_contract": definition,
        "hard_gates": {
            "zero_boundnor": {"required_value": 0, "threshold_m": ZERO_NORMAL_TOLERANCE_M, "status": "pending"},
            "normal_size": {"required_value": 0, "threshold_m": ZERO_NORMAL_TOLERANCE_M, "status": "pending"},
            "ids": {"required_value": True, "status": "pending"},
            "finite": {"required_value": True, "status": "pending"},
            "mass": {"max_relative_error": MASS_RELATIVE_ERROR_MAX, "status": "pending"},
            "endpoints": {"required_value": 0, "status": "pending"},
        },
        "permissions": permissions,
        "execution_controls": {
            "definition_read": True,
            "cpu_gencase_invoked": False,
            "cpu_native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "job_created": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
            "qualification_numerator_credit": 0,
        },
        "gate_evaluation": {
            "status": "not_run",
            "all_hard_gates_pass": False,
            "qualification_credit": 0,
            "threshold_relaxation": False,
            "same_input_retry": False,
            "survivor_renormalization": False,
        },
        "denominator": {
            "planned_rows": 15,
            "executed_rows": 0,
            "passed_rows": 0,
            "failed_rows": 0,
            "unattempted_rows": 15,
            "qualification_numerator": 0,
        },
        "prohibited_actions": [
            "no solver/GPU/job/queue/ledger/registry/matrix operation",
            "no v4 failed Definition/native input or old preflight receipt reuse",
            "no hard-gate relaxation or qualification credit",
        ],
    }
    write_json(Path(output), contract)
    return contract


def verify_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract_path = Path(path).resolve()
    contract = load_json(contract_path)
    if contract.get("schema") != CONTRACT_SCHEMA or contract.get("contract_id") != CONTRACT_ID:
        raise ValueError("v3 preflight contract schema/id mismatch")
    if contract.get("authorized_now") is not True or contract.get("proposal_only") is not False:
        raise ValueError("v3 preflight contract is not authorized exactly once")
    if contract.get("qualification_claim") != "none" or contract.get("matrix_credit") != 0:
        raise ValueError("v3 preflight contract carries credit")
    permissions = contract.get("permissions", {})
    if permissions.get("cpu_gencase") is not True or permissions.get("native_decode") is not True:
        raise ValueError("v3 contract closed an authorized CPU/native step")
    _assert_closed_runtime(permissions, "v3 contract")
    controls = contract.get("execution_controls", {})
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if controls.get(key) != 0:
            raise ValueError(f"v4 contract controls opened mutation: {key}")
    for key in ("cpu_gencase_invoked", "cpu_native_decode_invoked", "solver_invoked", "gpu_invoked", "job_created"):
        if controls.get(key) is not False:
            raise ValueError(f"v4 contract records execution: {key}")
    evaluation = contract.get("gate_evaluation", {})
    if evaluation.get("status") != "not_run" or evaluation.get("all_hard_gates_pass") is not False:
        raise ValueError("v4 contract records a preflight result")
    if evaluation.get("qualification_credit") != 0:
        raise ValueError("v4 contract gate evaluation carries credit")
    bindings = contract.get("input_bindings", {})
    receipt_path = verify_ref(bindings.get("v3_root_review_receipt", {}), "v3 contract receipt", DEFAULT_RECEIPT)
    definition_path = verify_ref(bindings.get("fresh_definition", {}), "v3 contract Definition", DEFAULT_DEFINITION)
    verify_ref(bindings.get("runner", {}), "v3 contract runner", Path(__file__).resolve())
    verify_ref(bindings.get("gencase_binary", {}), "v3 contract GenCase", GENCASE_BINARY)
    verify_ref(bindings.get("native_decoder", {}), "v3 contract native decoder", NATIVE_DECODER)
    verify_ref(bindings.get("v3_preflight_test", {}), "v3 contract test", TEST_PATH)
    rebuilt = build_contract(
        receipt_path=receipt_path,
        definition_path=definition_path,
        output=contract_path.with_suffix(".verify-rebuild.json"),
        generated_prefix=Path(contract["fresh_output"]["generated_prefix"]),
        allow_materialized=True,
    )
    try:
        rebuilt.pop("created_at_utc", None)
        observed = dict(contract)
        observed.pop("created_at_utc", None)
        if rebuilt != observed:
            raise ValueError("v3 preflight contract does not match current receipt/Definition")
    finally:
        rebuilt_path = contract_path.with_suffix(".verify-rebuild.json")
        if rebuilt_path.exists():
            rebuilt_path.unlink()
    return contract


def run_preflight(
    receipt_path: Path = DEFAULT_RECEIPT,
    definition_path: Path = DEFAULT_DEFINITION,
    *,
    generated_prefix: Path | None = None,
    gencase: Path | None = None,
    decoder: Path | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    """Explicitly run exactly one CPU GenCase/native decode preflight."""
    contract = verify_contract(DEFAULT_CONTRACT)
    receipt, definition = _receipt_definition(Path(receipt_path), Path(definition_path))
    identity = _output_identity(receipt, generated_prefix)
    _fresh_output_guard(identity)
    gencase_path = Path(gencase or GENCASE_BINARY).resolve()
    decoder_path = Path(decoder or NATIVE_DECODER).resolve()
    if gencase_path != GENCASE_BINARY.resolve() or decoder_path != NATIVE_DECODER.resolve():
        raise ValueError("v3 runner accepts only the pinned CPU/native executables")
    verify_ref(contract["input_bindings"]["gencase_binary"], "v3 GenCase binary", gencase_path)
    verify_ref(contract["input_bindings"]["native_decoder"], "v3 native decoder", decoder_path)
    identity["root"].mkdir(parents=True, exist_ok=False)
    command = [str(gencase_path), str(Path(definition_path).resolve().with_suffix("")), str(identity["prefix"]), "-save:all"]
    with identity["gencase_log"].open("w", encoding="utf-8") as stream:
        process = subprocess.run(command, cwd=identity["root"], stdout=stream, stderr=subprocess.STDOUT, check=False)
    if process.returncode != 0:
        raise RuntimeError(f"CPU GenCase failed with return code {process.returncode}")
    if not identity["xml"].is_file() or not identity["bi4"].is_file():
        raise FileNotFoundError("GenCase did not create fresh XML and BI4 products")
    counts = _generated_counts(identity["xml"])
    with tempfile.TemporaryDirectory(prefix="f2-orifice-v3-native-") as temporary:
        ids, positions, velocities, density, metadata, _info, arrays = native_frame(
            identity["bi4"], Path(temporary) / "initial", decoder_path
        )
        boundnor, normal_size, normal_source = _read_normal_arrays(arrays, counts["boundary_particles"])
        native = audit_decoded(
            ids=ids,
            positions=positions,
            velocities=velocities,
            density=density,
            boundnor=boundnor,
            normal_size=normal_size,
            counts=counts,
            mass_fluid_kg=float(metadata["MassFluid"]),
        )
        native["normal_size_source"] = normal_source
    input_hashes: dict[str, str] = {}
    for path in (
        Path(receipt_path),
        DEFAULT_CONTRACT,
        Path(definition_path),
        Path(__file__).resolve(),
        TEST_PATH,
        identity["gencase_log"],
        identity["xml"],
        identity["bi4"],
        identity["prefix"].with_name(identity["prefix"].name + "_hdp_Actual.vtk"),
        identity["prefix"].with_name(identity["prefix"].name + "_Bound.vtk"),
        gencase_path,
        decoder_path,
    ):
        if path.is_file():
            input_hashes[str(path.resolve())] = sha256(path)
    result = {
        "schema": PREFLIGHT_SCHEMA,
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "status": "cpu_native_preflight_pass_exact_one" if native["all_hard_gates_pass"] else "cpu_native_preflight_failed_hard_audit",
        "qualification_claim": "none",
        "qualified": False,
        "matrix_credit": 0,
        "authorized_matrix_index": MATRIX_INDEX,
        "case_id": CASE_ID,
        "q": Q,
        "dp_m": DP_M,
        "root_review": ref(Path(receipt_path), "v3 exact-one CPU/native authorization receipt"),
        "preflight_contract": ref(DEFAULT_CONTRACT, "v3 CPU/native preflight contract"),
        "runner": ref(Path(__file__).resolve(), "v3 CPU/native preflight runner"),
        "definition": ref(Path(definition_path), "fresh literal Definition"),
        "generated_prefix": str(identity["prefix"]),
        "generated_counts": counts,
        "definition_contract": definition,
        "native_initial": native,
        "mass_contract": native["hard_gates"]["mass"],
        "geometry_contract": native["hard_gates"]["endpoints"],
        "artifacts": {
            "definition": str(Path(definition_path).resolve()),
            "root_review_receipt": str(Path(receipt_path).resolve()),
            "preflight_contract": str(DEFAULT_CONTRACT.resolve()),
            "gencase_log": str(identity["gencase_log"]),
            "generated_xml": str(identity["xml"]),
            "native_bi4": str(identity["bi4"]),
            "sha256": input_hashes,
        },
        "input_hashes": input_hashes,
        "execution_controls": {
            "cpu_gencase_invoked": True,
            "cpu_native_decode_invoked": True,
            "solver_invoked": False,
            "gpu_invoked": False,
            "job_created": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
            "qualification_numerator_credit": 0,
        },
        "solver_product_present": False,
        "preflight_pass": bool(native["all_hard_gates_pass"]),
        "interpretation_boundary": (
            "fresh CPU GenCase/native BI4 integrity only; no solver trajectory, "
            "event result, qualification, or T1/matrix credit"
        ),
    }
    write_json(Path(output or identity["preflight"]), result)
    return result


def verify_preflight(path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    """Verify a materialized v3 preflight receipt without rerunning anything."""
    path = Path(path).resolve()
    result = load_json(path)
    if result.get("schema") != PREFLIGHT_SCHEMA or result.get("case_id") != CASE_ID:
        raise ValueError("v3 preflight schema/case mismatch")
    if result.get("qualification_claim") != "none" or result.get("matrix_credit") != 0:
        raise ValueError("v3 preflight contains qualification credit")
    if result.get("generated_prefix") != str(DEFAULT_GENERATED_PREFIX.resolve()):
        raise ValueError("v3 preflight output prefix changed")
    execution = result.get("execution_controls", {})
    if execution.get("cpu_gencase_invoked") is not True or execution.get("cpu_native_decode_invoked") is not True:
        raise ValueError("v3 preflight did not record exact CPU/native execution")
    for key in ("solver_invoked", "gpu_invoked", "job_created", "matrix_submission"):
        if execution.get(key) is not False:
            raise ValueError(f"v3 preflight recorded prohibited execution: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if execution.get(key) != 0:
            raise ValueError(f"v3 preflight recorded prohibited mutation: {key}")
    verify_ref(result.get("root_review", {}), "v3 preflight root receipt", DEFAULT_RECEIPT)
    verify_ref(result.get("preflight_contract", {}), "v3 preflight contract", DEFAULT_CONTRACT)
    verify_ref(result.get("runner", {}), "v3 preflight runner", Path(__file__).resolve())
    verify_ref(result.get("definition", {}), "v3 preflight Definition", DEFAULT_DEFINITION)
    counts = result.get("generated_counts", {})
    for key in ("total_particles", "boundary_particles", "fluid_particles", "fluid_begin"):
        if int(counts.get(key, -1)) < 0:
            raise ValueError("v3 preflight generated counts are invalid")
    native = result.get("native_initial", {})
    gates = native.get("hard_gates", {})
    if native.get("zero_boundnor_count") != gates.get("zero_boundnor", {}).get("observed"):
        raise ValueError("v3 preflight BoundNor gate mismatch")
    if native.get("zero_normal_size_count") != gates.get("normal_size", {}).get("observed"):
        raise ValueError("v3 preflight NormalSize gate mismatch")
    if gates.get("zero_boundnor", {}).get("required") != 0 or gates.get("normal_size", {}).get("required") != 0:
        raise ValueError("v3 preflight zero-normal gate was relaxed")
    if gates.get("mass", {}).get("max_relative_error") != MASS_RELATIVE_ERROR_MAX:
        raise ValueError("v3 preflight mass gate changed")
    if bool(result.get("preflight_pass")) != bool(native.get("all_hard_gates_pass")):
        raise ValueError("v3 preflight status/gates disagree")
    for key in ("generated_xml", "native_bi4", "gencase_log"):
        artifact = result.get("artifacts", {}).get(key)
        if not artifact or not Path(artifact).is_file():
            raise ValueError(f"v3 preflight artifact missing: {key}")
    return result


# The older F2 adapters call this operation ``prepare_anchor``.  Keep a
# descriptive alias for callers while preserving the explicit run command.
prepare_anchor = run_preflight


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write-contract", "verify-contract", "run-preflight", "verify-preflight"))
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--generated-prefix", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "write-contract":
        result = build_contract(args.receipt, args.definition, args.contract, args.generated_prefix)
    elif args.command == "verify-contract":
        result = verify_contract(args.contract)
    elif args.command == "run-preflight":
        result = run_preflight(
            args.receipt,
            args.definition,
            generated_prefix=args.generated_prefix,
            output=args.output,
        )
    else:
        result = verify_preflight(args.output or DEFAULT_OUTPUT)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0 if result.get("preflight_pass", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
