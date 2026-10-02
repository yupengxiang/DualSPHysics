#!/usr/bin/env python3
"""Prepare and run additive F6 DP025 native post-processing audits.

The solver outputs are already terminal and immutable.  This module creates a
new, source-hash-bound post-processing scope for the simple free-body output
and the wave output produced from the root-owned X-domain repair.  It may run
official FloatingInfo/ComputeForces through the shared CPU runner, and it
prepares deferred HDF5/label requests without launching a solver or GPU.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
FAMILY_ROOT = REPO_ROOT / "campaigns/ds-data-02/families/F6"
HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261002"
SCOPE_ROOT = HANDOFF_ROOT / "rigid_contract_003/dp025_postprocessing_003"
REQUEST_ROOT = SCOPE_ROOT / "execution_requests"
MANIFEST_ROOT = SCOPE_ROOT / "raw_tree_manifests"
RAW_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")
HISTORICAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
OFFICIAL_BIN = HISTORICAL_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux"
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
INTEGRATION_PYTHON = INTEGRATION_LAB / ".venv/bin/python"
RUNTIME_V2 = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
CONVERTER = INTEGRATION_LAB / "scripts/ds_data02_f6_stage8_convert.py"
LABELS = INTEGRATION_LAB / "scripts/ds_data02_native_labels.py"
SIMPLE_LABEL_CONFIG = INTEGRATION_LAB / "campaigns/ds-data-02/families/F6/labels/simple_free_response_event_config.json"
WAVE_LABEL_CONFIG = INTEGRATION_LAB / "campaigns/ds-data-02/families/F6/labels/wave_no_contact_event_config.json"
FLOATING_INFO = OFFICIAL_BIN / "FloatingInfo_linux64"
COMPUTE_FORCES = OFFICIAL_BIN / "ComputeForces_linux64"
PARTVTK = OFFICIAL_BIN / "PartVTK_linux64"

CASES: dict[str, dict[str, Any]] = {
    "simple_free_response": {
        "case_id": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_COMMENSURATE_RIGID003_DP025",
        "mechanism_id": "simple_free_response",
        "solver_attempt": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_COMMENSURATE_RIGID003_DP025_SOLVER_QUAL_DP025_001",
        "gencase_attempt": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_COMMENSURATE_RIGID003_DP025_GENCASE_001",
        "prefix_name": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_COMMENSURATE_RIGID003_DP025",
        "domain_repair": None,
    },
    "wave_no_contact": {
        "case_id": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025",
        "mechanism_id": "wave_no_contact",
        "solver_attempt": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025_SOLVER_QUAL_DP025_DOMAIN_X_REPAIR_001",
        "failed_solver_attempt": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025_SOLVER_QUAL_DP025_001",
        "gencase_attempt": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025_GENCASE_001",
        "prefix_name": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025",
        "domain_repair": "root-domain-x-repair-001",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _raw_case_root(case: dict[str, Any]) -> Path:
    return RAW_ROOT / str(case["case_id"])


def _paths(case: dict[str, Any]) -> dict[str, Path]:
    root = _raw_case_root(case)
    solver_root = root / str(case["solver_attempt"])
    if case.get("domain_repair"):
        native_root = root / str(case["domain_repair"]) / "native_inputs"
        prefix = native_root / str(case["prefix_name"])
    else:
        native_root = root / str(case["gencase_attempt"])
        prefix = native_root / str(case["prefix_name"])
    data = solver_root / "solver_output/data"
    return {
        "case_root": root,
        "solver_root": solver_root,
        "solver_receipt": solver_root / "execution-receipt.json",
        "data": data,
        "runout": solver_root / "solver_output/Run.out",
        "runparts": solver_root / "solver_output/RunPARTs.csv",
        "native_root": native_root,
        "prefix": prefix,
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
    }


def tree_manifest(data_root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(p for p in data_root.rglob("*") if p.is_file()):
        files.append({
            "path": path.relative_to(data_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    frames = sorted(int(m.group(1)) for row in files if (m := re.fullmatch(r"Part_(\d{4,})\.bi4", Path(row["path"]).name)) and Path(row["path"]).parent == Path("."))
    return {
        "schema": "ds-data-02.f6.dp025.native-data-tree-manifest.v1",
        "data_root": str(data_root.resolve()),
        "file_count": len(files),
        "total_bytes": sum(int(row["bytes"]) for row in files),
        "files": files,
        "tree_sha256": hashlib.sha256(payload).hexdigest(),
        "frame_count": len(frames),
        "frame_indices": frames,
    }


def _solver_receipt_inputs(paths: dict[str, Path]) -> list[Path]:
    receipt = read_json(paths["solver_receipt"])
    values = [Path(value) for value in receipt.get("request", {}).get("input_files", [])]
    values.extend([paths["solver_receipt"], paths["xml"], paths["bi4"], RUNTIME_V2, SCRIPT, CONVERTER, LABELS, FLOATING_INFO, COMPUTE_FORCES, PARTVTK])
    result: list[Path] = []
    seen: set[str] = set()
    for path in values:
        path = path.resolve()
        if str(path) not in seen and path.is_file():
            seen.add(str(path))
            result.append(path)
    missing = [str(path.resolve()) for path in values if not path.is_file()]
    if missing:
        raise FileNotFoundError("postprocessing source missing: " + ", ".join(sorted(set(missing))))
    return result


def _extra_source_inputs(key: str, paths: dict[str, Path]) -> list[Path]:
    values = [
        HANDOFF_ROOT / "rigid_contract_003/manifest.json",
        HANDOFF_ROOT / "rigid_contract_003/preflight_001.json",
        HANDOFF_ROOT / "rigid_contract_003/scope.json",
    ]
    if key == "wave_no_contact":
        values.extend([
            INTEGRATION_LAB / "campaigns/ds-data-02/families/F6/handoff_20261002/root_dp025_domain_x_repair_001/equivalence.json",
            INTEGRATION_LAB / "campaigns/ds-data-02/families/F6/handoff_20261002/root_dp025_domain_x_repair_001/wave_solver_request.json",
        ])
    return [path.resolve() for path in values if path.is_file()]


def _input_files(key: str, paths: dict[str, Path], manifest_path: Path) -> list[Path]:
    values = _solver_receipt_inputs(paths) + _extra_source_inputs(key, paths) + [manifest_path]
    result: list[Path] = []
    seen: set[str] = set()
    for path in values:
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.add(resolved)
            result.append(Path(resolved))
    return result


def _request_common(key: str, case: dict[str, Any], paths: dict[str, Path], manifest_path: Path, inputs: list[Path]) -> dict[str, Any]:
    solver_receipt = read_json(paths["solver_receipt"])
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F6",
        "case_id": str(case["case_id"]),
        "mechanism_id": str(case["mechanism_id"]),
        "resolution_id": "dp025",
        "repair_scope": "F6_HANDOFF_20261002_RIGID003_DOMAIN_X_REPAIR_001" if key == "wave_no_contact" else "F6_HANDOFF_20261002_RIGID003_DP025_NATIVE_POSTPROCESSING",
        "source_solver_attempt": str(paths["solver_root"].resolve()),
        "source_solver_receipt": str(paths["solver_receipt"].resolve()),
        "source_solver_receipt_sha256": sha256(paths["solver_receipt"]),
        "source_native_tree_manifest": str(manifest_path.resolve()),
        "source_native_tree_manifest_sha256": sha256(manifest_path),
        "source_solver_status": {"status": solver_receipt.get("status"), "returncode": solver_receipt.get("returncode")},
        "input_files": [str(path) for path in inputs],
        "input_hashes_at_request": {str(path): sha256(path) for path in inputs},
        "cwd": str(REPO_ROOT.resolve()),
        "worktree_root": str(REPO_ROOT.resolve()),
        "runtime_v2": str(RUNTIME_V2),
        "gpu_launch": False,
        "solver_launch_forbidden": True,
        "source_tree_integrity": "v33 verifies every manifest-listed native BI4/header file before and after each official audit; raw solver outputs are immutable",
        "rigid_contract": {
            "floating_type": 2,
            "floating_mk": 60,
            "aggregate_massbody_kg": 128.0,
            "center_m": [2.4, 1.2, 1.08],
            "inertia_diag_kg_m2": [8.533333333333335, 8.533333333333335, 13.653333333333336],
            "type2_particle_mass_is_separate_from_aggregate_massbody": True,
        },
        "complete_event_window_s": [0.0, 12.0],
        "native_frame_contract": {"expected_count": 241, "save_interval_s": 0.05, "frame_indices": [0, 240]},
        "qualification_claim": "none; postprocessing evidence only",
        "q_n_status": "pending native postprocessing and independent scientific review",
        "production_claim": "none",
    }


def _write_request(path: Path, request: dict[str, Any]) -> dict[str, Any]:
    write_json(path, request)
    return {"path": str(path.resolve()), "sha256": sha256(path), "attempt_id": request["attempt_id"], "kind": request["cpu_task_kind"]}


def prepare() -> dict[str, Any]:
    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for key, case in CASES.items():
        paths = _paths(case)
        required = [paths[name] for name in ("solver_receipt", "data", "xml", "bi4")]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError(f"{key} source missing: {', '.join(missing)}")
        manifest = tree_manifest(paths["data"])
        manifest["case_id"] = case["case_id"]
        manifest["mechanism_id"] = key
        manifest["solver_attempt"] = case["solver_attempt"]
        manifest["generated_xml_sha256"] = sha256(paths["xml"])
        manifest["generated_bi4_sha256"] = sha256(paths["bi4"])
        manifest_path = MANIFEST_ROOT / f"{key}_dp025.json"
        write_json(manifest_path, manifest)
        inputs = _input_files(key, paths, manifest_path)
        common = _request_common(key, case, paths, manifest_path, inputs)
        floating = {
            **common,
            "attempt_id": f"{case['case_id']}_FLOATINGINFO_002",
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 2,
            "max_wall_seconds": 600,
            "estimated_storage_bytes": 536870912,
            "command": [str(INTEGRATION_PYTHON), str(SCRIPT), "run-floating-info", "--data-dir", str(paths["data"].resolve()), "--manifest", str(manifest_path.resolve()), "--output-prefix", "{attempt_root}/floating/FloatingInfo"],
            "generated_xml": str(paths["xml"].resolve()),
            "purpose": "official FloatingInfo full rigid pose/orientation/linear-angular velocity audit for actual dp025 native trajectory",
            "required_outputs": ["FloatingInfo_Actual.csv", "FloatingInfo_Motion.csv"],
            "required_state_fields": ["pose", "orientation", "linear_velocity", "angular_velocity", "massbody", "inertia"],
            "torque_semantics": "FloatingInfo native fluidForceAng is retained with its solver current-COM origin; no ComputeForces reframe is applied",
        }
        forces = {
            **common,
            "attempt_id": f"{case['case_id']}_COMPUTEFORCES_002",
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 2,
            "max_wall_seconds": 600,
            "estimated_storage_bytes": 536870912,
            "command": [str(INTEGRATION_PYTHON), str(SCRIPT), "run-compute-forces", "--data-dir", str(paths["data"].resolve()), "--manifest", str(manifest_path.resolve()), "--generated-xml", str(paths["xml"].resolve()), "--output-prefix", "{attempt_root}/forces/FloatingForce"],
            "generated_xml": str(paths["xml"].resolve()),
            "purpose": "official ComputeForces force/torque audit for actual dp025 native trajectory",
            "required_outputs": ["FloatingForce.csv"],
            "required_state_fields": ["force", "torque", "massbody", "inertia"],
            "moment_reference": {"frame": "world", "point_m": [2.4, 1.2, 1.08], "point_semantics": "frozen initial aggregate center used by the official ComputeForces request; raw field is never relabeled current-COM"},
        }
        conversion_attempt = f"{case['case_id']}_NATIVE_H5_003"
        conversion = {
            **common,
            "attempt_id": conversion_attempt,
            "kind": "cpu",
            "cpu_task_kind": "conversion",
            "cpu_threads": 4,
            "max_wall_seconds": 3600,
            "estimated_storage_bytes": 12884901888,
            "command": [str(INTEGRATION_PYTHON), str(SCRIPT), "run-native-conversion", "--case-id", str(case["case_id"]), "--data-dir", str(paths["data"].resolve()), "--generated-xml", str(paths["xml"].resolve()), "--manifest", str(manifest_path.resolve()), "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json"],
            "purpose": "deferred full native BI4-to-HDF5 conversion with fixed typed identity and enriched rigid metadata",
            "required_outputs": ["trajectory.h5", "conversion-report.json"],
            "required_rigid_state_fields": ["pose", "orientation", "quaternion", "linear_velocity", "angular_velocity", "massbody", "inertia", "force", "torque"],
            "conversion_concurrency_note": "prepared only; submit after shared conversion slot is free",
        }
        config = SIMPLE_LABEL_CONFIG if key == "simple_free_response" else WAVE_LABEL_CONFIG
        h5_path = RAW_ROOT / str(case["case_id"]) / conversion_attempt / "trajectory.h5"
        labels = {
            **common,
            "attempt_id": f"{case['case_id']}_LABELS_003",
            "kind": "cpu",
            "cpu_task_kind": "labels",
            "cpu_threads": 2,
            "max_wall_seconds": 1200,
            "estimated_storage_bytes": 2147483648,
            "command": [str(INTEGRATION_PYTHON), str(SCRIPT), "run-labels", "--source", str(h5_path), "--config", str(config.resolve()), "--output", "{attempt_root}/native-labels.h5"],
            "purpose": "deferred fixed-identity fluid/rigid event labels after the new HDF5 exists",
            "source_trajectory": str(h5_path),
            "source_trajectory_sha256": "deferred_until_native_h5_receipt",
            "deferred_until_attempt": conversion_attempt,
            "required_label_semantics": ["fluid_type3_only", "fixed_identity", "mass_ledger", "first_passage_interval", "residence_time", "unknown_mass_bucket", "no_model"],
        }
        for suffix, request in (("floatinginfo", floating), ("computeforces", forces), ("native_h5", conversion), ("labels", labels)):
            rows.append(_write_request(REQUEST_ROOT / f"{key}_dp025_{suffix}.json", request))
    result = {
        "schema": "ds-data-02.f6.rigid003.dp025_postprocessing_003.manifest.v1",
        "family_id": "F6",
        "scope": "F6_HANDOFF_20261002_RIGID003_DP025_POSTPROCESSING_002",
        "created_at_utc": "2026-10-02T12:30:00+00:00",
        "status": "prepared_floatinginfo_computeforces_ready_conversion_deferred",
        "requests": rows,
        "gpu_launch": False,
        "solver_launch": False,
        "q_n_status": "pending actual postprocessing and scientific review; v33 converter invocation excludes unsupported manifest flag after wrapper verification",
        "production_claim": "none",
    }
    write_json(REQUEST_ROOT / "request_manifest.json", result)
    return result


def verify_tree(manifest_path: Path, data_root: Path) -> None:
    expected = read_json(manifest_path)
    actual = tree_manifest(data_root)
    if expected.get("tree_sha256") != actual.get("tree_sha256") or expected.get("files") != actual.get("files"):
        raise RuntimeError(f"native source tree changed since manifest: {data_root}")


def run_official(binary: Path, data_root: Path, manifest_path: Path, output_prefix: Path, args: list[str]) -> int:
    verify_tree(manifest_path, data_root)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [str(binary), "-dirdata", str(data_root)]
    command.extend(str(output_prefix) if arg == "{output}" else arg for arg in args)
    result = subprocess.run(command, cwd=output_prefix.parent, check=False)
    if result.returncode:
        return result.returncode
    verify_tree(manifest_path, data_root)
    return 0


def run_conversion(args: argparse.Namespace) -> int:
    data_root = args.data_dir.resolve()
    manifest = args.manifest.resolve()
    verify_tree(manifest, data_root)
    command = [str(INTEGRATION_PYTHON), str(CONVERTER), "--direct-run", "--case-id", args.case_id, "--data-dir", str(data_root), "--generated-xml", str(args.generated_xml.resolve()), "--output", str(args.output.resolve()), "--report", str(args.report.resolve())]
    result = subprocess.run(command, cwd=INTEGRATION_LAB, check=False)
    if result.returncode:
        return result.returncode
    verify_tree(manifest, data_root)
    return 0


def run_labels(args: argparse.Namespace) -> int:
    command = [str(INTEGRATION_PYTHON), str(LABELS), "--source", str(args.source.resolve()), "--config", str(args.config.resolve()), "--output", str(args.output.resolve())]
    return subprocess.run(command, cwd=INTEGRATION_LAB, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run-floating-info", "run-compute-forces", "run-native-conversion", "run-labels"])
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        print(json.dumps(prepare(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "run-floating-info":
        return run_official(FLOATING_INFO, args.data_dir.resolve(), args.manifest.resolve(), args.output_prefix.resolve(), ["-onlymk:60", "-savedata", "{output}", "-savemotion:1", "-csvsep:0"])
    if args.action == "run-compute-forces":
        return run_official(COMPUTE_FORCES, args.data_dir.resolve(), args.manifest.resolve(), args.output_prefix.resolve(), ["-filexml", str(args.generated_xml.resolve()), "-onlymk:60", "-viscoauto", "-gravity:0:0:-9.81", "-momentin_xyz:2.4:1.2:1.08", "-momentex_xyz:2.4:1.2:1.08", "-savecsv", "{output}", "-threads:2", "-csvsep:0"])
    if args.action == "run-native-conversion":
        return run_conversion(args)
    return run_labels(args)


if __name__ == "__main__":
    raise SystemExit(main())
