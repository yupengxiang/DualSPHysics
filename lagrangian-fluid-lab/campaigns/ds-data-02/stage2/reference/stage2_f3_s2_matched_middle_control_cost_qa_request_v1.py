#!/usr/bin/env python3
"""Build the launch-disabled F3-S2 middle-staging metadata QA request.

The builder hashes only bounded JSON/XML/Python/CSV metadata inputs.  It
never opens the 14.8 MB ROOT150 observer report, any native Part/VTK/HDF5
payload, or the 14 MB acceleration table.  Those artifacts are bound by the
parent-produced SHA records and are explicitly marked ``read_by_worker``
false.  The generated request is an audit/readiness request only; it emits
no solver request and cannot start a guard, GPU, GenCase, or native decoder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
WORKER = REFERENCE / "stage2_f3_s2_matched_middle_control_cost_qa_v1.py"
PLAN = REFERENCE / "stage2_f3_s2_matched_three_grid_plan_v2.json"
CONTRACT = REFERENCE / "stage2_f3_s2_observer_calibration_contract_v1.json"

ROOT150_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_FULL836_NATIVE_STREAM_ACTUAL_LIMITED_ROOT_VERIFICATION_150.json"
ROOT150_REPORT = DATA_ROOT / "families/F3/F3_S2_COARSE_FULL_NATIVE_STREAM_V3_ROOT_150/f3-s2-coarse-full-native-stream-v3-root-150-001-root-forward-030-001/observer/f3_s2_full_native_stream_v3_root150.json"
ROOT150_RECEIPT = DATA_ROOT / "families/F3/F3_S2_COARSE_FULL_NATIVE_STREAM_V3_ROOT_150/f3-s2-coarse-full-native-stream-v3-root-150-001-root-forward-030-001/execution-receipt.json"
ROOT133_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_DP015_COARSE_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_133.json"
ROOT133_REQUEST = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-coarse-external-v8-root-forward-133-001.json"
ROOT133_RECEIPT = DATA_ROOT / "families/F3/F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT_133/f3-s2-owner-centered-dp015-full-cfd-canary-v8-root-133-001/execution-receipt.json"
ROOT133_RUNPARTS = Path("/var/tmp/ds02-stage2/F3/F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT_133/f3-s2-owner-centered-dp015-full-cfd-canary-v8-root-133-001/solver_output/RunPARTs.csv")
ROOT133_GENERATED_XML = Path("/var/tmp/ds02-stage2/F3/F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT_133/f3-s2-owner-centered-dp015-full-cfd-canary-v8-root-133-001/solver-inputs/generated.xml")

MIDDLE_RECEIPT = DATA_ROOT / "families/F3/F3_S2_P1200_AY0750_MATCHED_SOURCE_GENCASE_ROOT_086/f3-s2-source-clone-gencase-v1-root-086-001-root-forward-030-001/execution-receipt.json"
MIDDLE_XML = DATA_ROOT / "families/F3/F3_S2_P1200_AY0750_MATCHED_SOURCE_GENCASE_ROOT_086/f3-s2-source-clone-gencase-v1-root-086-001-root-forward-030-001/generated/F3_S2_P1200_AY0750_MATCHED.xml"
MIDDLE_SUPPORT = DATA_ROOT / "families/F3/F3_S2_ROOT086_GUARDED_VTK_SUPPORT_V2_ROOT_093/f3-s2-root086-vtk-support-qa-v2-root-093-001-root-forward-030-001/f3-s2-root086-vtk-support-qa-v2.json"
FINE_RECEIPT = DATA_ROOT / "families/F3/F3_S2_MATCHED_SOURCE_COMMENSURATE_DP003_GENCASE_ROOT_102/f3-s2-commensurate-dp003-gencase-v1-root-102-001-root-forward-030-001/execution-receipt.json"
FINE_XML = DATA_ROOT / "families/F3/F3_S2_MATCHED_SOURCE_COMMENSURATE_DP003_GENCASE_ROOT_102/f3-s2-commensurate-dp003-gencase-v1-root-102-001-root-forward-030-001/worker/generated/F3_S2_P1200_AY0750_DP003_MATCHED.xml"
FINE_SUPPORT = DATA_ROOT / "families/F3/F3_S2_DP003_ACTUAL_INITIAL_SUPPORT_QA_ROOT_104/f3-s2-dp003-initial-support-qa-v1-root-104-001-root-forward-030-001/f3-s2-dp003-initial-support-qa-v1.json"
COARSE_SUPPORT_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_DP015_SUPPORT_V6_ACTUAL_ROOT_VERIFICATION_128.json"
SOURCE_XML = DATA_ROOT / "families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/prepared/pitch120_ay0750/F3_STAGE1_DP006_P1200_AY0750.xml"

ROOT150_PROOF_SHA = "c230518332163e790f6996563ecfc4f008cfbebea94f451b5cc670ab581827cf"
ROOT150_REPORT_SHA = "81148499db02132a7001dd30e9395bec335e21c5c401dc0347da635b215efc64"
ROOT150_REPORT_BYTES = 14825462
ROOT150_RECEIPT_SHA = "6f61b79c7311ba203a5a13fd6231db43e506b6586a00746d1c09d7ad920da626"
ROOT133_PROOF_SHA = "5d459c01728e83178903695b39f131b1c0b9ea30293454454c6c8c17f7be4706"
ROOT133_REQUEST_SHA = "0441462c5e8ed9198e10648d31f75bcdc844742abcf883478c2d02fa5a5de624"
ROOT133_RECEIPT_SHA = "10df2f69977034ca3be8d6b7fd388bd7a565049af1c225a78f9937bc7ef8cc75"
ROOT133_RUNPARTS_SHA = "81b85b927c023fcc4a798b2a86ca7193f4c5c8062174868bbcf7765aada08cd1"
ROOT133_XML_SHA = "e9991fa4864607c8bc754f6458bc867a9572708296aef9965e0c3797166bd2b1"
SOURCE_CONTROL_SHA = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
SOURCE_XML_SHA = "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
QUERY_TIMES_S = [0.0, 2.0, 4.0, 6.0, 8.0, 8.350016881886734]
SOURCE_WINDOW_S = [0.0, 8.350016881886734]

DEFAULT_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f3-s2-matched-middle-control-cost-qa-v1"
DEFAULT_OUTPUT = DEFAULT_ROOT / "f3_s2_matched_middle_control_cost_qa_v1_root-ready.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _small_record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    if stat.st_size > 2 * 1024 * 1024:
        raise ValueError(f"{label} is not a bounded metadata input: {path} ({stat.st_size} bytes)")
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "dev": int(stat.st_dev),
        "ino": int(stat.st_ino),
        "sha256": _sha256(path),
        "content_scope": "small_metadata_hashed_by_builder",
    }


def _known_record(path: Path, *, expected_sha: str, expected_bytes: int | None, label: str, read_by_worker: bool) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    if expected_bytes is not None and stat.st_size != expected_bytes:
        raise ValueError(f"{label} byte count changed: {stat.st_size} != {expected_bytes}")
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "dev": int(stat.st_dev),
        "ino": int(stat.st_ino),
        "sha256": expected_sha,
        "sha256_computed_by_builder": False,
        "read_by_worker": read_by_worker,
        "content_scope": "parent_produced_known_record; worker scope is explicit",
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build(output: Path, *, launch_commit: str | None = None) -> dict[str, Any]:
    plan = _load(PLAN)
    contract = _load(CONTRACT)
    proof = _load(ROOT150_PROOF)
    if plan.get("schema") != "ds02.stage2.f3-s2.matched-three-grid-plan.v2":
        raise ValueError("F3 matched plan schema drift")
    if contract.get("schema") != "ds02.stage2.f3-s2.observer-calibration-contract.v1":
        raise ValueError("F3 calibration contract schema drift")
    if proof.get("report_sha256") != ROOT150_REPORT_SHA or proof.get("report_bytes") != ROOT150_REPORT_BYTES:
        raise ValueError("ROOT150 report proof binding drift")
    if proof.get("frame_count") != 836 or proof.get("root_array_content_read") is not False:
        raise ValueError("ROOT150 full836/no-array proof is not the expected source")

    worker_record = _small_record(WORKER, "QA worker")
    small_paths = [
        (PLAN, "matched three-grid plan"),
        (CONTRACT, "observer calibration contract"),
        (ROOT150_PROOF, "ROOT150 proof"),
        (ROOT133_PROOF, "ROOT133 proof"),
        (ROOT133_REQUEST, "ROOT133 request"),
        (ROOT133_RECEIPT, "ROOT133 receipt"),
        (MIDDLE_RECEIPT, "middle GenCase receipt"),
        (MIDDLE_XML, "middle generated XML"),
        (MIDDLE_SUPPORT, "middle support report"),
        (FINE_RECEIPT, "fine GenCase receipt"),
        (FINE_XML, "fine generated XML"),
        (FINE_SUPPORT, "fine support report"),
        (COARSE_SUPPORT_PROOF, "coarse support proof"),
        (SOURCE_XML, "current source XML"),
    ]
    records: dict[str, dict[str, Any]] = {"worker": worker_record}
    for path, label in small_paths:
        records[label] = _small_record(path, label)
    runparts_record = _known_record(ROOT133_RUNPARTS, expected_sha=ROOT133_RUNPARTS_SHA, expected_bytes=None, label="ROOT133 RunPARTs", read_by_worker=True)
    report_record = _known_record(ROOT150_REPORT, expected_sha=ROOT150_REPORT_SHA, expected_bytes=ROOT150_REPORT_BYTES, label="ROOT150 observer report", read_by_worker=False)
    root150_receipt_record = _known_record(ROOT150_RECEIPT, expected_sha=ROOT150_RECEIPT_SHA, expected_bytes=None, label="ROOT150 receipt", read_by_worker=False)
    generated_xml_record = _known_record(ROOT133_GENERATED_XML, expected_sha=ROOT133_XML_SHA, expected_bytes=None, label="ROOT133 generated XML", read_by_worker=False)

    input_paths = [worker_record["path"]] + [records[label]["path"] for _, label in small_paths] + [runparts_record["path"]]
    input_hashes = {record["path"]: record["sha256"] for record in [worker_record, *records.values(), runparts_record]}
    attempt_id = "f3-s2-matched-middle-control-cost-qa-v1-root-ready-001"
    output_rel = "{attempt_root}/report/f3_s2_matched_middle_control_cost_qa_v1.json"
    command = [
        str(PYTHON), str(WORKER),
        "--plan", str(PLAN),
        "--calibration-contract", str(CONTRACT),
        "--root150-proof", str(ROOT150_PROOF),
        "--root133-proof", str(ROOT133_PROOF),
        "--root133-request", str(ROOT133_REQUEST),
        "--root133-receipt", str(ROOT133_RECEIPT),
        "--runparts", str(ROOT133_RUNPARTS),
        "--output", output_rel,
    ]
    grid = plan["grid_ladder"]
    request: dict[str, Any] = {
        "schema": "ds02.request.v1",
        "variant_schema": "ds02.stage2.f3-s2.matched-middle-control-cost-qa-request.v1",
        "status": "READY_FOR_PARENT_V8_AUDIT_ONLY",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
        "case_id": "F3_S2_MATCHED_MIDDLE_CONTROL_COST_QA_V1",
        "attempt_id": attempt_id,
        "launch_commit": launch_commit or _git_head(),
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "command": command,
        "input_files": input_paths,
        "input_sha256": input_hashes,
        "estimated_input_read_bytes": sum(int(record["bytes"]) for record in [worker_record, *records.values(), runparts_record]),
        "estimated_storage_bytes": 16 * 1024 * 1024,
        "estimated_peak_memory_bytes": 256 * 1024 * 1024,
        "max_wall_seconds": 900,
        "cpu_threads": 1,
        "omp_threads": 1,
        "execution_allowed": False,
        "launch_disabled": True,
        "solver_started": False,
        "solver_launch": False,
        "gencase_launch": False,
        "gpu_started": False,
        "bi4_read": False,
        "hdf5_read": False,
        "vtk_payload_read": False,
        "forcing_payload_read": False,
        "output": {"atomic": True, "refuse_overwrite": True, "path": output_rel},
        "source_binding": {
            "schema": "ds02.stage2.f3-s2.matched-middle-control-cost-binding.v1",
            "plan": records["matched three-grid plan"],
            "calibration_contract": records["observer calibration contract"],
            "actual_coarse": {
                "root150_proof": records["ROOT150 proof"],
                "root150_report": report_record,
                "root150_receipt": root150_receipt_record,
                "root133_proof": records["ROOT133 proof"],
                "root133_request": records["ROOT133 request"],
                "root133_receipt": records["ROOT133 receipt"],
                "root133_runparts": runparts_record,
                "root133_generated_xml": generated_xml_record,
                "observer_fields_read_by_this_worker": False,
                "actual_full_window": [0.0, 8.350023358431661],
                "frame_count": 836,
                "native_fields_parent_proofed_but_deferred": ["Pos", "Vel", "Rhop", "Idp", "MassFluid"],
            },
            "initial_grid_records": {
                "coarse_dp0.015": {
                    "source_case": "ROOT133/ROOT150 actual",
                    "generated_xml_sha256": ROOT133_XML_SHA,
                    "actual_counts": {"fluid": 4320, "fixed": 19944, "total": 24264},
                    "sample_mass_kg": 14.580000378191471,
                    "continuous_owner_equivalence": "UNKNOWN",
                    "support_scope": "ROOT128 discrete owner envelope only",
                },
                "middle_dp0.006": {
                    "receipt": records["middle GenCase receipt"],
                    "generated_xml": records["middle generated XML"],
                    "support_report": records["middle support report"],
                    "generated_xml_sha256": grid["current_source_middle_dp0.006"]["source_gencase"]["generated_xml_sha256"],
                    "actual_counts": grid["current_source_middle_dp0.006"]["actual_counts"],
                    "sample_mass_kg": 14.58,
                    "continuous_owner_equivalence": "UNKNOWN",
                    "solver_release": "PENDING_PARENT_CURRENT_CONTROL_SUPPORT_REVIEW",
                },
                "fine_dp0.003": {
                    "receipt": records["fine GenCase receipt"],
                    "generated_xml": records["fine generated XML"],
                    "support_report": records["fine support report"],
                    "generated_xml_sha256": grid["actual_owner_fine_dp0.003"]["source_gencase"]["generated_xml_sha256"],
                    "actual_counts": grid["actual_owner_fine_dp0.003"]["actual_counts"],
                    "sample_mass_kg": 14.58,
                    "continuous_owner_equivalence": "UNKNOWN",
                    "solver_release": "DEFER_UNTIL_MIDDLE_TERMINAL_COST_AND_OBSERVABLE_REVIEW",
                },
            },
            "current_control": {
                "path": str(plan["source_binding"]["current_forcing"]["path"]),
                "bytes": plan["source_binding"]["current_forcing"]["bytes"],
                "sha256": SOURCE_CONTROL_SHA,
                "read_by_builder": False,
                "read_by_worker": False,
                "full_hash_by_worker": False,
                "hash_authority": "existing source plan and actual ROOT133 request/receipt provenance",
                "historical_control_excluded": "6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3",
            },
            "source_xml": {"path": str(SOURCE_XML), "bytes": 9358, "sha256": SOURCE_XML_SHA, "read_by_worker": False},
        },
        "common_time_and_observables": {
            "registered_query_times_s": QUERY_TIMES_S,
            "time_source": "actual ROOT133 RunPARTs.csv; worker computes brackets, does not map frame index to time",
            "field_observables": ["mass_by_mk", "weighted_centroid_m", "weighted_velocity_m_per_s", "kinetic_energy_j", "region_assignment", "finite_Pos_Vel_Rhop"],
            "comparison_rule": "Use same physical query times and actual saved-time brackets; no particle/field interpolation in this request",
            "output_calibration": "timestamp/bracket closure only; field/output error remains UNKNOWN until a separate guarded native observer reads actual fields",
            "endpoint": "Do not extrapolate source endpoint; actual coarse terminal is 8.350023358431661 and source query endpoint is 8.350016881886734",
            "spatial_truth": "Adjacent-grid differences are diagnostics, never a truth/error bound",
        },
        "middle_staged_feasibility": {
            "candidate": "dp0.006 current-control middle",
            "same_cfl": {"cfl": 0.05, "output_cadence_s": 0.005, "status": "PARENT_REVIEW_AFTER_METADATA_QA; NO_SOLVER_REQUEST_EMITTED"},
            "half_cfl": {"cfl": 0.025, "output_cadence_s": 0.005, "status": "DEFERRED_SEPARATE_SOURCE_BOUND_OVERLAY"},
            "window_s": SOURCE_WINDOW_S,
            "required_terminal_evidence": ["RunPARTs.csv", "Run.out", "DtAllInfo.csv", "official DTsMin/clamp evidence", "actual field observer at registered query times", "receipt/storage/cpu/gpu closure"],
            "fine_gate": "Do not launch dp0.003 until the middle terminal receipt and common-time field/output audit are reviewed",
            "native_storage_proxy": {"middle_receipt_charge_bytes": 6604181245, "middle_gib": 6.1506230803, "fine_receipt_charge_bytes": 35971428340, "fine_gib": 33.5010032543, "semantics": "historical ROOT706 same-forcing particle-count proxy; not an actual new-run bound"},
            "native_input_or_forcing_read": False,
        },
        "frozen_calibration": {
            "position_L_m": 0.894,
            "velocity_scale_m_s": 0.9077664897978995,
            "kinetic_energy_scale_j": 6.0072516,
            "position_tolerance_fraction_L": 0.02,
            "velocity_and_ke_tolerance_fraction_scale": 0.05,
            "event_time_T": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
            "time_and_output_each_max_fraction_task": 0.25,
            "no_neighbor_grid_truth": True,
            "no_interpolation": True,
        },
        "resource_guard": {
            "parent_cpu_binding": "required if parent chooses to run this metadata audit",
            "parent_storage_binding": "required",
            "gpu": "none",
            "solver_launch": False,
            "gencase_launch": False,
            "native_payload_read": False,
            "forcing_payload_read": False,
            "hdf5_read": False,
            "launch_disabled": True,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    request = build(args.output, launch_commit=args.launch_commit)
    if args.self_test:
        assert request["launch_disabled"] is True
        assert request["execution_allowed"] is False
        assert request["solver_launch"] is False and request["gencase_launch"] is False
        assert request["source_binding"]["current_control"]["read_by_worker"] is False
        assert all("CaseSloshingAccData.csv" not in path for path in request["input_files"])
        print(json.dumps({"status": "PASS", "schema": request["variant_schema"], "input_files": len(request["input_files"]), "forcing_read": False, "native_payload_read": False}, indent=2))
        return 0
    if not args.build:
        parser.error("--build or --self-test is required")
    _write_once(args.output, request)
    print(json.dumps({"status": request["status"], "request": str(args.output.resolve()), "launch_disabled": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
