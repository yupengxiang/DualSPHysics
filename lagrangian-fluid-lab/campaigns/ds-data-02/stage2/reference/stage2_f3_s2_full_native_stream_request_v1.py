#!/usr/bin/env python3
"""Prepare a disabled, source-bound request for the complete F3 native stream.

This builder reads only small producer metadata and source code.  It never
opens a native Part payload.  The resulting request is deliberately held
behind the ten-frame native-header encoding result: a parent guard must first
show that the official decoder exposes finite MassFluid and the expected field
files.  If released, the new full-window worker performs its own first hash
immediately after reservation and records pre/decode/post SHA/stat for all
836 native files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from stage2_f3_s2_native_audit_request_v1 import (
    ACTUAL_PROOF,
    ACTUAL_PROOF_SHA,
    ACTUAL_RECEIPT,
    ACTUAL_RECEIPT_SHA,
    ACTUAL_REQUEST,
    ACTUAL_REQUEST_SHA,
    ACTUAL_RUNPARTS_SHA,
    CALIBRATION_CONTRACT,
    DECODER,
    DECODER_SOURCE,
    EXPECTED_FRAME_COUNT,
    FINAL_TIME_S,
    FORCING,
    FORCING_SHA,
    GENERATED_XML,
    GENERATED_XML_SHA,
    MAIN,
    RAW_ROOT,
    REPO,
    RUNPARTS,
    ROOT128_PROOF,
    ROOT128_PROOF_SHA,
    canonical_sha,
    known_record,
    sha256_file,
    small_record,
)


REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f3-s2.full-native-stream-request.v1"
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_observer_v1.py"
BASE_OBSERVER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py"
HEADER_OBSERVER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_native_header_observer_v1.py"
TEN_MANIFEST = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_S2_COARSE_SELECTED_SOURCE_SNAPSHOT_ROOT_139/f3-s2-coarse-selected-source-snapshot-root-139-001-root-forward-030-001/native_selected_source_snapshot_v2.json")
TEN_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_TEN_SELECTED_SOURCE_SNAPSHOT_ACTUAL_SCOPE_ROOT_VERIFICATION_139.json"
TEN_PROOF_SHA = "2c8cc5f2a11dca8d0d6052cf3c2ace870cacb792c50fd31dcf7c74e348bd9c35"
ROOT133_FULL_RAW_BYTES = 912592711
ROOT133_CPU_SECONDS = 203.232353
DEFAULT_OUTPUT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-full-native-stream-root133-001.json"
FRAMES = list(range(EXPECTED_FRAME_COUNT))
QUERY_TIMES = [0.0, 2.0, 4.0, 6.0, 8.0, FINAL_TIME_S]


def canonical(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in value.items() if k != "sha256"}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def require_regular(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")


def build(output: Path, *, case_id: str, attempt_id: str, launch_commit: str) -> dict[str, Any]:
    for path, label in (
        (WORKER, "full native stream worker"),
        (BASE_OBSERVER, "base decoder adapter"),
        (HEADER_OBSERVER, "native header adapter"),
        (TEN_MANIFEST, "ROOT139 ten-frame manifest"),
        (TEN_PROOF, "ROOT139 ten-frame proof"),
        (DECODER, "official BI4 decoder"),
        (DECODER_SOURCE, "official decoder source"),
        (CALIBRATION_CONTRACT, "F3 calibration contract"),
        (ACTUAL_PROOF, "ROOT133 proof"),
        (ACTUAL_RECEIPT, "ROOT133 receipt"),
        (ACTUAL_REQUEST, "ROOT133 request"),
        (ROOT128_PROOF, "ROOT128 support proof"),
    ):
        require_regular(path, label)
    calibration = json.loads(CALIBRATION_CONTRACT.read_text(encoding="utf-8"))
    if calibration.get("status") != "SOURCE_BOUND_SCALES_REGISTERED_EVENT_TIME_UNKNOWN":
        raise ValueError("F3 calibration contract is not the frozen source-bound contract")

    records: dict[str, dict[str, Any]] = {}
    for path, label in (
        (Path(__file__), "full request builder"),
        (WORKER, "full native stream worker"),
        (BASE_OBSERVER, "base decoder adapter"),
        (HEADER_OBSERVER, "native header adapter"),
        (DECODER, "official BI4 decoder"),
        (DECODER_SOURCE, "official decoder source"),
        (CALIBRATION_CONTRACT, "F3 calibration contract"),
        (TEN_MANIFEST, "ROOT139 ten-frame manifest"),
        (TEN_PROOF, "ROOT139 ten-frame proof"),
        (ROOT128_PROOF, "ROOT128 support proof"),
    ):
        record = small_record(path, label)
        records[record["path"]] = record
    records[str(ACTUAL_REQUEST.resolve())] = known_record(ACTUAL_REQUEST, ACTUAL_REQUEST_SHA, None, "ROOT133 proof-bound request; parent verifies", "ROOT133 request")
    records[str(ACTUAL_PROOF.resolve())] = known_record(ACTUAL_PROOF, ACTUAL_PROOF_SHA, None, "ROOT133 proof-bound metadata; parent verifies", "ROOT133 proof")
    records[str(ACTUAL_RECEIPT.resolve())] = known_record(ACTUAL_RECEIPT, ACTUAL_RECEIPT_SHA, None, "ROOT133 terminal receipt; parent verifies", "ROOT133 receipt")
    records[str(ROOT128_PROOF.resolve())] = known_record(ROOT128_PROOF, ROOT128_PROOF_SHA, None, "ROOT128 support proof; parent verifies", "ROOT128 proof")
    records[str(GENERATED_XML.resolve())] = known_record(GENERATED_XML, GENERATED_XML_SHA, 9328, "ROOT133 generated XML; parent after-reservation pre/post hash", "ROOT133 generated XML")
    records[str(RUNPARTS.resolve())] = known_record(RUNPARTS, ACTUAL_RUNPARTS_SHA, None, "ROOT133 RunPARTs; parent after-reservation pre/post hash", "ROOT133 RunPARTs")
    records[str(FORCING.resolve())] = known_record(FORCING, FORCING_SHA, 14377599, "ROOT133 forcing; parent after-reservation pre/post hash", "ROOT133 forcing")
    input_files = sorted(records)

    command = [
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
        str(WORKER),
        "--raw-root", str(RAW_ROOT.resolve()),
        "--runparts", str(RUNPARTS.resolve()),
        "--generated-xml", str(GENERATED_XML.resolve()),
        "--decoder", str(DECODER.resolve()),
        "--decoder-source", str(DECODER_SOURCE.resolve()),
        "--calibration-contract", str(CALIBRATION_CONTRACT.resolve()),
        "--output", "{attempt_root}/observer/f3_s2_full_native_stream_root133.json",
        "--scratch-root", "{attempt_root}/scratch/bi4_full_native_stream",
        "--expected-frame-count", str(EXPECTED_FRAME_COUNT),
        "--expected-final-time-s", repr(FINAL_TIME_S),
        "--final-time-tolerance-s", "1e-12",
        "--query-times", *[repr(value) for value in QUERY_TIMES],
        "--decoder-timeout-s", "300",
        "--max-decoder-log-bytes", "65536",
    ]
    deferred = [str((RAW_ROOT / f"Part_{frame:04d}.bi4").resolve()) for frame in FRAMES]
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": SCHEMA,
        "status": "READY_AFTER_TEN_FRAME_ENCODING_PROBE",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "launch_commit": launch_commit,
        "command": command,
        "input_files": input_files,
        "input_sha256": {path: records[path]["sha256"] for path in input_files},
        "deferred_input_files": deferred,
        "deferred_input_policy": {
            "parent_v8_input_hash": "NOT_CLAIMED_BY_BUILDER",
            "worker_first_sha_after_reservation": True,
            "worker_pre_decode_post_decode_full_sha_stat_all_frames": True,
            "raw_root_exact_frame_axis": "Part_0000.bi4..Part_0835.bi4; reject missing/extra numeric Part files",
        },
        "expected_frame_count": EXPECTED_FRAME_COUNT,
        "expected_final_time_s": FINAL_TIME_S,
        "query_times_s": QUERY_TIMES,
        "max_wall_seconds": 3600,
        "cpu_threads": 1,
        "omp_threads": 1,
        "estimated_storage_bytes": 512 * 1024 * 1024,
        "estimated_peak_memory_bytes": 2 * 1024 * 1024 * 1024,
        "actual_root133_reference": {
            "native_output_bytes": ROOT133_FULL_RAW_BYTES,
            "solver_cpu_seconds": ROOT133_CPU_SECONDS,
            "decode_read_proxy_bytes": 3 * ROOT133_FULL_RAW_BYTES,
            "proxy_semantics": "two full SHA passes plus decoder input; decoder CPU/time unknown until guarded run",
            "not_a_wall_or_accuracy_bound": True,
        },
        "estimated_input_read_bytes": 3 * ROOT133_FULL_RAW_BYTES + 64 * 1024 * 1024,
        "estimated_native_read_bytes": 3 * ROOT133_FULL_RAW_BYTES,
        "execution_allowed": False,
        "launch_disabled": True,
        "solver_started": False,
        "solver_launch": False,
        "gencase_launch": False,
        "hdf5_read": False,
        "bi4_decode": True,
        "raw_directory_scan": "bounded exact Part axis only",
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": "{attempt_root}/observer/f3_s2_full_native_stream_root133.json",
        },
        "encoding_go_no_go": {
            "required_before_parent_enable": {
                "ten_frame_observer_status": "PASS_DECODED_SELECTED_NATIVE_FIELDS",
                "native_MassFluid": "finite and constant across ten selected frames",
                "official_decoder_field_contract": ["Idp.bin", "Pos.bin_or_Posd.bin", "Vel.bin", "Rhop.bin"],
            },
            "current_status": "PENDING_ROOT_GUARDED_TEN_FRAME_RESULT",
            "if_probe_unknown_or_failed": "do not dispatch full836; preserve QI/QN/QE UNKNOWN",
        },
        "native_field_contract": {
            "mass_source": "official BI4 decoder MassFluid metadata only; XML mass is never fallback",
            "identity": "XML particle ranges label kind/mkfluid-relative/mk-absolute; no native Type/MK claim",
            "finite_fields": ["Idp", "Pos_or_Posd", "Vel", "Rhop"],
            "per_id_lifecycle": "exact first/last observed native Idp and appeared/disappeared sets",
            "continuum_owner_mass": "UNKNOWN; XML/native sample mass does not prove continuum equivalence",
            "pressure_eos": "UNKNOWN_NOT_DECODED",
            "rigid_body_mass_inertia": "UNKNOWN_NOT_INFERRED",
        },
        "source_binding": {
            "raw_root": str(RAW_ROOT.resolve()),
            "runparts": {"path": str(RUNPARTS.resolve()), "sha256": ACTUAL_RUNPARTS_SHA, "bytes": None, "parent_pre_post": True},
            "generated_xml": {"path": str(GENERATED_XML.resolve()), "sha256": GENERATED_XML_SHA, "bytes": 9328, "parent_pre_post": True},
            "forcing": {"path": str(FORCING.resolve()), "sha256": FORCING_SHA, "bytes": 14377599, "parent_pre_post": True},
            "actual_root133_request_sha256": ACTUAL_REQUEST_SHA,
            "actual_root133_receipt_sha256": ACTUAL_RECEIPT_SHA,
            "actual_root133_proof_sha256": ACTUAL_PROOF_SHA,
            "root128_support_proof_sha256": ROOT128_PROOF_SHA,
            "root139_ten_frame_manifest": {"path": str(TEN_MANIFEST.resolve()), "sha256": sha256_file(TEN_MANIFEST)},
            "root139_ten_frame_proof": {"path": str(TEN_PROOF.resolve()), "sha256": TEN_PROOF_SHA},
            "full_raw_tree_sha256": "WORKER_COMPUTED_PER_FRAME_ONLY; no single directory digest",
        },
        "calibration": {
            "contract_path": str(CALIBRATION_CONTRACT.resolve()),
            "contract_sha256": sha256_file(CALIBRATION_CONTRACT),
            "registered_L_m": calibration["reference_scales"].get("velocity_scale_m_per_s"),
            "position_L_m": calibration["source_geometry"].get("L_position_reference_scalar_m"),
            "velocity_scale_m_per_s": calibration["reference_scales"].get("velocity_scale_m_per_s"),
            "kinetic_energy_scale_j": calibration["reference_scales"].get("kinetic_energy_scale_j"),
            "event_time_T": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
            "position_tolerance_fraction_L": calibration["frozen_error_budget"]["position_fraction_of_L"],
            "velocity_and_ke_tolerance_fraction_scale": calibration["frozen_error_budget"]["velocity_and_ke_fraction_of_registered_nonzero_scale"],
            "event_time_tolerance_fraction_T": calibration["frozen_error_budget"]["event_time_fraction_of_characteristic_T"],
            "time_and_output_each_max_fraction_task": calibration["frozen_error_budget"]["time_and_output_each_max_fraction_of_task_budget"],
            "neighbor_grid_truth": False,
            "field_comparison": "NOT_PERFORMED_BY_STREAM_WORKER",
        },
        "resource_guard": {
            "parent_reservation_required": True,
            "parent_uuid_or_cpu_lease": "PARENT_ONLY",
            "worker_first_sha_after_reservation": True,
            "decoder_process_group": "new session; SIGTERM then SIGKILL and wait on timeout",
            "scratch_cleanup": "one frame temporary directory removed before next frame",
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    request["sha256"] = canonical_sha(request)
    return request


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    assert FRAMES[0] == 0 and FRAMES[-1] == 835 and len(FRAMES) == 836
    assert ROOT133_FULL_RAW_BYTES > 0 and ROOT133_CPU_SECONDS > 0
    assert QUERY_TIMES[-1] == FINAL_TIME_S
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "frame_count": len(FRAMES),
        "native_payload_read_by_builder": False,
        "execution_allowed": False,
        "ten_frame_encoding_probe_required": True,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case-id", default="F3_S2_FULL_NATIVE_STREAM_ROOT133")
    parser.add_argument("--attempt-id", default="f3-s2-full-native-stream-root133-001")
    parser.add_argument("--launch-commit", default=None)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if not args.prepare:
        parser.error("use --prepare or --self-test")
    launch_commit = args.launch_commit or subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()
    value = build(args.output, case_id=args.case_id, attempt_id=args.attempt_id, launch_commit=launch_commit)
    write_new(args.output, value)
    print(json.dumps({
        "status": value["status"],
        "request": str(args.output.resolve()),
        "frame_count": EXPECTED_FRAME_COUNT,
        "native_payload_read_by_builder": False,
        "execution_allowed": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
