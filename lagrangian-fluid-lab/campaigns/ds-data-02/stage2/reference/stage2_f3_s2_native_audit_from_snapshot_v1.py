#!/usr/bin/env python3
"""Build the bounded ROOT139 F3 native-field audit after a source snapshot.

The preceding ROOT139 request only hashes the ten selected ``Part_*.bi4``
files after a parent CPU reservation.  This forward builder consumes that
small immutable manifest and prepares a second, separately identified audit
request.  The audit enforcer hashes the same files before and after the child
decoder, while the child reads only the selected frames and emits finite
position/velocity/density/Idp, per-MK mass and weighted observables.

This module reads the manifest JSON and small producer metadata only.  It
never opens a BI4/VTK/HDF5 payload, walks the raw output directory, verifies
content outside the parent guard, or starts a solver.  A missing or malformed
manifest is a hard preparation error; no request with an unbound native
source is emitted.
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
    FRAMES,
    GENERATED_XML,
    GENERATED_XML_SHA,
    MAIN,
    OBSERVER_WORKER,
    RAW_ROOT,
    REPO,
    RUNPARTS,
    ROOT120_RECEIPT,
    ROOT120_RECEIPT_SHA,
    ROOT120_REQUEST,
    ROOT120_REQUEST_SHA,
    ROOT128_PROOF,
    ROOT128_PROOF_SHA,
    ROOT128_REPORT,
    ROOT132_PROOF,
    ROOT132_PROOF_SHA,
    ROOT132_SNAPSHOT,
    ROOT132_SNAPSHOT_SHA,
    RUNTIME_V2,
    RUNTIME_V6,
    RUNTIME_V8,
    SNAPSHOT_WORKER,
    STRICT_V8,
    ENFORCER_V1,
    ENFORCER_V2,
    QUERY_TIMES,
    SCHEMA as SNAPSHOT_REQUEST_SCHEMA,
    canonical_sha,
    known_record,
    load_json,
    sha256_file,
    small_record,
)


HEADER_OBSERVER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_native_header_observer_v1.py"
JPART_BI4_HEADER = Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.h")
JPART_BI4_SOURCE = Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.cpp")


REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f3-s2.native-field-audit-from-snapshot.v1"
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
DEFAULT_OUTPUT = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f3-s2-coarse-native-audit-root139-decode-001.json"
)


def manifest_records(manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate only the snapshot JSON and return its immutable file records."""

    manifest = load_json(manifest_path, "ROOT139 native source snapshot")
    if manifest.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError("snapshot manifest schema is not native-source-snapshot.v2")
    if manifest.get("status") != "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE":
        raise ValueError("snapshot manifest is not a successful selected-source hash")
    scope = manifest.get("worker_scope")
    if not isinstance(scope, dict) or scope.get("selected_native_bi4_only") is not True:
        raise ValueError("snapshot scope is not selected-BI4-only")
    for field in ("full_raw_tree_hash", "raw_root_hash", "unlisted_part_files"):
        if field in scope and scope[field] not in {"NOT_COMPUTED_BY_WORKER", "NOT_INSPECTED_BY_WORKER"}:
            raise ValueError(f"snapshot unexpectedly claims a full-tree result: {field}")
    entries = manifest.get("immutable_source_sha_list")
    if not isinstance(entries, list) or len(entries) != len(FRAMES):
        raise ValueError("snapshot selected-file list does not contain the ten registered frames")
    by_frame: dict[int, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("snapshot selected-file entry is not an object")
        frame = entry.get("frame")
        path = entry.get("path")
        digest = entry.get("sha256")
        size = entry.get("bytes")
        if not isinstance(frame, int) or frame in by_frame:
            raise ValueError("snapshot frame identity is not unique")
        expected = (RAW_ROOT / f"Part_{frame:04d}.bi4").resolve()
        if path != str(expected):
            raise ValueError(f"snapshot frame {frame} is outside the ROOT133 raw-root contract")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"snapshot frame {frame} has no SHA-256")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError(f"snapshot frame {frame} has no positive byte count")
        by_frame[frame] = entry
    if sorted(by_frame) != FRAMES:
        raise ValueError(f"snapshot frames differ from the registered ROOT139 selection: {sorted(by_frame)}")
    selected_total = manifest.get("selected_native_total_bytes")
    if selected_total != sum(int(by_frame[frame]["bytes"]) for frame in FRAMES):
        raise ValueError("snapshot selected_native_total_bytes does not close over its records")
    source_digest = manifest.get("source_sha_list_digest")
    if not isinstance(source_digest, str) or len(source_digest) != 64:
        raise ValueError("snapshot lacks source SHA-list digest")
    return manifest, [by_frame[frame] for frame in FRAMES]


