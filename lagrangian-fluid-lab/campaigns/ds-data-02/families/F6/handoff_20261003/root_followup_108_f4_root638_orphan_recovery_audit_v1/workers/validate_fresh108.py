#!/usr/bin/env python3
"""Fail-closed source/metadata validator for F6 fresh108.

Only package files and synthetic temporary metadata fixtures are touched.  No
DATA payload, shared ledger, renderer output, or job is opened by this
validator.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


PACKAGE = Path(__file__).resolve().parents[1]
META = PACKAGE / "metadata"
REQUESTS = PACKAGE / "requests"
WORKER = PACKAGE / "workers" / "audit_root638_orphan_render.py"
CASES = (
    "F4_DROP_gap0p24000_xoffm0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p24000_xoffm0p08000_yoffm0p04000_uz0p60000",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"JSON object required: {path}"
    return value


def check_package_manifest() -> None:
    manifest = load(PACKAGE / "manifest.json")
    assert manifest["schema"] == "ds02.f6.fresh108.source-package-manifest.v1"
    assert manifest["model"] == "gpt-5.6-luna-max"
    assert manifest["source_only"] is True
    assert manifest["scientific_payload_read_or_hashed"] is False
    assert manifest["job_started_or_signalled"] is False
    assert manifest["shared_state_mutated"] is False
    assert manifest["future_output_hashes"] is None
    listed = {row["path"]: row for row in manifest["files"]}
    actual = {
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    assert set(listed) == actual, (set(listed) ^ actual)
    for relative, row in listed.items():
        path = PACKAGE / relative
        assert row["size_bytes"] == path.stat().st_size, relative
        assert row["sha256"] == sha256(path), relative


def check_evidence_and_plan() -> None:
    evidence = load(META / "root638-orphan-recovery-evidence.json")
    plan = load(META / "root638-recovery-plan.json")
    assert evidence["schema"] == "ds02.f4.root638.orphan-recovery-evidence.v2"
    assert evidence["source_only"] is True
    assert evidence["payload_bytes_read_or_hashed"] is False
    assert evidence["root638_request_count"] == 24
    assert evidence["root638_receipt_status_counts"] == {
        "completed_returncode_0": 22,
        "running_unknown_receipts": 2,
    }
    assert set(evidence["root638_pending_cases"]) == set(CASES)
    assert len(evidence["root638_completed_cases"]) == 22
    assert evidence["current_process_scan"]["batch_controller_processes"] == []
    assert evidence["current_process_scan"]["launch_py_processes"] == []
    assert evidence["reconciliation_eligibility_now"]["source_agent_did_not_apply_settlement"] is True
    for case in CASES:
        row = evidence["last_two_cases"][case]
        assert row["old_receipt_observed"]["status"] == "running"
        assert row["old_receipt_observed"]["returncode"] is None
        output = row["renderer_output_metadata"]
        assert output["frame_file_count"] == 1201
        assert output["contact_sheet_file_count"] == 51
        assert output["png_bytes_read"] is False
        report = row["renderer_report_metadata"]
        assert report["exists"] is True
        assert report["frames"] == 1201
        assert report["source_frames"] == 1201
        assert report["all_frames_rendered"] is True
        assert report["actual_times_preserved_exactly"] is True
        assert report["native_identity_axis_preserved"] is True
        assert report["visual_review"].startswith("pending")
        assert report["numerical_precision_status"] == "not accepted"
    assert plan["schema"] == "ds02.f4.root638.orphan-recovery-plan.v1"
    assert plan["status"] == "disabled_source_contract"
    assert plan["lock_reconciliation"]["per_case_reserved_cpu_core_seconds"] == 345600
    assert plan["lock_reconciliation"]["aggregate_reserved_cpu_core_seconds"] == 691200
    assert plan["lock_reconciliation"]["child_returncode"] is None
    assert plan["lock_reconciliation"]["os_exit_zero"] is False
    assert plan["successor_gate"]["normal_root638_completed0_case_count"] == 22
    assert plan["successor_gate"]["recovery_audit_case_count"] == 2
    assert plan["successor_gate"]["case_increment"] == 0


def check_worker_source() -> None:
    source = WORKER.read_text(encoding="utf-8")
    for forbidden in ("numpy", "h5py", "vtk", "PIL", "import subprocess", "os.kill", "Popen", "import signal"):
        assert forbidden not in source, forbidden
    assert "read_bytes" not in source
    assert "png_bytes_read" in source
    assert "EXPECTED_FRAMES = 1201" in source
    assert "EXPECTED_CONTACT_SHEETS = 51" in source
    result = subprocess.run(
        [sys.executable, str(WORKER), "--self-test"],
        cwd=PACKAGE,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "fresh108 synthetic metadata checks: PASS" in result.stdout


def check_requests() -> None:
    request_paths = sorted(REQUESTS.glob("*.json"))
    assert len(request_paths) == 2
    for path in request_paths:
        request = load(path)
        assert request["schema"] == "ds02.runner-request.v2"
        assert request["family_id"] == "F4"
        assert request["case_id"] in CASES
        assert request["kind"] == "cpu"
        assert request["cpu_task_kind"] == "audit"
        assert request["launch_owner"] == "root"
        assert request["disabled"] is True
        assert request["execution_allowed"] is False
        assert request["launch_allowed"] is False
        assert request["source_only"] is True
        assert request["cpu_threads"] == 2
        assert request["max_wall_seconds"] == 1800
        assert request["estimated_storage_bytes"] == 268435456
        assert request["future_input_sha256"] is None
        assert all(value is None for value in request["future_outputs"].values())
        assert len(request["input_files"]) == 2
        for input_path in request["input_files"]:
            assert Path(input_path).is_file(), input_path
            assert request["input_sha256"][input_path] == sha256(Path(input_path))
        assert len(request["required_input_files_after_reconciliation"]) == 4
        assert request["acceptance"]["visual_review"] == "pending root inspection"
        assert request["acceptance"]["q_n"] == "not_assessed"
        assert request["acceptance"]["numerical_precision"] == "not accepted"
        assert request["acceptance"]["independent_case_increment"] == 0
        assert request["root_dataset_inventory_profile"] == "root_home_floor_no_legacy_dataset_walk_v1"
        command = request["command"]
        assert all(isinstance(arg, str) for arg in command)
        assert "{attempt_root}" in command
        assert not any(arg.startswith("-cpu") for arg in command)


def main() -> int:
    check_package_manifest()
    check_evidence_and_plan()
    check_worker_source()
    check_requests()
    print("fresh108 validator: PASS (metadata-only, synthetic tests only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
