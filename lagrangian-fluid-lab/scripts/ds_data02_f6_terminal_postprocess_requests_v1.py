#!/usr/bin/env python3
"""Register additive F6 DP020 post-processing and DP0125 solver requests.

This module only audits already terminal native output and writes new request
JSON.  It never launches a GPU or solver.  The raw solver trees, generated
inputs, and all older requests are treated as immutable.  CPU execution, when
requested by the root agent, is guarded by a complete native-data manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
FAMILY_ROOT = REPO_ROOT / "campaigns/ds-data-02/families/F6"
HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261002"
CONTRACT_ROOT = HANDOFF_ROOT / "rigid_contract_003"
RAW_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")
HISTORICAL_LAB = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
INTEGRATION_PYTHON = INTEGRATION_LAB / ".venv/bin/python"
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
V35 = REPO_ROOT / "scripts/ds_data02_f6_handoff_20261002_v35.py"
CONVERTER = REPO_ROOT / "scripts/ds_data02_f6_native_h5_v35.py"
LABELS = INTEGRATION_LAB / "scripts/ds_data02_native_labels.py"
FINITE_FACE_AUDIT = REPO_ROOT / "scripts/ds_data02_f6_dp0125_finite_face_audit_v1.py"
FINITE_FACE_HELPER = INTEGRATION_LAB / "scripts/ds_data02_finite_faces_v1.py"
FLOATING_INFO = HISTORICAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/FloatingInfo_linux64"
COMPUTE_FORCES = HISTORICAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/ComputeForces_linux64"
PARTVTK = HISTORICAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
SOLVER = HISTORICAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"

DP020_POST_ROOT = CONTRACT_ROOT / "dp020_repair_002_postprocessing_001"
DP020_REQUEST_ROOT = DP020_POST_ROOT / "execution_requests"
DP020_MANIFEST_ROOT = DP020_POST_ROOT / "native_tree_manifests"
DP0125_ROOT = CONTRACT_ROOT / "dp0125_finite_face_reference_001"
DP0125_AUDIT = DP0125_ROOT / "finite_face_audit_001.json"
DP0125_REQUEST_ROOT = DP0125_ROOT / "solver_requests_001"

SEMANTICS = CONTRACT_ROOT / "domain_xy_repair_02/postprocessing_008/rigid_force_torque_semantics_002.json"
OLD_EQUIV = CONTRACT_ROOT / "dp020_dp0125_cpu_003/equivalence_domain_audit_001.json"
OLD_DP020_AUDIT = CONTRACT_ROOT / "dp020_dp0125_cpu_003/finite_wall_discretization_repair_002/native_audit_001.json"
OLD_REPAIR_MANIFEST = CONTRACT_ROOT / "dp020_dp0125_cpu_003/finite_wall_discretization_repair_002/repair_manifest_002.json"
DOMAIN_STAGE = CONTRACT_ROOT / "dp020_dp0125_cpu_003/finite_wall_discretization_repair_002/solver_domain_stage_001.json"

DP020_CASES: dict[str, dict[str, Any]] = {
    "simple_free_response": {
        "case_id": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_EPSFREE002_PHASE003_DP020_FINITE_WALL_REPAIR_002",
        "mechanism_id": "simple_free_response",
        "gencase_case_id": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_EPSFREE002_PHASE003_DP020",
    },
    "wave_no_contact": {
        "case_id": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_EPSFREE002_PHASE003_DP020_FINITE_WALL_REPAIR_002",
        "mechanism_id": "wave_no_contact",
        "gencase_case_id": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_EPSFREE002_PHASE003_DP020",
    },
}

DP0125_CASES: dict[str, dict[str, Any]] = {
    "simple_free_response": {
        "case_id": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_EPSFREE002_PHASE003_DP0125",
        "mechanism_id": "simple_free_response",
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": 64 * 2**30,
        "gencase_particles": {"total": 3053861, "fixed": 292996, "moving": 0, "floating": 139425, "fluid": 2621440},
    },
    "wave_no_contact": {
        "case_id": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_EPSFREE002_PHASE003_DP0125",
        "mechanism_id": "wave_no_contact",
        "max_wall_seconds": 9600,
        "estimated_storage_bytes": 72 * 2**30,
        "gencase_particles": {"total": 3362611, "fixed": 292996, "moving": 308750, "floating": 139425, "fluid": 2621440},
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


def _hash_entries(paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    seen: set[str] = set()
    for path in paths:
        path = path.resolve()
        if str(path) in seen:
            continue
        seen.add(str(path))
        if not path.is_file():
            raise FileNotFoundError(path)
        result[str(path)] = sha256(path)
    return result


def dp020_paths(row: dict[str, Any]) -> dict[str, Path]:
    case_id = str(row["case_id"])
    case_root = RAW_ROOT / case_id
    solver_root = case_root / f"{case_id}_SOLVER_QUAL_DOMAIN_STAGE_001"
    receipt_path = solver_root / "execution-receipt.json"
    receipt = read_json(receipt_path)
    command = receipt.get("request", {}).get("command", [])
    if len(command) < 2:
        raise ValueError(f"solver request command missing: {receipt_path}")
    prefix = Path(str(command[1])).resolve()
    paths = {
        "case_root": case_root,
        "solver_root": solver_root,
        "solver_receipt": receipt_path,
        "data": solver_root / "solver_output/data",
        "runparts": solver_root / "solver_output/RunPARTs.csv",
        "runcsv": solver_root / "solver_output/Run.csv",
        "runout": solver_root / "solver_output/Run.out",
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
        "bound_vtk": prefix.with_name(prefix.name + "_Bound.vtk"),
        "fluid_vtk": prefix.with_name(prefix.name + "_Fluid.vtk"),
        "all_vtk": prefix.with_name(prefix.name + "_All.vtk"),
        "mkcells_vtk": prefix.with_name(prefix.name + "_MkCells.vtk"),
        "dp_vtk": prefix.with_name(prefix.name + "__Dp.vtk"),
        # Repair002 solver output is stored under the repair case, while its
        # unchanged GenCase mother remains under the original DP020 case root.
        "gencase_receipt": RAW_ROOT / str(row["gencase_case_id"]) / f"{row['gencase_case_id']}_GENCASE_001/execution-receipt.json",
        "original_xml": RAW_ROOT / str(row["gencase_case_id"]) / f"{row['gencase_case_id']}_GENCASE_001/{row['gencase_case_id']}.xml",
        "original_bi4": RAW_ROOT / str(row["gencase_case_id"]) / f"{row['gencase_case_id']}_GENCASE_001/{row['gencase_case_id']}.bi4",
    }
    required = ("solver_receipt", "data", "runparts", "runcsv", "runout", "xml", "bi4", "gencase_receipt", "original_xml", "original_bi4")
    missing = [str(paths[name]) for name in required if not paths[name].exists()]
    if missing:
        raise FileNotFoundError(f"{case_id}: {missing}")
    return paths


def parse_xml_contract(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    particles = root.find("./execution/particles")
    constants = root.find("./execution/constants")
    source_floating = root.find("./casedef/floatings/floating")
    if particles is None or constants is None or source_floating is None:
        raise ValueError(f"incomplete generated XML: {xml_path}")

    def f(node: ET.Element | None, key: str) -> float:
        if node is None or node.get(key) is None:
            raise ValueError(f"missing {key} in {xml_path}")
        return float(node.get(key, "nan"))

    groups = {}
    for role in ("fixed", "moving", "floating", "fluid"):
        node = particles.find(role)
        if node is not None:
            groups[role] = {"begin": int(node.get("begin", 0)), "count": int(node.get("count", 0)), "mk": int(node.get("mk", 0))}
    massbody = f(source_floating.find("massbody"), "value")
    center_node = source_floating.find("center")
    inertia_node = source_floating.find("inertia")
    center = [f(center_node, axis) for axis in "xyz"]
    inertia = [f(inertia_node, axis) for axis in "xyz"]
    dp_node = constants.find("dp")
    dp = f(dp_node, "value")
    data2d = root.find("./execution/parameters/data2d")
    data2d_value = None if data2d is None else data2d.get("value", "false").lower() == "true"
    return {
        "total_particles": int(particles.get("np", 0)),
        "fixed_particles": int(particles.get("nbf", 0)),
        "groups": groups,
        "fluid_particles": groups.get("fluid", {}).get("count", 0),
        "moving_particles": groups.get("moving", {}).get("count", 0),
        "floating_particles": groups.get("floating", {}).get("count", 0),
        "dp_m": dp,
        "massfluid_kg": f(constants.find("massfluid"), "value"),
        "massbody_kg": massbody,
        "center_m": center,
        "inertia_diag_kg_m2": inertia,
        "data2d": data2d_value,
    }


def native_tree_manifest(data_root: Path, case_id: str) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in sorted(p for p in data_root.rglob("*") if p.is_file()):
        entries.append({"path": path.relative_to(data_root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    frame_indices = []
    for entry in entries:
        rel = Path(entry["path"])
        match = re.fullmatch(r"Part_(\d{4,})\.bi4", rel.name)
        if match and rel.parent == Path("."):
            frame_indices.append(int(match.group(1)))
    compact = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema": "ds-data-02.f6.native-tree-manifest.v2",
        "case_id": case_id,
        "data_root": str(data_root.resolve()),
        "file_count": len(entries),
        "total_bytes": sum(int(row["bytes"]) for row in entries),
        "files": entries,
        "tree_sha256": hashlib.sha256(compact).hexdigest(),
        "frame_indices": sorted(frame_indices),
        "frame_count": len(frame_indices),
        "frame_contract": {"first": 0, "last": 240, "expected_count": 241},
    }


def runpart_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            if row.get("Part", "").strip().isdigit():
                rows.append(row)
    return rows


def int_field(row: dict[str, str], key: str) -> int:
    return int((row.get(key) or "0").replace(",", ""))


def terminal_audit(key: str, row: dict[str, Any], paths: dict[str, Path], manifest: dict[str, Any]) -> dict[str, Any]:
    receipt = read_json(paths["solver_receipt"])
    xml = parse_xml_contract(paths["xml"])
    parts = runpart_rows(paths["runparts"])
    nonzero = []
    for item in parts:
        values = {field: int_field(item, field) for field in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
        if any(values.values()):
            nonzero.append({"part": int(item["Part"]), "time_s": float(item["TimeStep [s]"]), **values})
    sums = {field: sum(int_field(item, field) for item in parts) for field in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
    run_line = paths["runcsv"].read_text(encoding="utf-8").splitlines()[-1].split(";")
    run_header = next(line for line in paths["runcsv"].read_text(encoding="utf-8").splitlines() if line.startswith("#RunName;"))[1:].split(";")
    run = dict(zip(run_header, run_line))
    status_pass = receipt.get("status") == "completed" and int(receipt.get("returncode", -1)) == 0
    frame_pass = manifest["frame_count"] == 241 and manifest["frame_indices"] == list(range(241)) and len(parts) == 241
    time_pass = float(run.get("PhysicalTime", 0)) >= 11.99 and float(parts[-1]["TimeStep [s]"]) >= 11.99
    contract_pass = (
        xml["fluid_particles"] == 640000
        and abs(xml["massfluid_kg"] * xml["fluid_particles"] - 5120.0) < 1e-6
        and abs(xml["massbody_kg"] - 128.0) < 1e-9
        and all(abs(a - b) < 1e-8 for a, b in zip(xml["center_m"], [2.4, 1.2, 1.08]))
        and all(abs(a - b) < 1e-8 for a, b in zip(xml["inertia_diag_kg_m2"], [8.53333333333, 8.53333333333, 13.6533333333]))
        and xml["data2d"] is not True
    )
    return {
        "schema": "ds-data-02.f6.dp020.repair002.terminal-audit.v1",
        "case_id": row["case_id"],
        "mechanism_id": row["mechanism_id"],
        "solver_receipt": {"path": str(paths["solver_receipt"].resolve()), "sha256": sha256(paths["solver_receipt"]), "status": receipt.get("status"), "returncode": receipt.get("returncode"), "gpu_seconds": receipt.get("gpu_seconds")},
        "native_tree_manifest": {"path": str((DP020_MANIFEST_ROOT / f"{key}_native_tree.json").resolve()), "sha256": "filled_after_write"},
        "generated_xml": {"path": str(paths["xml"].resolve()), "sha256": sha256(paths["xml"]), "contract": xml},
        "native_frame_audit": {"frame_count": manifest["frame_count"], "frame_indices": manifest["frame_indices"], "runparts_numeric_rows": len(parts), "first_time_s": float(parts[0]["TimeStep [s]"]), "last_time_s": float(parts[-1]["TimeStep [s]"])},
        "run_summary": {"fields": run, "run_csv_sha256": sha256(paths["runcsv"]), "runparts_sha256": sha256(paths["runparts"]), "runout_sha256": sha256(paths["runout"])},
        "native_exclusion": {"sums": sums, "nonzero_intervals": nonzero, "unknown_position_exclusion_policy": "one NpOutPos particle is retained as an unknown source/trajectory bucket until typed PartVTK/H5 audit; it is not assigned to density, motion, wall loss, or zero mass"},
        "checks": {"terminal_code0": status_pass, "full_12s": time_pass, "241_frames": frame_pass, "frozen_rigid_and_fluid_contract": contract_pass, "no_density_or_motion_exclusions": sums["NpOutRho"] == 0 and sums["NpOutMov"] == 0},
        "qualification_claim": "none; terminal native evidence only",
        "q_n_status": "pending FloatingInfo, ComputeForces, typed H5, labels, exclusion attribution and scientific review",
        "production_claim": "none",
        "manifest_tree_sha256": manifest["tree_sha256"],
    }


def dp020_source_inputs(paths: dict[str, Path], manifest_path: Path, audit_path: Path) -> list[Path]:
    values = [
        SCRIPT, V35, CONVERTER, LABELS, RUNTIME_V2, FLOATING_INFO, COMPUTE_FORCES, PARTVTK,
        SEMANTICS, OLD_DP020_AUDIT, OLD_REPAIR_MANIFEST, DOMAIN_STAGE, paths["solver_receipt"],
        paths["gencase_receipt"], paths["xml"], paths["bi4"], paths["original_xml"], paths["original_bi4"],
        paths["runparts"], paths["runcsv"], paths["runout"], manifest_path, audit_path,
    ]
    return [Path(path).resolve() for path in values if Path(path).is_file()]


def common_post_request(key: str, row: dict[str, Any], paths: dict[str, Path], manifest_path: Path, audit_path: Path, audit: dict[str, Any], inputs: list[Path]) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F6",
        "case_id": row["case_id"],
        "mechanism_id": row["mechanism_id"],
        "resolution_id": "dp020",
        "repair_scope": "F6_HANDOFF_20261002_RIGID003_DP020_FINITE_WALL_REPAIR_002_DOMAIN_STAGE_001",
        "source_solver_attempt": str(paths["solver_root"].resolve()),
        "source_solver_receipt": str(paths["solver_receipt"].resolve()),
        "source_solver_receipt_sha256": sha256(paths["solver_receipt"]),
        "source_native_tree_manifest": str(manifest_path.resolve()),
        "source_native_tree_manifest_sha256": sha256(manifest_path),
        "source_terminal_audit": str(audit_path.resolve()),
        "source_terminal_audit_sha256": sha256(audit_path),
        "source_solver_status": {"status": audit["solver_receipt"]["status"], "returncode": audit["solver_receipt"]["returncode"]},
        "input_files": [str(path) for path in inputs],
        "input_hashes_at_request": _hash_entries(inputs),
        "cwd": str(INTEGRATION_LAB.resolve()),
        "worktree_root": str(REPO_ROOT.resolve()),
        "runtime_v2": str(RUNTIME_V2.resolve()),
        "gpu_launch": False,
        "solver_launch_forbidden": True,
        "complete_event_window_s": [0.0, 12.0],
        "native_frame_contract": {"expected_count": 241, "save_interval_s": 0.05, "frame_indices": [0, 240]},
        "rigid_contract": {"floating_type": 2, "floating_mk": 60, "aggregate_massbody_kg": 128.0, "center_m": [2.4, 1.2, 1.08], "inertia_diag_kg_m2": [8.53333333333, 8.53333333333, 13.6533333333], "type2_particle_mass_is_separate_from_aggregate_massbody": True},
        "native_exclusion_contract": audit["native_exclusion"],
        "torque_semantics": {"floating_info": "native fluidForceAng is current COM at the force accumulation step and is retained without reframe", "compute_forces": "separate fixed world reference point (2.4,1.2,1.08) and separate saved force-computation phase", "time_alignment": "FloatingInfo is saved after the solver step; exact force accumulation instant can differ by the integration step"},
        "qualification_claim": "none; postprocessing evidence only",
        "q_n_status": "pending native postprocessing and independent scientific review",
        "production_claim": "none",
    }


def write_request(path: Path, request: dict[str, Any]) -> dict[str, Any]:
    write_immutable(path, request)
    return {"path": str(path.resolve()), "sha256": sha256(path), "attempt_id": request["attempt_id"], "kind": request["cpu_task_kind"]}


def prepare_dp020() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for key, row in DP020_CASES.items():
        paths = dp020_paths(row)
        manifest = native_tree_manifest(paths["data"], row["case_id"])
        manifest_path = DP020_MANIFEST_ROOT / f"{key}_native_tree.json"
        write_immutable(manifest_path, manifest)
        audit_path = DP020_POST_ROOT / "terminal_audits" / f"{key}_terminal_audit_001.json"
        audit = terminal_audit(key, row, paths, manifest)
        audit["native_tree_manifest"] = {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)}
        write_immutable(audit_path, audit)
        inputs = dp020_source_inputs(paths, manifest_path, audit_path)
        common = common_post_request(key, row, paths, manifest_path, audit_path, audit, inputs)
        h5_bytes = int(manifest["total_bytes"] * 1.45 + 2**30)
        h5_attempt = f"{row['case_id']}_NATIVE_H5_REPAIR002_001"
        requests = {
            "floatinginfo": {
                **common,
                "attempt_id": f"{row['case_id']}_FLOATINGINFO_REPAIR002_001",
                "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2, "max_wall_seconds": 900, "estimated_storage_bytes": 2**30,
                "command": [str(INTEGRATION_PYTHON), str(V35), "run-floating-info", "--data-dir", str(paths["data"].resolve()), "--manifest", str(manifest_path.resolve()), "--output-prefix", "{attempt_root}/floating/FloatingInfo"],
                "generated_xml": str(paths["xml"].resolve()),
                "purpose": "official FloatingInfo full pose/orientation/quaternion/linear-angular velocity and native force/torque audit for terminal DP020 repair002 trajectory",
                "required_outputs": ["FloatingInfo_Actual.csv", "FloatingInfo_Motion.csv"],
                "required_state_fields": ["pose", "orientation", "quaternion", "linear_velocity", "angular_velocity", "massbody", "inertia", "fluid_force", "fluid_torque"],
                "source_semantics_file": str(SEMANTICS.resolve()),
            },
            "computeforces": {
                **common,
                "attempt_id": f"{row['case_id']}_COMPUTEFORCES_REPAIR002_001",
                "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2, "max_wall_seconds": 900, "estimated_storage_bytes": 2**30,
                "command": [str(INTEGRATION_PYTHON), str(V35), "run-compute-forces", "--data-dir", str(paths["data"].resolve()), "--manifest", str(manifest_path.resolve()), "--generated-xml", str(paths["xml"].resolve()), "--output-prefix", "{attempt_root}/forces/FloatingForce"],
                "generated_xml": str(paths["xml"].resolve()),
                "purpose": "official ComputeForces force/torque audit with fixed initial aggregate center, kept separate from native FloatingInfo current-COM torque",
                "required_outputs": ["FloatingForce.csv"],
                "required_state_fields": ["force", "torque", "massbody", "inertia"],
                "moment_reference": {"frame": "world", "point_m": [2.4, 1.2, 1.08], "point_semantics": "fixed initial aggregate center; raw torque is not relabeled current-COM"},
            },
            "native_h5": {
                **common,
                "attempt_id": h5_attempt,
                "kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 4, "max_wall_seconds": 7200, "estimated_storage_bytes": h5_bytes,
                "command": [str(INTEGRATION_PYTHON), str(SCRIPT), "run-native-conversion", "--case-id", str(row["case_id"]), "--data-dir", str(paths["data"].resolve()), "--generated-xml", str(paths["xml"].resolve()), "--manifest", str(manifest_path.resolve()), "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json"],
                "purpose": "full native BI4-to-HDF5 conversion with typed identity and complete rigid state metadata",
                "required_outputs": ["trajectory.h5", "conversion-report.json"],
                "required_rigid_state_fields": ["pose", "orientation", "quaternion", "linear_velocity", "angular_velocity", "massbody", "inertia", "force", "torque"],
                "native_exclusion_policy": "preserve one invalid-position particle as unknown and expose valid masks; do not impute or drop it",
                "conversion_concurrency_note": "root submits only when a shared conversion slot is free",
            },
            "labels": {
                **common,
                "attempt_id": f"{row['case_id']}_LABELS_REPAIR002_001",
                "kind": "cpu", "cpu_task_kind": "labels", "cpu_threads": 2, "max_wall_seconds": 1800, "estimated_storage_bytes": 4 * 2**30,
                "command": [str(INTEGRATION_PYTHON), str(LABELS), "--source", str(RAW_ROOT / row["case_id"] / h5_attempt / "trajectory.h5"), "--config", str((INTEGRATION_LAB / "campaigns/ds-data-02/families/F6/labels" / ("simple_free_response_event_config.json" if key == "simple_free_response" else "wave_no_contact_event_config.json")).resolve()), "--output", "{attempt_root}/native-labels.h5"],
                "purpose": "typed fluid/rigid event labels after the new H5 conversion",
                "deferred_until_attempt": h5_attempt,
                "required_label_semantics": ["fluid_type3_only", "fixed_identity", "mass_ledger", "first_passage_interval", "residence_time", "unknown_mass_bucket", "no_model"],
            },
        }
        for suffix, request in requests.items():
            rows.append(write_request(DP020_REQUEST_ROOT / f"{key}_repair002_{suffix}.json", request))
        audit_rows.append({"mechanism_id": key, "audit": str(audit_path.resolve()), "audit_sha256": sha256(audit_path), "native_tree": str(manifest_path.resolve()), "native_tree_sha256": sha256(manifest_path)})
    result = {"schema": "ds-data-02.f6.dp020.repair002.postprocessing.manifest.v1", "family_id": "F6", "scope": str(DP020_POST_ROOT.relative_to(FAMILY_ROOT)), "created_at_utc": datetime.now(timezone.utc).isoformat(), "status": "terminal_audit_and_postprocessing_requests_prepared", "audits": audit_rows, "requests": rows, "gpu_launch": False, "solver_launch": False, "qualification_claim": "none", "q_n_status": "pending CPU postprocessing and scientific review"}
    write_immutable(DP020_REQUEST_ROOT / "request_manifest.json", result)
    return result


def dp0125_paths(row: dict[str, Any]) -> dict[str, Path]:
    cid = str(row["case_id"])
    gen = RAW_ROOT / cid / f"{cid}_GENCASE_001"
    prefix = gen / cid
    names = {
        "case_root": RAW_ROOT / cid,
        "gencase_root": gen,
        "prefix": prefix,
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
        "bound_vtk": prefix.with_name(prefix.name + "_Bound.vtk"),
        "fluid_vtk": prefix.with_name(prefix.name + "_Fluid.vtk"),
        "all_vtk": prefix.with_name(prefix.name + "_All.vtk"),
        "mkcells_vtk": prefix.with_name(prefix.name + "_MkCells.vtk"),
        "dp_vtk": prefix.with_name(prefix.name + "__Dp.vtk"),
        "gencase_receipt": gen / "execution-receipt.json",
    }
    missing = [str(path) for name, path in names.items() if name != "prefix" and not path.exists()]
    if missing:
        raise FileNotFoundError(f"{cid}: {missing}")
    return names


def dp0125_inputs(paths: dict[str, Path], audit_path: Path) -> list[Path]:
    values = [SCRIPT, V35, CONVERTER, RUNTIME_V2, SOLVER, FLOATING_INFO, COMPUTE_FORCES, PARTVTK, FINITE_FACE_AUDIT, FINITE_FACE_HELPER, audit_path, OLD_EQUIV, paths["gencase_receipt"]]
    values.extend(paths[name] for name in ("xml", "bi4", "bound_vtk", "fluid_vtk", "all_vtk", "mkcells_vtk", "dp_vtk"))
    # Wave motion is embedded in the generated XML.  Keep any co-located
    # control/normal/native files in the request provenance when present.
    values.extend(p for p in paths["gencase_root"].iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".json", ".xml", ".bi4", ".vtk"})
    result: list[Path] = []
    seen: set[str] = set()
    for path in values:
        path = Path(path).resolve()
        if path.is_file() and str(path) not in seen:
            seen.add(str(path)); result.append(path)
    return result


def prepare_dp0125() -> dict[str, Any]:
    if not DP0125_AUDIT.is_file():
        raise FileNotFoundError(f"run finite-face audit first: {DP0125_AUDIT}")
    audit = read_json(DP0125_AUDIT)
    if audit.get("all_cases_finite_faces_pass") is not True:
        raise RuntimeError("DP0125 finite-face audit is not a pass")
    rows: list[dict[str, Any]] = []
    for key, row in DP0125_CASES.items():
        paths = dp0125_paths(row)
        source_case_audit = next(item for item in audit["cases"] if item["mechanism_id"] == key)
        inputs = dp0125_inputs(paths, DP0125_AUDIT)
        xml_contract = parse_xml_contract(paths["xml"])
        total = int(row["gencase_particles"]["total"])
        common = {
            "schema": "ds-data-02.runner.request.v1",
            "family_id": "F6", "case_id": row["case_id"], "mechanism_id": key, "resolution_id": "dp0125",
            "repair_scope": "F6_HANDOFF_20261002_RIGID003_DP0125_FINITE_FACE_REFERENCE_001",
            "gencase_receipt": str(paths["gencase_receipt"].resolve()), "gencase_receipt_sha256": sha256(paths["gencase_receipt"]),
            "finite_face_audit": str(DP0125_AUDIT.resolve()), "finite_face_audit_sha256": sha256(DP0125_AUDIT),
            "finite_face_case_result": source_case_audit["finite_face_audit"],
            "input_files": [str(path) for path in inputs], "input_sha256": _hash_entries(inputs),
            "cwd": str(paths["gencase_root"].resolve()), "worktree_root": str(REPO_ROOT.resolve()), "runtime_v2": str(RUNTIME_V2.resolve()),
            "command": [str(SOLVER.resolve()), str(paths["prefix"].resolve()), "{attempt_root}/solver_output", "-tmax:12", "-tout:0.05"],
            "kind": "qualification", "cpu_task_kind": "solver", "solver_dimension_required": 3, "launch_authority": "root only through shared ds_data02_runtime_v2.py", "gpu_launch": True,
            "complete_event_window_s": [0.0, 12.0], "output_interval_s": 0.05, "expected_native_frames": 241,
            "gencase_actual_particles": row["gencase_particles"], "generated_xml_contract": xml_contract,
            "native_initial_mass_contract": {"fluid_particles": 2621440, "fluid_mass_kg": 5120.0, "massbody_kg": 128.0, "center_m": [2.4,1.2,1.08], "inertia_diag_kg_m2": [8.53333333333,8.53333333333,13.6533333333], "type2_particle_mass_is_separate": True},
            "finite_wall_contract": {"physical_low_m": [0.0,0.0,0.0], "physical_high_m": [4.8,2.4,2.4], "finite_faces": ["x_low","x_high","y_low","y_high","z_low"], "top_open": True, "native_face_gate": "pass"},
            "simulationdomain_gate": {"status": "pending_root_domain_review", "reason": "default generated XML domain was not executed in this child task; finite-wall coverage pass does not prove swept-domain coverage", "root_must_check": ["MapRealPos", "all fixed/moving/floating native extents", "wave prescribed motion envelope plus kernel margin"]},
            "rigid_state_required": ["pose", "orientation", "quaternion", "linear_velocity", "angular_velocity", "massbody", "inertia", "force", "torque"],
            "torque_semantics": {"native_floating_info": "current COM at force accumulation step", "compute_forces": "separate fixed world point (2.4,1.2,1.08); never relabel as current-COM torque"},
            "qualification_claim": "none until root domain review, solver completion, native postprocessing and scientific review", "q_n_status": "pending", "production_claim": "none",
        }
        request = {**common, "attempt_id": f"{row['case_id']}_SOLVER_QUAL_DP0125_FINITE_FACE_REFERENCE_001", "max_wall_seconds": row["max_wall_seconds"], "estimated_storage_bytes": row["estimated_storage_bytes"], "purpose": "root-only full 12 s DP0125 reference solver after independent all-five finite-face native audit"}
        rows.append(write_request(DP0125_REQUEST_ROOT / f"{key}_solver.json", request))
    result = {"schema": "ds-data-02.f6.dp0125.finite-face-reference.solver-manifest.v1", "family_id": "F6", "scope": str(DP0125_ROOT.relative_to(FAMILY_ROOT)), "created_at_utc": datetime.now(timezone.utc).isoformat(), "status": "root_ready_pending_domain_review", "finite_face_audit": str(DP0125_AUDIT.resolve()), "finite_face_audit_sha256": sha256(DP0125_AUDIT), "requests": rows, "gpu_launch": False, "solver_launch": False, "qualification_claim": "none", "q_n_status": "pending root dispatch and full native review"}
    write_immutable(DP0125_REQUEST_ROOT / "request_manifest.json", result)
    return result


def verify_tree(manifest_path: Path, data_root: Path) -> None:
    expected = read_json(manifest_path)
    actual = native_tree_manifest(data_root, expected["case_id"])
    if expected.get("tree_sha256") != actual.get("tree_sha256") or expected.get("files") != actual.get("files"):
        raise RuntimeError(f"native source tree changed: {data_root}")


def run_native_conversion(args: argparse.Namespace) -> int:
    data_root = args.data_dir.resolve()
    manifest = args.manifest.resolve()
    verify_tree(manifest, data_root)
    command = [str(INTEGRATION_PYTHON), str(CONVERTER), "--direct-run", "--case-id", args.case_id, "--data-dir", str(data_root), "--generated-xml", str(args.generated_xml.resolve()), "--output", str(args.output.resolve()), "--report", str(args.report.resolve())]
    result = subprocess.run(command, cwd=INTEGRATION_LAB, check=False)
    if result.returncode:
        return result.returncode
    verify_tree(manifest, data_root)
    return 0


def prepare_all() -> dict[str, Any]:
    return {"dp020": prepare_dp020(), "dp0125": prepare_dp0125()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare-dp020", "prepare-dp0125", "prepare-all", "run-native-conversion"])
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.action == "prepare-dp020":
        print(json.dumps(prepare_dp020(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "prepare-dp0125":
        print(json.dumps(prepare_dp0125(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "prepare-all":
        print(json.dumps(prepare_all(), ensure_ascii=False, indent=2))
        return 0
    for required in (args.data_dir, args.generated_xml, args.manifest, args.case_id, args.output):
        if required is None:
            parser.error("run-native-conversion requires --data-dir --generated-xml --manifest --case-id --output")
    if args.report is None:
        args.report = args.output.parent / "conversion-report.json"
    return run_native_conversion(args)


if __name__ == "__main__":
    raise SystemExit(main())