def build(manifest_path: Path, output: Path, *, case_id: str, attempt_id: str, launch_commit: str) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    manifest, selected = manifest_records(manifest_path)
    # Small metadata and producer artifacts are bound here.  XML/RunPARTs/
    # forcing are intentionally represented by proof-backed SHA values and
    # rehashed by the parent runtime after reservation; this builder does not
    # open their payloads.
    for path, label in (
        (manifest_path, "ROOT139 snapshot manifest"),
        (SNAPSHOT_WORKER, "snapshot worker"),
        (OBSERVER_WORKER, "base observer worker"),
        (HEADER_OBSERVER, "native header observer worker"),
        (ENFORCER_V1, "enforcer v1 dependency"),
        (ENFORCER_V2, "enforcer v2"),
        (DECODER, "official decoder"),
        (DECODER_SOURCE, "decoder source"),
        (RUNTIME_V8, "runtime v8"),
        (RUNTIME_V6, "runtime v6"),
        (RUNTIME_V2, "runtime v2"),
        (STRICT_V8, "strict dispatch v8"),
        (ACTUAL_REQUEST, "ROOT133 actual request"),
        (ACTUAL_PROOF, "ROOT133 actual proof"),
        (ACTUAL_RECEIPT, "ROOT133 actual receipt"),
        (ROOT132_PROOF, "ROOT132 proof"),
        (ROOT128_PROOF, "ROOT128 proof"),
        (ROOT120_REQUEST, "ROOT120 request"),
        (ROOT120_RECEIPT, "ROOT120 receipt"),
        (ROOT132_SNAPSHOT, "ROOT132 snapshot"),
        (ROOT128_REPORT, "ROOT128 support report"),
        (CALIBRATION_CONTRACT, "F3 calibration contract"),
        (JPART_BI4_HEADER, "official JPartDataBi4 header source"),
        (JPART_BI4_SOURCE, "official JPartDataBi4 implementation source"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label}: {path}")

    records: dict[str, dict[str, Any]] = {}
    small_paths = [
        Path(__file__), manifest_path, SNAPSHOT_WORKER, OBSERVER_WORKER, HEADER_OBSERVER,
        ENFORCER_V1, ENFORCER_V2, DECODER, DECODER_SOURCE, RUNTIME_V8,
        RUNTIME_V6, RUNTIME_V2, STRICT_V8, ACTUAL_REQUEST, ACTUAL_PROOF,
        ACTUAL_RECEIPT, ROOT132_PROOF, ROOT128_PROOF, ROOT120_REQUEST,
        ROOT120_RECEIPT, ROOT132_SNAPSHOT, ROOT128_REPORT, CALIBRATION_CONTRACT,
        JPART_BI4_HEADER, JPART_BI4_SOURCE,
    ]
    for path in small_paths:
        record = small_record(path, "bounded audit source or manifest")
        records[record["path"]] = record
    records[str(GENERATED_XML.resolve())] = known_record(
        GENERATED_XML, GENERATED_XML_SHA, 9328, "parent_after_reservation_pre_post_hash", "ROOT133 generated XML"
    )
    records[str(RUNPARTS.resolve())] = known_record(
        RUNPARTS, ACTUAL_RUNPARTS_SHA, None, "parent_after_reservation_pre_post_hash", "ROOT133 RunPARTs"
    )
    records[str(FORCING.resolve())] = known_record(
        FORCING, FORCING_SHA, 14377599, "parent_after_reservation_pre_post_hash", "ROOT133 forcing copy"
    )
    input_files = sorted(records)
    input_sha256 = {path: records[path]["sha256"] for path in input_files}
    deferred = [str(Path(item["path"]).resolve()) for item in selected]
    selected_bytes = sum(int(item["bytes"]) for item in selected)
    # The enforcer hashes each selected source before and after the child; the
    # child then decodes it once.  This is a planning proxy only; the parent
    # receipt remains the authority for actual bytes/time.
    input_bytes = sum(int(records[path]["bytes"]) for path in input_files)
    command = [
        str(Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")),
        str(ENFORCER_V2),
        "--observer-worker", str(HEADER_OBSERVER),
        "--expected-source-manifest", str(manifest_path),
        "--raw-root", str(RAW_ROOT.resolve()),
        "--runparts", str(RUNPARTS.resolve()),
        "--generated-xml", str(GENERATED_XML.resolve()),
        "--decoder", str(DECODER.resolve()),
        "--decoder-source", str(DECODER_SOURCE.resolve()),
        "--output", "{attempt_root}/observer/f3_s2_coarse_native_audit_root139.json",
        "--scratch-root", "{attempt_root}/scratch/bi4_decode",
        "--cwd", str(REPO),
        "--expected-frame-count", str(EXPECTED_FRAME_COUNT),
        "--expected-final-time-s", repr(FINAL_TIME_S),
        "--final-time-tolerance-s", "1e-12",
        "--frames", *[str(frame) for frame in FRAMES],
        "--query-times", *[repr(value) for value in QUERY_TIMES],
    ]
    request: dict[str, Any] = {
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
        "query_brackets": {
            str(value): {
                "status": "UNKNOWN_UNTIL_RUNPARTS_AND_NATIVE_AUDIT",
                "query_time_s": value,
                "native_saved_time_interpolation": "FORBIDDEN_BY_WORKER",
            }
            for value in QUERY_TIMES
        },
        "max_wall_seconds": 1800,
        "cpu_threads": 1,
        "omp_threads": 1,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "estimated_peak_memory_bytes": 2 * 1024 * 1024 * 1024,
        "estimated_input_read_bytes": input_bytes + 3 * selected_bytes,
        "estimated_native_read_bytes": 3 * selected_bytes,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "hdf5_read": False,
        "bi4_decode": True,
        "raw_directory_scan": False,
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": "{attempt_root}/observer/f3_s2_coarse_native_audit_root139.json",
        },
        "source_binding": {
            "schema": SCHEMA,
            "snapshot_manifest": {
                "path": str(manifest_path),
                "sha256": sha256_file(manifest_path),
                "selected_source_sha_list_digest": manifest["source_sha_list_digest"],
                "selected_native_total_bytes": selected_bytes,
                "content_scope": "parent_snapshot_worker_after_reservation_manifest",
            },
            "raw_root": str(RAW_ROOT.resolve()),
            "runparts": {"path": str(RUNPARTS.resolve()), "sha256": ACTUAL_RUNPARTS_SHA, "content_scope": "parent_after_reservation_pre_post_hash"},
            "generated_xml": {"path": str(GENERATED_XML.resolve()), "sha256": GENERATED_XML_SHA, "content_scope": "parent_after_reservation_pre_post_hash"},
            "forcing_copy": {"path": str(FORCING.resolve()), "sha256": FORCING_SHA, "content_scope": "parent_after_reservation_pre_post_hash"},
            "actual_solver_request": {"path": str(ACTUAL_REQUEST.resolve()), "sha256": ACTUAL_REQUEST_SHA},
            "actual_solver_receipt": {"path": str(ACTUAL_RECEIPT.resolve()), "sha256": ACTUAL_RECEIPT_SHA},
            "actual_verification_proof": {"path": str(ACTUAL_PROOF.resolve()), "sha256": ACTUAL_PROOF_SHA},
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
            "sample_mass": "native BI4 header MassFluid multiplied by decoded fluid count; XML mass is not substituted",
            "native_header_fields": ["MassFluid", "MassBound", "Rhop0", "Dp", "H", "PeriMode"],
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
        "snapshot_provenance": {
            "manifest_status": manifest.get("status"),
            "selected_frame_records": selected,
            "selected_source_sha_list_digest": manifest["source_sha_list_digest"],
            "native_fields_read_by_builder": False,
            "native_payload_read_by_builder": False,
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(STRICT_V8.resolve()),
            "parent_reservation_required": True,
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "deferred_native_payload": "enforcer pre/decode/post selected frames only after reservation",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "source_provenance": {
            "actual_root133_request_sha256": ACTUAL_REQUEST_SHA,
            "actual_root133_receipt_sha256": ACTUAL_RECEIPT_SHA,
            "actual_root133_proof_sha256": ACTUAL_PROOF_SHA,
            "root139_snapshot_manifest_sha256": sha256_file(manifest_path),
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
    fake = {
        "schema": SNAPSHOT_SCHEMA,
        "status": "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE",
        "worker_scope": {
            "selected_native_bi4_only": True,
            "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER",
            "unlisted_part_files": "NOT_INSPECTED_BY_WORKER",
        },
        "immutable_source_sha_list": [
            {"frame": frame, "path": str(RAW_ROOT / f"Part_{frame:04d}.bi4"), "bytes": 1, "sha256": "0" * 64}
            for frame in FRAMES
        ],
        "selected_native_total_bytes": len(FRAMES),
        "source_sha_list_digest": "1" * 64,
    }
    with __import__("tempfile").TemporaryDirectory(prefix="ds02-f3-native-audit-") as root:
        path = Path(root) / "manifest.json"
        path.write_text(json.dumps(fake), encoding="utf-8")
        _, selected = manifest_records(path)
        assert len(selected) == len(FRAMES)
    return {
        "status": "PASS",
        "selected_frame_count": len(FRAMES),
        "manifest_payload_only": True,
        "solver_started": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--snapshot-manifest", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case-id", default="F3_S2_COARSE_NATIVE_AUDIT_ROOT139_DECODE")
    parser.add_argument("--attempt-id", default="f3-s2-coarse-native-audit-root139-decode-001")
    parser.add_argument("--launch-commit", default=None)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if not args.prepare or args.snapshot_manifest is None:
        parser.error("use --prepare --snapshot-manifest PATH")
    launch_commit = args.launch_commit or subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()
    value = build(args.snapshot_manifest, args.output, case_id=args.case_id, attempt_id=args.attempt_id, launch_commit=launch_commit)
    write_new(args.output, value)
    print(json.dumps({
        "status": "PREPARED_F3_NATIVE_FIELD_AUDIT_FROM_SNAPSHOT",
        "request": str(args.output.resolve()),
        "snapshot_manifest": str(args.snapshot_manifest.resolve()),
        "selected_frame_count": len(FRAMES),
        "native_payload_read_by_builder": False,
        "solver_started": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
