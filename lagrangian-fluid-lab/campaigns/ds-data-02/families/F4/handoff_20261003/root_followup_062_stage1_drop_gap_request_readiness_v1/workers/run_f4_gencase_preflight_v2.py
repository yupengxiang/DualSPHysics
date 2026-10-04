#!/usr/bin/env python3
"""Root-strict GenCase preflight for the two F4 gap endpoint Definitions.

This is the request-only successor of the 060 worker.  It keeps the same
source and command contract, but creates the substituted output root before
the first endpoint.  The 060 command would fail under a fresh strict attempt
because the runner creates ``{attempt_root}``, while the worker tried to make
``{attempt_root}/gencase/<endpoint>`` with ``parents=False``.  No launch is
performed by this source handoff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


SCHEMA = "ds02.f4.drop-gap-gencase-preflight-result.v2"
DEFAULT_GENCASE = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
DEFAULT_GENCASE_SHA256 = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_records(plan_path: Path, plan: dict[str, Any]) -> list[dict[str, Any]]:
    receipt_path = plan_path.parent / "source-build-receipt.json"
    receipt = load_json(receipt_path)
    by_id = {row["endpoint_id"]: row for row in receipt.get("endpoints", [])}
    records: list[dict[str, Any]] = []
    for endpoint in plan["endpoints"]:
        endpoint_id = str(endpoint["endpoint_id"])
        source = plan_path.parent / str(endpoint["source_definition_output"])
        if not source.is_file():
            raise FileNotFoundError(source)
        record = by_id.get(endpoint_id)
        if not record:
            raise RuntimeError(f"missing source builder receipt row: {endpoint_id}")
        observed = sha256(source)
        if observed != record["source_definition_sha256"]:
            raise RuntimeError(f"source Definition hash mismatch: {endpoint_id}")
        records.append(
            {
                "endpoint_id": endpoint_id,
                "source_definition": str(source),
                "source_definition_sha256": observed,
                "drop_point_z_literal": endpoint["drop_point_z_literal"],
                "physical_condition_sha256": endpoint["physical_condition_sha256"],
            }
        )
    return records


def run(
    plan_path: Path,
    gencase_exe: Path,
    output_root: Path,
    report_path: Path,
    execute: bool,
    expected_gencase_sha256: str | None,
    threads: int,
) -> int:
    if threads < 1:
        raise ValueError("threads must be positive")
    plan = load_json(plan_path)
    if plan.get("stage_contract", {}).get("launch_allowed") is not False:
        raise RuntimeError("endpoint plan must keep launch_allowed=false")
    sources = source_records(plan_path, plan)
    if not gencase_exe.is_file():
        raise FileNotFoundError(gencase_exe)
    observed_exe_sha = sha256(gencase_exe)
    if expected_gencase_sha256 and observed_exe_sha != expected_gencase_sha256:
        raise RuntimeError(f"GenCase hash mismatch: {observed_exe_sha} != {expected_gencase_sha256}")

    commands: list[dict[str, Any]] = []
    failures = 0
    if execute:
        # The strict runner creates only {attempt_root}; make the worker's
        # nested output root explicit and fail if this attempt is reused.
        output_root.mkdir(parents=True, exist_ok=False)
    for source in sources:
        endpoint_id = source["endpoint_id"]
        endpoint_root = output_root / endpoint_id
        prefix = endpoint_root / endpoint_id
        command = [
            str(gencase_exe),
            str(Path(source["source_definition"]).with_suffix("")),
            str(prefix),
            "-save:all",
            f"-threads:{threads}",
        ]
        record: dict[str, Any] = {
            "endpoint_id": endpoint_id,
            "source_definition": source["source_definition"],
            "source_definition_sha256": source["source_definition_sha256"],
            "physical_condition_sha256": source["physical_condition_sha256"],
            "command": command,
            "cwd": str(endpoint_root),
            "output_prefix": str(prefix),
            "executed": False,
            "returncode": None,
            "stdout_tail": None,
            "stderr_tail": None,
            "generated_xml": None,
            "generated_bi4": None,
            "initial_qa": "required separately; not performed by this worker",
        }
        if execute:
            endpoint_root.mkdir(parents=False, exist_ok=False)
            completed = subprocess.run(
                command,
                cwd=str(endpoint_root),
                check=False,
                capture_output=True,
                text=True,
            )
            record.update(
                {
                    "executed": True,
                    "returncode": int(completed.returncode),
                    "stdout_tail": completed.stdout[-4000:],
                    "stderr_tail": completed.stderr[-4000:],
                    "generated_xml": str(prefix.with_suffix(".xml")),
                    "generated_bi4": str(prefix.with_suffix(".bi4")),
                }
            )
            if completed.returncode != 0:
                failures += 1
        commands.append(record)

    result = {
        "schema": SCHEMA,
        "family_id": plan["family_id"],
        "scope_id": plan["scope_id"],
        "source_plan": str(plan_path),
        "source_plan_sha256": sha256(plan_path),
        "gencase_executable": str(gencase_exe),
        "gencase_executable_sha256": observed_exe_sha,
        "execute_requested": bool(execute),
        "endpoint_count": len(commands),
        "commands": commands,
        "status": "completed" if execute and failures == 0 else ("failed" if execute else "disabled"),
        "gencase_returncode_failures": failures,
        "initial_qa": "not performed; Root must run the disabled initial-native QA request after successful GenCase",
        "conversion": "forbidden in this preflight",
        "solver": "forbidden",
        "rendering": "forbidden",
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "production_approval": "none",
        "launch_allowed": False,
    }
    write_json(report_path, result)
    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--gencase-exe", type=Path, default=Path(DEFAULT_GENCASE))
    parser.add_argument("--expected-gencase-sha256", default=DEFAULT_GENCASE_SHA256)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--execute", action="store_true", help="Root-only explicit launch switch")
    args = parser.parse_args()
    return run(
        args.plan,
        args.gencase_exe,
        args.output_root,
        args.report,
        args.execute,
        args.expected_gencase_sha256,
        args.threads,
    )


if __name__ == "__main__":
    raise SystemExit(main())
