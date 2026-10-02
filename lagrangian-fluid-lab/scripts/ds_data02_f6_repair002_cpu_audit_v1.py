#!/usr/bin/env python3
"""Audit completed F6 repair002 CPU post-processing without rerunning tools.

The first PartVTKOut requests are immutable and the official tool appends the
frame number to the requested VTK basename (``excluded_0000.vtk``).  This
additive audit records that actual output, the typed exclusion row, and the
completed FloatingInfo/ComputeForces CSVs.  It does not create H5 files,
labels, solver output, or qualification claims.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
FAMILY_ROOT = REPO_ROOT / "campaigns/ds-data-02/families/F6"
HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261002/rigid_contract_003"
RAW_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")
SCOPE = HANDOFF_ROOT / "dp020_repair_002_postprocessing_002"
PARTVTK_SCOPE = HANDOFF_ROOT / "dp020_repair_002_partvtkout_001"
OLD_POST_SCOPE = HANDOFF_ROOT / "dp020_repair_002_postprocessing_001"
SEMANTICS = HANDOFF_ROOT / "domain_xy_repair_02/postprocessing_008/rigid_force_torque_semantics_002.json"

CASES: dict[str, dict[str, str]] = {
    "simple_free_response": {
        "case_id": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_EPSFREE002_PHASE003_DP020_FINITE_WALL_REPAIR_002",
        "mechanism_id": "simple_free_response",
    },
    "wave_no_contact": {
        "case_id": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_EPSFREE002_PHASE003_DP020_FINITE_WALL_REPAIR_002",
        "mechanism_id": "wave_no_contact",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_immutable(path: Path, value: Any) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise RuntimeError(f"refusing to overwrite existing artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _path_entry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path.resolve()), "exists": False}
    return {"path": str(path.resolve()), "exists": True, "bytes": path.stat().st_size, "sha256": sha256(path)}


def _solver_paths(row: dict[str, str]) -> dict[str, Path]:
    case_id = row["case_id"]
    solver_root = RAW_ROOT / case_id / f"{case_id}_SOLVER_QUAL_DOMAIN_STAGE_001"
    receipt_path = solver_root / "execution-receipt.json"
    receipt = read_json(receipt_path)
    command = receipt.get("request", {}).get("command", [])
    prefix = Path(str(command[1])).resolve()
    data = solver_root / "solver_output/data"
    post_root = RAW_ROOT / case_id
    part_attempt = f"{case_id}_PARTVTKOUT_UNKNOWN_POSITION_001"
    floating_attempt = f"{case_id}_FLOATINGINFO_REPAIR002_001"
    forces_attempt = f"{case_id}_COMPUTEFORCES_REPAIR002_001"
    return {
        "solver_root": solver_root,
        "solver_receipt": receipt_path,
        "data": data,
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
        "part_request": PARTVTK_SCOPE / "requests" / f"{row['mechanism_id']}_partvtkout.json",
        "part_root": post_root / part_attempt,
        "part_receipt": post_root / part_attempt / "execution-receipt.json",
        "part_csv": post_root / part_attempt / "excluded.csv",
        "part_resume": post_root / part_attempt / "excluded-resume.csv",
        "part_vtk": post_root / part_attempt / "excluded_0000.vtk",
        "floating_request": OLD_POST_SCOPE / "execution_requests" / f"{row['mechanism_id']}_repair002_floatinginfo.json",
        "floating_root": post_root / floating_attempt,
        "floating_receipt": post_root / floating_attempt / "execution-receipt.json",
        "floating_csv": post_root / floating_attempt / "floating/FloatingInfo_mk60.csv",
        "forces_request": OLD_POST_SCOPE / "execution_requests" / f"{row['mechanism_id']}_repair002_computeforces.json",
        "forces_root": post_root / forces_attempt,
        "forces_receipt": post_root / forces_attempt / "execution-receipt.json",
        "forces_csv": post_root / forces_attempt / "forces/FloatingForce.csv",
    }


def _csv_rows(path: Path, delimiter: str = ";") -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as stream:
        reader = csv.DictReader(stream, delimiter=delimiter)
        fields = [str(item).strip() for item in (reader.fieldnames or [])]
        rows = []
        for raw in reader:
            rows.append({str(key).strip(): (value or "").strip() for key, value in raw.items() if key is not None})
        return fields, rows


def _float(value: str) -> float:
    return float(value.strip().replace(",", ""))


def _xml_contract(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find("./execution/particles")
    constants = root.find("./execution/constants")
    floating = root.find("./casedef/floatings/floating")
    if particles is None or constants is None or floating is None:
        raise ValueError(f"incomplete XML contract: {path}")

    def attr(node: ET.Element | None, name: str) -> float:
        if node is None or node.get(name) is None:
            raise ValueError(f"missing {name} in {path}")
        return float(node.get(name, "nan"))

    groups: dict[str, dict[str, int]] = {}
    for role in ("fixed", "moving", "floating", "fluid"):
        node = particles.find(role)
        if node is not None:
            groups[role] = {"begin": int(node.get("begin", 0)), "count": int(node.get("count", 0)), "mk": int(node.get("mk", 0))}
    center = floating.find("center")
    inertia = floating.find("inertia")
    return {
        "data2d": root.findtext("./execution/parameters/data2d", default="false").lower() == "true",
        "total_particles": int(particles.get("np", 0)),
        "fixed_particles": int(particles.get("nbf", 0)),
        "groups": groups,
        "fluid_mass_kg": attr(constants.find("massfluid"), "value"),
        "dp_m": attr(constants.find("dp"), "value"),
        "aggregate_massbody_kg": attr(floating.find("massbody"), "value"),
        "center_m": [attr(center, axis) for axis in "xyz"],
        "inertia_diag_kg_m2": [attr(inertia, axis) for axis in "xyz"],
        "floating_mkbound": int(floating.get("mkbound", 0)),
    }


def _receipt(path: Path) -> dict[str, Any]:
    value = read_json(path)
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "status": value.get("status"),
        "returncode": value.get("returncode"),
        "elapsed_seconds": value.get("elapsed_seconds"),
        "cpu_core_seconds": value.get("cpu_core_seconds"),
        "output_root": value.get("output_root"),
        "request_sha256": value.get("request_sha256"),
    }


def _ranges(fields: list[str], rows: list[dict[str, str]], names: list[str]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for name in names:
        values = [_float(row[name]) for row in rows if row.get(name, "")]
        if values:
            result[name] = {"min": min(values), "max": max(values), "first": values[0], "last": values[-1]}
    return result


def _partvtk_audit(key: str, row: dict[str, str], paths: dict[str, Path]) -> dict[str, Any]:
    fields, rows = _csv_rows(paths["part_csv"], delimiter=",")
    resume_fields, resume_rows = _csv_rows(paths["part_resume"], delimiter=";")
    if len(rows) != 1:
        raise ValueError(f"expected one typed PartVTKOut row for {key}, got {len(rows)}")
    item = rows[0]
    typed = {name: item.get(name, "") for name in fields}
    return {
        "request": _path_entry(paths["part_request"]),
        "receipt": _receipt(paths["part_receipt"]),
        "outputs": {
            "csv": {**_path_entry(paths["part_csv"]), "fields": fields, "rows": len(rows), "typed_row": typed},
            "resume": {**_path_entry(paths["part_resume"]), "fields": resume_fields, "rows": len(resume_rows), "rows_data": resume_rows},
            "vtk": {**_path_entry(paths["part_vtk"]), "official_basename_suffix": "_0000.vtk appended by PartVTKOut for frame 0"},
        },
        "expected_native_exclusion": {"NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0},
        "unknown_position_policy": "retain PartOut/Motive/Idp/position/rho/velocity/Mk as an unknown native exclusion; no destination or mass is inferred before H5 lifecycle reconciliation",
        "qualification_claim": "none",
    }


def _floating_audit(paths: dict[str, Path], contract: dict[str, Any]) -> dict[str, Any]:
    fields, rows = _csv_rows(paths["floating_csv"], delimiter=";")
    required = ["part", "time [s]", "center.x [m]", "center.y [m]", "center.z [m]", "fvel.x [m/s]", "fvel.y [m/s]", "fvel.z [m/s]", "fomega.x [rad/s]", "fomega.y [rad/s]", "fomega.z [rad/s]", "roll [deg]", "pitch [deg]", "yaw [deg]", "fluidforcelin.x [N]", "fluidforcelin.y [N]", "fluidforcelin.z [N]", "fluidforceang.x [Nm]", "fluidforceang.y [Nm]", "fluidforceang.z [Nm]"]
    missing = [name for name in required if name not in fields]
    if missing or len(rows) != 241:
        raise ValueError(f"FloatingInfo contract failed: missing={missing}, rows={len(rows)}")
    force_fields = [name for name in required if name.startswith("fluidforce")]
    return {
        "receipt": _receipt(paths["floating_receipt"]),
        "csv": {**_path_entry(paths["floating_csv"]), "fields": fields, "rows": len(rows)},
        "frame_contract": {"first_part": int(rows[0]["part"]), "last_part": int(rows[-1]["part"]), "first_time_s": _float(rows[0]["time [s]"]), "last_time_s": _float(rows[-1]["time [s]"]), "expected_rows": 241},
        "required_state_fields": required,
        "state_ranges": _ranges(fields, rows, required[1:]),
        "nonzero_fluid_force_and_torque": {name: any(abs(_float(item[name])) > 0.0 for item in rows) for name in force_fields},
        "selector_contract": {"command_onlymk": 60, "xml_floating_mkbound": contract["floating_mkbound"], "xml_floating_particle_mk": contract["groups"].get("floating", {}).get("mk"), "selected_particle_count_from_compute_forces": 35301, "help_semantics": "official FloatingInfo -onlymk selects floating particle mk; generated XML maps floating mkbound=50 to particle mk=60"},
        "mass_inertia_reference": {"aggregate_massbody_kg": contract["aggregate_massbody_kg"], "center_m": contract["center_m"], "inertia_diag_kg_m2": contract["inertia_diag_kg_m2"], "source": "generated XML; FloatingInfo CSV has no mass/inertia columns"},
        "torque_semantics": "native fluidforceang is current COM at solver force accumulation; saved row can differ from exact accumulation instant by the integration step",
    }


def _forces_audit(paths: dict[str, Path]) -> dict[str, Any]:
    fields, rows = _csv_rows(paths["forces_csv"], delimiter=";")
    required = ["Part", "Time [s]", "Np", "ForceFluid.x [N]", "ForceFluid.y [N]", "ForceFluid.z [N]", "Moment_iMx [Nm]", "Moment_iMy [Nm]", "Moment_iMz [Nm]", "Moment_eMx [Nm]", "Moment_eMy [Nm]", "Moment_eMz [Nm]"]
    missing = [name for name in required if name not in fields]
    if missing or len(rows) != 241:
        raise ValueError(f"ComputeForces contract failed: missing={missing}, rows={len(rows)}")
    force_fields = required[3:]
    return {
        "receipt": _receipt(paths["forces_receipt"]),
        "csv": {**_path_entry(paths["forces_csv"]), "fields": fields, "rows": len(rows)},
        "frame_contract": {"first_part": int(rows[0]["Part"]), "last_part": int(rows[-1]["Part"]), "first_time_s": _float(rows[0]["Time [s]"]), "last_time_s": _float(rows[-1]["Time [s]"]), "expected_rows": 241, "selected_np_unique": sorted({int(row["Np"]) for row in rows})},
        "force_moment_ranges": _ranges(fields, rows, force_fields),
        "nonzero_force_and_moment": {name: any(abs(_float(item[name])) > 0.0 for item in rows) for name in force_fields},
        "selector_contract": {"command_onlymk": 60, "selected_np": 35301, "xml_floating_particle_mk": 60},
        "moment_semantics": {"reference_m": [2.4, 1.2, 1.08], "frame": "world/extrinsic and body/intrinsic columns as emitted by ComputeForces", "phase": "official ComputeForces saved force calculation; separate from FloatingInfo saved solver force row", "current_com_reframe": "not applied"},
    }


def audit() -> dict[str, Any]:
    cases: dict[str, Any] = {}
    for key, row in CASES.items():
        paths = _solver_paths(row)
        contract = _xml_contract(paths["xml"])
        if contract["data2d"] or contract["groups"].get("fluid", {}).get("count") != 640000:
            raise ValueError(f"native contract failed for {key}: {contract}")
        if abs(contract["aggregate_massbody_kg"] - 128.0) > 1e-9 or any(abs(a - b) > 1e-8 for a, b in zip(contract["center_m"], [2.4, 1.2, 1.08])):
            raise ValueError(f"rigid contract failed for {key}: {contract}")
        cases[key] = {
            "case_id": row["case_id"],
            "generated_xml": {**_path_entry(paths["xml"]), "contract": contract},
            "generated_bi4": _path_entry(paths["bi4"]),
            "solver_source": _receipt(paths["solver_receipt"]),
            "partvtkout": _partvtk_audit(key, row, paths),
            "floatinginfo": _floating_audit(paths, contract),
            "computeforces": _forces_audit(paths),
            "source_semantics": _path_entry(SEMANTICS),
            "q_n_status": "pending H5/labels/spatial and scientific review",
            "qualification_claim": "none",
        }
    result = {
        "schema": "ds-data-02.f6.repair002.actual-cpu-audit.v1",
        "family_id": "F6",
        "scope": str(SCOPE.relative_to(FAMILY_ROOT)),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_script": _path_entry(SCRIPT),
        "supersedes_additively": {"old_bytes_preserved": True, "prior_partvtk_audit": str((PARTVTK_SCOPE / "audits/audit_manifest.json").resolve())},
        "cases": cases,
        "h5_conversion": "not run; remains queued",
        "labels": "not run",
        "gpu_launch": False,
        "solver_launch": False,
        "qualification_claim": "none",
        "q_n_status": "pending H5/labels/spatial/scientific review",
    }
    write_immutable(SCOPE / "actual_cpu_audit_001.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit"])
    args = parser.parse_args()
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
