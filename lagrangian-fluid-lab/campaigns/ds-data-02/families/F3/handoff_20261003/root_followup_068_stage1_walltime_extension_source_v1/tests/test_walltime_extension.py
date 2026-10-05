#!/usr/bin/env python3
"""Static metadata checks for fresh068 wall-time derivatives."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parents[1]
BUILDER = HERE / "build_walltime_extension.py"
SOURCE_DIR = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    """lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"""
    """root_stage1_f3_first24_eight_solver_resource_policy_134/requests"""
)
CASES = ("0590", "0610", "0670", "0710")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text())


def main() -> None:
    check = subprocess.run(
        [sys.executable, "-B", str(BUILDER), "--check"],
        cwd=HERE,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "fresh068 checked: 4 disabled wall-time derivatives" in check.stdout

    lineage = read(HERE / "source-lineage.json")
    assert lineage["fresh_id"] == "fresh068"
    assert lineage["family_id"] == "F3"
    assert lineage["derived_requests_disabled"] is True
    assert lineage["independent_case_count_increment"] == 0
    assert lineage["physical_conditions_changed"] is False
    assert lineage["actual_native_receipts_created"] is False

    policy = read(HERE / "policy-lineage.json")
    guards = policy["inherited_guards"]
    assert guards["solver_concurrency_maximum"] == 8
    assert guards["conversion_concurrency_maximum"] == 2
    assert guards["shared_cpu_thread_cap"] == 64
    assert guards["home_min_free_gib"] == 500
    assert guards["parent_gpu_hours"] == 512
    assert guards["parent_cpu_core_hours"] == 3840
    assert guards["qualification_attempts"] == 1024
    assert guards["production_attempts"] == 720
    assert guards["deadline_utc"] == "2026-10-14T07:23:48+00:00"
    assert policy["lease_policy"]["active_leases_protected"] is True
    assert policy["source_policy"]["effective_function_sha256"] == "46e62ea197862a833797556d09350126b3632b2e3b1d496d08816ee42f7abecf"

    by_case = {row["case_id"]: row for row in lineage["cases"]}
    assert len(by_case) == 4
    for ay in CASES:
        name = f"F3_STAGE1_DP006_P1000_AY{ay}.json"
        source_path = SOURCE_DIR / name
        derived_path = HERE / "requests" / name
        source = read(source_path)
        derived = read(derived_path)
        assert digest(source_path) == by_case[source["case_id"]]["source_request_sha256"]
        assert digest(source_path) == derived["fresh068_lineage"]["source_request_sha256"]
        assert derived["fresh068_lineage"]["source_request_path"] == str(source_path)
        assert derived["fresh068_lineage"]["source_attempt_id"] == source["attempt_id"]
        assert derived["fresh068_lineage"]["source_max_wall_seconds"] == 7200
        assert derived["fresh068_lineage"]["derived_max_wall_seconds"] == 14400
        assert derived["fresh068_lineage"]["walltime_extension_only"] is True
        assert derived["fresh068_lineage"]["active_root134_requests_untouched"] is True
        assert derived["fresh068_lineage"]["future_execution_receipt_sha256"] is None
        assert derived["fresh068_lineage"]["future_native_receipt_sha256"] is None
        assert derived["fresh068_lineage"]["future_visual_decision_sha256"] is None

        assert derived["attempt_id"] == source["attempt_id"] + "-wall14400"
        assert derived["max_wall_seconds"] == 14400
        assert derived["launch_allowed"] is False
        assert derived["execution_allowed"] is False
        assert derived["production_approval"] == "none"
        assert derived["independent_case_count_increment"] == 0
        assert derived["command"] == source["command"] == derived["actual_solver_command"]
        assert derived["cwd"] == source["cwd"] == derived["actual_solver_cwd"]
        assert derived["command"][-2:] == ["-tmax:8.35", "-tout:0.01"]
        assert "-mdbc_noslip:1" in derived["command"]
        assert derived["expected_saved_frames"] == source["expected_saved_frames"] == 836
        assert derived["save_interval_s"] == source["save_interval_s"] == 0.01
        assert derived["nominal_pitch_multiplier"] == source["nominal_pitch_multiplier"] == 1.0
        assert derived["physical_condition_sha256"] == source["physical_condition_sha256"]
        assert derived["input_files"] == source["input_files"]
        assert derived["input_hashes"] == source["input_hashes"]
        assert derived["input_sha256"] == source["input_sha256"]
        assert derived["root_solver_concurrency_cap"] == source["root_solver_concurrency_cap"] == 8
        assert derived["root_gpu_selection_profile"] == source["root_gpu_selection_profile"] == "root_live_all_idle_uuid_leased_eight_solver_v2"
        assert derived["root_effective_reservation_function_sha256"] == source["root_effective_reservation_function_sha256"]
        assert derived["estimated_storage_bytes"] == source["estimated_storage_bytes"]
        assert derived["cpu_threads"] == source["cpu_threads"]
        assert derived["estimated_peak_gpu_mib"] == source["estimated_peak_gpu_mib"]

    payload_suffixes = {".bi4", ".csv", ".h5", ".hdf5", ".npy", ".npz"}
    payloads = [p for p in HERE.rglob("*") if p.is_file() and p.suffix.lower() in payload_suffixes]
    assert not payloads, payloads
    print("fresh068 static contract: PASS (4 disabled wall-time-only requests; no payloads)")


if __name__ == "__main__":
    main()
