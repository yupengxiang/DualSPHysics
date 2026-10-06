#!/usr/bin/env python3
"""Read-only static/runtime-contract audit for the committed fresh110 source."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


HERE = Path(__file__).resolve().parents[1]
FRESH110 = HERE.parent / "root_followup_110_f3_f6_nvme_renderer_successor_v1"
ROOT920 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F6_actual722_full241_independent_Renderer023_CPU24_16GiB_Home_admission_920"
)
LEDGER_LOCK = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.lock")
LEDGER = LEDGER_LOCK.parent / "resource-ledger.json"
FORBIDDEN = {".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz", ".raw", ".bin"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return value


def sha256_source(path: Path) -> str:
    if path.suffix.lower() in FORBIDDEN:
        raise AssertionError(f"refusing scientific payload hash: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def line_of(text: str, needle: str) -> int | None:
    for number, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return number
    return None


def package_audit() -> dict[str, Any]:
    manifest = load_json(FRESH110 / "manifest.json")
    assert manifest.get("schema") == "ds02.f3.fresh110.package-manifest.v1"
    assert manifest.get("package_id") == "F3_fresh110_F6_root722_nvme_render_successor"
    checked_files = 0
    for entry in manifest.get("files", []):
        rel = entry["path"]
        path = FRESH110 / rel
        assert path.is_file(), f"manifest file missing: {path}"
        assert path.stat().st_size == int(entry["bytes"]), f"manifest size mismatch: {path}"
        assert sha256_source(path) == entry["sha256"], f"manifest digest mismatch: {path}"
        checked_files += 1
    for path in FRESH110.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.name != "manifest.json":
            assert path.suffix.lower() not in FORBIDDEN, f"scientific suffix in source package: {path}"

    request_files = sorted((FRESH110 / "requests").glob("*.json"))
    assert len(request_files) == 24, f"expected 24 disabled requests, got {len(request_files)}"
    disabled = 0
    for path in request_files:
        request = load_json(path)
        assert request.get("disabled") is True
        assert request.get("launch") is False
        assert request.get("launch_allowed") is False
        assert request.get("execution_allowed") is False
        assert request.get("source_only") is True
        assert request.get("future_input_hashes_null") is True
        assert request.get("family_id") == "F6"
        assert request.get("expected_frames") == 241
        assert request.get("expected_particles") == 417505
        assert request.get("reservation_id") is None
        assert request.get("current_attempt_id") is None
        disabled += 1

    worker = FRESH110 / "workers/nvme_render_successor.py"
    source = worker.read_text(encoding="utf-8")
    required = {
        "live_ledger_lock": "fcntl.LOCK_EX",
        "live_ledger_reader": "_live_resource_snapshot",
        "own_reservation_match": "current_attempt_id",
        "renderer_new_session": "start_new_session=True",
        "owned_group_term": "os.killpg(pgid, signal.SIGTERM)",
        "owned_group_kill": "os.killpg(pgid, signal.SIGKILL)",
        "report_rewrite": "_rewrite_report(stage_render, home_output)",
        "pvsm_rewrite": "_rewrite_pvsm(stage_render, home_output)",
        "report_path_check": "_report_paths_rebound(stage_render, final_output)",
        "receipt_cap_check": "Home publish cap exceeded after receipt creation",
        "stage_cap_check": "NVMe stage cap exceeded before Home publication",
        "home_floor_check": "Home free-floor check failed after final report/receipt serialization",
        "atomic_publish": "os.replace(temp, final_output)",
        "stage_cleanup": "_remove_stage(stage_root)",
    }
    source_evidence = {name: line_of(source, needle) for name, needle in required.items()}
    assert all(value is not None for value in source_evidence.values()), source_evidence

    restore_line = line_of(source, "signal.signal(signum, handler)")
    publish_line = line_of(source, "result = _publish_files(stage_render, home_output, request, report)")
    copy_except_line = line_of(source, "except Exception:")
    replace_line = line_of(source, "os.replace(temp, final_output)")
    findings = [
        {
            "id": "F111-SIG-PUBLISH",
            "severity": "advisory-repair-required-for-unattended-execute",
            "status": "open",
            "evidence": {
                "handler_restore_line": restore_line,
                "publish_call_line": publish_line,
                "copy_cleanup_except_line": copy_except_line,
                "copy_cleanup_catches": "Exception, not BaseException",
            },
            "impact": "SIGTERM/SIGINT after renderer exit but during report rewrite or temporary Home copy is outside the installed handlers; a temporary publish directory can remain.",
            "repair": "Keep own-process handlers through publication or make the publication transaction catch BaseException and remove its own temporary directory before re-raising.",
        },
        {
            "id": "F111-PATH-SCOPE",
            "severity": "advisory-repair-required-for-unattended-execute",
            "status": "open",
            "evidence": {
                "pvsm_rebind_line": line_of(source, "text = text.replace(str(stage_render), str(final_output))"),
                "json_prefix_absence_line": line_of(source, "if str(stage_render) in encoded:"),
                "report_output_check_line": line_of(source, "value.startswith(str(final_output))"),
            },
            "impact": "The source checks the exact stage_render string and three named output fields; it does not reject a different private stage-root/NVMe path and uses raw prefix matching for final output paths.",
            "repair": "Recursively inspect all serialized PVSM/JSON path values, reject every private stage/NVMe root, and use resolved path-component containment rather than startswith.",
        },
        {
            "id": "F111-FLOOR-AFTER-RENAME",
            "severity": "advisory",
            "status": "open",
            "evidence": {
                "pre_publish_floor_line": line_of(source, "Home free-floor check failed after final report/receipt serialization"),
                "atomic_rename_line": replace_line,
            },
            "impact": "The final Home-floor check occurs before copying and os.replace; an external Home writer can change free space during the copy.",
            "repair": "Recheck and record Home free space after the atomic rename while the ledger lock is held, with an explicit own-output rollback policy if the floor is lost.",
        },
    ]
    return {
        "fresh110_manifest_package_id": manifest["package_id"],
        "fresh110_manifest_files_checked": checked_files,
        "disabled_request_count": disabled,
        "scientific_payloads_opened_or_hashed": False,
        "source_contract_checks": source_evidence,
        "findings": findings,
    }


def observe_root920() -> dict[str, Any]:
    launch = load_json(ROOT920 / "controller-launch-process.json")
    pid = int(launch["pid"])
    stat_path = Path(f"/proc/{pid}/stat")
    process = {"pid": pid, "present": stat_path.exists()}
    if stat_path.exists():
        raw = stat_path.read_text(encoding="utf-8")
        process["state"] = raw[raw.rfind(")") + 2 : raw.rfind(")") + 3]
        children_path = Path(f"/proc/{pid}/task/{pid}/children")
        process["children"] = children_path.read_text(encoding="utf-8").split() if children_path.exists() else []
    result_path = ROOT920 / "controller-result.json"
    stdout_path = ROOT920 / "controller.stdout.log"
    stdout_tail = stdout_path.read_text(encoding="utf-8", errors="replace")[-4096:] if stdout_path.exists() else ""
    with LEDGER_LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        ledger = load_json(LEDGER)
        limits = ledger.get("limits", {})
        reservations = ledger.get("reservations", [])
    return {
        "controller_path": str(ROOT920 / "batch-controller.py"),
        "controller_sha256_from_launch_record": launch.get("controller_sha256"),
        "pid": pid,
        "recorded_start_ticks": launch.get("proc_start_ticks"),
        "process": process,
        "controller_result_exists": result_path.exists(),
        "render_receipts_in_controller_dir": len(list(ROOT920.glob("**/execution-receipt.json"))),
        "controller_stdout_tail": stdout_tail,
        "ledger_path": str(LEDGER),
        "ledger_reservation_count": len(reservations) if isinstance(reservations, list) else None,
        "ledger_limits": {
            "home_path": limits.get("home_path"),
            "home_min_free_bytes": limits.get("home_min_free_bytes"),
            "storage_policy": limits.get("storage_policy"),
        },
        "reservation_match": "not_provable_at_capture_zero_active_rows",
        "shared_state_mutated_by_audit": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe-root920", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    report: dict[str, Any] = {
        "schema": "ds02.stage1.f3.fresh111.fresh110-runtime-publication-audit.v1",
        "source_package": str(FRESH110),
        "source_commit": "878f1526d6bdefebbe2ff1c8621ba1ec01ab4232",
        "science_payloads_opened_or_hashed": False,
        "package_audit": package_audit(),
    }
    if args.observe_root920:
        report["root920_observation"] = observe_root920()
    report["status"] = "source_pass_runtime_wait" if args.observe_root920 else "source_pass"
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.write_report:
        (HERE / "metadata/fresh111-audit-report.json").write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

