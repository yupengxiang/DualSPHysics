#!/usr/bin/env python3
"""Build the ROOT147 ten-frame header request with a manifest adapter.

The consumed ROOT144 request passed the ROOT139 producer wrapper directly to
the enforcer and therefore stopped before native decoding.  This forward
builder invokes ``stage2_f3_s2_native_header_root147_runner_v1.py``.  The
runner first turns the ROOT139 small JSON into the enforcer v1 manifest, then
execs the existing v2 enforcer with that manifest.  The request remains
strictly ten-frame, source-bound, and scientific-qualification UNKNOWN.

The builder reads/hashes only small JSON/source inputs.  Selected BI4 paths
are deferred to the parent/enforcer after reservation and are never opened by
this builder.
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
    FORCING,
    FORCING_SHA,
    GENERATED_XML,
    GENERATED_XML_SHA,
    MAIN,
    RAW_ROOT,
    REPO,
    ROOT128_PROOF,
    ROOT128_PROOF_SHA,
    ROOT132_PROOF,
    ROOT132_PROOF_SHA,
    RUNPARTS,
    RUNTIME_V2,
    RUNTIME_V6,
    RUNTIME_V8,
    STRICT_V8,
    known_record,
    small_record,
)

import stage2_f3_s2_native_source_manifest_adapter_v1 as adapter


REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f3-s2.native-header-root147-request.v1"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
HEADER_OBSERVER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_native_header_observer_v1.py"
BASE_OBSERVER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py"
ENFORCER_V1 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_enforcer_v1.py"
ENFORCER_V2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_enforcer_v2.py"
ADAPTER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_native_source_manifest_adapter_v1.py"
RUNNER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_native_header_root147_runner_v1.py"
SNAPSHOT = adapter.SNAPSHOT
SNAPSHOT_PROOF = adapter.SNAPSHOT_PROOF
SNAPSHOT_PROOF_SHA = adapter.SNAPSHOT_PROOF_SHA256
SNAPSHOT_REQUEST = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f3-s2-coarse-selected-source-snapshot-v2-root-forward-139-001.json"
)
SNAPSHOT_REQUEST_SHA = adapter.SNAPSHOT_REQUEST_SHA256
MANIFEST_OUTPUT = "{attempt_root}/source-manifest/root139-compatible-manifest-v1.json"
OBSERVER_OUTPUT = "{attempt_root}/observer/f3_s2_coarse_native_header_root147.json"
SCRATCH_OUTPUT = "{attempt_root}/scratch/bi4_decode"
FRAMES = list(adapter.EXPECTED_FRAMES)
QUERY_TIMES = [0.0, 2.0, 4.0, 6.0, 8.0, 8.350023358431661]
FINAL_TIME_S = 8.350023358431661
EXPECTED_FRAME_COUNT = 836


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def require_file(path: Path, label: str) -> None:
    if path.expanduser().resolve().is_symlink() or not path.expanduser().resolve().is_file():
        raise FileNotFoundError(f"{label}: {path}")


def build(output: Path, *, case_id: str, attempt_id: str, launch_commit: str) -> dict[str, Any]:
    snapshot = adapter.load_root139_snapshot(SNAPSHOT)
    if snapshot["snapshot_sha256"] != adapter.SNAPSHOT_SHA256:
        raise ValueError("ROOT139 snapshot SHA changed")
    for path, label in (
        (SNAPSHOT, "ROOT139 snapshot wrapper"),
        (SNAPSHOT_REQUEST, "ROOT139 request"),
        (SNAPSHOT_PROOF, "ROOT139 proof"),
        (ADAPTER, "ROOT147 manifest adapter"),
        (RUNNER, "ROOT147 runner"),
        (ENFORCER_V1, "enforcer v1 dependency"),
        (ENFORCER_V2, "enforcer v2"),
        (HEADER_OBSERVER, "native header observer"),
        (BASE_OBSERVER, "base observer"),
        (DECODER, "official decoder"),
        (DECODER_SOURCE, "decoder source"),
        (CALIBRATION_CONTRACT, "calibration contract"),
        (ACTUAL_REQUEST, "ROOT133 actual request"),
        (ACTUAL_PROOF, "ROOT133 proof"),
        (ACTUAL_RECEIPT, "ROOT133 receipt"),
        (ROOT132_PROOF, "ROOT132 proof"),
        (ROOT128_PROOF, "ROOT128 proof"),
        (RUNTIME_V2, "runtime v2"),
        (RUNTIME_V6, "runtime v6"),
        (RUNTIME_V8, "runtime v8"),
        (STRICT_V8, "strict dispatch v8"),
    ):
        require_file(path, label)
    if sha256_file(SNAPSHOT_REQUEST) != SNAPSHOT_REQUEST_SHA:
        raise ValueError("ROOT139 request SHA differs from the actual request")
    if sha256_file(SNAPSHOT_PROOF) != SNAPSHOT_PROOF_SHA:
        raise ValueError("ROOT139 proof SHA differs from the actual proof")

    paths = [
        Path(__file__), ADAPTER, RUNNER, ENFORCER_V1, ENFORCER_V2, HEADER_OBSERVER, BASE_OBSERVER,
        DECODER, DECODER_SOURCE, CALIBRATION_CONTRACT, SNAPSHOT, SNAPSHOT_REQUEST, SNAPSHOT_PROOF,
        ACTUAL_REQUEST, ACTUAL_PROOF, ACTUAL_RECEIPT, ROOT132_PROOF, ROOT128_PROOF,
        RUNTIME_V2, RUNTIME_V6, RUNTIME_V8, STRICT_V8,
    ]
    records = {str(path.expanduser().resolve()): small_record(path, "ROOT147 bounded input") for path in paths}
    records[str(GENERATED_XML.resolve())] = known_record(
        GENERATED_XML, GENERATED_XML_SHA, 9328, "parent_after_reservation_pre_post_hash", "ROOT133 generated XML"
    )
    records[str(RUNPARTS.resolve())] = known_record(
        RUNPARTS, ACTUAL_RUNPARTS_SHA, None, "parent_after_reservation_pre_post_hash", "ROOT133 RunPARTs"
    )
    records[str(FORCING.resolve())] = known_record(
        FORCING, FORCING_SHA, 14377599, "parent_after_reservation_pre_post_hash", "ROOT133 forcing"
    )
    input_files = sorted(records)
    input_sha256 = {path: records[path]["sha256"] for path in input_files}
    manifest_output = MANIFEST_OUTPUT
    enforcer_args = [
        "--observer-worker", str(HEADER_OBSERVER),
        "--expected-source-manifest", manifest_output,
        "--raw-root", str(RAW_ROOT.resolve()),
        "--runparts", str(RUNPARTS.resolve()),
        "--generated-xml", str(GENERATED_XML.resolve()),
        "--decoder", str(DECODER.resolve()),
        "--decoder-source", str(DECODER_SOURCE.resolve()),
        "--output", OBSERVER_OUTPUT,
        "--scratch-root", SCRATCH_OUTPUT,
        "--cwd", str(REPO),
        "--expected-frame-count", str(EXPECTED_FRAME_COUNT),
        "--expected-final-time-s", repr(FINAL_TIME_S),
        "--final-time-tolerance-s", "1e-12",
        "--frames", *[str(frame) for frame in FRAMES],
        "--query-times", *[repr(value) for value in QUERY_TIMES],
    ]
    command = [
        str(PYTHON), str(RUNNER),
        "--snapshot", str(SNAPSHOT.resolve()),
        "--manifest-output", manifest_output,
        "--expected-snapshot-sha", adapter.SNAPSHOT_SHA256,
        "--enforcer", str(ENFORCER_V2),
        "--enforcer-argv", *enforcer_args,
    ]
    deferred = [str((RAW_ROOT / f"Part_{frame:04d}.bi4").resolve()) for frame in FRAMES]
    selected_bytes = int(snapshot["selected_native_total_bytes"])
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": adapter.EXPECTED_FAMILY_ID,
        "sentinel_id": adapter.EXPECTED_SENTINEL_ID,
        "physical_case_id": adapter.EXPECTED_PHYSICAL_CASE_ID,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "launch_commit": launch_commit,
        "command": command,
        "input_files": input_files,
        "input_sha256": input_sha256,
        "deferred_input_files": deferred,
        "deferred_input_policy": {
            "parent_v8_input_hash": "NOT_CLAIMED_FOR_SELECTED_BI4",
            "adapter_reads_snapshot_json_only": True,
            "enforcer_hashes_selected_frames_after_parent_reservation": True,
            "selected_frame_ids": FRAMES,
            "raw_root_exact": str(RAW_ROOT.resolve()),
        },
        "selected_native_frame_ids": FRAMES,
        "query_times_s": QUERY_TIMES,
        "query_brackets": {
            str(value): {
                "status": "UNKNOWN_UNTIL_RUNPARTS_NATIVE_HEADER_RUN",
                "query_time_s": value,
                "native_saved_time_interpolation": "FORBIDDEN_BY_HEADER_WORKER",
            }
            for value in QUERY_TIMES
        },
        "max_wall_seconds": 1800,
        "cpu_threads": 1,
        "omp_threads": 1,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "estimated_peak_memory_bytes": 2 * 1024 * 1024 * 1024,
        "estimated_input_read_bytes": selected_bytes * 3 + 64 * 1024 * 1024,
        "estimated_native_read_bytes": selected_bytes * 3,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "hdf5_read": False,
        "bi4_decode": True,
        "raw_directory_scan": False,
        "output": {"atomic": True, "refuse_overwrite": True, "path": OBSERVER_OUTPUT},
        "source_binding": {
            "schema": SCHEMA,
            "root139_snapshot_wrapper": {
                "path": str(SNAPSHOT.resolve()),
                "sha256": adapter.SNAPSHOT_SHA256,
                "selected_source_sha_list_digest": snapshot["source_sha_list_digest"],
                "selected_native_total_bytes": selected_bytes,
                "selected_frame_ids": FRAMES,
                "identity": snapshot["identity"],
                "proof_sha256": SNAPSHOT_PROOF_SHA,
            },
            "adapted_manifest_output": manifest_output,
            "raw_root": str(RAW_ROOT.resolve()),
            "runparts": {"path": str(RUNPARTS.resolve()), "sha256": ACTUAL_RUNPARTS_SHA, "parent_pre_post": True},
            "generated_xml": {"path": str(GENERATED_XML.resolve()), "sha256": GENERATED_XML_SHA, "parent_pre_post": True},
            "actual_root133_request_sha256": ACTUAL_REQUEST_SHA,
            "actual_root133_proof_sha256": ACTUAL_PROOF_SHA,
            "actual_root133_receipt_sha256": ACTUAL_RECEIPT_SHA,
        },
        "field_contract": {
            "native_header_fields": ["MassFluid", "MassBound", "Rhop0", "Dp", "H", "PeriMode"],
            "sample_mass": "native_header_MassFluid_only; XML mass is never fallback",
            "finite_fields": ["Idp", "Pos_or_Posd", "Vel", "Rhop"],
            "identity": "XML range labels only; no native Type/MK claim",
            "continuum_owner_mass": "UNKNOWN",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "resource_guard": {
            "parent_reservation_required": True,
            "runner": str(STRICT_V8.resolve()),
            "adapter_scope": "small ROOT139 JSON only",
            "enforcer_scope": "ten selected Part files only",
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "no_verify_content_true": True,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    request["sha256"] = canonical_sha(request)
    return request


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    assert FRAMES == adapter.EXPECTED_FRAMES and len(FRAMES) == 10
    assert EXPECTED_FRAME_COUNT == 836 and FINAL_TIME_S > 8.0
    assert "--enforcer-argv" in build_command_shape()
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "selected_frame_count": len(FRAMES),
        "manifest_adapter_required": True,
        "native_payload_read_by_builder": False,
        "execution_allowed": True,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build_command_shape() -> list[str]:
    return [str(PYTHON), str(RUNNER), "--manifest-output", MANIFEST_OUTPUT, "--enforcer-argv"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--output", type=Path, default=REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-coarse-ten-native-header-root147-001.json")
    parser.add_argument("--case-id", default="F3_S2_COARSE_TEN_NATIVE_HEADER_AUDIT_ROOT147")
    parser.add_argument("--attempt-id", default="f3-s2-coarse-ten-native-header-audit-root147-001")
    parser.add_argument("--launch-commit", default=None)
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
        "status": "READY_FOR_PARENT_GUARD",
        "request": str(args.output.expanduser().resolve()),
        "selected_frame_count": len(FRAMES),
        "manifest_adapter": str(ADAPTER),
        "native_payload_read_by_builder": False,
        "execution_allowed": True,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
