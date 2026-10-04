#!/usr/bin/env python3
"""Run the actual F4 native initial audit after Root strict GenCase.

The 060 QA request consumed a hand-written ``generated-inputs.json`` whose
paths were placeholders.  This successor binds the output names emitted by
the 060/v2 GenCase worker directly:

``{attempt_root}/gencase/<endpoint>/<endpoint>.xml`` and ``.bi4``.

For each endpoint it materializes the small per-endpoint receipt expected by
the consumed F4 audit script, invokes that script, and adds an explicit
positive drop/bath source-separation check.  It never runs in this source
handoff; Root must first run GenCase and then launch this disabled audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA = "ds02.f4.drop-gap-initial-native-audit-index.v2"


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


def finite_bounds(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    return all(
        isinstance(point, list)
        and len(point) == 3
        and all(isinstance(component, (int, float)) and math.isfinite(float(component)) for component in point)
        for point in value
    )


def positive_source_separation(result: dict[str, Any]) -> dict[str, bool]:
    rows = result.get("source_rows")
    by_source = {
        str(row.get("source")): row
        for row in rows
        if isinstance(row, dict) and row.get("source") is not None
    } if isinstance(rows, list) else {}
    drop = by_source.get("drop", {})
    bath = by_source.get("pool", {})
    positive = (
        set(by_source) == {"drop", "pool"}
        and int(drop.get("fluid_count", 0)) > 0
        and int(bath.get("fluid_count", 0)) > 0
        and float(drop.get("native_mass_kg", 0.0)) > 0.0
        and float(bath.get("native_mass_kg", 0.0)) > 0.0
    )
    drop_bounds = drop.get("bounds_m")
    bath_bounds = bath.get("bounds_m")
    finite = finite_bounds(drop_bounds) and finite_bounds(bath_bounds)
    separated = False
    if finite:
        drop_low, drop_high = drop_bounds
        bath_low, bath_high = bath_bounds
        separated = bool(drop_low[2] > bath_high[2] or bath_low[2] > drop_high[2])
    return {
        "positive_drop_and_bath_source_rows": positive,
        "finite_drop_and_bath_bounds": finite,
        "drop_and_bath_bounds_are_separated": separated,
        "native_uid_type_mass_and_full3d_checks_present": all(
            bool(result.get("checks", {}).get(name))
            for name in (
                "finite_unique_complete_ids",
                "complete_type_partition",
                "all_source_population_checks",
                "true_3d",
            )
        ),
    }


def endpoint_receipt(
    *,
    gencase_result_path: Path,
    gencase_result: dict[str, Any],
    command: dict[str, Any],
    endpoint_id: str,
    xml_path: Path,
    bi4_path: Path,
) -> dict[str, Any]:
    if gencase_result.get("status") != "completed":
        raise RuntimeError("GenCase preflight did not complete successfully")
    if not command.get("executed") or command.get("returncode") != 0:
        raise RuntimeError(f"GenCase endpoint did not complete successfully: {endpoint_id}")
    if command.get("generated_xml") != str(xml_path) or command.get("generated_bi4") != str(bi4_path):
        raise RuntimeError(f"GenCase output naming differs from the strict worker contract: {endpoint_id}")
    if not xml_path.is_file() or not bi4_path.is_file():
        raise FileNotFoundError(f"missing actual GenCase output for {endpoint_id}")
    return {
        "schema": "ds02.f4.drop-gap-endpoint-execution-receipt.v1",
        "status": "completed",
        "returncode": 0,
        "endpoint_id": endpoint_id,
        "generated_xml": str(xml_path),
        "generated_xml_sha256": sha256(xml_path),
        "generated_bi4": str(bi4_path),
        "generated_bi4_sha256": sha256(bi4_path),
        "gencase_command": command.get("command"),
        "gencase_preflight_result": str(gencase_result_path),
        "gencase_preflight_result_sha256": sha256(gencase_result_path),
        "source_gencase_executable_sha256": gencase_result.get("gencase_executable_sha256"),
    }


def run(
    plan_path: Path,
    gencase_result_path: Path,
    generated_root: Path,
    metadata_root: Path,
    audit_script: Path,
    output_root: Path,
    python_binary: Path,
) -> int:
    plan = load_json(plan_path)
    if plan.get("stage_contract", {}).get("launch_allowed") is not False:
        raise RuntimeError("endpoint plan must keep launch_allowed=false")
    gencase_result = load_json(gencase_result_path)
    commands = {
        str(row.get("endpoint_id")): row
        for row in gencase_result.get("commands", [])
        if isinstance(row, dict)
    }
    endpoint_results: list[dict[str, Any]] = []
    all_pass = True
    for endpoint in plan["endpoints"]:
        endpoint_id = str(endpoint["endpoint_id"])
        command = commands.get(endpoint_id)
        if command is None:
            raise ValueError(f"GenCase result lacks endpoint {endpoint_id}")
        prefix = generated_root / endpoint_id / endpoint_id
        xml_path = prefix.with_suffix(".xml")
        bi4_path = prefix.with_suffix(".bi4")
        receipt_path = prefix.parent / "execution-receipt.json"
        receipt = endpoint_receipt(
            gencase_result_path=gencase_result_path,
            gencase_result=gencase_result,
            command=command,
            endpoint_id=endpoint_id,
            xml_path=xml_path,
            bi4_path=bi4_path,
        )
        if receipt_path.exists():
            existing = load_json(receipt_path)
            if existing.get("status") != "completed" or existing.get("returncode") != 0:
                raise RuntimeError(f"existing endpoint receipt is not successful: {receipt_path}")
        else:
            write_json(receipt_path, receipt)
        metadata = metadata_root / f"{endpoint_id}.metadata.json"
        if not metadata.is_file():
            raise FileNotFoundError(metadata)
        endpoint_output = output_root / endpoint_id
        endpoint_output.mkdir(parents=True, exist_ok=False)
        raw_output = endpoint_output / "native-preflight-audit.raw.json"
        final_output = endpoint_output / "native-preflight-audit.json"
        audit_command = [
            str(python_binary),
            str(audit_script),
            "audit",
            "--metadata",
            str(metadata),
            "--prefix",
            str(prefix),
            "--output",
            str(raw_output),
        ]
        completed = subprocess.run(
            audit_command,
            cwd=str(audit_script.parents[1]),
            check=False,
            capture_output=True,
            text=True,
        )
        if not raw_output.is_file():
            raise RuntimeError(
                f"native audit did not produce its expected report for {endpoint_id}; "
                f"returncode={completed.returncode}, stderr={completed.stderr[-2000:]}"
            )
        result = load_json(raw_output)
        extra_checks = positive_source_separation(result)
        checks = result.setdefault("checks", {})
        checks.update(extra_checks)
        result["pass"] = bool(result.get("pass")) and all(extra_checks.values())
        result["schema"] = "ds02.f4.drop-gap-native-preflight-audit.v2"
        result["endpoint_id"] = endpoint_id
        result["physical_condition_sha256"] = endpoint["physical_condition_sha256"]
        result["generated_xml_contract"] = {
            "path": str(xml_path),
            "sha256": sha256(xml_path),
            "native_bi4_path": str(bi4_path),
            "native_bi4_sha256": sha256(bi4_path),
        }
        result["execution_receipt"] = str(receipt_path)
        result["execution_receipt_sha256"] = sha256(receipt_path)
        result["native_audit_command"] = audit_command
        result["native_audit_returncode"] = int(completed.returncode)
        result["read_policy"] = {
            "native_bi4": "delegated to consumed F4 audit only after Root strict GenCase",
            "h5": False,
            "csv": False,
            "conversion": False,
            "solver": False,
            "rendering": False,
        }
        result["q_n_status"] = "not_assessed"
        result["precision_status"] = "not_accepted"
        result["production_approval"] = "none"
        write_json(final_output, result)
        endpoint_results.append(
            {
                "endpoint_id": endpoint_id,
                "generated_xml": str(xml_path),
                "generated_xml_sha256": sha256(xml_path),
                "generated_bi4": str(bi4_path),
                "generated_bi4_sha256": sha256(bi4_path),
                "execution_receipt": str(receipt_path),
                "initial_qa_json": str(final_output),
                "initial_qa_json_sha256": sha256(final_output),
                "native_audit_returncode": int(completed.returncode),
                "pass": bool(result["pass"]),
                "checks": checks,
            }
        )
        all_pass = all_pass and bool(result["pass"])
    index = {
        "schema": SCHEMA,
        "family_id": plan["family_id"],
        "scope_id": plan["scope_id"],
        "source_plan": str(plan_path),
        "source_plan_sha256": sha256(plan_path),
        "gencase_preflight_result": str(gencase_result_path),
        "gencase_preflight_result_sha256": sha256(gencase_result_path),
        "endpoints": endpoint_results,
        "pass": all_pass,
        "status": "initial-native-input-integrity-pass" if all_pass else "initial-native-input-integrity-fail",
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "production_approval": "none",
        "launch_allowed": False,
    }
    write_json(output_root / "initial-native-audit-index.json", index)
    return 0 if all_pass else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--gencase-result", required=True, type=Path)
    parser.add_argument("--generated-root", required=True, type=Path)
    parser.add_argument("--metadata-root", required=True, type=Path)
    parser.add_argument("--audit-script", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    args = parser.parse_args()
    return run(
        args.plan,
        args.gencase_result,
        args.generated_root,
        args.metadata_root,
        args.audit_script,
        args.output_root,
        args.python,
    )


if __name__ == "__main__":
    raise SystemExit(main())
