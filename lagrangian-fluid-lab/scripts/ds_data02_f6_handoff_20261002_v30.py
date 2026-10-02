#!/usr/bin/env python3
"""Audit the dp025 wave boundary failure and register one bounded x-domain repair.

This additive audit reads the failed native output only.  It computes the
measured piston envelope, confirms that every excluded point is a moving
particle at the default x-minimum, and records the previously validated
``[-0.2, 5.0]`` x-domain as the sole repair candidate.  It does not edit the
consumed XML/BI4, run GenCase, or launch a solver.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    import numpy as np
except (ImportError, OSError, ValueError):
    np = None  # type: ignore[assignment]


SCRIPT = Path(__file__).resolve()
FAMILY_ROOT = SCRIPT.parents[1] / "campaigns/ds-data-02/families/F6"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")
CASE_ID = "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025"
GENCASE_ATTEMPT = f"{CASE_ID}_GENCASE_001"
SOLVER_ATTEMPT = f"{CASE_ID}_SOLVER_QUAL_DP025_001"
CASE_ROOT = DATA_ROOT / CASE_ID
GENCASE_ROOT = CASE_ROOT / GENCASE_ATTEMPT
SOLVER_ROOT = CASE_ROOT / SOLVER_ATTEMPT
XML = GENCASE_ROOT / f"{CASE_ID}.xml"
BI4 = GENCASE_ROOT / f"{CASE_ID}.bi4"
CONTROL = FAMILY_ROOT / "handoff_20261002/commensurate_dp025_rigid003/cases/wave_no_contact/dp025" / f"{CASE_ID}_Control.csv"
NATIVE = FAMILY_ROOT / "handoff_20261002/commensurate_dp025_rigid003/cases/wave_no_contact/dp025" / f"{CASE_ID}_Native.json"
NORMAL = FAMILY_ROOT / "handoff_20261002/commensurate_dp025_rigid003/cases/wave_no_contact/dp025" / f"{CASE_ID}_Normal.json"
FAILED_RECEIPT = SOLVER_ROOT / "execution-receipt.json"
RUN_OUT = SOLVER_ROOT / "solver_output/Run.out"
ERROR_VTK = SOLVER_ROOT / "solver_output/Error_BoundaryOut.vtk"
WAVE_TRACE = SOLVER_ROOT / "solver_output/WavePaddle_mkb0010.csv"
OLD_REQUEST = FAMILY_ROOT / "handoff_20261002/commensurate_dp025_rigid003/qualification_requests_001" / f"{CASE_ID}.json"
PRIOR_DOMAIN_XML = DATA_ROOT / "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_DOMAIN_XY_REPAIR_02_FINE" / "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_DOMAIN_XY_REPAIR_02_FINE_GENCASE_001" / "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_DOMAIN_XY_REPAIR_02_FINE.xml"
PRIOR_DOMAIN_RECEIPT = DATA_ROOT / "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_DOMAIN_XY_REPAIR_02_FINE" / "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_DOMAIN_XY_REPAIR_02_FINE_SOLVER_QUAL_001/execution-receipt.json"
OUTPUT = FAMILY_ROOT / "handoff_20261002/commensurate_dp025/domain_x_repair_001/wave_domain_x_evidence_001.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def _binary_points(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    match = re.search(rb"POINTS\s+(\d+)\s+float\r?\n", payload)
    if match is None:
        raise ValueError(f"VTK POINTS header missing: {path}")
    count = int(match.group(1))
    start = match.end()
    raw = payload[start : start + count * 3 * 4]
    if len(raw) != count * 3 * 4:
        raise ValueError("truncated binary VTK points")
    values = struct.unpack(f">{count * 3}f", raw)
    points = [values[index : index + 3] for index in range(0, len(values), 3)]
    mins = [min(point[axis] for point in points) for axis in range(3)]
    maxs = [max(point[axis] for point in points) for axis in range(3)]
    unique_x = sorted({round(point[0], 9) for point in points})
    return {"count": count, "bounds_m": {"min": mins, "max": maxs}, "unique_x_count": len(unique_x), "all_x_equal": len(unique_x) == 1}


def _motion_trace(path: Path) -> dict[str, Any]:
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ";" not in line:
            continue
        fields = line.split(";")
        try:
            rows.append([float(value) for value in fields])
        except ValueError:
            continue
    if not rows:
        raise ValueError(f"no numeric wave-paddle rows: {path}")
    times = [row[0] for row in rows]
    displacement = [row[1] for row in rows]
    return {
        "rows": len(rows),
        "time_s": [min(times), max(times)],
        "displacement_m": [min(displacement), max(displacement)],
        "max_abs_displacement_m": max(abs(value) for value in displacement),
        "source": bind(path, "actual solver WavePaddle trace"),
    }


def _xml_contract(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    summary = root.find("./execution/particles/_summary")
    positions = summary.find("positions") if summary is not None else None
    moving = summary.find("moving") if summary is not None else None
    if summary is None or positions is None or moving is None:
        raise ValueError(f"generated XML native summary missing: {path}")
    domain = root.find("./execution/parameters/simulationdomain")
    posmin = positions.find("posmin")
    posmax = positions.find("posmax")
    piston = next((node for node in root.findall("./casedef/geometry/commands/mainlist/drawbox") if "piston" in node.attrib.get("cmt", "").lower()), None)
    if domain is None or piston is None:
        raise ValueError("generated XML lacks simulation domain or moving piston")
    point = piston.find("point")
    size = piston.find("size")
    assert point is not None and size is not None and posmin is not None and posmax is not None
    return {
        "sha256": sha256(path),
        "initial_particle_bounds_m": {
            "min": [float(posmin.attrib[axis]) for axis in "xyz"],
            "max": [float(posmax.attrib[axis]) for axis in "xyz"],
        },
        "moving_count": int(moving.attrib["count"]),
        "moving_initial_box_m": {
            "min": [float(point.attrib[axis]) for axis in "xyz"],
            "max": [float(point.attrib[axis]) + float(size.attrib[axis]) for axis in "xyz"],
        },
        "simulationdomain_source": {
            "posmin": root.find("./execution/parameters/simulationdomain/posmin").attrib,
            "posmax": root.find("./execution/parameters/simulationdomain/posmax").attrib,
        },
    }


def audit() -> dict[str, Any]:
    required = [XML, BI4, CONTROL, NATIVE, NORMAL, FAILED_RECEIPT, RUN_OUT, ERROR_VTK, WAVE_TRACE, OLD_REQUEST, PRIOR_DOMAIN_XML, PRIOR_DOMAIN_RECEIPT]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("domain-x audit input missing: " + ", ".join(missing))
    receipt = json.loads(FAILED_RECEIPT.read_text(encoding="utf-8"))
    run = RUN_OUT.read_text(encoding="utf-8", errors="replace")
    failure = re.search(r"TimeStep:\s*([0-9.]+).*?Total boundary:\s*(\d+)\s+\(fixed=(\d+)\s+moving=(\d+)\s+floating=(\d+)\).*?Some boundary particle exceeded the -X limit", run, re.DOTALL)
    if failure is None:
        raise ValueError("expected moving -X boundary failure not found")
    xml_contract = _xml_contract(XML)
    trace = _motion_trace(WAVE_TRACE)
    vtk = _binary_points(ERROR_VTK)
    initial_min = xml_contract["initial_particle_bounds_m"]["min"][0]
    initial_max = xml_contract["initial_particle_bounds_m"]["max"][0]
    moving_min = xml_contract["moving_initial_box_m"]["min"][0] + trace["displacement_m"][0]
    moving_max = xml_contract["moving_initial_box_m"]["max"][0] + trace["displacement_m"][1]
    candidate = {"x_min_m": -0.2, "x_max_m": 5.0}
    result = {
        "schema": "ds-data-02.f6.rigid003.domain_x_repair_001.wave_evidence.v1",
        "family_id": "F6",
        "case_id": CASE_ID,
        "status": "root_dispatch_pending",
        "failure": {
            "solver_receipt": bind(FAILED_RECEIPT, "immutable failed solver receipt"),
            "solver_status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "run_out": bind(RUN_OUT, "immutable failed solver log"),
            "time_s": float(failure.group(1)),
            "boundary_count": int(failure.group(2)),
            "fixed_count": int(failure.group(3)),
            "moving_count": int(failure.group(4)),
            "floating_count": int(failure.group(5)),
            "cause": "all excluded particles are moving type 20 at the generated default x-minimum; the physical wall is swept to negative x and is outside the auto-domain",
            "error_vtk": {**bind(ERROR_VTK, "immutable Error_BoundaryOut.vtk"), **vtk},
        },
        "source_recipe_immutable": {
            "generated_xml": bind(XML, "consumed RIGID003 generated XML"),
            "generated_bi4": bind(BI4, "consumed RIGID003 BI4"),
            "control": bind(CONTROL, "frozen source control ledger"),
            "native": bind(NATIVE, "frozen native contract"),
            "normal": bind(NORMAL, "frozen normal contract"),
            "old_request": bind(OLD_REQUEST, "consumed root-only solver request"),
        },
        "motion_envelope": {
            **trace,
            "moving_initial_box_x_m": [xml_contract["moving_initial_box_m"]["min"][0], xml_contract["moving_initial_box_m"]["max"][0]],
            "moving_swept_x_m": [moving_min, moving_max],
            "initial_generated_x_m": [initial_min, initial_max],
            "formula": "initial moving box x interval plus measured WavePaddle displacement interval; full generated particle bounds also retained",
        },
        "repair": {
            "change_only": "simulationdomain posmin.x/posmax.x in an additive copied XML; no GenCase, BI4, geometry, control, mass, inertia, or wave parameters change",
            "candidate_domain_x_m": candidate,
            "candidate_margin_to_initial_generated_bounds_m": [initial_min - candidate["x_min_m"], candidate["x_max_m"] - initial_max],
            "candidate_margin_to_moving_sweep_m": [moving_min - candidate["x_min_m"], candidate["x_max_m"] - moving_max],
            "candidate_dp_margin_at_left": (moving_min - candidate["x_min_m"]) / 0.025,
            "prior_validated_domain_xml": bind(PRIOR_DOMAIN_XML, "completed DOMAIN_XY_REPAIR_02 reference XML"),
            "prior_validated_domain_receipt": bind(PRIOR_DOMAIN_RECEIPT, "completed DOMAIN_XY_REPAIR_02 reference solver receipt"),
            "prior_rule": "same x bounds [-0.2,5.0] already used by completed RIGID003 DOMAIN_XY_REPAIR_02; y/z remain default and z+20%",
            "dispatch": "root-only helper may colocate immutable generated XML/BI4 and all control/native/normal dependencies under a fresh attempt prefix, edit only simulationdomain x bounds, and record before/after hashes",
        },
        "qualification_claim": "none",
        "q_n_status": "pending additive domain repair solver evidence",
        "gpu_launch": "root_only",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit"])
    args = parser.parse_args()
    result = audit() if args.action == "audit" else None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
