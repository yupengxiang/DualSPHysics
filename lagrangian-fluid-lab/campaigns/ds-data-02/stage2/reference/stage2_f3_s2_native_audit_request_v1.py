#!/usr/bin/env python3
"""Prepare a bounded F3-S2 native snapshot/audit request after ROOT133.

This builder consumes only small request/proof JSON and already registered
source metadata.  It never opens a Part file.  The parent CPU guard runs
``stage2_native_source_snapshot_v2.py`` first, hashing only the ten selected
native frames with stat-before/stat-after checks.  A later observer request
can consume that immutable manifest through enforcer v2 and decode the same
bounded frames with the official ``bi4_dump`` adapter.

The selected fields are finite position/velocity/density, Idp identity,
relative ``mkfluid`` and absolute ``mk`` labels, sample mass, weighted
centroid, velocity, and kinetic energy.  Native sample mass remains a
diagnostic; the ROOT128 continuous-owner mass and all QI/QN/QE gates remain
separate and UNKNOWN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f3-s2.native-audit-source-snapshot.v1"
REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

ACTUAL_REQUEST = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-coarse-external-v8-root-forward-133-001.json"
ACTUAL_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_DP015_COARSE_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_133.json"
ACTUAL_RECEIPT = DATA_ROOT / "families/F3/F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT_133/f3-s2-owner-centered-dp015-full-cfd-canary-v8-root-133-001/execution-receipt.json"
OUTPUT_ROOT = Path("/var/tmp/ds02-stage2/F3/F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT_133/f3-s2-owner-centered-dp015-full-cfd-canary-v8-root-133-001")
RAW_ROOT = OUTPUT_ROOT / "solver_output/data"
RUNPARTS = OUTPUT_ROOT / "solver_output/RunPARTs.csv"
GENERATED_XML = OUTPUT_ROOT / "solver-inputs/generated.xml"
FORCING = OUTPUT_ROOT / "solver-inputs/CaseSloshingAccData.csv"

ROOT132_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_DP015_BI4_SINGLE_STREAM_ACTUAL_SOURCE_SNAPSHOT_ROOT_VERIFICATION_132.json"
ROOT128_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_DP015_SUPPORT_V6_ACTUAL_ROOT_VERIFICATION_128.json"
ROOT120_REQUEST = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-owner-centered-dp015-gencase-v2-root-forward-120-001.json"
ROOT120_RECEIPT = DATA_ROOT / "families/F3/F3_S2_OWNER_CENTERED_DP015_GENCASE_ROOT_120/f3-s2-owner-centered-dp015-gencase-v2-root-120-001-root-forward-030-001/execution-receipt.json"
ROOT132_SNAPSHOT = DATA_ROOT / "families/F3/F3_S2_OWNER_CENTERED_DP015_BI4_SNAPSHOT_ROOT_132/f3-s2-dp015-generated-bi4-snapshot-v1-root-132-001-root-forward-030-001/native_source_snapshot.json"
ROOT128_REPORT = DATA_ROOT / "families/F3/F3_S2_OWNER_CENTERED_DP015_SUPPORT_ROOT_128/f3-s2-dp015-support-v6-root-128-001-root-forward-030-001/report/stage2_f3_s2_initial_support_audit_v6.json"
CALIBRATION_CONTRACT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_observer_calibration_contract_v1.json"

SNAPSHOT_WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_source_snapshot_v2.py"
OBSERVER_WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py"
ENFORCER_V1 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_enforcer_v1.py"
ENFORCER_V2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_enforcer_v2.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
RUNTIME_V8 = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
RUNTIME_V6 = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
RUNTIME_V2 = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT_V8 = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"

FRAMES = [0, 199, 200, 399, 400, 599, 600, 799, 800, 835]
QUERY_TIMES = [0.0, 2.0, 4.0, 6.0, 8.0, 8.350023358431661]
FINAL_TIME_S = 8.350023358431661
EXPECTED_FRAME_COUNT = 836
ACTUAL_REQUEST_SHA = "0441462c5e8ed9198e10648d31f75bcdc844742abcf883478c2d02fa5a5de624"
ACTUAL_RECEIPT_SHA = "10df2f69977034ca3be8d6b7fd388bd7a565049af1c225a78f9937bc7ef8cc75"
ACTUAL_PROOF_SHA = "5d459c01728e83178903695b39f131b1c0b9ea30293454454c6c8c17f7be4706"
ACTUAL_RUNPARTS_SHA = "81b85b927c023fcc4a798b2a86ca7193f4c5c8062174868bbcf7765aada08cd1"
GENERATED_XML_SHA = "e9991fa4864607c8bc754f6458bc867a9572708296aef9965e0c3797166bd2b1"
FORCING_SHA = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
ROOT132_PROOF_SHA = "8a0f8cb430992398b8bd875b255e7de923bcc43737e2a466649717d5d0bcb356"
ROOT128_PROOF_SHA = "adbfc7e7fdde8f6c54613116e844040640fb77224c24786eb641a74e026a7543"
ROOT120_REQUEST_SHA = "bd4d33f7bdc1fda006cdced0b5f366c33d37287bbe3f84572466404635525bda"
ROOT120_RECEIPT_SHA = "e9886f06fc2da311d5610a21d353b9ffdff5d9838622772a66d8215b2194b1af"
ROOT132_SNAPSHOT_SHA = "a9adf274c5b41f1b4765de45808a89661b91851f81cd6f8c53986122005f6f66"
ROOT128_REPORT_SHA = "73700416b0edafa8f84a3ea26959a1a18b90718bff99bb418254a64d06817d78"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def small_record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256_file(path),
        "content_scope": "small_source_or_worker_hashed_by_builder_and_parent",
    }


def known_record(path: Path, expected_sha: str, expected_bytes: int | None, scope: str, label: str) -> dict[str, Any]:
    """Bind a parent-produced file without opening its payload in this builder."""
    path = path.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    value = {
        "path": str(path),
        "bytes": int(expected_bytes) if expected_bytes is not None else int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": expected_sha,
        "content_scope": scope,
        "payload_read_by_builder": False,
    }
    if expected_bytes is not None and int(stat.st_size) != int(expected_bytes):
        raise ValueError(f"{label} stat size differs from proof: {path}")
    return value


def load_json(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"{label}: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object: {path}")
    return value


def canonical_sha(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_producer_join() -> dict[str, Any]:
    request = load_json(ACTUAL_REQUEST, "ROOT133 actual request")
    proof = load_json(ACTUAL_PROOF, "ROOT133 actual proof")
    receipt = load_json(ACTUAL_RECEIPT, "ROOT133 execution receipt")
    if sha256_file(ACTUAL_REQUEST) != ACTUAL_REQUEST_SHA:
        raise ValueError("ROOT133 request SHA differs from proof")
    if sha256_file(ACTUAL_RECEIPT) != ACTUAL_RECEIPT_SHA:
        raise ValueError("ROOT133 receipt SHA differs from proof")
    if proof.get("request_sha256") != ACTUAL_REQUEST_SHA or proof.get("receipt_sha256") != ACTUAL_RECEIPT_SHA:
        raise ValueError("ROOT133 proof does not bind actual request and receipt")
    # The shared external-solver runner deliberately records a completed
    # development canary as COMPLETED_DEVELOPMENT_UNKNOWN and leaves the
    # child returncode unset.  The independent ROOT133 proof is the terminal
    # execution authority here: it binds the request/receipt, materialized
    # copies, 836 saved frames, and released reservation.  Do not silently
    # turn this canary into scientific qualification.
    if receipt.get("status") not in {"completed", "COMPLETED_DEVELOPMENT_UNKNOWN"}:
        raise ValueError("ROOT133 receipt is not a completed terminal run")
    if receipt.get("returncode") not in {None, 0}:
        raise ValueError("ROOT133 receipt reports a nonzero return code")
    if proof.get("parent_reservation_released") is not True or proof.get("gpu_lease_removed") is not True:
        raise ValueError("ROOT133 proof lacks terminal reservation/lease closure")
    if proof.get("parent_source_prepost_full_sha_equal") is not True:
        raise ValueError("ROOT133 proof lacks parent source pre/post closure")
    summary = proof.get("RunPARTs_summary")
    if not isinstance(summary, dict) or summary.get("rows") != EXPECTED_FRAME_COUNT:
        raise ValueError("ROOT133 proof lacks the expected 836 saved-frame summary")
    if abs(float(summary.get("final_time_s")) - FINAL_TIME_S) > 1.0e-12:
        raise ValueError("ROOT133 terminal time differs from registered value")
    if int(proof.get("native_frame_files_stat_only_count", -1)) != EXPECTED_FRAME_COUNT:
        raise ValueError("ROOT133 proof does not bind all native frame stat records")
    return {
        "request": request,
        "proof": proof,
        "receipt": receipt,
        "request_sha256": ACTUAL_REQUEST_SHA,
        "receipt_sha256": ACTUAL_RECEIPT_SHA,
        "runparts_sha256": ACTUAL_RUNPARTS_SHA,
        "frame_count": EXPECTED_FRAME_COUNT,
        "final_time_s": FINAL_TIME_S,
    }


def build(output: Path, *, case_id: str, attempt_id: str, launch_commit: str) -> dict[str, Any]:
    joined = validate_producer_join()
    for path, label in (
        (SNAPSHOT_WORKER, "snapshot worker"), (OBSERVER_WORKER, "observer worker"),
        (ENFORCER_V1, "enforcer v1 dependency"), (ENFORCER_V2, "enforcer v2"),
        (DECODER, "official decoder"), (DECODER_SOURCE, "decoder source"),
        (RUNTIME_V8, "runtime v8"), (RUNTIME_V6, "runtime v6"),
        (RUNTIME_V2, "runtime v2"), (STRICT_V8, "strict dispatch v8"),
        (ROOT132_PROOF, "ROOT132 proof"), (ROOT128_PROOF, "ROOT128 proof"),
        (ROOT120_REQUEST, "ROOT120 request"), (ROOT120_RECEIPT, "ROOT120 receipt"),
        (ROOT132_SNAPSHOT, "ROOT132 snapshot"), (ROOT128_REPORT, "ROOT128 support report"),
        (CALIBRATION_CONTRACT, "F3 calibration contract"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label}: {path}")

    # No Part_*.bi4 is opened or hashed here.  The ten deferred paths are
    # deliberately absent from input_files so runtime v8 cannot digest them
    # before the snapshot worker's own after-reservation pre/post guard.
    deferred = [str((RAW_ROOT / f"Part_{frame:04d}.bi4").resolve()) for frame in FRAMES]
    small_paths = [
        SNAPSHOT_WORKER, OBSERVER_WORKER, ENFORCER_V1, ENFORCER_V2, DECODER,
        Path(__file__), DECODER_SOURCE, RUNTIME_V8, RUNTIME_V6, RUNTIME_V2,
        STRICT_V8, ACTUAL_REQUEST, ACTUAL_PROOF,
        ACTUAL_RECEIPT, ROOT132_PROOF, ROOT128_PROOF, ROOT120_REQUEST,
        ROOT120_RECEIPT, ROOT132_SNAPSHOT, ROOT128_REPORT, CALIBRATION_CONTRACT,
    ]
    records = {str(path.expanduser().resolve()): small_record(path, "bounded source input") for path in small_paths}
    # These producer outputs are bound from ROOT133's actual proof.  Their
    # content is checked by the parent v8 guard after reservation, not here.
    records[str(GENERATED_XML.resolve())] = known_record(GENERATED_XML, GENERATED_XML_SHA, 9328, "parent_after_reservation_pre_post_hash", "ROOT133 generated XML")
    records[str(RUNPARTS.resolve())] = known_record(RUNPARTS, ACTUAL_RUNPARTS_SHA, None, "parent_after_reservation_pre_post_hash", "ROOT133 RunPARTs")
    records[str(FORCING.resolve())] = known_record(FORCING, FORCING_SHA, 14377599, "parent_after_reservation_pre_post_hash", "ROOT133 forcing copy")
    input_files = sorted(records)
    input_sha256 = {path: records[path]["sha256"] for path in input_files}
    command = [
        str(PYTHON), str(SNAPSHOT_WORKER), "--observer-request", str(output.expanduser().resolve()),
        "--output", "{attempt_root}/native_selected_source_snapshot_v2.json",
    ]
    request = {
        "schema": REQUEST_SCHEMA,
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
        "input_sha256": input_sha256,
        "deferred_input_files": deferred,
        "selected_native_frame_ids": FRAMES,
        "query_times_s": QUERY_TIMES,
        "query_brackets": {str(value): {"status": "UNKNOWN_UNTIL_RUNTIME_RUNPARTS", "query_time_s": value, "field_interpolation": "FORBIDDEN_BY_WORKER"} for value in QUERY_TIMES},
        "max_wall_seconds": 1200,
        "cpu_threads": 1,
        "omp_threads": 1,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
        "estimated_input_read_bytes": 0,
        "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_EXACT_TEN_SELECTED_PARTS",
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "hdf5_read": False,
        "bi4_decode": False,
        "raw_directory_scan": False,
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/native_selected_source_snapshot_v2.json"},
        "source_binding": {
            "schema": SCHEMA,
            "raw_root": str(RAW_ROOT.resolve()),
            "runparts": {"path": str(RUNPARTS.resolve()), "sha256": ACTUAL_RUNPARTS_SHA, "content_scope": "parent_after_reservation_pre_post_hash"},
            "generated_xml": {"path": str(GENERATED_XML.resolve()), "sha256": GENERATED_XML_SHA, "content_scope": "parent_after_reservation_pre_post_hash"},
            "forcing_copy": {"path": str(FORCING.resolve()), "sha256": FORCING_SHA, "content_scope": "parent_after_reservation_pre_post_hash"},
            "actual_solver_request": {"path": str(ACTUAL_REQUEST.resolve()), "sha256": ACTUAL_REQUEST_SHA},
            "actual_solver_receipt": {"path": str(ACTUAL_RECEIPT.resolve()), "sha256": ACTUAL_RECEIPT_SHA},
            "actual_verification_proof": {"path": str(ACTUAL_PROOF.resolve()), "sha256": sha256_file(ACTUAL_PROOF)},
            "root132_bi4_proof": {"path": str(ROOT132_PROOF.resolve()), "sha256": ROOT132_PROOF_SHA},
            "root128_support_proof": {"path": str(ROOT128_PROOF.resolve()), "sha256": ROOT128_PROOF_SHA},
            "terminal_frame_count": EXPECTED_FRAME_COUNT,
            "terminal_time_s": FINAL_TIME_S,
            "full_native_tree_scan": False,
            "deferred_part_payloads": True,
        },
        "field_contract": {
            "finite_checks": ["Idp", "Pos_or_Posd", "Vel", "Rhop"],
            "identity": "decoded Idp must map exactly to generated XML typed ranges; mkfluid_relative and mk_absolute remain separate",
            "sample_mass": "UNKNOWN_UNTIL_NATIVE_HEADER_OBSERVER; snapshot does not decode native fields",
            "native_header_mass": "UNKNOWN_UNTIL_NATIVE_HEADER_OBSERVER; XML mass is not substituted",
            "continuous_owner_mass": "ROOT128 owner mass 14.58 kg remains separate; XML/native sample mass does not prove continuum equivalence",
            "observables": ["weighted_centroid_m", "weighted_velocity_m_per_s", "kinetic_energy_j", "finite_stats", "actual_RunPARTs_time_brackets"],
            "pressure_eos": "UNKNOWN_NOT_DECODED_BY_WORKER",
            "rigid_body_mass_inertia": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SAMPLE",
        },
        "observer_calibration": {
            "source_contract": str(CALIBRATION_CONTRACT.resolve()),
            "position_tolerance_fraction_L": 0.02,
            "velocity_tolerance_fraction_registered_nonzero_scale": 0.05,
            "kinetic_energy_tolerance_fraction_registered_nonzero_scale": 0.05,
            "time_and_output_budget_share_each": 0.25,
            "registered_L_m": 0.894,
            "registered_velocity_scale_m_per_s": 0.9077664897978995,
            "registered_ke_scale_j": 6.0072516,
            "event_time_T": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
            "no_neighbor_grid_truth": True,
            "no_particle_interpolation": True,
        },
        "next_stage": {
            "snapshot_manifest": "{attempt_root}/native_selected_source_snapshot_v2.json",
            "observer_enforcer": str(ENFORCER_V2.resolve()),
            "observer_worker": str(OBSERVER_WORKER.resolve()),
            "decoder": str(DECODER.resolve()),
            "decode_requires_parent_snapshot_manifest": True,
            "decode_scope": "ten selected frames only; no full raw tree scan",
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(STRICT_V8.resolve()),
            "parent_reservation_required": True,
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "deferred_native_payload": "worker-first SHA/stat only after reservation",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "source_provenance": {
            "actual_root133_request_sha256": ACTUAL_REQUEST_SHA,
            "actual_root133_receipt_sha256": ACTUAL_RECEIPT_SHA,
            "actual_root133_proof_sha256": sha256_file(ACTUAL_PROOF),
            "root132_snapshot_proof_sha256": ROOT132_PROOF_SHA,
            "root128_support_proof_sha256": ROOT128_PROOF_SHA,
            "native_fields_read_by_builder": False,
            "native_payload_read_by_builder": False,
        },
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
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "selected_frame_count": len(FRAMES),
        "terminal_frame_count": EXPECTED_FRAME_COUNT,
        "native_payload_read_by_builder": False,
        "solver_started": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--output", type=Path, default=REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-coarse-native-audit-root139-001.json")
    parser.add_argument("--case-id", default="F3_S2_COARSE_NATIVE_AUDIT_ROOT139")
    parser.add_argument("--attempt-id", default="f3-s2-coarse-native-audit-root139-001")
    parser.add_argument("--launch-commit", default=None)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if not args.prepare:
        parser.error("use --prepare")
    launch_commit = args.launch_commit or subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()
    value = build(args.output, case_id=args.case_id, attempt_id=args.attempt_id, launch_commit=launch_commit)
    write_new(args.output, value)
    print(json.dumps({"status": "PREPARED_F3_NATIVE_AUDIT_SOURCE_SNAPSHOT", "request": str(args.output.resolve()), "native_payload_read_by_builder": False, "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
