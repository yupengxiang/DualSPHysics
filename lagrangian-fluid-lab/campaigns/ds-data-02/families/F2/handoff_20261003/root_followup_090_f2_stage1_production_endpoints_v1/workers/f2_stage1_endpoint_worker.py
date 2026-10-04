#!/usr/bin/env python3
"""Read-only lifecycle binding worker for F2 Stage1 endpoints.

Run this after Root supplies actual GenCase, bounded initial-QA, and optional
full solver receipts.  It verifies immutable source identity and terminal
receipt fields only.  It never launches a process and never opens BI4/H5/CSV
arrays, so it cannot manufacture a completion or a mass result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "ds02.f2.stage1.endpoint-lifecycle-audit.v1"
DP = 0.01
TIME_MAX = 4.0
TIME_OUT = 0.01
EXPECTED_FRAMES = 401


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Mapping[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return value


def binding(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "exists": path.is_file(), "sha256": sha256(path) if path.is_file() else None}


def xml_contract(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    root = ET.parse(path).getroot()
    definition = root.find(".//casedef/geometry/definition")
    params = {item.attrib.get("key", ""): item.attrib.get("value", "") for item in root.findall(".//execution/parameters/parameter")}
    try:
        dp = float(definition.attrib["dp"]) if definition is not None else math.nan
        tmax = float(params["TimeMax"])
        tout = float(params["TimeOut"])
    except (KeyError, TypeError, ValueError):
        dp, tmax, tout = math.nan, math.nan, math.nan
    if not math.isfinite(dp) or abs(dp - DP) > 1e-12:
        errors.append(f"dp={dp!r}")
    if not math.isfinite(tmax) or abs(tmax - TIME_MAX) > 1e-12:
        errors.append(f"TimeMax={tmax!r}")
    if not math.isfinite(tout) or abs(tout - TIME_OUT) > 1e-12:
        errors.append(f"TimeOut={tout!r}")
    motion = root.find(".//casedef/motion/objreal/mvrotfile/file")
    motion_path = (path.parent / motion.attrib["name"]).resolve() if motion is not None else None
    motion_valid = False
    motion_sha = None
    if motion_path is not None and motion_path.is_file():
        motion_sha = sha256(motion_path)
        times: list[float] = []
        angles: list[float] = []
        for raw in motion_path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                t_text, a_text = raw.split(";", 1)
                times.append(float(t_text))
                angles.append(float(a_text))
            except ValueError:
                times.append(math.nan)
                angles.append(math.nan)
        motion_valid = bool(times) and all(math.isfinite(v) for v in times + angles) and all(b > a for a, b in zip(times, times[1:])) and abs(times[0]) <= 1e-12 and abs(times[-1] - TIME_MAX) <= 1e-9 and abs(angles[-1] + 105.0) <= 1e-6
    else:
        errors.append("motion file missing")
    if not motion_valid:
        errors.append("native mvrotfile motion contract failed")
    return {"status": "pass" if not errors else "fail", "errors": errors, "path": str(path), "sha256": sha256(path), "dp_m": dp, "time_max_s": tmax, "time_out_s": tout, "motion": {"path": str(motion_path) if motion_path else None, "sha256": motion_sha, "valid": motion_valid}}


def terminal_gencase(path: Path) -> tuple[bool, dict[str, Any]]:
    receipt = load(path)
    ok = receipt.get("status") == "completed" and receipt.get("returncode") == 0 and receipt.get("solver_dimension_from_gencase") == 3
    total = receipt.get("total_particles")
    fluid = receipt.get("fluid_particles")
    ok = ok and isinstance(total, int) and total > 0 and isinstance(fluid, int) and fluid > 0 and fluid <= total
    return ok, {"path": str(path.resolve()), "sha256": sha256(path), "status": receipt.get("status"), "returncode": receipt.get("returncode"), "solver_dimension": receipt.get("solver_dimension_from_gencase"), "actual_total_particles": total, "actual_fluid_particles": fluid}


def qa_binding(path: Path | None) -> tuple[bool, dict[str, Any]]:
    if path is None:
        return False, {"status": "pending"}
    report = load(path)
    ok = report.get("schema") == "ds02.f2.stage1.actual-initial-qa.v1" and report.get("status") == "pass"
    return ok, {"path": str(path.resolve()), "sha256": sha256(path), "schema": report.get("schema"), "status": report.get("status"), "checks": report.get("checks", {})}


def solver_binding(path: Path | None) -> tuple[bool, dict[str, Any]]:
    if path is None:
        return False, {"status": "pending"}
    receipt = load(path)
    status = receipt.get("status")
    returncode = receipt.get("returncode")
    frames = receipt.get("frame_count", receipt.get("frames", receipt.get("actual_frame_count")))
    frame_ok = frames is None or frames == EXPECTED_FRAMES
    ok = status == "completed" and returncode == 0 and frame_ok
    return ok, {"path": str(path.resolve()), "sha256": sha256(path), "status": status, "returncode": returncode, "frame_count": frames, "frame_count_check": frame_ok}


def audit(args: argparse.Namespace) -> dict[str, Any]:
    metadata_path = Path(args.metadata).resolve()
    metadata = load(metadata_path)
    definition = Path(str(metadata["definition_path"])).resolve()
    source_id_ok = metadata.get("case_id") == args.case_id and metadata.get("dp_m") == DP and metadata.get("time_max_s") == TIME_MAX and metadata.get("time_out_s") == TIME_OUT and metadata.get("expected_saved_frames") == EXPECTED_FRAMES
    xml = xml_contract(definition)
    gencase_ok, gencase = (False, {"status": "pending"})
    if args.gencase_receipt:
        gencase_ok, gencase = terminal_gencase(Path(args.gencase_receipt).resolve())
    qa_ok, qa = qa_binding(Path(args.qa_report).resolve() if args.qa_report else None)
    solver_ok, solver = solver_binding(Path(args.solver_receipt).resolve() if args.solver_receipt else None)
    checks = {"source_identity": source_id_ok, "xml_native_recipe": xml["status"] == "pass", "gencase_terminal": gencase_ok if args.gencase_receipt else None, "actual_initial_qa": qa_ok if args.qa_report else None, "solver_terminal_full401": solver_ok if args.solver_receipt else None}
    provided = [value for value in checks.values() if value is not None]
    status = "source_only_pending" if not provided or not args.gencase_receipt else "pass" if all(provided) else "fail"
    report = {
        "schema": SCHEMA,
        "case_id": args.case_id,
        "status": status,
        "source_only_worker": not bool(args.gencase_receipt),
        "claim": "lifecycle identity/receipt audit only; no mass, trajectory, precision, Q-N, or visual acceptance claim",
        "metadata": binding(metadata_path),
        "source": {"definition": binding(definition), "physical_condition_sha256": metadata.get("physical_condition_sha256"), "numerical_recipe_sha256": metadata.get("numerical_recipe_sha256")},
        "xml_contract": xml,
        "gencase": gencase,
        "actual_initial_qa": qa,
        "solver": solver,
        "checks": checks,
        "counting": {"mother_case_id": "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010", "new_case_count": 1 if status == "pass" else 0, "rule": "only Root actual complete lifecycle may increment independent case count"},
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--gencase-receipt")
    parser.add_argument("--qa-report")
    parser.add_argument("--solver-receipt")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = audit(args)
    return 0 if report["status"] == "pass" else 2 if report["status"] == "fail" else 3


if __name__ == "__main__":
    raise SystemExit(main())
