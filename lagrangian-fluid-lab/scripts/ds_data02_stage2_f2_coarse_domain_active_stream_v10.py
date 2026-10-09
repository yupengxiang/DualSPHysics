#!/usr/bin/env python3
"""Bounded native identity audit for the completed ROOT130 domain control.

This forward-only worker consumes the completed numerical-domain control
product and, after a shared parent guard, streams its 401 ``Part_####.bi4``
frames one at a time.  It binds the ROOT130 request, receipt, verification
proof, output root, source XML, RunPARTs and the completed MassFluid raw-byte
predecessor.  It records finite active fields and exact saved-frame identity
losses.  RunPARTs motive counters are retained as aggregate diagnostics;
there is no per-identity PartOut/motive input in this manifest, so per-ID
motive remains UNKNOWN.

The worker never starts a solver or creates HDF5.  It uses the repository's
bounded V10 decoder path, including per-frame scratch cleanup, process-group
termination and Linux parent-death supervision.  The XML whole-initial mass
is the frozen .003 screening denominator; neither a count match nor a smaller
domain-loss fraction grants QI/QN/QE or proves physical spill, legal flux or
dynamical impact.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any


HELPER_PATH = Path(__file__).with_name("ds_data02_stage2_f2_coarse_active_stream_v10.py")
_SPEC = importlib.util.spec_from_file_location("ds02_f2_stream_v10_helper", HELPER_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"cannot import bounded V10 helper: {HELPER_PATH}")
_HELPER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_HELPER)


SCHEMA = "ds02.stage2.f2.coarse-domain-active-stream.v10"
MANIFEST_SCHEMA = "ds02.stage2.f2.coarse-domain-active-stream.manifest.v10"
CASE_KEY = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_DOMAIN_SENSITIVITY_MARGIN_V1"
PHYSICAL_CASE_ID = CASE_KEY
V7_CASE_KEY = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
FRAME_RE = re.compile(r"^Part_(\d{4})\.bi4$")
TIME_TOLERANCE_S = 1.0e-8
MAX_RESULT_JSON_BYTES = 128 * 1024 * 1024


class DomainStreamError(ValueError):
    """Raised when ROOT130 source or native closure is not exact."""


def sha256(path: Path) -> str:
    return _HELPER.sha256(path)


def stat_record(path: Path) -> dict[str, Any]:
    return _HELPER.stat_record(path)


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DomainStreamError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise DomainStreamError(f"{label} is not finite")
    return result


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DomainStreamError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise DomainStreamError(f"{label} is not a JSON object")
    return value


def require_file(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise DomainStreamError(f"{label} path is missing")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise DomainStreamError(f"{label} is not a file: {path}")
    if path.suffix.lower() in {".h5", ".hdf5"}:
        raise DomainStreamError(f"{label} points to forbidden HDF5 content: {path}")
    return path


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise DomainStreamError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_RESULT_JSON_BYTES:
        raise DomainStreamError(f"result exceeds bounded JSON output size: {len(payload)}>{MAX_RESULT_JSON_BYTES}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _bind_input(manifest: dict[str, Any], key: str) -> Path:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict) or key not in inputs:
        raise DomainStreamError(f"manifest lacks input {key}")
    ref = inputs[key]
    if not isinstance(ref, dict):
        raise DomainStreamError(f"manifest input {key} is malformed")
    path = require_file(ref.get("path"), key)
    expected = ref.get("sha256")
    if expected and expected != "PARENT_GUARD_COMPUTED" and sha256(path) != str(expected):
        raise DomainStreamError(f"{key} SHA differs: {path}")
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if ref.get(field) is not None and stat_record(path)[field] != int(ref[field]):
            raise DomainStreamError(f"{key} {field} differs: {path}")
    return path


def _bind_frame_refs(manifest: dict[str, Any], raw_root: Path) -> list[Path]:
    refs = manifest.get("frames")
    if not isinstance(refs, list) or len(refs) != 401:
        raise DomainStreamError("ROOT130 manifest must contain exactly 401 deferred frames")
    paths: list[Path] = []
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict):
            raise DomainStreamError(f"frame[{index}] is malformed")
        path = require_file(ref.get("path"), f"frame[{index}]")
        if path.parent != raw_root:
            raise DomainStreamError(f"frame[{index}] is outside the exact ROOT130 raw root")
        match = FRAME_RE.fullmatch(path.name)
        if match is None or int(match.group(1)) != index:
            raise DomainStreamError(f"frame[{index}] is not contiguous Part_{index:04d}.bi4")
        # Frame bytes and SHA are intentionally deferred to the shared parent
        # guard.  If present, a manifest stat field is still checked here.
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if ref.get(field) is not None and stat_record(path)[field] != int(ref[field]):
                raise DomainStreamError(f"frame[{index}] {field} differs")
        paths.append(path)
    return paths


def _validate_domain_binding(
    manifest: dict[str, Any],
    paths: dict[str, Path],
    raw_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    request = read_json(paths["domain_request"], "ROOT130 request")
    receipt = read_json(paths["domain_receipt"], "ROOT130 receipt")
    proof = read_json(paths["domain_proof"], "ROOT130 verification proof")
    if request.get("schema") != "ds02.stage2.external-solver-request.v5" or request.get("case_id") != CASE_KEY:
        raise DomainStreamError("ROOT130 request identity differs")
    if request.get("family_id") != "F2" or request.get("status") not in {"READY_FOR_PARENT_GUARD", "COMPLETED_DEVELOPMENT_UNKNOWN"}:
        raise DomainStreamError("ROOT130 request family/status differs")
    if receipt.get("schema") != "ds02.stage2.external-solver-report.v5" or receipt.get("status") != "COMPLETED_DEVELOPMENT_UNKNOWN":
        raise DomainStreamError("ROOT130 receipt is not the completed source product")
    receipt_request = receipt.get("request")
    if not isinstance(receipt_request, dict) or receipt_request.get("path") != str(paths["domain_request"]):
        raise DomainStreamError("ROOT130 receipt does not bind exact request path")
    if receipt_request.get("sha256") != sha256(paths["domain_request"]):
        raise DomainStreamError("ROOT130 receipt request SHA differs")
    proof_request = proof.get("request")
    if proof_request != str(paths["domain_request"]):
        raise DomainStreamError("ROOT130 proof request path differs")
    if proof.get("request_sha256") != sha256(paths["domain_request"]):
        raise DomainStreamError("ROOT130 proof request SHA differs")
    if proof.get("receipt") != str(paths["domain_receipt"]):
        raise DomainStreamError("ROOT130 proof receipt path differs")
    if proof.get("receipt_sha256") != sha256(paths["domain_receipt"]):
        raise DomainStreamError("ROOT130 proof receipt SHA differs")
    if proof.get("status") != "VERIFIED_ACTUAL_NUMERICAL_DOMAIN_CONTROL_NATIVE_OUTPUTS_NO_SCIENTIFIC_Q":
        raise DomainStreamError("ROOT130 proof status differs")
    if proof.get("BI4_H5_VTK_or_native_content_read_by_root") is not False:
        raise DomainStreamError("ROOT130 proof reports unexpected pre-audit payload read")
    if proof.get("native_frame_files_stat_only_count") != 401:
        raise DomainStreamError("ROOT130 proof does not bind 401 frame inventory")
    runparts_summary = proof.get("RunPARTs_summary")
    if not isinstance(runparts_summary, dict) or runparts_summary.get("rows") != 401:
        raise DomainStreamError("ROOT130 RunPARTs summary is not 401 rows")
    saved = runparts_summary.get("saved_window_new_exclusion_sums")
    if saved != {"NpOut": 67.0, "NpOutPos": 67.0, "NpOutRho": 0.0, "NpOutMov": 0.0}:
        raise DomainStreamError("ROOT130 expected aggregate motive counts differ")
    if proof.get("scientific_qualification") != {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}:
        raise DomainStreamError("ROOT130 proof grants unsupported scientific qualification")
    if proof.get("physical_fate_contact_flux_dynamics") != "UNKNOWN":
        raise DomainStreamError("ROOT130 proof widens physical fate claim")
    launch = receipt.get("execution", {}).get("launch_argv")
    if not isinstance(launch, list) or len(launch) < 4:
        raise DomainStreamError("ROOT130 receipt launch argv is incomplete")
    launch_root = Path(str(launch[3])).expanduser().resolve()
    # ROOT130 stores ``RunPARTs.csv`` beside ``data/``; the solver launch
    # output root is therefore the direct parent of the deferred BI4 root.
    if launch_root != raw_root.parent.resolve():
        raise DomainStreamError("ROOT130 launch output root differs from frame root")
    command = request.get("command")
    if not isinstance(command, list) or len(command) < 4:
        raise DomainStreamError("ROOT130 request command is incomplete")
    command_output = str(command[3])
    if command_output != "{output_root}" and Path(command_output).expanduser().resolve() != launch_root:
        raise DomainStreamError("ROOT130 request output root differs from receipt")
    if request.get("hdf5_opened") is not False or request.get("raw_opened") is not False:
        raise DomainStreamError("ROOT130 request permits forbidden payload reads")
    expected_small = {row.get("path"): row.get("sha256") for row in proof.get("fresh_small_inputs", []) if isinstance(row, dict)}
    xml_path = paths["domain_xml"]
    if expected_small.get(str(xml_path)) != sha256(xml_path):
        raise DomainStreamError("ROOT130 source XML is not the proof-bound small input")
    domain_changes = proof.get("source_xml_domain_only_changes")
    if not isinstance(domain_changes, list) or {row.get("path") for row in domain_changes if isinstance(row, dict)} != {
        "/case/execution/parameters/simulationdomain/posmin",
        "/case/execution/parameters/simulationdomain/posmax",
    }:
        raise DomainStreamError("ROOT130 source XML changes are not limited to numerical domain")
    return request, receipt, proof, runparts_summary


def _validate_v7(paths: dict[str, Path]) -> dict[str, Any]:
    report = read_json(paths["v7_report"], "V7 raw scalar report")
    source_contract = read_json(paths["v7_source_contract"], "V7 source contract")
    result = _HELPER._validate_v7_precondition(
        report,
        paths["v7_report"],
        source_contract,
        paths["v7_source_contract"],
    )
    result["execution_receipt"] = _HELPER._validate_v7_execution_receipt(
        read_json(paths["v7_execution_receipt"], "V7 execution receipt"),
        paths["v7_execution_receipt"],
        paths["v7_report"],
    )
    return result


def _validate_manifest(manifest: dict[str, Any]) -> tuple[dict[str, Path], Path]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise DomainStreamError("unsupported ROOT130 native-stream manifest schema")
    if manifest.get("case_key") != CASE_KEY or manifest.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise DomainStreamError("ROOT130 native-stream case identity differs")
    if manifest.get("status") != "READY_FOR_PARENT_GUARD_NATIVE_IDENTITY_AUDIT":
        raise DomainStreamError("ROOT130 manifest status is not guarded-ready")
    scope = manifest.get("source_scope")
    if not isinstance(scope, dict):
        raise DomainStreamError("ROOT130 manifest lacks source scope")
    for key in ("root130_actual_reference_only", "old_root095_native_identity_reused", "runparts_67_is_log_check_only", "no_count_fabricated_ids", "xml_type_mk_not_independent_native_fields"):
        expected = False if key == "old_root095_native_identity_reused" else True
        if scope.get(key) is not expected:
            raise DomainStreamError(f"ROOT130 source scope {key} is not strict")
    raw_ref = manifest.get("raw_data_root")
    if not isinstance(raw_ref, dict) or not isinstance(raw_ref.get("path"), str):
        raise DomainStreamError("ROOT130 manifest lacks raw data root")
    raw_root = Path(raw_ref["path"]).expanduser().resolve()
    if not raw_root.is_dir():
        raise DomainStreamError(f"ROOT130 raw root is not a directory: {raw_root}")
    keys = {
        "stream_worker", "stream_helper",
        "domain_request", "domain_receipt", "domain_proof", "domain_xml", "domain_prepared",
        "runparts", "direct_converter", "bi4_dump", "timing_contract",
        "v7_report", "v7_source_contract", "v7_execution_receipt",
    }
    paths = {key: _bind_input(manifest, key) for key in keys}
    return paths, raw_root


def _stream(
    manifest: dict[str, Any],
    paths: dict[str, Path],
    raw_root: Path,
    frames: list[Path],
    v7: dict[str, Any],
    solver_request: dict[str, Any],
) -> dict[str, Any]:
    backend = _HELPER.load_backend(paths["direct_converter"])
    runtime_closure = _HELPER._runtime_closure(manifest, backend)
    blocks = backend.parse_particle_blocks(paths["domain_xml"])
    expected = manifest.get("expected")
    if not isinstance(expected, dict):
        raise DomainStreamError("ROOT130 manifest lacks expected counts")
    if blocks["np"] != int(expected["initial_particles_total"]):
        raise DomainStreamError("ROOT130 XML total count differs")
    fluid_blocks = [block for block in blocks["blocks"] if block["type"] == 3]
    if sum(block["count"] for block in fluid_blocks) != int(expected["initial_fluid_count"]):
        raise DomainStreamError("ROOT130 XML fluid count differs")
    expected_fluid_blocks = expected.get("fluid_blocks")
    actual_fluid_blocks = [{key: block[key] for key in ("begin", "count", "mkfluid", "mk")} for block in fluid_blocks]
    if actual_fluid_blocks != expected_fluid_blocks:
        raise DomainStreamError("ROOT130 XML fluid block layout differs")
    expected_bits = str(v7["expected_native_massfluid_bits_hex"])
    expected_native_mass = finite(v7["expected_native_massfluid_kg"], "V7 native MassFluid")
    xml_mass = finite(v7["xml_massfluid_kg"], "V7 XML MassFluid")
    if finite(expected.get("massfluid_kg"), "manifest XML MassFluid") != xml_mass:
        raise DomainStreamError("ROOT130 manifest XML MassFluid differs from V7 source")
    import numpy as np

    base_ids = np.arange(blocks["np"], dtype=np.uint32)
    base_type, base_mk = backend._assign_types(base_ids, blocks)
    fluid_ids = {int(value) for value in base_ids[base_type == 3].tolist()}
    if len(fluid_ids) != int(expected["initial_fluid_count"]):
        raise DomainStreamError("ROOT130 XML fluid identity axis differs")
    lifecycle = {
        int(idp): {
            "case_key": CASE_KEY,
            "idp": int(idp),
            "mk": int(base_mk[idp]),
            "type": int(base_type[idp]),
            "first_missing_frame": None,
            "first_missing_time_s": None,
            "last_present_frame": None,
            "last_present_time_s": None,
            "missing_frame_count": 0,
            "consecutive_missing_frame_count": 0,
            "reappeared_after_missing": False,
            "reentry_count": 0,
        }
        for idp in fluid_ids
    }
    first_metadata: dict[str, Any] | None = None
    first_massfluid: float | None = None
    previous_missing: set[int] = set()
    previous_time: float | None = None
    times: list[float] = []
    frame_summaries: list[dict[str, Any]] = []
    dynamic_contract: dict[str, Any] | None = None
    scratch_limit = int(manifest["runtime"].get("max_scratch_bytes", 128 * 1024 * 1024))
    scratch_parent = Path(manifest["output"]["path"].replace("{attempt_root}", str(Path.cwd()))).parent
    scratch_parent.mkdir(parents=True, exist_ok=True)
    scratch_peak_bytes = 0
    scratch_peak_frame: int | None = None
    decoder_input_bytes = 0
    with tempfile.TemporaryDirectory(prefix=".ds02-f2-domain-stream-", dir=str(scratch_parent)) as scratch:
        for index, frame_path in enumerate(frames):
            decoder_input_bytes += frame_path.stat().st_size
            with tempfile.TemporaryDirectory(prefix=f"frame-{index:04d}-", dir=scratch) as frame_scratch:
                frame, peak = _HELPER.decode_frame_bounded(
                    backend,
                    frame_path,
                    paths["bi4_dump"],
                    Path(frame_scratch),
                    index,
                    scratch_limit,
                    poll_interval_s=float(manifest["runtime"].get("scratch_poll_interval_s", 0.01)),
                    max_decoder_seconds=float(manifest["runtime"].get("max_decoder_seconds_per_frame", 180.0)),
                )
                scratch_peak_bytes = max(scratch_peak_bytes, peak)
                if peak >= scratch_peak_bytes:
                    scratch_peak_frame = index
            time_s = finite(frame.time, f"BI4 frame {index} TimeStep")
            if previous_time is not None and time_s <= previous_time:
                raise DomainStreamError(f"BI4 TimeStep is not increasing at frame {index}")
            previous_time = time_s
            times.append(time_s)
            if first_metadata is None:
                first_metadata = dict(frame.metadata)
                if int(first_metadata.get("CaseNp", blocks["np"])) != blocks["np"]:
                    raise DomainStreamError("BI4 CaseNp differs from ROOT130 XML")
                if int(first_metadata.get("CaseNfluid", len(fluid_ids))) != len(fluid_ids):
                    raise DomainStreamError("BI4 CaseNfluid differs from ROOT130 XML")
                first_massfluid = finite(first_metadata.get("MassFluid"), "BI4 first-frame MassFluid")
                if _HELPER._binary64_bits(first_massfluid, "BI4 first-frame MassFluid") != expected_bits:
                    raise DomainStreamError("ROOT130 first-frame MassFluid bits differ from V7 raw scalar")
                if _HELPER._binary64_bits(expected_native_mass, "V7 native MassFluid") != expected_bits:
                    raise DomainStreamError("V7 native MassFluid bits are internally inconsistent")
                dynamic_contract = backend._reject_dynamic_contract(paths["domain_xml"], first_metadata)
            else:
                backend._check_frame_constants(first_metadata, frame.metadata)
                massfluid = finite(frame.metadata.get("MassFluid"), f"BI4 frame {index} MassFluid")
                if _HELPER._binary64_bits(massfluid, f"BI4 frame {index} MassFluid") != expected_bits:
                    raise DomainStreamError(f"BI4 frame {index} MassFluid bits differ from V7 raw scalar")
            ids = frame.ids
            if ids.dtype != np.dtype("uint32") or len(ids) == 0 or len(np.unique(ids)) != len(ids):
                raise DomainStreamError(f"BI4 frame {index} Idp axis is invalid")
            if np.any(ids >= blocks["np"]):
                raise DomainStreamError(f"BI4 frame {index} Idp is outside XML axis")
            types, mks = backend._assign_types(ids, blocks)
            active = types == 3
            masses = backend._mass_for_types(types, frame.metadata)
            if not np.isfinite(frame.position[active]).all() or not np.isfinite(frame.velocity[active]).all() or not np.isfinite(frame.density[active]).all() or not np.isfinite(masses[active]).all():
                raise DomainStreamError(f"BI4 frame {index} active fields are non-finite")
            if np.any(frame.density[active] <= 0) or np.any(masses[active] <= 0):
                raise DomainStreamError(f"BI4 frame {index} active fields are non-positive")
            active_ids = {int(value) for value in ids[active].tolist()}
            missing, _ = _HELPER.update_lifecycle(lifecycle, fluid_ids, active_ids, index, time_s, previous_missing)
            previous_missing = missing
            summary = _HELPER.weighted_active_summary(frame.position[active], frame.velocity[active], frame.density[active], masses[active], mks[active])
            frame_summaries.append({
                "frame": index,
                "actual_native_time_s": time_s,
                "massfluid_bits_hex": _HELPER._binary64_bits(first_massfluid if first_massfluid is not None else expected_native_mass, "frame MassFluid"),
                "active_fluid": summary,
                "missing_fluid_count": len(missing),
                "missing_fluid_ids_sha256": hashlib.sha256(np.asarray(sorted(missing), dtype=np.uint32).tobytes()).hexdigest(),
                "typed_fields": {
                    "type": {"source": "generated XML Idp ranges", "independently_decoded": False},
                    "mk": {"source": "generated XML Idp ranges", "independently_decoded": False},
                },
            })
            del frame
            gc.collect()
    if first_metadata is None or first_massfluid is None:
        raise DomainStreamError("ROOT130 produced no decoded frame")
    runparts = _HELPER.read_runparts(paths["runparts"])
    if len(runparts["rows"]) != len(frames):
        raise DomainStreamError("ROOT130 RunPARTs rows differ from 401 frames")
    for frame_summary, run_row in zip(frame_summaries, runparts["rows"]):
        if abs(frame_summary["actual_native_time_s"] - run_row["time_s"]) > TIME_TOLERANCE_S:
            raise DomainStreamError(f"BI4 time differs from RunPARTs Part {run_row['part']}")
    expected_summary = read_json(paths["domain_proof"], "ROOT130 proof") ["RunPARTs_summary"]
    final_frame = frame_summaries[-1]
    final_missing = [row for row in lifecycle.values() if row["last_present_frame"] != len(frames) - 1]
    count_match = len(final_missing) == int(expected_summary["saved_window_new_exclusion_sums"]["NpOut"])
    xml_whole = float(xml_mass * len(fluid_ids))
    native_whole = float(first_massfluid * len(fluid_ids))
    missing_mass = float(len(final_missing) * first_massfluid)
    motive_counts = runparts["totals"]
    rows = []
    for row in sorted(final_missing, key=lambda item: item["idp"]):
        rows.append({
            **row,
            "motive": "UNKNOWN_PER_ID_MOTIVE",
            "motive_source": "RunPARTs aggregate counters only; no per-identity PartOut source bound",
            "saved_record_time_s": None,
        })
    return {
        "schema": SCHEMA,
        "status": "COMPLETED_F2_COARSE_DOMAIN_ACTIVE_STREAM_V10_EXACT_NATIVE_MASS_BITS",
        "case_key": CASE_KEY,
        "family_id": "F2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "source": {
            "domain_request": stat_record(paths["domain_request"]),
            "domain_receipt": stat_record(paths["domain_receipt"]),
            "domain_proof": stat_record(paths["domain_proof"]),
            "domain_xml": stat_record(paths["domain_xml"]),
            "domain_prepared": stat_record(paths["domain_prepared"]),
            "runparts": stat_record(paths["runparts"]),
            "direct_converter": stat_record(paths["direct_converter"]),
            "bi4_dump": stat_record(paths["bi4_dump"]),
            "timing_contract": stat_record(paths["timing_contract"]),
            "v7_report": v7["report"],
            "v7_source_contract": v7["source_contract"],
            "v7_execution_receipt": v7["execution_receipt"],
            "raw_frame_count": len(frames),
            "raw_frame_pre_post_sha_snapshot": "recorded around the guarded stream; no source frame is modified",
            "runtime_closure": runtime_closure,
        },
        "native_identity_join": {
            "key": "(case_key, Idp)",
            "identity_scope": "final saved-frame missing fluid identities only",
            "row_count": len(rows),
            "rows": rows,
            "aggregate_motive_counts_from_RunPARTs": motive_counts,
            "aggregate_motive_count_expected_67": expected_summary["saved_window_new_exclusion_sums"],
            "aggregate_count_matches_decoded_final_missing": count_match,
            "per_identity_motive": "UNKNOWN",
            "type_mk_source": "generated XML Idp ranges; not independently encoded native labels",
            "physical_fate": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN",
        },
        "active_fluid_stream": {
            "frame_count": len(frames),
            "initial_particles_total": int(blocks["np"]),
            "initial_fluid_count": len(fluid_ids),
            "initial_massfluid_kg": first_massfluid,
            "xml_whole_initial_fluid_mass_kg": xml_whole,
            "native_whole_initial_fluid_mass_kg": native_whole,
            "massfluid_bits_hex": v7["expected_native_massfluid_bits_hex"],
            "massfluid_bit_gate": {"all_frames_exact_match": True, "absolute_tolerance": None, "mass_rescaling": False},
            "first_metadata": {key: first_metadata.get(key) for key in ("CaseNp", "CaseNfluid", "Piece", "TimeStep", "MassFluid", "MassBound", "Dp")},
            "decoder_dynamic_contract": dynamic_contract,
            "frame_summaries": frame_summaries,
            "final_missing_fluid_count": len(final_missing),
            "ever_missing_fluid_count": sum(row["first_missing_frame"] is not None for row in lifecycle.values()),
            "decoder_cost": {
                "decoder_input_bytes_total": decoder_input_bytes,
                "scratch_peak_bytes": scratch_peak_bytes,
                "scratch_peak_frame": scratch_peak_frame,
                "scratch_limit_bytes": scratch_limit,
                "scratch_cleanup": "one actor-owned per-frame directory deleted after scalar reduction",
                "process_supervision": "V10 helper start_new_session + PR_SET_PDEATHSIG + bounded killpg/wait",
            },
        },
        "mass_and_material": {
            "native_excluded_mass_lower_bound_kg": missing_mass,
            "native_excluded_mass_fraction_xml_whole_initial": missing_mass / xml_whole,
            "native_excluded_mass_fraction_native_whole_initial": missing_mass / native_whole,
            "unknown_identity_mass_screen": {
                "whole_initial_fraction_max": 0.003,
                "observed_lower_bound_fraction": missing_mass / xml_whole,
                "screen_result_only": (missing_mass / xml_whole) <= 0.003,
                "denominator_basis": "XML whole-initial fluid mass; native whole mass reported separately",
                "physical_fate": "UNKNOWN",
                "meaning": "decoded saved-frame identity lower bound; not a bound on spill, velocity, impulse, coupling or dynamics",
            },
        },
        "domain_control": {
            "source_preserving_changes": "ROOT130 proof binds only simulationdomain posmin/posmax changes",
            "logged_count_expected": 67,
            "logged_count_is_not_identity_proxy": True,
            "domain_sensitivity_is_not_physical_boundary_validation": True,
        },
        "claim_boundary": {
            "native_identity_and_finite_fields": "SOURCE_CLOSED_IF_PRE_POST_AND_EXACT_MASS_BITS_PASS",
            "per_identity_motive": "UNKNOWN_WITHOUT_BOUND_PARTOUT_IDENTITY_ROWS",
            "physical_destination_or_legal_flux": "UNKNOWN",
            "continuous_event_time": "UNKNOWN_BEYOND_SAVED_FRAME_BRACKETS",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "read_policy": {
            "part_bi4_frames_opened": True,
            "hdf5_opened": False,
            "solver_started": False,
            "gencase_started": False,
            "model_or_cfd_started": False,
            "old_products_modified": False,
        },
    }


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_file(str(manifest_path), "ROOT130 manifest")
    manifest = read_json(manifest_path, "ROOT130 manifest")
    paths, raw_root = _validate_manifest(manifest)
    _validate_domain_binding(manifest, paths, raw_root)
    v7 = _validate_v7(paths)
    frames = _bind_frame_refs(manifest, raw_root)
    pre = {"frames": [_HELPER.stat_record(path) for path in frames], "inputs": {key: stat_record(path) for key, path in paths.items()}}
    # This is deliberately after the source/receipt checks: no frame decoder
    # starts until the exact ROOT130 product and all small sources are bound.
    result = _stream(manifest, paths, raw_root, frames, v7, read_json(paths["domain_request"], "ROOT130 request"))
    post = {"frames": [_HELPER.stat_record(path) for path in frames], "inputs": {key: stat_record(path) for key, path in paths.items()}}
    result["input_stability"] = {"pre": pre, "post": post, "all_equal": pre == post}
    if not result["input_stability"]["all_equal"]:
        raise DomainStreamError("ROOT130 source or BI4 frame inputs changed during stream")
    result["manifest"] = stat_record(manifest_path)
    atomic_json(output_path, result)
    return {"schema": result["schema"], "status": result["status"], "frame_count": result["active_fluid_stream"]["frame_count"], "identity_rows": result["native_identity_join"]["row_count"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.manifest, args.output), sort_keys=True))
    except Exception as exc:
        print(f"F2 coarse domain active stream failed: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
