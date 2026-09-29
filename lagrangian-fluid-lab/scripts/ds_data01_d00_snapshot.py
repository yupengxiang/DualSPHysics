#!/usr/bin/env python3
"""Create the read-only D00 state snapshot for the dataset-only activity.

This script observes the worktree, legacy receipts, processes, and visible GPUs.
It never starts or stops a solver, worker, learner, or coordinator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = LAB_ROOT.parent
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-01"
BASELINE = "49df6847404b9c2d3d20c465e8f9cf2e00cde712"
OFFICIAL_ROOT = LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4"


def run(argv: list[str], cwd: Path = REPO_ROOT) -> tuple[int, str]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return result.returncode, result.stdout.strip()


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_snapshot() -> dict[str, Any]:
    def value(*args: str) -> str | None:
        code, output = run(["git", *args])
        return output if code == 0 else None

    status_code, status = run(["git", "status", "--short", "--branch"])
    remote_code, remotes = run(["git", "remote", "-v"])
    refs_code, refs = run(
        [
            "git",
            "for-each-ref",
            "--format=%(refname:short) %(objectname)",
            "refs/remotes/origin",
        ]
    )
    ignored_code, ignored = run(["git", "status", "--ignored", "--short"])
    ignored_lines = ignored.splitlines() if ignored_code == 0 and ignored else []
    return {
        "repo_root": str(REPO_ROOT),
        "branch": value("branch", "--show-current"),
        "head": value("rev-parse", "HEAD"),
        "baseline_commit": BASELINE,
        "baseline_present": value("cat-file", "-e", f"{BASELINE}^{{commit}}") is not None,
        "status_short": status if status_code == 0 else None,
        "remote_urls": remotes if remote_code == 0 else None,
        "origin_refs": refs if refs_code == 0 else None,
        "ignored_entry_count": len(ignored_lines),
        "untracked_entries": sum(line.startswith("??") for line in ignored_lines),
        "ignored_entries": sum(line.startswith("!!") for line in ignored_lines),
    }


def process_snapshot() -> list[dict[str, Any]]:
    code, output = run(
        [
            "ps",
            "-eo",
            "pid=,user=,etimes=,stat=,pcpu=,pmem=,args=",
        ]
    )
    if code != 0:
        return [{"error": output}]
    current_user = os.environ.get("USER", "jade")
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        fields = line.strip().split(None, 6)
        if len(fields) < 7:
            continue
        pid, user, elapsed, stat, cpu, mem, command = fields
        if not any(
            token in command
            for token in (
                "core_runtime.py",
                "core_archive.py",
                "DualSPHysics",
                "GenCase",
                "training",
                "train.py",
                "torchrun",
                "python -",
            )
        ):
            continue
        if user != current_user:
            classification = "protected_unrelated_user_process"
        elif "core_runtime.py" in command or "core_archive.py" in command:
            classification = "preexisting_dataset_activity"
        elif "training" in command or "train.py" in command or "torchrun" in command:
            classification = "legacy_learning_process_observe_only"
        elif "python -" in command:
            classification = "unresolved_user_process_observe_only"
        else:
            classification = "unclassified_user_process_observe_only"
        rows.append(
            {
                "pid": int(pid),
                "user": user,
                "elapsed_seconds": int(elapsed),
                "state": stat,
                "cpu_percent": float(cpu),
                "memory_percent": float(mem),
                "command": command,
                "classification": classification,
                "action": "observe_only",
            }
        )
    return rows


def gpu_snapshot() -> dict[str, Any]:
    code, output = run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader",
        ]
    )
    gpus: list[dict[str, str]] = []
    if code == 0:
        for line in output.splitlines():
            values = [part.strip() for part in line.split(",")]
            if len(values) == 5:
                gpus.append(
                    {
                        "index": values[0],
                        "name": values[1],
                        "memory_used": values[2],
                        "memory_total": values[3],
                        "utilization": values[4],
                    }
                )
    apps_code, apps = run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
            "--format=csv,noheader",
        ]
    )
    return {
        "query_status": "ok" if code == 0 else "unavailable",
        "gpus": gpus,
        "compute_apps": apps.splitlines() if apps_code == 0 and apps else [],
        "policy": "do not touch unrelated processes; prefer idle GPUs only after a fresh preflight",
    }


def count_files(root: Path, suffix: str | None = None) -> int:
    if not root.exists():
        return 0
    pattern = f"*{suffix}" if suffix else "*"
    return sum(1 for path in root.rglob(pattern) if path.is_file())


def package_snapshot() -> dict[str, Any]:
    version_file = OFFICIAL_ROOT / "bin" / "linux" / "VERSION_INFO.txt"
    version_text = (
        version_file.read_text(encoding="utf-8", errors="replace").strip()
        if version_file.exists()
        else None
    )
    examples = OFFICIAL_ROOT / "examples"
    return {
        "root": str(OFFICIAL_ROOT),
        "present": OFFICIAL_ROOT.is_dir(),
        "version_info": version_text,
        "file_count": count_files(OFFICIAL_ROOT),
        "example_directory_count": sum(1 for path in examples.glob("*") if path.is_dir())
        if examples.is_dir()
        else 0,
        "example_case_directory_count": sum(1 for path in examples.glob("*/*") if path.is_dir())
        if examples.is_dir()
        else 0,
        "example_pdf_count": count_files(examples, ".pdf"),
        "download_sha256": sha256(LAB_ROOT / "vendor" / "downloads" / "DualSPHysics_v5.4.3.zip"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=CAMPAIGN_ROOT / "DATASET_STATUS.json")
    parser.add_argument("--next-ready-task", default="D01")
    args = parser.parse_args()
    status = {
        "schema": "ds-data-01.status.v1",
        "scope": "DS-DATA-01",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "learning_allowed": False,
        "scope_reset": {
            "status": "recorded",
            "legacy_learning": "superseded_by_owner_scope",
            "historical_assets": "read_only_and_retained",
            "unrelated_processes": "protected",
        },
        "git": git_snapshot(),
        "official_package": package_snapshot(),
        "assets": {
            "official_derived_file_count": count_files(LAB_ROOT / "data-official"),
            "official_case_file_count": count_files(LAB_ROOT / "cases" / "official"),
            "f3_archive_present": (REPO_ROOT / "f3-ref0081818-material-archive").is_dir(),
            "legacy_learning_directory_present": (LAB_ROOT / "campaigns" / "core-v1" / "learning").is_dir(),
        },
        "processes": process_snapshot(),
        "gpu": gpu_snapshot(),
        "legacy_queue_observation": {
            "command": ".venv/bin/python scripts/core_runtime.py status --compact",
            "interpretation": "preexisting queue only; not a DS-DATA-01 ledger",
        },
        "next_ready_task": args.next_ready_task,
        "completion_claim": False,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
