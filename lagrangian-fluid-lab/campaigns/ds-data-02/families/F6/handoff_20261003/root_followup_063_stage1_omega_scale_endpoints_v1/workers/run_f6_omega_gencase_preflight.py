#!/usr/bin/env python3
"""Root-strict GenCase preflight for the two F6 omega endpoints.

This worker is intentionally disabled in the source handoff.  When Root
strictly enables it, each genuine ``*_Def.xml`` is passed to the official
GenCase binary and its own XML/BI4 prefix is recorded.  The worker never
invokes a solver, H5 converter, CSV exporter, PartVTK, or renderer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SCHEMA = "ds02.f6.omega-scale-gencase-preflight-result.v1"
DEFAULT_GENCASE = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
DEFAULT_GENCASE_SHA256 = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"
BASE = Path(__file__).resolve().parents[5]


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


def xml_contract(xml_path: Path, endpoint: dict[str, Any]) -> dict[str, Any]:
    """Read generated XML metadata only; no particle payload is opened."""
    root = ET.parse(xml_path).getroot()
    expected_omega = [float(v) for v in endpoint["initial_angular_velocity_rad_s"]]
    floating = root.find(".//execution/particles/floating") or root.find(".//particles/floating")
    casedef_floating = root.find(".//casedef/floatings/floating")
    angular = floating.find("angularvelini") if floating is not None else None
    if angular is None and casedef_floating is not None:
        angular = casedef_floating.find("angularvelini")
    if angular is None:
        raise RuntimeError(f"generated XML lacks angularvelini: {xml_path}")
    actual_omega = [float(angular.get(axis, "nan")) for axis in ("x", "y", "z")]
    center = floating.find("center") if floating is not None else None
    if center is None and casedef_floating is not None:
        center = casedef_floating.find("center")
    massbody = floating.find("massbody") if floating is not None else None
    if massbody is None and casedef_floating is not None:
        massbody = casedef_floating.find("massbody")
    center_actual = [float(center.get(axis, "nan")) for axis in ("x", "y", "z")] if center is not None else []
    mass_actual = float(massbody.get("value", "nan")) if massbody is not None else float("nan")
    params = {node.get("key"): node.get("value") for node in root.findall(".//execution/parameters/parameter")}
    dp_node = root.find(".//constants/dp")
    if dp_node is None:
        dp_node = root.find(".//geometry/definition")
    dp_actual = float(dp_node.get("value", dp_node.get("dp", "nan"))) if dp_node is not None else float("nan")
    count_nodes = {
        "fixed": root.find(".//particles/_summary/fixed"),
        "floating": root.find(".//particles/_summary/floating"),
        "fluid": root.find(".//particles/_summary/fluid"),
    }
    counts = {name: int(node.get("count", "-1")) if node is not None else None for name, node in count_nodes.items()}
    checks = {
        "angularvelini_matches_endpoint": all(abs(a - b) <= 1e-9 for a, b in zip(actual_omega, expected_omega)),
        "center_matches_fixed_m": all(abs(a - b) <= 1e-9 for a, b in zip(center_actual, [2.4, 1.2, 1.08])),
        "massbody_matches_physical_kg": abs(mass_actual - 128.0) <= 1e-9,
        "dp_matches_0p025_m": abs(dp_actual - 0.025) <= 1e-12,
        "time_max_matches_12_s": abs(float(params.get("TimeMax", "nan")) - 12.0) <= 1e-9,
        "time_out_matches_0p05_s": abs(float(params.get("TimeOut", "nan")) - 0.05) <= 1e-12,
        "counts_match_expected": counts == {"fixed": 73441, "floating": 16384, "fluid": 327680},
    }
    return {
        "xml": str(xml_path),
        "xml_sha256": sha256(xml_path),
        "angularvelini_rad_s": actual_omega,
        "expected_angularvelini_rad_s": expected_omega,
        "center_m": center_actual,
        "massbody_kg": mass_actual,
        "dp_m": dp_actual,
        "time_max_s": float(params.get("TimeMax", "nan")),
        "time_out_s": float(params.get("TimeOut", "nan")),
        "typed_summary_counts": counts,
        "checks": checks,
        "all_xml_contract_checks_passed": all(checks.values()),
    }


def source_records(plan_path: Path, plan: dict[str, Any]) -> list[dict[str, Any]]:
    receipt_path = plan_path.parent / "source-build-receipt.json"
    receipt = load_json(receipt_path)
    by_id = {str(row["endpoint_id"]): row for row in receipt.get("endpoints", [])}
    records: list[dict[str, Any]] = []
    for endpoint in plan.get("endpoints", []):
        endpoint_id = str(endpoint["endpoint_id"])
        source = plan_path.parent / str(endpoint["source_definition_output"])
        if not source.is_file():
            raise FileNotFoundError(source)
        receipt_row = by_id.get(endpoint_id)
        if receipt_row is None:
            raise RuntimeError(f"source-build receipt lacks endpoint: {endpoint_id}")
        observed = sha256(source)
        if observed != receipt_row.get("source_definition_sha256") or observed != endpoint.get("source_definition_sha256"):
            raise RuntimeError(f"source Definition hash mismatch: {endpoint_id}")
        records.append({
            "endpoint": endpoint,
            "endpoint_id": endpoint_id,
            "source_definition": source,
            "source_definition_sha256": observed,
            "physical_condition_sha256": endpoint["physical_condition_sha256"],
        })
    return records


def run(
    plan_path: Path,
    gencase_exe: Path,
    output_root: Path,
    report_path: Path,
    execute: bool,
    expected_gencase_sha256: str,
    threads: int,
) -> int:
    plan = load_json(plan_path)
    if plan.get("stage_contract", {}).get("launch_allowed") is not False:
        raise RuntimeError("F6 endpoint plan must keep launch_allowed=false")
    records = source_records(plan_path, plan)
    if not gencase_exe.is_file():
        raise FileNotFoundError(gencase_exe)
    observed_binary_hash = sha256(gencase_exe)
    if observed_binary_hash != expected_gencase_sha256:
        raise RuntimeError(f"GenCase hash mismatch: {observed_binary_hash} != {expected_gencase_sha256}")
    if threads < 1:
        raise ValueError("threads must be positive")

    if execute:
        output_root.mkdir(parents=True, exist_ok=False)
    commands: list[dict[str, Any]] = []
    failures = 0
    for record in records:
        endpoint = record["endpoint"]
        endpoint_id = record["endpoint_id"]
        endpoint_root = output_root / endpoint_id
        prefix = endpoint_root / endpoint_id
        command = [
            str(gencase_exe),
            str(record["source_definition"].with_suffix("")),
            str(prefix),
            "-save:all",
            f"-threads:{threads}",
        ]
        item: dict[str, Any] = {
            "endpoint_id": endpoint_id,
            "physical_case_id": endpoint["physical_case_id"],
            "physical_condition_sha256": record["physical_condition_sha256"],
            "source_definition": str(record["source_definition"]),
            "source_definition_sha256": record["source_definition_sha256"],
            "command": command,
            "cwd": str(endpoint_root),
            "output_prefix": str(prefix),
            "executed": False,
            "returncode": None,
            "elapsed_seconds": None,
            "stdout_tail": None,
            "stderr_tail": None,
            "generated_xml": str(prefix.with_suffix(".xml")),
            "generated_bi4": str(prefix.with_suffix(".bi4")),
            "xml_contract": None,
            "initial_qa": "required separately; not performed by GenCase worker",
        }
        if execute:
            endpoint_root.mkdir(parents=False, exist_ok=False)
            started = time.monotonic()
            completed = subprocess.run(command, cwd=str(endpoint_root), check=False, capture_output=True, text=True)
            elapsed = time.monotonic() - started
            item.update({
                "executed": True,
                "returncode": int(completed.returncode),
                "elapsed_seconds": elapsed,
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            })
            if completed.returncode != 0:
                failures += 1
            else:
                xml_path = prefix.with_suffix(".xml")
                bi4_path = prefix.with_suffix(".bi4")
                if not xml_path.is_file() or not bi4_path.is_file():
                    failures += 1
                    item["postcondition_error"] = "GenCase returned zero but XML/BI4 output naming was incomplete"
                else:
                    try:
                        item["xml_contract"] = xml_contract(xml_path, endpoint)
                        if not item["xml_contract"]["all_xml_contract_checks_passed"]:
                            failures += 1
                    except Exception as exc:  # report source/runtime failure without hiding it
                        failures += 1
                        item["xml_contract_error"] = str(exc)
                if xml_path.is_file():
                    item["generated_xml_sha256"] = sha256(xml_path)
                if bi4_path.is_file():
                    item["generated_bi4_sha256"] = sha256(bi4_path)
                receipt_path = endpoint_root / "execution-receipt.json"
                write_json(receipt_path, {
                    "schema": "ds02.f6.omega-scale-endpoint-execution-receipt.v1",
                    "family_id": "F6",
                    "endpoint_id": endpoint_id,
                    "physical_case_id": endpoint["physical_case_id"],
                    "physical_condition_sha256": record["physical_condition_sha256"],
                    "source_definition": str(record["source_definition"]),
                    "source_definition_sha256": record["source_definition_sha256"],
                    "gencase_executable": str(gencase_exe),
                    "gencase_executable_sha256": observed_binary_hash,
                    "command": command,
                    "returncode": int(completed.returncode),
                    "generated_xml": str(xml_path),
                    "generated_xml_sha256": sha256(xml_path) if xml_path.is_file() else None,
                    "generated_bi4": str(bi4_path),
                    "generated_bi4_sha256": sha256(bi4_path) if bi4_path.is_file() else None,
                    "mass_policy": "128 kg physical and 256 kg native support remain distinct; no rescale",
                    "launch_allowed": False,
                })
                item["execution_receipt"] = str(receipt_path)
        commands.append(item)

    result = {
        "schema": SCHEMA,
        "family_id": plan["family_id"],
        "scope_id": plan["scope_id"],
        "source_plan": str(plan_path),
        "source_plan_sha256": sha256(plan_path),
        "gencase_executable": str(gencase_exe),
        "gencase_executable_sha256": observed_binary_hash,
        "execute_requested": bool(execute),
        "endpoint_count": len(commands),
        "commands": commands,
        "status": "completed" if execute and failures == 0 else ("failed" if execute else "disabled"),
        "gencase_returncode_or_contract_failures": failures,
        "initial_qa": "not performed; Root must run disabled native initial QA after successful fresh GenCase",
        "bi4_policy": "fresh output only; baseline BI4 is never copied or reused",
        "solver": "forbidden",
        "conversion": "forbidden",
        "h5": "forbidden",
        "csv": "forbidden by this worker",
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
    return run(args.plan, args.gencase_exe, args.output_root, args.report, args.execute, args.expected_gencase_sha256, args.threads)


if __name__ == "__main__":
    raise SystemExit(main())
