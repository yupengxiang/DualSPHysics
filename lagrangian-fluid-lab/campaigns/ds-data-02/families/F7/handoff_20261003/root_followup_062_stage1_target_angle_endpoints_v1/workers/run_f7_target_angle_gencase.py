#!/usr/bin/env python3
"""Root-strict genuine GenCase worker for the two F7 angle endpoints.

The source request is disabled.  At a later Root strict launch this worker
consumes the preceding motion-preparation attempt, runs the official GenCase
binary once per endpoint, and records the exact generated XML/BI4 prefixes and
per-endpoint execution receipts.  It does not run a solver, convert, render,
or make a numerical/visual acceptance claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA = "ds02.f7.target-angle-gencase-result.v1"
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


def generated_contract(xml_path: Path, endpoint: dict[str, Any]) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    definition = root.find("casedef/geometry/definition")
    particles = root.find("execution/particles")
    constants = root.find("execution/constants")
    if definition is None or particles is None or constants is None:
        raise RuntimeError(f"GenCase XML lacks required generated sections: {xml_path}")
    data2d = constants.find("data2d")
    params = {str(n.attrib.get("key")): str(n.attrib.get("value")) for n in root.findall("execution/parameters/parameter")}
    counts = {
        "fixed": int(particles.find("fixed").attrib["count"]),
        "moving": int(particles.find("moving").attrib["count"]),
        "fluid": int(particles.find("fluid").attrib["count"]),
    }
    total = int(particles.attrib["np"])
    checks = {
        "dp_is_native_020": definition.attrib.get("dp") == "0.02",
        "time_max_is_12": params.get("TimeMax") == "12",
        "time_out_is_002": params.get("TimeOut") == "0.02",
        "actual_3d": data2d is not None and data2d.attrib.get("value") == "false",
        "positive_fixed_moving_fluid": all(value > 0 for value in counts.values()),
        "counts_match_source": counts == {
            "fixed": int(endpoint["expected_fixed"]),
            "moving": int(endpoint["expected_moving"]),
            "fluid": int(endpoint["expected_fluid"]),
        },
        "total_matches_partition": total == sum(counts.values()),
        "total_matches_source": total == int(endpoint["expected_total"]),
    }
    return {
        "xml_sha256": sha256(xml_path),
        "generated_xml": str(xml_path),
        "geometry_dp_m": definition.attrib.get("dp"),
        "time_max_s": params.get("TimeMax"),
        "time_out_s": params.get("TimeOut"),
        "particles": {"total": total, **counts, "native_types": {"fixed": [0], "moving": [1], "fluid": [3]}},
        "checks": checks,
        "mass_policy": "native unscaled MassFluid and native body support weights; no continuum rescale",
    }


def run(
    plan_path: Path,
    prepared_root: Path,
    output_root: Path,
    report_path: Path,
    gencase_exe: Path,
    threads: int,
    execute: bool,
    expected_gencase_sha256: str | None,
) -> int:
    plan = load_json(plan_path)
    if plan.get("stage_contract", {}).get("launch_allowed") is not False:
        raise RuntimeError("endpoint plan must remain launch_allowed=false")
    prep_report = load_json(prepared_root / "motion-source-preparation.json")
    if prep_report.get("endpoint_count") != 2:
        raise RuntimeError("motion preparation report does not contain both endpoints")
    if not gencase_exe.is_file():
        raise FileNotFoundError(gencase_exe)
    observed_exe_sha = sha256(gencase_exe)
    if expected_gencase_sha256 and observed_exe_sha != expected_gencase_sha256:
        raise RuntimeError(f"GenCase hash mismatch: {observed_exe_sha} != {expected_gencase_sha256}")
    if execute:
        output_root.mkdir(parents=True, exist_ok=False)
    endpoint_results: list[dict[str, Any]] = []
    failures = 0
    for endpoint in plan["endpoints"]:
        endpoint_id = str(endpoint["endpoint_id"])
        prepared_endpoint = prepared_root / endpoint_id
        definition = prepared_endpoint / f"{endpoint_id}_Def.xml"
        motion = prepared_endpoint / "motion_obstacle_quintic.dat"
        if not definition.is_file() or not motion.is_file():
            raise FileNotFoundError(f"motion-prepared endpoint assets missing: {endpoint_id}")
        endpoint_root = output_root / endpoint_id
        prefix = endpoint_root / endpoint_id
        command = [str(gencase_exe), str(definition.with_suffix("")), str(prefix), "-save:all", f"-threads:{threads}"]
        row: dict[str, Any] = {
            "endpoint_id": endpoint_id,
            "physical_condition_sha256": endpoint["physical_condition_sha256"],
            "prepared_definition": str(definition),
            "prepared_definition_sha256": sha256(definition),
            "motion_file": str(motion),
            "motion_file_sha256": sha256(motion),
            "command": command,
            "cwd": str(prepared_endpoint),
            "output_prefix": str(prefix),
            "executed": False,
            "returncode": None,
            "generated_xml": None,
            "generated_bi4": None,
            "xml_contract": None,
        }
        if execute:
            endpoint_root.mkdir(parents=False, exist_ok=False)
            completed = subprocess.run(command, cwd=str(prepared_endpoint), check=False, capture_output=True, text=True)
            row.update(
                {
                    "executed": True,
                    "returncode": int(completed.returncode),
                    "stdout_tail": completed.stdout[-4000:],
                    "stderr_tail": completed.stderr[-4000:],
                }
            )
            xml_path = prefix.with_suffix(".xml")
            bi4_path = prefix.with_suffix(".bi4")
            row["generated_xml"] = str(xml_path)
            row["generated_bi4"] = str(bi4_path)
            if completed.returncode == 0 and xml_path.is_file() and bi4_path.is_file():
                row["xml_contract"] = generated_contract(xml_path, endpoint)
                if not all(row["xml_contract"]["checks"].values()):
                    row["returncode"] = 1
            else:
                failures += 1
            receipt = {
                "schema": "ds02.f7.target-angle-endpoint-execution-receipt.v1",
                "status": "completed" if row["returncode"] == 0 else "failed",
                "returncode": row["returncode"],
                "endpoint_id": endpoint_id,
                "physical_condition_sha256": endpoint["physical_condition_sha256"],
                "command": command,
                "cwd": str(prepared_endpoint),
                "generated_xml": str(xml_path),
                "generated_xml_sha256": sha256(xml_path) if xml_path.is_file() else None,
                "generated_bi4": str(bi4_path),
                "generated_bi4_sha256": sha256(bi4_path) if bi4_path.is_file() else None,
                "prepared_definition_sha256": sha256(definition),
                "motion_file_sha256": sha256(motion),
                "q_n_status": "not_assessed",
                "precision_status": "not_accepted",
                "production_approval": "none",
            }
            write_json(endpoint_root / "execution-receipt.json", receipt)
            if row["returncode"] != 0:
                failures += 1
        endpoint_results.append(row)
    report = {
        "schema": SCHEMA,
        "scope_id": plan["scope_id"],
        "source_plan": str(plan_path),
        "source_plan_sha256": sha256(plan_path),
        "prepared_root": str(prepared_root),
        "prepared_report_sha256": sha256(prepared_root / "motion-source-preparation.json"),
        "gencase_executable": str(gencase_exe),
        "gencase_executable_sha256": observed_exe_sha,
        "execute_requested": bool(execute),
        "endpoint_count": len(endpoint_results),
        "endpoints": endpoint_results,
        "status": "completed" if execute and failures == 0 else ("failed" if execute else "disabled"),
        "returncode_failures": failures,
        "initial_qa": "required separately; not performed by this worker",
        "solver": "forbidden",
        "conversion": "forbidden",
        "rendering": "forbidden",
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "production_approval": "none",
        "launch_allowed": False,
    }
    write_json(report_path, report)
    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--prepared-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--gencase-exe", type=Path, default=Path(DEFAULT_GENCASE))
    parser.add_argument("--expected-gencase-sha256", default=DEFAULT_GENCASE_SHA256)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--execute", action="store_true", help="Root-only explicit launch switch")
    args = parser.parse_args()
    return run(args.plan, args.prepared_root, args.output_root, args.report, args.gencase_exe, args.threads, args.execute, args.expected_gencase_sha256)


if __name__ == "__main__":
    raise SystemExit(main())
