#!/usr/bin/env python3
"""Static F8 R008 native-fluid table and metric adapter.

This module validates/projections decoded native frames and evaluates the
adopted profile, transverse-RMS, cycle-flux, and comparison metrics. It does not
launch or schedule a solver, worker, GPU job, or qualification run. Native
integrity gates outside this metric contract remain separate prerequisites.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

import h5py
import numpy as np

from scripts.f8_observation_window_parser_v2 import select_closed_native_window
from scripts.f8_womersley_oracle import (
    ChannelParameters,
    cross_sectional_flux_per_width,
    steady_velocity,
)

SCHEMA = "core.cfd.f8.r008_t1_metric_adapter.v1"
TABLE_SCHEMA = "core.cfd.f8.r008_native_fluid_frame_table.v1"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
LAB = Path(__file__).resolve().parents[1]
FROZEN_SCOPE_RECEIPT = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-scope-design-v1/receipt.json"
FROZEN_PARAMETER_CONTRACT = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json"
FROZEN_DEFINITION_PACK = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/definition-control-pack-v1/receipt.json"
FROZEN_METRIC_PROPOSAL = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-metric-semantics-proposal-v2/receipt.json"
FROZEN_METRIC_REVIEW = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-metric-semantics-review-v2/receipt.json"
FROZEN_ANCHOR_PREFLIGHT = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/cpu-native-preflight-v3/receipt.json"
FROZEN_GENCASE_METRICS = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/cpu-native-preflight-v3/gencase.scope-metrics.json"
FROZEN_GENCASE_BINARY = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
# These digests pin the adopted R008 scope/semantics and the sole existing
# zero-credit native preflight. Any future execution receipt needs a separately
# reviewed verifier; changing these anchors is a contract revision.
FROZEN_INPUT_SHA256 = {
    "scope": "65671b42523cd3a5f82338cc7e2d88890af634195d7013ad969311166ab36ac8",
    "parameter_contract": "f15d9db7e41fd626311f0040b3a3fd4c4498cf6152f23e446d0c23cc495865d6",
    "definition_pack": "d5b657db398e0c0b102cdb84de8fe0a302c22c85d4bbf16bc0b6e6bf16065fcb",
    "metric_proposal": "fecbdfea584c9984e700126d8ca34942bfeddaa6c7b733cec88df8145c0e1008",
    "metric_review": "6242b5c0d70bb31509c438af5e569e3a54ca8e3d3f1020f2766074b054035042",
    "anchor_preflight": "4db07cb997746352d13850103aba86f58bbd9af4d71e22bafdcde67919d38b13",
    "gencase_metrics": "e549824c4d2d57360d76119b31bf3ae12d03ee0a505ba2c3eb0364f1b895bdf6",
    "gencase_binary": "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226",
}
ANCHOR_CASE_ID = "space-q0p5-dp0p0075"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PLANE_ABSOLUTE_TOLERANCE_M = 1e-9


@dataclass(frozen=True)
class NativeFluidTable:
    time_s: np.ndarray
    particle_id: np.ndarray
    position_m: np.ndarray
    velocity_m_s: np.ndarray
    mass_kg: np.ndarray
    valid: np.ndarray
    case_id: str
    generated_xml_sha256: str
    definition_sha256: str = ""
    generation_receipt_path: str = ""
    generation_receipt_sha256: str = ""
    scope_receipt_sha256: str = ""
    parameter_contract_sha256: str = ""
    source_table_path: str = ""
    source_table_sha256: str = ""


def _finite_scalar(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a finite numeric scalar")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite numeric scalar") from error
    if not math.isfinite(result) or (positive and result <= 0.0):
        qualifier = "positive and finite" if positive else "finite"
        raise ValueError(f"{name} must be {qualifier}")
    return result


def _assert_frozen_inputs() -> None:
    files = {
        "scope": FROZEN_SCOPE_RECEIPT,
        "parameter_contract": FROZEN_PARAMETER_CONTRACT,
        "definition_pack": FROZEN_DEFINITION_PACK,
        "metric_proposal": FROZEN_METRIC_PROPOSAL,
        "metric_review": FROZEN_METRIC_REVIEW,
        "anchor_preflight": FROZEN_ANCHOR_PREFLIGHT,
        "gencase_metrics": FROZEN_GENCASE_METRICS,
        "gencase_binary": FROZEN_GENCASE_BINARY,
    }
    for name, path in files.items():
        if not path.is_file() or sha256_file(path) != FROZEN_INPUT_SHA256[name]:
            raise ValueError(f"frozen F8 R008 input changed or is missing: {name}")


def _canonical_ids(values: Any, name: str) -> np.ndarray:
    raw = np.asarray(values)
    if raw.ndim == 1 and raw.size == 0:
        return np.empty(0, dtype=np.uint32)
    if raw.ndim != 1 or raw.dtype.kind not in "iu" or raw.dtype.kind == "b":
        raise ValueError(f"{name} must be a one-dimensional integer ID array")
    as_u64 = raw.astype(np.uint64, copy=False)
    if np.any(as_u64 > np.iinfo(np.uint32).max):
        raise ValueError(f"{name} contains an ID outside uint32 range")
    if len(np.unique(as_u64)) != len(as_u64):
        raise ValueError(f"{name} contains duplicate IDs")
    return np.sort(as_u64.astype(np.uint32, copy=False))


def validate_raw_frame_ids(
    raw_particle_ids: Any,
    expected_fluid_ids: Any,
    registered_nonfluid_ids: Any,
) -> np.ndarray:
    """Return raw row indices in sorted-fluid-ID order; reject all ID drift.

    The caller must derive and hash-bind both registered cohorts from this
    case's generated XML before passing them here. The raw frame is required to
    contain exactly their disjoint union, once each.
    """
    raw = np.asarray(raw_particle_ids)
    if raw.ndim != 1 or raw.dtype.kind not in "iu" or raw.dtype.kind == "b":
        raise ValueError("raw native particle IDs must be a one-dimensional integer array")
    if raw.dtype.kind == "i" and np.any(raw < 0):
        raise ValueError("raw native particle IDs cannot be negative")
    raw_u64 = raw.astype(np.uint64, copy=False)
    if np.any(raw_u64 > np.iinfo(np.uint32).max):
        raise ValueError("raw native particle ID is outside uint32 range")
    fluid = _canonical_ids(expected_fluid_ids, "expected fluid IDs")
    nonfluid = _canonical_ids(registered_nonfluid_ids, "registered nonfluid IDs")
    if len(fluid) == 0:
        raise ValueError("expected fluid cohort cannot be empty")
    if np.intersect1d(fluid, nonfluid).size:
        raise ValueError("fluid and registered nonfluid ID cohorts overlap")
    raw32 = raw_u64.astype(np.uint32, copy=False)
    if len(np.unique(raw32)) != len(raw32):
        raise ValueError("duplicate native identities")
    expected = np.sort(np.concatenate((fluid, nonfluid)))
    if not np.array_equal(np.sort(raw32), expected):
        missing = np.setdiff1d(expected, raw32).tolist()
        unknown = np.setdiff1d(raw32, expected).tolist()
        raise ValueError(f"native raw ID universe changed; missing={missing[:8]}, unknown={unknown[:8]}")
    row_by_id = {int(particle_id): index for index, particle_id in enumerate(raw32)}
    return np.asarray([row_by_id[int(particle_id)] for particle_id in fluid], dtype=np.int64)


def generated_xml_cohorts(path: Path) -> tuple[np.ndarray, np.ndarray, str]:
    """Derive complete fluid/nonfluid identity cohorts from a bound GenCase XML."""
    xml_path = Path(path).resolve()
    if not xml_path.is_file():
        raise ValueError("generated GenCase XML is missing")
    root = ET.parse(xml_path).getroot()
    groups = root.findall(".//particles/*")
    if not groups:
        raise ValueError("generated XML has no particle groups to bind the native ID universe")
    fluid_ids: list[int] = []
    nonfluid_ids: list[int] = []
    recognized = {"fluid", "fixed", "moving", "floating"}
    for group in groups:
        if group.tag == "_summary":
            continue
        if group.tag not in recognized:
            raise ValueError(f"generated XML has an unclassified particle group: {group.tag}")
        try:
            begin, count = int(group.get("begin", "-1")), int(group.get("count", "-1"))
        except ValueError as error:
            raise ValueError("generated XML particle group has invalid begin/count") from error
        if begin < 0 or count <= 0 or begin + count - 1 > np.iinfo(np.uint32).max:
            raise ValueError("generated XML particle group range is outside uint32 or empty")
        target = fluid_ids if group.tag == "fluid" else nonfluid_ids
        target.extend(range(begin, begin + count))
    fluid = _canonical_ids(fluid_ids, "generated XML fluid IDs")
    nonfluid = _canonical_ids(nonfluid_ids, "generated XML registered nonfluid IDs")
    if len(fluid) == 0 or len(nonfluid) == 0 or np.intersect1d(fluid, nonfluid).size:
        raise ValueError("generated XML must define disjoint, nonempty fluid and nonfluid cohorts")
    return fluid, nonfluid, sha256_file(xml_path)


def _verified_file_binding(binding: Mapping[str, Any], name: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(binding, Mapping) or not isinstance(binding.get("path"), str):
        raise ValueError(f"{name} provenance binding is missing a path")
    path = Path(binding["path"])
    if not path.is_absolute():
        path = LAB / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"bound {name} file is missing: {path}")
    size, digest = path.stat().st_size, sha256_file(path)
    if binding.get("bytes") != size or binding.get("sha256") != digest:
        raise ValueError(f"bound {name} file changed: {path}")
    return path, {"path": str(path), "bytes": size, "sha256": digest}


def _frozen_definition_binding(case_id: str) -> dict[str, Any]:
    _assert_frozen_inputs()
    pack = json.loads(FROZEN_DEFINITION_PACK.read_text(encoding="utf-8"))
    case = next((item for item in pack.get("cases", []) if item.get("case_id") == case_id), None)
    if case is None or not isinstance(case.get("definition"), dict):
        raise ValueError(f"case has no frozen Definition binding in the R008 input pack: {case_id}")
    _, verified = _verified_file_binding(case["definition"], "frozen Definition")
    return verified


def _frozen_case_row(case_id: str) -> dict[str, Any]:
    _assert_frozen_inputs()
    scope = json.loads(FROZEN_SCOPE_RECEIPT.read_text(encoding="utf-8"))
    if scope.get("scope_id") != SCOPE_ID:
        raise ValueError("frozen F8 R008 scope receipt has an unexpected scope_id")
    row = next((item for item in scope.get("matrix", {}).get("rows", [])
                if item.get("case_id") == case_id), None)
    if row is None:
        raise ValueError(f"case_id is not a frozen F8 R008 matrix row: {case_id}")
    return row


def _validate_frozen_case_geometry(case_id: str, dp_m: float, half_height_m: float) -> None:
    row = _frozen_case_row(case_id)
    parameters = json.loads(FROZEN_PARAMETER_CONTRACT.read_text(encoding="utf-8"))
    frozen_half_height = float(parameters["geometry_and_fluid"]["half_height_m"])
    if not (
        math.isclose(_finite_scalar(dp_m, "dp_m", positive=True), float(row["dp_m"]),
                     rel_tol=0.0, abs_tol=1e-12)
        and math.isclose(_finite_scalar(half_height_m, "half_height_m", positive=True),
                         frozen_half_height, rel_tol=0.0, abs_tol=1e-12)
    ):
        raise ValueError("native table H/dp must match the frozen F8 R008 case row and parameter contract")


def _command_references_path(command: Any, expected_path: Path) -> bool:
    if not isinstance(command, list) or not command or not all(isinstance(token, str) for token in command):
        return False
    expected = Path(expected_path).resolve()
    for token in command:
        candidate = Path(token)
        if not candidate.is_absolute():
            candidate = LAB / candidate
        if candidate.resolve() == expected:
            return True
    return False


def verify_gencase_receipt(path: Path, case_id: str) -> dict[str, Any]:
    """Verify a GenCase output receipt against the frozen row Definition and files.

    Only the hash-pinned, already-existing zero-credit anchor preflight is
    trusted here. Per-case runtime receipts need a separately reviewed
    verifier and cannot self-assert their way into metric provenance.
    """
    _assert_frozen_inputs()
    receipt_path = Path(path).resolve()
    if not receipt_path.is_file():
        raise ValueError("GenCase materialization receipt is missing")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("scope_id") != SCOPE_ID or receipt.get("qualification_credit") != 0:
        raise ValueError("GenCase receipt is outside F8 R008 or claims qualification credit")
    expected_definition = _frozen_definition_binding(case_id)

    if receipt.get("schema") == "core.cfd.f8.r008_cpu_native_preflight.v1":
        if case_id != ANCHOR_CASE_ID or receipt_path != FROZEN_ANCHOR_PREFLIGHT.resolve():
            raise ValueError("the pinned R008 CPU/native preflight receipt is valid only for its anchor row")
        if sha256_file(receipt_path) != FROZEN_INPUT_SHA256["anchor_preflight"]:
            raise ValueError("the pinned R008 anchor preflight receipt changed")
        _, receipt_definition = _verified_file_binding(
            receipt.get("input", {}).get("definition", {}), "GenCase input Definition",
        )
        if not (
            receipt.get("status") == "cpu_native_preflight_passed_zero_credit"
            and receipt_definition == expected_definition
            and receipt.get("generated_audit", {}).get("pass") is True
            and receipt.get("execution_controls", {}).get("cpu_gencase_invoked") is True
            and receipt.get("execution_controls", {}).get("solver_invoked") is False
            and receipt.get("execution_controls", {}).get("worker_started") is False
            and receipt.get("execution_controls", {}).get("gpu_invoked") is False
            and receipt.get("execution_controls", {}).get("queue_mutation") == 0
        ):
            raise ValueError("R008 CPU/native receipt does not bind a passed zero-credit GenCase result")
        generated_binding = receipt["generated_audit"]["required_artifacts"]["generated_xml"]
        gencase = receipt.get("gencase", {})
        payload = gencase.get("native_payload", [])
        generated_path_arg = Path(generated_binding["path"])
        if not generated_path_arg.is_absolute():
            generated_path_arg = LAB / generated_path_arg
        if not (
            gencase.get("native_payload_invoked") is True
            and gencase.get("native_return_code") == 0
            and _command_references_path(payload, Path(expected_definition["path"]).with_suffix(""))
            and _command_references_path(payload, generated_path_arg.resolve().with_suffix(""))
            and payload[0] == str(FROZEN_GENCASE_BINARY.resolve())
            and sha256_file(FROZEN_GENCASE_BINARY) == FROZEN_INPUT_SHA256["gencase_binary"]
        ):
            raise ValueError("R008 GenCase command does not bind the expected Definition and output prefix")
        metrics_path, metrics_binding = _verified_file_binding(
            gencase.get("metrics_receipt", {}), "scoped GenCase wrapper audit",
        )
        scoped_audit = json.loads(metrics_path.read_text(encoding="utf-8"))
        if not (
            metrics_path == FROZEN_GENCASE_METRICS.resolve()
            and metrics_binding["sha256"] == FROZEN_INPUT_SHA256["gencase_metrics"]
            and _command_references_path(gencase.get("command", []), metrics_path)
            and scoped_audit == gencase.get("wrapper_receipt")
            and scoped_audit.get("schema") == "core.cfd.f8.r008_scoped_native_command.v1"
            and scoped_audit.get("child_argv") == payload
            and scoped_audit.get("child_return_code") == 0
            and scoped_audit.get("scope_process_tree_clean") is True
            and scoped_audit.get("timed_out") is False
            and scoped_audit.get("residual_scope_pids_after_cleanup") == []
        ):
            raise ValueError("R008 GenCase wrapper audit is not the pinned successful scoped execution")
    else:
        raise ValueError("untrusted per-case GenCase receipt schema; no reviewed runtime verifier is available")

    if not isinstance(generated_binding, dict):
        raise ValueError("GenCase receipt is missing its generated XML binding")
    generated_path, generated_verified = _verified_file_binding(generated_binding, "GenCase generated XML")
    fluid, nonfluid, xml_digest = generated_xml_cohorts(generated_path)
    if generated_verified["sha256"] != xml_digest:
        raise ValueError("generated XML cohort hash differs from the receipt binding")
    _, receipt_verified = _verified_file_binding({
        "path": str(receipt_path), "bytes": receipt_path.stat().st_size,
        "sha256": sha256_file(receipt_path),
    }, "GenCase receipt")
    return {
        "case_id": case_id,
        "definition": expected_definition,
        "generated_xml": generated_verified,
        "generated_xml_sha256": xml_digest,
        "fluid_particle_count": len(fluid),
        "registered_nonfluid_particle_count": len(nonfluid),
        "receipt": receipt_verified,
    }


def validate_fluid_table(table: NativeFluidTable) -> NativeFluidTable:
    times = np.asarray(table.time_s, dtype=np.float64)
    ids = _canonical_ids(table.particle_id, "fluid particle IDs")
    if not np.array_equal(np.asarray(table.particle_id), ids):
        raise ValueError("fluid particle ID axis must be sorted and immutable")
    position = np.asarray(table.position_m, dtype=np.float64)
    velocity = np.asarray(table.velocity_m_s, dtype=np.float32)
    mass = np.asarray(table.mass_kg, dtype=np.float32)
    valid = np.asarray(table.valid)
    if times.ndim != 1 or len(times) < 2 or not np.isfinite(times).all():
        raise ValueError("native fluid table needs at least two finite time rows")
    if times[0] != 0.0 or np.any(np.diff(times) <= 0.0):
        raise ValueError("native fluid table time must start exactly at zero and increase strictly")
    expected_position = (len(times), len(ids), 3)
    expected_scalar = (len(times), len(ids))
    if position.shape != expected_position or velocity.shape != expected_position:
        raise ValueError("native fluid position and velocity must have shape [T,P,3]")
    if mass.shape != expected_scalar or valid.shape != expected_scalar or valid.dtype.kind != "b":
        raise ValueError("native fluid mass and valid fields must have shape [T,P] and valid must be bool")
    if not np.isfinite(position).all() or not np.isfinite(velocity).all():
        raise ValueError("native fluid position and velocity must be finite")
    if not np.isfinite(mass).all() or np.any(mass <= 0.0):
        raise ValueError("native fluid mass must be finite and strictly positive")
    if not np.all(valid):
        raise ValueError("native fluid table contains a missing or invalid fluid ID")
    if not np.array_equal(mass, np.broadcast_to(mass[0], mass.shape)):
        raise ValueError("native fluid mass changed by particle ID")
    if not isinstance(table.case_id, str) or not table.case_id:
        raise ValueError("native fluid table case_id is required")
    if not isinstance(table.generated_xml_sha256, str) or not SHA256_PATTERN.fullmatch(table.generated_xml_sha256):
        raise ValueError("generated XML hash must be a lowercase SHA-256 digest")
    provenance = (
        table.definition_sha256, table.generation_receipt_path,
        table.generation_receipt_sha256, table.scope_receipt_sha256,
        table.parameter_contract_sha256,
    )
    if any(provenance) and not (
        SHA256_PATTERN.fullmatch(table.definition_sha256)
        and bool(table.generation_receipt_path)
        and SHA256_PATTERN.fullmatch(table.generation_receipt_sha256)
        and SHA256_PATTERN.fullmatch(table.scope_receipt_sha256)
        and SHA256_PATTERN.fullmatch(table.parameter_contract_sha256)
    ):
        raise ValueError("native fluid table provenance bindings must be complete and hash-valid")
    if bool(table.source_table_path) != bool(table.source_table_sha256):
        raise ValueError("native fluid table source path and digest must be bound together")
    if table.source_table_sha256 and not SHA256_PATTERN.fullmatch(table.source_table_sha256):
        raise ValueError("native fluid table source hash is invalid")
    return NativeFluidTable(
        times.copy(), ids.copy(), position.copy(), velocity.copy(), mass.copy(),
        valid.astype(bool, copy=True), table.case_id, table.generated_xml_sha256,
        table.definition_sha256, table.generation_receipt_path,
        table.generation_receipt_sha256, table.scope_receipt_sha256,
        table.parameter_contract_sha256, table.source_table_path,
        table.source_table_sha256,
    )


def build_native_fluid_table(
    frames: Sequence[Mapping[str, Any]],
    *,
    generated_xml_path: Path,
    generation_receipt_path: Path | None = None,
    dp_m: float,
    half_height_m: float,
    case_id: str,
) -> NativeFluidTable:
    """Strictly validate decoded frames, then materialize the fluid-only table."""
    _validate_frozen_case_geometry(case_id, dp_m, half_height_m)
    generated_xml_path = Path(generated_xml_path).resolve()
    fluid, nonfluid, generated_hash = generated_xml_cohorts(generated_xml_path)
    provenance: dict[str, Any] | None = None
    if generation_receipt_path is not None:
        provenance = verify_gencase_receipt(generation_receipt_path, case_id)
        if (provenance["generated_xml"]["path"] != str(generated_xml_path)
                or provenance["generated_xml_sha256"] != generated_hash):
            raise ValueError("GenCase receipt and generated XML input do not identify the same output")
    dp = _finite_scalar(dp_m, "dp_m", positive=True)
    half_height = _finite_scalar(half_height_m, "half_height_m", positive=True)
    intervals_float = 2.0 * half_height / dp
    intervals = round(intervals_float)
    if not math.isclose(intervals_float, intervals, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("2H/dp must be an integer number of registered spacing intervals")
    if len(frames) < 2:
        raise ValueError("at least two decoded native frames are required")
    times = np.empty(len(frames), dtype=np.float64)
    position = np.empty((len(frames), len(fluid), 3), dtype=np.float64)
    velocity = np.empty((len(frames), len(fluid), 3), dtype=np.float32)
    mass = np.empty((len(frames), len(fluid)), dtype=np.float32)
    valid = np.ones((len(frames), len(fluid)), dtype=bool)

    for frame_index, frame in enumerate(frames):
        required = {"time_s", "particle_id", "position_m", "velocity_m_s", "mass_kg"}
        if not isinstance(frame, Mapping) or not required.issubset(frame):
            raise ValueError(f"decoded frame {frame_index} is missing required native arrays")
        times[frame_index] = _finite_scalar(frame["time_s"], f"frame {frame_index} time")
        raw_ids = np.asarray(frame["particle_id"])
        order = validate_raw_frame_ids(raw_ids, fluid, nonfluid)
        raw_count = len(raw_ids)
        raw_position = np.asarray(frame["position_m"], dtype=np.float64)
        raw_velocity = np.asarray(frame["velocity_m_s"], dtype=np.float64)
        raw_mass = np.asarray(frame["mass_kg"], dtype=np.float64)
        if raw_position.shape != (raw_count, 3) or raw_velocity.shape != (raw_count, 3) or raw_mass.shape != (raw_count,):
            raise ValueError(f"decoded frame {frame_index} native arrays do not align with particle IDs")
        fluid_position = raw_position[order]
        fluid_velocity = raw_velocity[order]
        fluid_mass = raw_mass[order]
        if not np.isfinite(fluid_position).all() or not np.isfinite(fluid_velocity).all():
            raise ValueError(f"decoded frame {frame_index} has non-finite fluid position or velocity")
        if not np.isfinite(fluid_mass).all() or np.any(fluid_mass <= 0.0):
            raise ValueError(f"decoded frame {frame_index} has non-positive or non-finite fluid mass")
        position[frame_index] = fluid_position
        velocity[frame_index] = fluid_velocity.astype(np.float32)
        mass[frame_index] = fluid_mass.astype(np.float32)

    if times[0] != 0.0 or np.any(np.diff(times) <= 0.0):
        raise ValueError("decoded native times must start exactly at zero and increase strictly")
    if not np.isfinite(mass).all() or np.any(mass <= 0.0):
        raise ValueError("fluid mass is not representable as positive finite float32")
    table = validate_fluid_table(NativeFluidTable(
        times, fluid, position, velocity, mass, valid, case_id, generated_hash,
        provenance["definition"]["sha256"] if provenance else "",
        provenance["receipt"]["path"] if provenance else "",
        provenance["receipt"]["sha256"] if provenance else "",
        sha256_file(FROZEN_SCOPE_RECEIPT) if provenance else "",
        sha256_file(FROZEN_PARAMETER_CONTRACT) if provenance else "",
    ))
    assign_plane_cohorts(table.position_m[0, :, 2], table.particle_id, dp, half_height)
    return table


def write_fluid_table(path: Path, table: NativeFluidTable) -> Path:
    """Write an immutable Core schema-v3 HDF5 table after full validation."""
    checked = validate_fluid_table(table)
    if not checked.generation_receipt_path:
        raise ValueError("refusing to write an unbound F8 fluid table without a verified GenCase receipt")
    generation = verify_gencase_receipt(Path(checked.generation_receipt_path), checked.case_id)
    if not (
        generation["generated_xml_sha256"] == checked.generated_xml_sha256
        and generation["definition"]["sha256"] == checked.definition_sha256
        and generation["receipt"]["sha256"] == checked.generation_receipt_sha256
        and checked.scope_receipt_sha256 == sha256_file(FROZEN_SCOPE_RECEIPT)
        and checked.parameter_contract_sha256 == sha256_file(FROZEN_PARAMETER_CONTRACT)
    ):
        raise ValueError("fluid table provenance no longer matches frozen R008 inputs")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(target, "x") as handle:
        handle.attrs.update(
            schema="core.cfd.v1",
            schema_version=3,
            f8_table_schema=TABLE_SCHEMA,
            scope_id=SCOPE_ID,
            case_id=checked.case_id,
            identity_key="particle_id",
            trajectory_semantics="native numerical particle identity; not material identity",
            generated_xml_sha256=checked.generated_xml_sha256,
            definition_sha256=checked.definition_sha256,
            generation_receipt_path=checked.generation_receipt_path,
            generation_receipt_sha256=checked.generation_receipt_sha256,
            frozen_scope_receipt_sha256=checked.scope_receipt_sha256,
            parameter_contract_sha256=checked.parameter_contract_sha256,
        )
        handle.create_dataset("time", data=checked.time_s, dtype="f8")
        handle.create_dataset("particle_id", data=checked.particle_id, dtype="u4")
        handle.create_dataset("position", data=checked.position_m, dtype="f8", compression="lzf")
        handle.create_dataset("velocity", data=checked.velocity_m_s, dtype="f4", compression="lzf")
        handle.create_dataset("mass", data=checked.mass_kg, dtype="f4", compression="lzf")
        handle.create_dataset("valid", data=checked.valid, dtype="bool", compression="lzf")
    return target


def read_fluid_table(path: Path, *, generation_receipt_path: Path, case_id: str | None = None) -> NativeFluidTable:
    expected_case = case_id
    receipt = json.loads(Path(generation_receipt_path).read_text(encoding="utf-8"))
    if expected_case is None:
        expected_case = receipt.get("case_id")
        if expected_case is None and isinstance(receipt.get("input", {}).get("definition"), dict):
            expected_case = Path(receipt["input"]["definition"]["path"]).parent.name
    if not isinstance(expected_case, str) or not expected_case:
        raise ValueError("case_id is required to read an R008 native fluid table")
    generation = verify_gencase_receipt(generation_receipt_path, expected_case)
    expected_fluid_ids, _, expected_xml_hash = generated_xml_cohorts(Path(generation["generated_xml"]["path"]))
    with h5py.File(path, "r") as handle:
        if (
            handle.attrs.get("schema") != "core.cfd.v1"
            or int(handle.attrs.get("schema_version", -1)) != 3
            or handle.attrs.get("f8_table_schema") != TABLE_SCHEMA
            or handle.attrs.get("scope_id") != SCOPE_ID
        ):
            raise ValueError("HDF5 file does not match the proposed F8 fluid-table contract")
        if set(handle.keys()) != {"time", "particle_id", "position", "velocity", "mass", "valid"}:
            raise ValueError("F8 fluid-only table contains missing or unregistered datasets")
        for name, dtype in (("time", "f8"), ("particle_id", "u4"), ("position", "f8"),
                            ("velocity", "f4"), ("mass", "f4"), ("valid", "bool")):
            if name not in handle or handle[name].dtype != np.dtype(dtype):
                raise ValueError(f"F8 fluid-table dataset {name} is missing or has the wrong dtype")
        ids = handle["particle_id"][:]
        if not np.array_equal(ids, _canonical_ids(expected_fluid_ids, "expected fluid IDs")):
            raise ValueError("HDF5 fluid particle axis differs from the hash-bound generated XML cohort")
        stored_case_id = str(handle.attrs.get("case_id", ""))
        if case_id is not None and stored_case_id != case_id:
            raise ValueError("HDF5 case_id differs from the requested frozen matrix row")
        hash_value = handle.attrs.get("generated_xml_sha256", "")
        if isinstance(hash_value, bytes):
            hash_value = hash_value.decode("ascii")
        if hash_value != expected_xml_hash:
            raise ValueError("HDF5 generated XML hash differs from its supplied cohort source")
        stored_definition_hash = str(handle.attrs.get("definition_sha256", ""))
        stored_generation_path = str(handle.attrs.get("generation_receipt_path", ""))
        stored_generation_hash = str(handle.attrs.get("generation_receipt_sha256", ""))
        stored_scope_hash = str(handle.attrs.get("frozen_scope_receipt_sha256", ""))
        stored_parameter_hash = str(handle.attrs.get("parameter_contract_sha256", ""))
        if stored_case_id != expected_case:
            raise ValueError("HDF5 case_id differs from its verified GenCase receipt")
        if not (
            stored_definition_hash == generation["definition"]["sha256"]
            and Path(stored_generation_path).resolve() == Path(generation["receipt"]["path"]).resolve()
            and stored_generation_hash == generation["receipt"]["sha256"]
            and stored_scope_hash == sha256_file(FROZEN_SCOPE_RECEIPT)
            and stored_parameter_hash == sha256_file(FROZEN_PARAMETER_CONTRACT)
        ):
            raise ValueError("HDF5 provenance differs from its frozen Definition, GenCase, scope, or parameter contract")
        table = NativeFluidTable(
            handle["time"][:], ids, handle["position"][:], handle["velocity"][:],
            handle["mass"][:], handle["valid"][:], stored_case_id, str(hash_value),
            stored_definition_hash, stored_generation_path, stored_generation_hash,
            stored_scope_hash, stored_parameter_hash,
            str(Path(path).resolve()), sha256_file(Path(path)),
        )
    return validate_fluid_table(table)


def assign_plane_cohorts(initial_z_m: Any, particle_ids: Any, dp_m: float, half_height_m: float) -> tuple[np.ndarray, np.ndarray]:
    z = np.asarray(initial_z_m, dtype=np.float64)
    ids = _canonical_ids(particle_ids, "fluid particle IDs")
    dp = _finite_scalar(dp_m, "dp_m", positive=True)
    half_height = _finite_scalar(half_height_m, "half_height_m", positive=True)
    if z.shape != ids.shape or not np.isfinite(z).all():
        raise ValueError("initial z and fluid ID axes must have matching finite shapes")
    intervals_float = 2.0 * half_height / dp
    intervals = round(intervals_float)
    if not math.isclose(intervals_float, intervals, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("2H/dp must be an integer number of spacing intervals")
    tolerance = max(1e-6 * dp, PLANE_ABSOLUTE_TOLERANCE_M)
    if np.any(np.abs(z) > half_height + tolerance):
        raise ValueError("initial fluid particle lies outside the closed wall interval")
    plane_indices = np.rint((z + half_height) / dp).astype(np.int64)
    plane_z = -half_height + np.arange(intervals + 1, dtype=np.float64) * dp
    if np.any(plane_indices < 0) or np.any(plane_indices > intervals):
        raise ValueError("initial fluid particle lies outside the registered wall planes")
    if np.any(np.abs(z - plane_z[plane_indices]) > tolerance):
        raise ValueError("initial fluid particle does not map uniquely to a registered z plane")
    counts = np.bincount(plane_indices, minlength=intervals + 1)
    if len(counts) != intervals + 1 or np.any(counts == 0):
        raise ValueError("every registered fluid z plane must have a non-empty immutable particle cohort")
    return plane_indices, plane_z


def mass_weighted_velocity_profile(velocity_m_s: Any, mass_kg: Any, plane_indices: Any, plane_count: int) -> np.ndarray:
    velocity = np.asarray(velocity_m_s, dtype=np.float64)
    mass = np.asarray(mass_kg, dtype=np.float64)
    planes = np.asarray(plane_indices, dtype=np.int64)
    if velocity.ndim != 3 or velocity.shape[2] != 3:
        raise ValueError("velocity must have shape [T,P,3]")
    if mass.shape != velocity.shape[:2] or planes.shape != (velocity.shape[1],):
        raise ValueError("mass or immutable plane cohort axis does not match velocity")
    if not np.isfinite(velocity).all() or not np.isfinite(mass).all() or np.any(mass <= 0.0):
        raise ValueError("profile reduction requires finite velocity and positive finite mass")
    if np.any(planes < 0) or np.any(planes >= plane_count):
        raise ValueError("particle plane index is outside the registered profile")
    result = np.empty((velocity.shape[0], plane_count), dtype=np.float64)
    for plane in range(plane_count):
        cohort = planes == plane
        if not np.any(cohort):
            raise ValueError(f"registered plane {plane} has an empty fluid cohort")
        weights = mass[:, cohort]
        denominator = weights.sum(axis=1)
        if np.any(denominator <= 0.0):
            raise ValueError("plane cohort has non-positive total mass")
        result[:, plane] = (weights * velocity[:, cohort, 0]).sum(axis=1) / denominator
    return result


def fit_harmonic_coefficients(time_s: Any, signal: Any, omega_rad_s: float) -> dict[str, float]:
    """Fit mean+a*sin(omega*t)+b*cos(omega*t) at fixed omega and absolute time."""
    times = np.asarray(time_s, dtype=np.float64)
    values = np.asarray(signal, dtype=np.float64)
    omega = _finite_scalar(omega_rad_s, "omega_rad_s", positive=True)
    if times.ndim != 1 or values.shape != times.shape or len(times) < 4:
        raise ValueError("harmonic fit requires matching one-dimensional arrays with at least four rows")
    if not np.isfinite(times).all() or not np.isfinite(values).all():
        raise ValueError("harmonic fit inputs must be finite")
    if np.any(np.diff(times) <= 0.0):
        raise ValueError("harmonic fit times must be strictly increasing")
    design = np.column_stack((np.ones(len(times)), np.sin(omega * times), np.cos(omega * times)))
    coefficients, _, rank, _ = np.linalg.lstsq(design, values, rcond=None)
    if rank != 3 or not np.isfinite(coefficients).all():
        raise ValueError("fixed-frequency harmonic design must have finite rank-three coefficients")
    mean, sine, cosine = map(float, coefficients)
    amplitude = math.hypot(sine, cosine)
    phase = math.atan2(cosine, sine)
    return {
        "mean_m_s": mean,
        "sine_coefficient_a_m_s": sine,
        "cosine_coefficient_b_m_s": cosine,
        "amplitude_m_s": amplitude,
        "phase_rad": phase,
    }


def wrapped_phase_difference(phase_a_rad: float, phase_b_rad: float) -> float:
    a = _finite_scalar(phase_a_rad, "phase_a_rad")
    b = _finite_scalar(phase_b_rad, "phase_b_rad")
    return abs(math.atan2(math.sin(a - b), math.cos(a - b)))


def three_cycle_mean_fluxes(time_s: Any, instantaneous_flux_m3_s_per_m: Any,
                            period_s: float, samples_per_period: int) -> np.ndarray:
    times = np.asarray(time_s, dtype=np.float64)
    flux = np.asarray(instantaneous_flux_m3_s_per_m, dtype=np.float64)
    period = _finite_scalar(period_s, "period_s", positive=True)
    if isinstance(samples_per_period, bool) or int(samples_per_period) != samples_per_period or samples_per_period < 1:
        raise ValueError("samples_per_period must be a positive integer")
    n = int(samples_per_period)
    if times.ndim != 1 or flux.shape != times.shape or len(times) != 3 * n + 1:
        raise ValueError("three-cycle flux requires exactly 3N+1 aligned native rows")
    if not np.isfinite(times).all() or not np.isfinite(flux).all() or np.any(np.diff(times) <= 0.0):
        raise ValueError("cycle flux times and samples must be finite with increasing times")
    dt = period / n
    if not np.allclose(np.diff(times), dt, rtol=0.0, atol=1e-12):
        raise ValueError("cycle flux rows do not have the frozen native cadence")
    means = np.empty(3, dtype=np.float64)
    for cycle in range(3):
        first, last = cycle * n, (cycle + 1) * n
        if last - first != n:
            raise AssertionError("internal cycle partition error")
        means[cycle] = np.trapezoid(flux[first:last + 1], times[first:last + 1]) / period
    if not np.isfinite(means).all():
        raise ValueError("cycle means are non-finite")
    return means


def transverse_velocity_rms(velocity_m_s: Any, mass_kg: Any) -> float:
    velocity = np.asarray(velocity_m_s, dtype=np.float64)
    mass = np.asarray(mass_kg, dtype=np.float64)
    if velocity.ndim != 3 or velocity.shape[2] != 3 or mass.shape != velocity.shape[:2]:
        raise ValueError("transverse RMS requires velocity [T,P,3] and mass [T,P]")
    if not np.isfinite(velocity).all() or not np.isfinite(mass).all() or np.any(mass <= 0.0):
        raise ValueError("transverse RMS requires finite velocity and positive finite mass")
    denominator = float(mass.sum())
    if denominator <= 0.0:
        raise ValueError("transverse RMS total mass must be positive")
    square = velocity[:, :, 1] ** 2 + velocity[:, :, 2] ** 2
    return float(math.sqrt(float(np.sum(mass * square)) / denominator))


def evaluate_case_metrics(table: NativeFluidTable, case_row: Mapping[str, Any],
                          parameter_contract: Mapping[str, Any], *,
                          solver_timestep_audit_path: Path | None = None,
                          generation_receipt_path: Path | None = None) -> dict[str, Any]:
    _assert_frozen_inputs()
    checked = validate_fluid_table(table)
    if checked.case_id != case_row.get("case_id"):
        raise ValueError("native fluid table case_id differs from the frozen R008 case row")
    frozen_scope = json.loads(FROZEN_SCOPE_RECEIPT.read_text(encoding="utf-8"))
    frozen_rows = frozen_scope["matrix"]["rows"]
    frozen_row = next((row for row in frozen_rows if row["case_id"] == case_row.get("case_id")), None)
    if frozen_scope.get("scope_id") != SCOPE_ID or frozen_row is None or dict(case_row) != frozen_row:
        raise ValueError("case row differs from the frozen R008 qualification matrix")
    frozen_parameters = json.loads(FROZEN_PARAMETER_CONTRACT.read_text(encoding="utf-8"))
    if dict(parameter_contract) != frozen_parameters:
        raise ValueError("physical constants or numerical limits differ from the frozen F8 parameter contract")
    receipt_path = generation_receipt_path
    if receipt_path is None and checked.generation_receipt_path:
        receipt_path = Path(checked.generation_receipt_path)
    provenance: dict[str, Any] | None = None
    provenance_verified = False
    if receipt_path is not None:
        generation = verify_gencase_receipt(receipt_path, str(case_row["case_id"]))
        expected_receipt = generation["receipt"]
        if not (
            checked.generated_xml_sha256 == generation["generated_xml_sha256"]
            and checked.definition_sha256 == generation["definition"]["sha256"]
            and Path(checked.generation_receipt_path).resolve() == Path(expected_receipt["path"]).resolve()
            and checked.generation_receipt_sha256 == expected_receipt["sha256"]
            and checked.scope_receipt_sha256 == sha256_file(FROZEN_SCOPE_RECEIPT)
            and checked.parameter_contract_sha256 == sha256_file(FROZEN_PARAMETER_CONTRACT)
        ):
            raise ValueError("native fluid table provenance differs from the frozen Definition/GenCase/scope/parameter inputs")
        if checked.source_table_path:
            checked = read_fluid_table(
                Path(checked.source_table_path), generation_receipt_path=receipt_path,
                case_id=str(case_row["case_id"]),
            )
            provenance_verified = True
            provenance = {
                "case_id": checked.case_id,
                "definition": generation["definition"],
                "generated_xml": generation["generated_xml"],
                "generation_receipt": generation["receipt"],
                "table": {
                    "path": checked.source_table_path,
                    "bytes": Path(checked.source_table_path).stat().st_size,
                    "sha256": checked.source_table_sha256,
                },
                "scope_receipt_sha256": checked.scope_receipt_sha256,
                "parameter_contract_sha256": checked.parameter_contract_sha256,
            }
    geometry = parameter_contract["geometry_and_fluid"]
    forcing = parameter_contract["parameterization"]
    gates = parameter_contract["error_gates"]
    half_height = float(geometry["half_height_m"])
    viscosity = float(geometry["kinematic_viscosity_m2_s"])
    acceleration = float(forcing["acceleration_amplitude_m_s2"])
    omega = float(case_row["omega_rad_s"])
    period = float(case_row["period_s"])
    if not math.isclose(2.0 * math.pi / period, omega, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("case period and omega disagree")
    selected_times, selected_velocity = select_closed_native_window(
        checked.time_s, checked.velocity_m_s,
        start_s=float(case_row["observation_start_s"]),
        end_s=float(case_row["observation_end_s"]),
        period_s=period,
        output_samples_per_period=int(case_row["native_output_samples_per_period"]),
        cycles=int(case_row["observation_cycles"]),
    )
    first = int(np.searchsorted(checked.time_s, selected_times[0]))
    last = first + len(selected_times)
    selected_mass = checked.mass_kg[first:last]
    plane_indices, plane_z = assign_plane_cohorts(
        checked.position_m[0, :, 2], checked.particle_id,
        float(case_row["dp_m"]), half_height,
    )
    profile = mass_weighted_velocity_profile(selected_velocity, selected_mass, plane_indices, len(plane_z))
    intervals = len(plane_z) - 1
    interior = np.arange(1, intervals, dtype=np.int64)
    parameters = ChannelParameters(half_height, viscosity, omega, acceleration)
    reference = steady_velocity(selected_times, plane_z[interior], parameters)
    observed_coefficients = [fit_harmonic_coefficients(selected_times, profile[:, index], omega)
                             for index in range(len(plane_z))]
    reference_coefficients = [fit_harmonic_coefficients(selected_times, reference[:, local], omega)
                              for local, index in enumerate(interior)]
    amplitude_errors: list[float] = []
    phase_errors: list[float] = []
    for local, plane_index in enumerate(interior):
        observed = observed_coefficients[int(plane_index)]
        expected = reference_coefficients[local]
        if expected["amplitude_m_s"] <= 0.0:
            raise ValueError("continuum profile amplitude is non-positive at an interior plane")
        amplitude_errors.append(abs(observed["amplitude_m_s"] - expected["amplitude_m_s"]) /
                                expected["amplitude_m_s"])
        phase_errors.append(wrapped_phase_difference(observed["phase_rad"], expected["phase_rad"]))

    instantaneous_flux = np.asarray([
        cross_sectional_flux_per_width(plane_z, row) for row in profile
    ], dtype=np.float64)
    cycle_means = three_cycle_mean_fluxes(
        selected_times, instantaneous_flux, period,
        int(case_row["native_output_samples_per_period"]),
    )
    u_ref = acceleration / omega
    flux_ratio = float(np.max(np.abs(cycle_means)) / (u_ref * 2.0 * half_height))
    transverse_rms = transverse_velocity_rms(selected_velocity, selected_mass)
    transverse_ratio = transverse_rms / u_ref
    center_series = np.asarray([np.interp(0.0, plane_z, row) for row in profile])
    center_coefficients = fit_harmonic_coefficients(selected_times, center_series, omega)
    solver_timestep_audit = None
    solver_max_dt_s = None
    if solver_timestep_audit_path is not None:
        solver_max_dt_s, solver_timestep_audit = _load_solver_timestep_audit(
            solver_timestep_audit_path, str(case_row["case_id"]),
        )

    metric_values = {
        "profile_amplitude_relative_error_max": float(max(amplitude_errors)),
        "profile_phase_absolute_error_max_rad": float(max(phase_errors)),
        "cycle_mean_fluxes_m3_s_per_m": cycle_means.tolist(),
        "cycle_mean_flux_ratio": flux_ratio,
        "transverse_velocity_rms_m_s": transverse_rms,
        "transverse_velocity_rms_ratio": transverse_ratio,
        "u_ref_m_s": u_ref,
    }
    metric_gates = {
        "profile_amplitude": metric_values["profile_amplitude_relative_error_max"] <= float(gates["profile_amplitude_relative_max"]),
        "profile_phase": metric_values["profile_phase_absolute_error_max_rad"] <= float(gates["profile_phase_absolute_max_rad"]),
        "cycle_mean_flux": flux_ratio <= float(gates["cycle_mean_flux_over_uref_area_max"]),
        "transverse_velocity_rms": transverse_ratio <= float(gates["transverse_velocity_rms_over_uref_max"]),
    }
    coefficients = {
        key: [float(value[key]) for value in observed_coefficients]
        for key in ("mean_m_s", "sine_coefficient_a_m_s", "cosine_coefficient_b_m_s", "amplitude_m_s", "phase_rad")
    }
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE_ID,
        "frozen_scope_receipt_sha256": sha256_file(FROZEN_SCOPE_RECEIPT),
        "parameter_contract_sha256": sha256_file(FROZEN_PARAMETER_CONTRACT),
        "case_id": str(case_row["case_id"]),
        "status": "case_provenance_verified" if provenance_verified else "diagnostic_metrics_only_unbound_table",
        "provenance_verified": provenance_verified,
        "provenance": provenance,
        "selected_time_s": selected_times.tolist(),
        "maximum_saved_output_dt_s": float(np.max(np.diff(checked.time_s))),
        "solver_max_dt_s": solver_max_dt_s,
        "solver_timestep_audit": solver_timestep_audit,
        "profile_z_m": plane_z.tolist(),
        "plane_coefficients": coefficients,
        "center_coefficients": center_coefficients,
        "metrics": metric_values,
        "metric_gates": metric_gates,
        "metric_gates_passed": all(metric_gates.values()),
        "native_integrity_gates_evaluated": False,
        "full_t1_decision": False,
        "qualification_credit": 0,
    }


def compare_profile_coefficients(candidate: Mapping[str, Any], production: Mapping[str, Any],
                                 common_z_m: Any, *, amplitude_relative_max: float,
                                 phase_absolute_max_rad: float) -> dict[str, Any]:
    common = np.asarray(common_z_m, dtype=np.float64)
    if common.ndim != 1 or len(common) == 0 or not np.isfinite(common).all() or np.any(np.diff(common) <= 0.0):
        raise ValueError("cross-resolution common z grid must be finite, nonempty, and increasing")
    candidate_z = np.asarray(candidate["profile_z_m"], dtype=np.float64)
    production_z = np.asarray(production["profile_z_m"], dtype=np.float64)
    if any(z.ndim != 1 or len(z) < 2 or not np.isfinite(z).all() or np.any(np.diff(z) <= 0.0)
           for z in (candidate_z, production_z)):
        raise ValueError("cross-resolution source profiles must be strictly increasing")
    if (common[0] < candidate_z[0] or common[-1] > candidate_z[-1]
            or common[0] < production_z[0] or common[-1] > production_z[-1]):
        raise ValueError("cross-resolution profile interpolation would extrapolate")
    def coefficients(result: Mapping[str, Any], z: np.ndarray, key: str) -> np.ndarray:
        values = np.asarray(result["plane_coefficients"][key], dtype=np.float64)
        if values.shape != z.shape or not np.isfinite(values).all():
            raise ValueError(f"cross-resolution coefficient {key} does not match its finite z grid")
        return values

    candidate_a = np.interp(common, candidate_z, coefficients(candidate, candidate_z, "sine_coefficient_a_m_s"))
    candidate_b = np.interp(common, candidate_z, coefficients(candidate, candidate_z, "cosine_coefficient_b_m_s"))
    production_a = np.interp(common, production_z, coefficients(production, production_z, "sine_coefficient_a_m_s"))
    production_b = np.interp(common, production_z, coefficients(production, production_z, "cosine_coefficient_b_m_s"))
    candidate_amp = np.hypot(candidate_a, candidate_b)
    production_amp = np.hypot(production_a, production_b)
    if np.any(production_amp <= 0.0) or not np.isfinite(production_amp).all():
        raise ValueError("production profile has a non-positive cross-resolution amplitude denominator")
    amplitude_error = np.abs(candidate_amp - production_amp) / production_amp
    candidate_phase = np.arctan2(candidate_b, candidate_a)
    production_phase = np.arctan2(production_b, production_a)
    phase_error = np.abs(np.arctan2(np.sin(candidate_phase - production_phase),
                                   np.cos(candidate_phase - production_phase)))
    amplitude_max = _finite_scalar(amplitude_relative_max, "amplitude_relative_max")
    phase_max = _finite_scalar(phase_absolute_max_rad, "phase_absolute_max_rad")
    if amplitude_max < 0.0 or phase_max < 0.0:
        raise ValueError("cross-resolution limits must be nonnegative")
    return {
        "maximum_relative_amplitude_difference": float(np.max(amplitude_error)),
        "maximum_wrapped_phase_difference_rad": float(np.max(phase_error)),
        "amplitude_limit": amplitude_max,
        "phase_limit_rad": phase_max,
        "passed": bool(np.max(amplitude_error) <= amplitude_max and np.max(phase_error) <= phase_max),
        "extrapolation_performed": False,
    }


def _load_solver_timestep_audit(path: Path, case_id: str) -> tuple[float, dict[str, Any]]:
    report_path = Path(path).resolve()
    if not report_path.is_file():
        raise ValueError("solver timestep audit receipt does not exist")
    receipt = json.loads(report_path.read_text(encoding="utf-8"))
    if (
        receipt.get("schema") != "core.cfd.f8.r008_solver_timestep_audit.v1"
        or receipt.get("status") != "passed"
        or receipt.get("case_id") != case_id
        or not isinstance(receipt.get("checks"), dict)
        or not receipt["checks"]
        or not all(value is True for value in receipt["checks"].values())
    ):
        raise ValueError("solver timestep audit is absent, failed, or bound to another case")
    maximum_step = _finite_scalar(receipt.get("max_solver_dt_s"), "max_solver_dt_s", positive=True)
    source = receipt.get("source_log")
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        raise ValueError("solver timestep audit must bind its native source log")
    source_path = Path(source["path"])
    if not source_path.is_absolute():
        source_path = LAB / source_path
    if not source_path.is_file():
        raise ValueError("bound native solver timestep source log is missing")
    observed_bytes = source_path.stat().st_size
    observed_hash = sha256_file(source_path)
    if source.get("bytes") != observed_bytes or source.get("sha256") != observed_hash:
        raise ValueError("bound native solver timestep source log changed")
    return maximum_step, {
        "path": str(report_path),
        "bytes": report_path.stat().st_size,
        "sha256": sha256_file(report_path),
        "source_log": {
            "path": str(source_path),
            "bytes": observed_bytes,
            "sha256": observed_hash,
        },
    }


def evaluate_metric_matrix(case_results: Mapping[str, Mapping[str, Any]],
                           rows: Sequence[Mapping[str, Any]],
                           comparisons: Sequence[Mapping[str, Any]], *,
                           half_height_m: float, production_dp_m: float,
                           time_step_comparison: Mapping[str, Any],
                           output_cadence_comparison: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate the 15-row metric/comparison gates, not the full T1 integrity gate."""
    _assert_frozen_inputs()
    frozen_scope = json.loads(FROZEN_SCOPE_RECEIPT.read_text(encoding="utf-8"))
    frozen_matrix = frozen_scope["matrix"]
    frozen_applicability = frozen_scope["predeclared_t1_gates"]["gate_applicability_by_case_and_comparison"]
    parameters = json.loads(FROZEN_PARAMETER_CONTRACT.read_text(encoding="utf-8"))
    if not (
        frozen_scope.get("scope_id") == SCOPE_ID
        and list(rows) == frozen_matrix["rows"]
        and list(comparisons) == frozen_applicability["cross_resolution_comparisons"]
        and dict(time_step_comparison) == frozen_applicability["time_step_comparison"]
        and dict(output_cadence_comparison) == frozen_applicability["output_cadence_comparison"]
    ):
        raise ValueError("metric adjudication inputs differ from the hash-bound frozen R008 scope")
    frozen_half_height = float(parameters["geometry_and_fluid"]["half_height_m"])
    frozen_production_dp = float(parameters["resolution_contract"]["production_dp_m"])
    if not (
        math.isclose(float(half_height_m), frozen_half_height, rel_tol=0.0, abs_tol=1e-12)
        and math.isclose(float(production_dp_m), frozen_production_dp, rel_tol=0.0, abs_tol=1e-12)
    ):
        raise ValueError("cross-resolution target grid must use the frozen H and production dp")
    row_by_id = {str(row["case_id"]): row for row in rows}
    if len(row_by_id) != 15 or set(case_results) != set(row_by_id):
        raise ValueError("metric adjudication requires exactly the frozen 15 unique R008 case rows")

    verified_results: dict[str, Mapping[str, Any]] = {}
    for case_id, row in row_by_id.items():
        result = case_results[case_id]
        provenance = result.get("provenance")
        if (result.get("schema") != SCHEMA or result.get("case_id") != case_id
                or result.get("provenance_verified") is not True or not isinstance(provenance, dict)):
            raise ValueError(f"metric matrix requires case-bound immutable provenance: {case_id}")
        generation_receipt = provenance.get("generation_receipt")
        if not isinstance(generation_receipt, dict) or not generation_receipt.get("path"):
            raise ValueError(f"metric result has no bound GenCase receipt: {case_id}")
        generation = verify_gencase_receipt(Path(generation_receipt["path"]), case_id)
        table_path, table_binding = _verified_file_binding(provenance.get("table", {}), "native fluid HDF5 table")
        if not (
            provenance.get("case_id") == case_id
            and provenance.get("definition") == generation["definition"]
            and provenance.get("generated_xml") == generation["generated_xml"]
            and provenance.get("generation_receipt") == generation["receipt"]
            and provenance.get("scope_receipt_sha256") == sha256_file(FROZEN_SCOPE_RECEIPT)
            and provenance.get("parameter_contract_sha256") == sha256_file(FROZEN_PARAMETER_CONTRACT)
            and provenance.get("table") == table_binding
        ):
            raise ValueError(f"metric provenance differs from frozen R008 sources: {case_id}")
        table = read_fluid_table(
            table_path, generation_receipt_path=Path(generation_receipt["path"]), case_id=case_id,
        )
        if table.source_table_sha256 != table_binding["sha256"]:
            raise ValueError(f"native fluid HDF5 changed after metric evaluation: {case_id}")
        timestep_audit = result.get("solver_timestep_audit")
        recomputed = evaluate_case_metrics(
            table, row, parameters,
            solver_timestep_audit_path=Path(timestep_audit["path"]) if isinstance(timestep_audit, dict) else None,
            generation_receipt_path=Path(generation_receipt["path"]),
        )
        compared_fields = (
            "scope_id", "frozen_scope_receipt_sha256", "parameter_contract_sha256",
            "status", "provenance_verified", "provenance", "selected_time_s",
            "maximum_saved_output_dt_s", "solver_max_dt_s", "solver_timestep_audit",
            "profile_z_m", "plane_coefficients", "center_coefficients", "metrics",
            "metric_gates", "metric_gates_passed", "native_integrity_gates_evaluated",
            "full_t1_decision", "qualification_credit",
        )
        if any(result.get(field) != recomputed.get(field) for field in compared_fields):
            raise ValueError(f"case metrics do not recompute from the bound native table: {case_id}")
        verified_results[case_id] = recomputed

    if len(comparisons) != 8:
        raise ValueError("metric adjudication requires exactly eight frozen cross-resolution comparisons")
    intervals = round(2.0 * float(half_height_m) / float(production_dp_m))
    common_z = -float(half_height_m) + np.arange(1, intervals, dtype=np.float64) * float(production_dp_m)
    cross_results = []
    for pair in comparisons:
        candidate_id = pair.get("coarse_case", pair.get("fine_case"))
        production_id = pair["production_case"]
        candidate_row, production_row = row_by_id[candidate_id], row_by_id[production_id]
        if not (
            candidate_row["q"] == production_row["q"]
            and candidate_row["period_s"] == production_row["period_s"]
            and candidate_row["observation_start_s"] == production_row["observation_start_s"]
            and candidate_row["observation_end_s"] == production_row["observation_end_s"]
            and candidate_row["native_output_samples_per_period"] == production_row["native_output_samples_per_period"]
            and np.allclose(verified_results[candidate_id]["selected_time_s"],
                            verified_results[production_id]["selected_time_s"], rtol=0.0, atol=1e-12)
        ):
            raise ValueError(f"registered cross-resolution cases do not share the frozen time grid: {pair}")
        result = compare_profile_coefficients(
            verified_results[candidate_id], verified_results[production_id], common_z,
            amplitude_relative_max=float(pair["amplitude_relative_max"]),
            phase_absolute_max_rad=float(pair["phase_absolute_max_rad"]),
        )
        cross_results.append({"candidate_case_id": candidate_id, "production_case_id": production_id, **result})

    baseline_id = str(time_step_comparison["baseline_case_id"])
    refined_id = str(time_step_comparison["case_id"])
    baseline, refined = verified_results[baseline_id], verified_results[refined_id]
    timestep_phase_difference = wrapped_phase_difference(
        baseline["center_coefficients"]["phase_rad"], refined["center_coefficients"]["phase_rad"]
    )
    baseline_solver_dt = baseline.get("solver_max_dt_s")
    refined_solver_dt = refined.get("solver_max_dt_s")
    for case_id, result in ((baseline_id, baseline), (refined_id, refined)):
        audit = result.get("solver_timestep_audit")
        if not isinstance(audit, dict) or not audit.get("path"):
            raise ValueError("time-step comparison requires measured and hash-bound solver timestep audits")
        verified_dt, verified_audit = _load_solver_timestep_audit(Path(audit["path"]), case_id)
        if verified_dt != result.get("solver_max_dt_s") or verified_audit != audit:
            raise ValueError("solver timestep metric result does not match its immutable audit receipt")
    if baseline_solver_dt is None or refined_solver_dt is None:
        raise ValueError("time-step comparison is missing a measured solver timestep maximum")
    time_step_passed = bool(
        baseline["metric_gates_passed"] and refined["metric_gates_passed"]
        and refined_solver_dt < baseline_solver_dt
        and timestep_phase_difference <= float(time_step_comparison["phase_difference_absolute_max_rad"])
    )

    cadence_baseline_id = str(output_cadence_comparison["baseline_case_id"])
    dense_id = str(output_cadence_comparison["case_id"])
    cadence_baseline, dense = verified_results[cadence_baseline_id], verified_results[dense_id]
    dense_times = np.asarray(dense["selected_time_s"], dtype=np.float64)
    baseline_times = np.asarray(cadence_baseline["selected_time_s"], dtype=np.float64)
    downsampled = dense_times[::2]
    cadence_passed = bool(
        cadence_baseline["metric_gates_passed"] and dense["metric_gates_passed"]
        and len(downsampled) == len(baseline_times)
        and np.allclose(downsampled, baseline_times, rtol=0.0, atol=1e-12)
    )
    all_case_metrics_passed = all(verified_results[key]["metric_gates_passed"] for key in row_by_id)
    all_comparisons_passed = all(item["passed"] for item in cross_results)
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE_ID,
        "frozen_scope_receipt_sha256": sha256_file(FROZEN_SCOPE_RECEIPT),
        "status": "metric_and_comparison_gates_evaluated_native_integrity_pending",
        "case_count": len(row_by_id),
        "case_metric_gates_passed": all_case_metrics_passed,
        "cross_resolution": cross_results,
        "cross_resolution_gates_passed": all_comparisons_passed,
        "time_step_comparison": {
            "baseline_case_id": baseline_id,
            "refined_case_id": refined_id,
            "baseline_solver_max_dt_s": baseline_solver_dt,
            "refined_solver_max_dt_s": refined_solver_dt,
            "wrapped_center_phase_difference_rad": timestep_phase_difference,
            "passed": time_step_passed,
        },
        "output_cadence_comparison": {
            "baseline_case_id": cadence_baseline_id,
            "dense_case_id": dense_id,
            "downsampled_timestamp_match": bool(len(downsampled) == len(baseline_times)
                                                  and np.allclose(downsampled, baseline_times, rtol=0.0, atol=1e-12)),
            "passed": cadence_passed,
        },
        "all_metric_and_comparison_gates_passed": bool(
            all_case_metrics_passed and all_comparisons_passed and time_step_passed and cadence_passed
        ),
        "native_integrity_gates_evaluated": False,
        "full_t1_decision": False,
        "qualification_credit": 0,
        "execution_authority": {"solver": False, "gpu": False, "worker": False, "queue": False},
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = [
    "SCHEMA", "TABLE_SCHEMA", "SCOPE_ID", "NativeFluidTable",
    "generated_xml_cohorts", "verify_gencase_receipt", "validate_raw_frame_ids",
    "validate_fluid_table", "build_native_fluid_table",
    "write_fluid_table", "read_fluid_table", "assign_plane_cohorts",
    "mass_weighted_velocity_profile", "fit_harmonic_coefficients",
    "wrapped_phase_difference", "three_cycle_mean_fluxes", "transverse_velocity_rms",
    "evaluate_case_metrics", "compare_profile_coefficients", "evaluate_metric_matrix",
    "sha256_file",
]
