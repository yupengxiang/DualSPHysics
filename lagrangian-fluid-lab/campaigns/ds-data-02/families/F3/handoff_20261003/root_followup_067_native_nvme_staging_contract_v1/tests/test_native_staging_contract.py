#!/usr/bin/env python3
"""Static checks for the fresh067 staging design record.

The only external source read here is the reviewed runtime Python text.  The
probe is deliberately not imported, so this test cannot enter the runner.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parents[1]
CONTRACT = HERE / "native-staging-contract.json"
PROBE = HERE / "diagnose_native_stage_support.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    contract = json.loads(CONTRACT.read_text())
    assert contract["fresh_id"] == "fresh067"
    assert contract["family_id"] == "F3"
    assert contract["status"] == "design_only_blocked_until_shared_runtime_support"
    assert contract["source_only"] is True
    assert contract["jobs_started"] is False
    assert contract["shared_state_modified"] is False

    capacity = contract["capacity_snapshot"]
    assert capacity["home_min_free_bytes"] == 536_870_912_000
    assert capacity["nvme_min_free_bytes"] == 107_374_182_400
    assert capacity["single_stage_limit_bytes"] == 25_769_803_776
    assert capacity["requested_max_native_solver_concurrency"] == 8
    assert capacity["current_runtime_initial_solver_concurrency_cap"] == 4
    assert capacity["current_runtime_conversion_concurrency_cap"] == 2
    assert capacity["observation_is_read_only"] is True

    runtime = Path(contract["runtime_reference"]["path"])
    assert runtime.is_file(), runtime
    assert sha256(runtime) == contract["runtime_reference"]["sha256"]

    future = contract["future_hash_policy"]
    assert future["stage_manifest_sha256"] is None
    assert future["native_archive_receipt_sha256"] is None
    assert future["archive_output_sha256"] is None
    assert future["source_package_does_not_fabricate_runtime_evidence"] is True

    completed = subprocess.run(
        [sys.executable, "-B", str(PROBE), "--json"],
        cwd=HERE,
        check=True,
        capture_output=True,
        text=True,
    )
    diagnostic = json.loads(completed.stdout)
    assert diagnostic["status"] == "blocked"
    assert diagnostic["source_only"] is True
    assert diagnostic["jobs_started"] is False
    assert diagnostic["arrays_read"] is False
    assert diagnostic["shared_state_modified"] is False
    assert diagnostic["runtime_sha256"] == contract["runtime_reference"]["sha256"]
    missing = set(diagnostic["missing_required_support"])
    assert "native_archive_kind_missing" in missing
    assert "native_stage_root_missing" in missing
    assert "archive_hook_missing" in missing
    assert "separate_native_returncode_missing" in missing

    payload_suffixes = {".bi4", ".csv", ".h5", ".hdf5", ".npy", ".npz"}
    payloads = [path for path in HERE.rglob("*") if path.is_file() and path.suffix.lower() in payload_suffixes]
    assert not payloads, payloads
    print("fresh067 static contract: PASS (read-only blocked staging diagnostic; no payloads)")


if __name__ == "__main__":
    main()
