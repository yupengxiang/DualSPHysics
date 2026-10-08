#!/usr/bin/env python3
"""Guard-ready F7 half-CFL frame-0 typed initial QA.

The earlier v2 artifact only described a decoder command and left the actual
BI4 content hash/typed comparison pending.  This forward worker is executable
after a parent-approved CPU slot.  It decodes exactly the half and baseline
frame-0 BI4 files into a fresh private namespace, assigns type/MK/mass from
each generated XML, and compares the ``(Zone, Idp)`` identity, position,
valid, type, MK, and initial mass arrays.  It does not run GenCase, a solver,
CFD, HDF5, or a GPU job.

The request deliberately leaves the newly generated half BI4 hash as a
post-reservation value.  ``run --io-slot-approved`` computes it immediately
before decoding and records pre/post stat/hash evidence; a missing, changed,
or stale source fails closed.  The future solver launch remains forbidden
until this QA and motion staging have a new parent-approved request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Mapping

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_f5_bi4 as trusted_bi4


CASE = "F7_OBSTACLE_QUINTIC_B08_A065"
HALF_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_OBSTACLE_QUINTIC_B08_A065/f7-half-cfl-gencase-v8-001-root-001")
BASELINE_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_OBSTACLE_QUINTIC_B08_A065/root-stage1-f7-angle065-genuine-gencase-085")
MOTION = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_TARGET_ANGLE_ENDPOINTS/root-stage1-f7-target030-065-actual-motion-preparation-074/"
    f"prepared/{CASE}/motion_obstacle_quintic.dat")
V5_ROOT = Path(
    "/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/"
    "f7-s2-a065-same-cfl-dense-savedt-v5-001")
DECODER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/"
    "campaigns/l1-resume/artifacts/bi4_dump")
HALF_XML = HALF_ROOT / "prepared" / f"{CASE}_half_cfl01.xml"
HALF_BI4 = HALF_ROOT / "prepared" / f"{CASE}_half_cfl01.bi4"
BASELINE_XML = BASELINE_ROOT / "prepared" / f"{CASE}.xml"
BASELINE_BI4 = BASELINE_ROOT / "prepared" / f"{CASE}.bi4"
GENCASE_RECEIPT = HALF_ROOT / "execution-receipt.json"
GENCASE_STDOUT = HALF_ROOT / "stdout.log"
# The immutable receipt is indexed under the data family; the large solver
# products remain in the approved NVMe namespace.
V5_RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "f7-obstacle-quintic-b08-a065/f7-s2-a065-same-cfl-dense-savedt-v5-001/execution-receipt.json")
V5_RUNPARTS = V5_ROOT / "solver_output" / "RunPARTs.csv"

REQUEST_SCHEMA = "ds02.stage2.f7-half-cfl-initial-typed-qa-request.v8"
REPORT_SCHEMA = "ds02.stage2.f7-half-cfl-initial-typed-qa.v8"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
BASELINE_BI4_SHA = "f905a45f615304877f2a753471639bf812021d1741df7fcd4b5dc536b258864a"
V5_RECEIPT_SHA = "99db999678d8de10790cee7462d3eed5657b85ced1f52bf561e95e3625e3fa0e"
V5_RUNPARTS_SHA = "832e71d8f914ebc96d741c6df28736fb3880952eea5d301d78c7222cfb43c27c"
MOTION_SHA = "6aedfbd0d7daff931917bcb126368856c63c1bb53ba17aebf9033ebea0067814"
DECODER_SHA = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"


class F7InitialQAError(RuntimeError):
    """A missing, changed, or semantically unsafe initial source."""


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=_json_default).encode()).hexdigest()


def sha256_file(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise F7InitialQAError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise F7InitialQAError(f"JSON object required: {path}")
    return value


def _require_file(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise F7InitialQAError(f"{role} is missing: {target}")
    return target


def _binding(path: Path, role: str, *, content: bool = True,
             expected_sha256: str | None = None) -> dict[str, Any]:
    path = _require_file(path, role)
    stat = path.stat()
    value: dict[str, Any] = {
        "role": role, "path": str(path), "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns,
        "inode": stat.st_ino, "device": stat.st_dev, "mode": stat.st_mode,
    }
    if content:
        value["sha256"] = sha256_file(path)
        value["content_scope"] = "source_content"
    else:
        value["sha256"] = expected_sha256
        value["content_scope"] = "PARENT_GUARD_CONTENT_HASH_REQUIRED"
    return value


def _xml_semantics(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find(".//execution/particles") or root.find(".//particles")
    if particles is None:
        raise F7InitialQAError(f"{path} has no particle block")
    constants = root.find(".//casedef/constantsdef")
    definition = root.find(".//casedef/geometry/definition")
    cfl_node = constants.find("cflnumber") if constants is not None else None
    cfl = float(cfl_node.get("value")) if cfl_node is not None else None
    blocks = {}
    for name in ("fixed", "moving", "fluid"):
        child = particles.find(name)
        if child is not None:
            blocks[name] = {"begin": int(child.get("begin")), "count": int(child.get("count")),
                            "mk": int(child.get("mk", child.get("mkbound", child.get("mkfluid"))))}
    motion = root.find(".//casedef/motion/objreal/mvrotfile")
    return {
        "np": int(particles.get("np")), "nb": int(particles.get("nb")),
        "nbf": int(particles.get("nbf")), "cflnumber": cfl,
        "dp_m": float(definition.get("dp")) if definition is not None else None,
        "blocks": blocks,
        "motion_duration_s": float(motion.get("duration")) if motion is not None else None,
    }


def _snapshot(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns, "inode": stat.st_ino,
            "device": stat.st_dev, "mode": stat.st_mode}


def _verify_immutable_source(path: Path, expected_sha: str, before: Mapping[str, Any], role: str) -> dict[str, Any]:
    after = _snapshot(path)
    if dict(before) != after:
        raise F7InitialQAError(f"{role} stat changed during initial QA")
    actual = sha256_file(path)
    if actual != expected_sha:
        raise F7InitialQAError(f"{role} content SHA differs")
    return {"role": role, "path": str(path), "before": dict(before), "after": after,
            "sha256": actual, "content_verified": True}


_INPUT_PATHS = {
    "half_generated_xml": HALF_XML,
    "baseline_generated_xml": BASELINE_XML,
    "half_gencase_receipt": GENCASE_RECEIPT,
    "half_gencase_stdout": GENCASE_STDOUT,
    "F7_motion_control": MOTION,
    "v5_same_cfl_receipt": V5_RECEIPT,
    "v5_same_cfl_RunPARTs": V5_RUNPARTS,
    "pinned_native_bi4_decoder": DECODER,
    "half_generated_bi4": HALF_BI4,
    "baseline_generated_bi4": BASELINE_BI4,
}
_DEFERRED_CONTENT_ROLES = {"half_generated_bi4"}
_FIXED_CONTENT_SHA = {
    "baseline_generated_bi4": BASELINE_BI4_SHA,
    "F7_motion_control": MOTION_SHA,
    "pinned_native_bi4_decoder": DECODER_SHA,
}


def _request_input_contract(request: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    inputs = request.get("inputs")
    if not isinstance(inputs, Mapping):
        raise F7InitialQAError("v8 request inputs are missing")
    if set(inputs) != set(_INPUT_PATHS):
        raise F7InitialQAError("v8 request input roles are not the frozen ten-role closure")
    result: dict[str, dict[str, Any]] = {}
    for role, expected_path in _INPUT_PATHS.items():
        item = inputs.get(role)
        if not isinstance(item, Mapping):
            raise F7InitialQAError(f"v8 input binding is malformed: {role}")
        actual_path = Path(str(item.get("path", ""))).expanduser().resolve()
        if actual_path != expected_path.resolve():
            raise F7InitialQAError(f"{role} path is not the frozen source path")
        if str(item.get("role")) != role:
            raise F7InitialQAError(f"{role} role field differs")
        frozen = {key: item.get(key) for key in
                  ("bytes", "mtime_ns", "ctime_ns", "inode", "device", "mode")}
        if any(value is None for value in frozen.values()):
            raise F7InitialQAError(f"{role} lacks complete frozen stat binding")
        current = _snapshot(actual_path)
        expected_stat = {key: int(value) for key, value in frozen.items()}
        if current != expected_stat:
            raise F7InitialQAError(f"{role} current stat differs from frozen request")
        expected_sha = item.get("sha256")
        if role in _DEFERRED_CONTENT_ROLES:
            if expected_sha is not None or item.get("content_scope") != "PARENT_GUARD_CONTENT_HASH_REQUIRED":
                raise F7InitialQAError("half BI4 must defer its producer content hash")
        else:
            if not isinstance(expected_sha, str) or len(expected_sha) != 64:
                raise F7InitialQAError(f"{role} lacks a source content SHA")
            fixed = _FIXED_CONTENT_SHA.get(role)
            if fixed is not None and expected_sha != fixed:
                raise F7InitialQAError(f"{role} differs from its frozen known SHA")
        result[role] = {"path": actual_path, "expected_stat": expected_stat,
                        "expected_sha256": expected_sha}
    return result


def _verify_request_sources(contract: Mapping[str, Mapping[str, Any]], *, phase: str,
                            half_sha: str | None = None) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for role, item in contract.items():
        path = Path(item["path"])
        before = dict(item["expected_stat"])
        after = _snapshot(path)
        if after != before:
            raise F7InitialQAError(f"{role} stat differs during {phase}")
        expected = str(item["expected_sha256"] or "")
        if role in _DEFERRED_CONTENT_ROLES:
            expected = half_sha or sha256_file(path)
        actual = sha256_file(path)
        if actual != expected:
            raise F7InitialQAError(f"{role} content SHA differs during {phase}")
        evidence[role] = {"role": role, "path": str(path), "phase": phase,
                           "stat": after, "sha256": actual, "content_verified": True}
    return evidence


def _stage_motion(source: Path, output_dir: Path) -> dict[str, Any]:
    target = output_dir / "solver_input" / source.name
    if target.exists() or target.is_symlink():
        raise F7InitialQAError(f"refusing existing motion target: {target}")
    target.parent.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(source, target)
    source_sha = sha256_file(source)
    target_sha = sha256_file(target)
    if target_sha != source_sha or target.stat().st_size != source.stat().st_size:
        raise F7InitialQAError("staged motion source content differs")
    return {"source": str(source), "source_sha256": source_sha,
            "target": str(target), "target_sha256": target_sha,
            "target_bytes": target.stat().st_size,
            "fallback_forbidden": True, "copied_for_future_solver_only": True}


def _array_summary(name: str, left: np.ndarray, right: np.ndarray) -> dict[str, Any]:
    if left.shape != right.shape:
        return {"name": name, "shape_equal": False, "left_shape": list(left.shape),
                "right_shape": list(right.shape), "exact": False}
    if left.dtype.kind in "fc" or right.dtype.kind in "fc":
        finite = bool(np.isfinite(left).all() and np.isfinite(right).all())
        max_abs = float(np.max(np.abs(left.astype(np.float64) - right.astype(np.float64)))) if left.size else 0.0
    else:
        finite = True
        max_abs = 0.0
    return {"name": name, "shape_equal": True, "left_shape": list(left.shape),
            "right_shape": list(right.shape), "finite": finite,
            "max_abs_error": max_abs, "exact": bool(np.array_equal(left, right))}


def _decode_typed(path: Path, xml: Path, decoder: Path, scratch: Path, tag: str) -> dict[str, Any]:
    try:
        frame = trusted_bi4.decode_frame(path, decoder, scratch / tag, 0)
        blocks = trusted_bi4.parse_particle_blocks(xml)
        base_ids = np.arange(blocks["np"], dtype=np.uint32)
        types, mks = trusted_bi4._assign_types(base_ids, blocks)
        mass = trusted_bi4._mass_for_types(types, frame.metadata)
    except Exception as error:
        raise F7InitialQAError(f"{tag} native frame-0 decode failed: {error}") from error
    if frame.ids.shape != base_ids.shape or not np.array_equal(frame.ids, base_ids):
        raise F7InitialQAError(f"{tag} Idp axis is not the complete GenCase identity axis")
    zone = frame.metadata.get("Piece")
    if isinstance(zone, bool) or not isinstance(zone, (int, float)) or int(zone) != zone:
        raise F7InitialQAError(f"{tag} BI4 Piece/Zone is missing or non-integer")
    if not np.isfinite(frame.position).all() or not np.isfinite(mass).all() or np.any(mass <= 0):
        raise F7InitialQAError(f"{tag} initial position or mass is invalid")
    valid = np.ones(base_ids.size, dtype=bool)
    return {"tag": tag, "frame": frame, "ids": frame.ids, "zone": int(zone),
            "position": frame.position, "type": types, "mk": mks, "mass": mass,
            "valid": valid, "blocks": blocks, "decoder_xml_sha256": frame.decoder_xml_sha256,
            "metadata": frame.metadata, "time_s": frame.time}


def compare_initial_arrays(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    if left["zone"] != right["zone"]:
        raise F7InitialQAError("frame-0 Zone/Piece differs between half and baseline")
    expected_count = 70179
    if left["ids"].size != expected_count or right["ids"].size != expected_count:
        raise F7InitialQAError("frame-0 particle count is not the bound 70179")
    comparisons = [_array_summary(name, left[name], right[name])
                   for name in ("ids", "position", "valid", "type", "mk", "mass")]
    metadata_keys = ("Dp", "B", "Rhop0", "Gamma", "MassBound", "MassFluid")
    metadata = {}
    for key in metadata_keys:
        a, b = left["metadata"].get(key), right["metadata"].get(key)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or not math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12):
            raise F7InitialQAError(f"frame-0 decoder constant differs: {key}")
        metadata[key] = {"half": float(a), "baseline": float(b), "equal": True}
    if not all(item.get("exact") is True for item in comparisons):
        raise F7InitialQAError("half/baseline initial typed arrays differ")
    return {"zone_equal": True, "expected_particle_count": expected_count,
            "arrays": comparisons, "decoder_constants": metadata,
            "valid_all_true": bool(left["valid"].all() and right["valid"].all()),
            "identity_key": "(Zone,Idp)"}


def run_request(request: Mapping[str, Any], *, output_dir: Path, io_slot_approved: bool) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise F7InitialQAError("v8 request schema/canonical hash differs")
    if request.get("status") != "PENDING_PARENT_IO_SLOT" or request.get("launch_allowed") is not False:
        raise F7InitialQAError("v8 request is not a pending development QA")
    if not io_slot_approved:
        raise F7InitialQAError("frame-0 BI4 read requires --io-slot-approved")
    contract = _request_input_contract(request)
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise F7InitialQAError(f"refusing existing output namespace: {output_dir}")
    output_dir.mkdir(parents=True)
    # Every source, including metadata and the pinned native decoder, is
    # checked against the frozen request before and after the decode.  The
    # half BI4 deliberately has no producer SHA in the request; its SHA is
    # observed only after this parent-approved worker starts.
    pre_sources = _verify_request_sources(contract, phase="pre_decode")
    half_before = dict(pre_sources["half_generated_bi4"]["stat"])
    half_sha = str(pre_sources["half_generated_bi4"]["sha256"])
    baseline_binding = pre_sources["baseline_generated_bi4"]
    half_path = Path(contract["half_generated_bi4"]["path"])
    baseline_path = Path(contract["baseline_generated_bi4"]["path"])
    half_xml_path = Path(contract["half_generated_xml"]["path"])
    baseline_xml_path = Path(contract["baseline_generated_xml"]["path"])
    decoder_path = Path(contract["pinned_native_bi4_decoder"]["path"])
    motion_path = Path(contract["F7_motion_control"]["path"])
    if half_sha == BASELINE_BI4_SHA:
        raise F7InitialQAError("half BI4 unexpectedly equals baseline producer artifact")
    scratch = output_dir / "decoder-scratch"
    half = _decode_typed(half_path, half_xml_path, decoder_path, scratch, "half")
    baseline = _decode_typed(baseline_path, baseline_xml_path, decoder_path, scratch, "baseline")
    comparisons = compare_initial_arrays(half, baseline)
    post_sources = _verify_request_sources(contract, phase="post_decode", half_sha=half_sha)
    half_after = dict(post_sources["half_generated_bi4"]["stat"])
    if half_after != half_before or baseline["frame"].ids.size != 70179:
        raise F7InitialQAError("BI4 source changed during decode")
    motion_stage = _stage_motion(motion_path, output_dir)
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "PASS_INITIAL_TYPED_QA_DEVELOPMENT_UNKNOWN",
        "role": "DEVELOPMENT", "family_id": "F7", "case_id": CASE,
        "source_validation": {
            "all_inputs_pre_decode": pre_sources,
            "all_inputs_post_decode": post_sources,
            "half_bi4": {"path": str(half_path), "before": half_before, "after": half_after,
                          "sha256": half_sha, "content_scope": "parent_approved_worker_observation"},
            "baseline_bi4": baseline_binding,
            "decoder": {"path": str(decoder_path), "sha256": DECODER_SHA,
                         "content_verified_pre_and_post": True},
        },
        "decoded": {
            "half": {"particle_count": int(half["ids"].size), "zone": half["zone"],
                     "time_s": half["time_s"], "decoder_xml_sha256": half["decoder_xml_sha256"]},
            "baseline": {"particle_count": int(baseline["ids"].size), "zone": baseline["zone"],
                          "time_s": baseline["time_s"], "decoder_xml_sha256": baseline["decoder_xml_sha256"]},
        },
        "comparisons": comparisons,
        "future_solver_gate": {
            "launch_allowed": False,
            "motion_stage_required": True,
            "motion_sha256": MOTION_SHA,
            "motion_stage": motion_stage,
            "predecessor_v5_receipt_sha256": V5_RECEIPT_SHA,
            "predecessor_runparts_sha256": V5_RUNPARTS_SHA,
            "predecessor_actual_rows": 1201,
            "predecessor_actual_end_time_s": 12.00003209155591,
            "planned_row_count_must_not_be_substituted": True,
            "gpu_fee_contract": "future runner must record selected UUID and one exact post-output GPU charge cutoff; v5 receipt remains historical evidence",
        },
        "qualification": dict(UNKNOWN),
        "model_invoked": False, "cfd_invoked": False,
        "limitations": [
            "This is frame-0 typed initial QA only; it grants no solver or scientific qualification.",
            "Half BI4 content hash was computed only inside this parent-approved worker; no hash is prefilled in the request.",
            "Motion is copied into a fresh QA namespace and hash-verified; it is not launched by this worker and a new solver request must bind this exact target.",
            "Body/support weight and fluid mass semantics remain separate; no rigid-body mass is inferred from particles.",
        ],
    }
    report["sha256"] = canonical_sha(report)
    report_path = output_dir / "f7-s2-half-cfl-initial-typed-qa-v8-report.json"
    if report_path.exists():
        raise F7InitialQAError(f"refusing existing report: {report_path}")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False,
                                      default=_json_default) + "\n", encoding="utf-8")
    return report


def build_request(*, output: Path) -> dict[str, Any]:
    """Build v8 metadata without reading BI4 payloads.

    Complete stat tuples are frozen for every source.  The half-CFL BI4
    content SHA intentionally remains deferred until the parent guard grants
    this bounded worker; no invented producer hash is accepted.
    """
    for path, role in ((HALF_XML, "half XML"), (BASELINE_XML, "baseline XML"),
                       (GENCASE_RECEIPT, "GenCase receipt"), (GENCASE_STDOUT, "GenCase stdout"),
                       (MOTION, "motion"), (V5_RECEIPT, "v5 receipt"),
                       (V5_RUNPARTS, "v5 RunPARTs"), (DECODER, "decoder"),
                       (HALF_BI4, "half BI4"), (BASELINE_BI4, "baseline BI4")):
        _require_file(path, role)
    half_semantics, baseline_semantics = _xml_semantics(HALF_XML), _xml_semantics(BASELINE_XML)
    gencase_receipt = load_json(GENCASE_RECEIPT)
    v5_receipt = load_json(V5_RECEIPT)
    if gencase_receipt.get("status") != "completed":
        raise F7InitialQAError("half GenCase receipt is not the exact completed attempt")
    if v5_receipt.get("status") != "COMPLETED_DEVELOPMENT_UNKNOWN":
        raise F7InitialQAError("v5 predecessor is not the exact completed development receipt")
    if sha256_file(MOTION) != MOTION_SHA or sha256_file(DECODER) != DECODER_SHA:
        raise F7InitialQAError("motion or decoder SHA differs from frozen source")
    output = output.expanduser().resolve()
    inputs = [
        _binding(HALF_XML, "half_generated_xml"), _binding(BASELINE_XML, "baseline_generated_xml"),
        _binding(GENCASE_RECEIPT, "half_gencase_receipt"), _binding(GENCASE_STDOUT, "half_gencase_stdout"),
        _binding(MOTION, "F7_motion_control"), _binding(V5_RECEIPT, "v5_same_cfl_receipt"),
        _binding(V5_RUNPARTS, "v5_same_cfl_RunPARTs"), _binding(DECODER, "pinned_native_bi4_decoder"),
        _binding(HALF_BI4, "half_generated_bi4", content=False),
        _binding(BASELINE_BI4, "baseline_generated_bi4", content=False, expected_sha256=BASELINE_BI4_SHA),
    ]
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA, "request_id": "f7-s2-half-cfl-initial-typed-qa-v8-001",
        "status": "PENDING_PARENT_IO_SLOT", "role": "DEVELOPMENT",
        "family_id": "F7", "case_id": CASE,
        "inputs": {item["role"]: item for item in inputs},
        "input_contract": {
            "roles": list(_INPUT_PATHS),
            "stat_fields": ["bytes", "mtime_ns", "ctime_ns", "inode", "device", "mode"],
            "all_inputs_pre_and_post_hash_required": True,
            "deferred_content_sha_roles": sorted(_DEFERRED_CONTENT_ROLES),
            "original_path_fallback": "FORBIDDEN",
        },
        "predecessor": {
            "receipt_path": str(V5_RECEIPT), "receipt_sha256": V5_RECEIPT_SHA,
            "runparts_path": str(V5_RUNPARTS), "runparts_sha256": V5_RUNPARTS_SHA,
            "actual_row_count": 1201, "actual_end_time_s": 12.00003209155591,
            "planned_1202_rows_not_required": True,
        },
        "xml_semantics": {"half": half_semantics, "baseline": baseline_semantics,
                           "only_intended_change": "CFL 0.1 versus 0.2; initial particle intent must be compared from decoded arrays"},
        "compare_contract": {
            "decode_scope": "exactly two frame-0 native BI4 decodes",
            "identity_key": "(Zone,Idp)", "identity_source": "BI4 Piece as Zone + Idp.bin",
            "fields": ["identity", "position", "valid", "type", "mk", "mass"],
            "expected_particle_count": 70179,
            "expected_mk_counts": {"fixed_mk10": 27495, "moving_mk12": 1984, "fluid_mk2": 40700},
            "expected_type_counts": {"fixed_type0": 27495, "moving_type1": 1984, "fluid_type3": 40700},
            "exact_array_comparison": True,
            "invalid_or_missing_identity": "FAIL; XML counts cannot substitute for decoded identity",
            "mass_semantics": "MassBound for fixed/moving support and MassFluid for type-3 fluid; no rigid-body mass inference",
        },
        "execution": {
            "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
                         str((SCRIPT_DIR / "ds_data02_stage2_f7_half_cfl_initial_qa_v8.py").resolve()),
                         "run", "--request", "<this-request>", "--io-slot-approved",
                         "--output-dir", "<fresh-absent-output-dir>"],
            "requires_shared_four_guard": True, "python": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            "hdf5": False, "solver": False, "cfd": False, "gpu": False,
            "original_path_fallback": "FORBIDDEN", "fresh_output_required": True,
            "model_invoked": False, "cfd_invoked": False,
        },
        "resource_request": {
            "cpu_threads": 1, "max_wall_seconds": 900,
            "max_rss_bytes": 2 * 1024**3, "new_storage_budget_bytes": 512 * 1024**2,
            "source_read_scope": "two ~3.1 MB frame-0 BI4 files plus decoder outputs; no H5/solver",
        },
        "motion_stage": {
            "source": str(MOTION), "source_sha256": MOTION_SHA,
            "target_relative": "solver_input/motion_obstacle_quintic.dat",
            "copy_and_target_hash_required_before_solver": True,
        },
        "future_solver_gate": {
            "launch_allowed": False, "requires_initial_typed_qa_pass": True,
            "requires_motion_stage_pass": True, "requires_new_parent_request": True,
            "gpu_fee_contract": "selected GPU UUID plus exact post-output charge cutoff in terminal receipt; no auto/null UUID credit",
        },
        "qualification": dict(UNKNOWN), "launch_allowed": False,
        "limitations": [
            "Request is guard-ready but does not claim that the half BI4 has been decoded.",
            "The half BI4 hash is intentionally deferred until the parent-approved worker reads it.",
            "GenCase stdout's missing-motion-copy warnings and OMP=16 observation remain unresolved for a future solver request.",
            "The v5 RunPARTs predecessor is a development/unknown gate and its actual 1201 rows/end time are preserved.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    if output.exists():
        raise F7InitialQAError(f"refusing existing request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False,
                                 default=_json_default) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--io-slot-approved", action="store_true")
    run.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            request = build_request(output=args.output)
            print(json.dumps({"status": request["status"], "sha256": request["sha256"],
                              "input_count": len(request["inputs"])}, sort_keys=True))
        else:
            request = load_json(args.request)
            report = run_request(request, output_dir=args.output_dir,
                                 io_slot_approved=args.io_slot_approved)
            print(json.dumps({"status": report["status"], "sha256": report["sha256"]}, sort_keys=True))
    except (F7InitialQAError, OSError, ValueError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
