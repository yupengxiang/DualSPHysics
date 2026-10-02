#!/usr/bin/env python3
"""Register and audit bounded PartVTKOut diagnostics for F6 repair002.

PartVTKOut reads only the terminal solver ``PartOut_000.obi4`` exclusion
stream.  The requests below are CPU-only, one-thread audits; they never rerun
GenCase or a solver and never alter the native repair002 trees.  The follow-up
``audit`` action records the actual typed CSV/resume rows while preserving the
unknown-position bucket until a full native H5/PartVTK lifecycle review.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
FAMILY_ROOT = REPO_ROOT / "campaigns/ds-data-02/families/F6"
HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261002/rigid_contract_003"
RAW_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")
HISTORICAL_LAB = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
PARTVTKOUT = HISTORICAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
SCOPE = HANDOFF_ROOT / "dp020_repair_002_partvtkout_001"
REQUEST_ROOT = SCOPE / "requests"
AUDIT_ROOT = SCOPE / "audits"

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


def paths_for(row: dict[str, str]) -> dict[str, Path]:
    case_id = row["case_id"]
    case_root = RAW_ROOT / case_id
    solver_root = case_root / f"{case_id}_SOLVER_QUAL_DOMAIN_STAGE_001"
    receipt = solver_root / "execution-receipt.json"
    request = read_json(receipt).get("request", {})
    command = request.get("command", [])
    if len(command) < 2:
        raise ValueError(f"terminal solver command missing: {receipt}")
    prefix = Path(str(command[1])).resolve()
    data = solver_root / "solver_output/data"
    paths = {
        "case_root": case_root,
        "solver_root": solver_root,
        "solver_receipt": receipt,
        "data": data,
        "partout": data / "PartOut_000.obi4",
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
        "runparts": solver_root / "solver_output/RunPARTs.csv",
        "runcsv": solver_root / "solver_output/Run.csv",
        "runout": solver_root / "solver_output/Run.out",
        "terminal_audit": HANDOFF_ROOT / "dp020_repair_002_postprocessing_001/terminal_audits" / f"{row['mechanism_id']}_terminal_audit_001.json",
        "native_manifest": HANDOFF_ROOT / "dp020_repair_002_postprocessing_001/native_tree_manifests" / f"{row['mechanism_id']}_native_tree.json",
        "finite_audit": HANDOFF_ROOT / "dp0125_finite_face_reference_001/finite_face_audit_001.json",
        "repair_manifest": HANDOFF_ROOT / "dp020_dp0125_cpu_003/finite_wall_discretization_repair_002/repair_manifest_002.json",
        "native_audit": HANDOFF_ROOT / "dp020_dp0125_cpu_003/finite_wall_discretization_repair_002/native_audit_001.json",
        "domain_stage": HANDOFF_ROOT / "dp020_dp0125_cpu_003/finite_wall_discretization_repair_002/solver_domain_stage_001.json",
    }
    required = ("solver_receipt", "partout", "xml", "bi4", "runparts", "runcsv", "runout", "terminal_audit", "native_manifest", "repair_manifest", "native_audit", "domain_stage")
    missing = [str(paths[name]) for name in required if not paths[name].is_file()]
    if missing:
        raise FileNotFoundError(f"{case_id}: {missing}")
    return paths


def source_inputs(paths: dict[str, Path]) -> list[Path]:
    values = [SCRIPT, RUNTIME_V2, PARTVTKOUT]
    values.extend(paths[name] for name in ("solver_receipt", "partout", "xml", "bi4", "runparts", "runcsv", "runout", "terminal_audit", "native_manifest", "finite_audit", "repair_manifest", "native_audit", "domain_stage"))
    result: list[Path] = []
    seen: set[str] = set()
    for path in values:
        path = path.resolve()
        if not path.is_file() or str(path) in seen:
            continue
        seen.add(str(path)); result.append(path)
    return result


def prepare() -> dict[str, Any]:
    rows = []
    for key, row in CASES.items():
        paths = paths_for(row)
        inputs = source_inputs(paths)
        attempt = f"{row['case_id']}_PARTVTKOUT_UNKNOWN_POSITION_001"
        request = {
            "schema": "ds-data-02.runner.request.v1",
            "family_id": "F6",
            "case_id": row["case_id"],
            "mechanism_id": row["mechanism_id"],
            "attempt_id": attempt,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 1,
            "max_wall_seconds": 600,
            "estimated_storage_bytes": 64 * 2**20,
            "command": [
                str(PARTVTKOUT.resolve()),
                "-dirdata", str(paths["data"].resolve()),
                "-filexml", str(paths["xml"].resolve()),
                "-first:0", "-last:0",
                "-savevtk", "{attempt_root}/excluded.vtk",
                "-savecsv", "{attempt_root}/excluded.csv",
                "-saveresume", "{attempt_root}/excluded-resume.csv",
                "-createdirs:1", "-csvsep:1",
            ],
            "cwd": str(INTEGRATION_LAB.resolve()),
            "worktree_root": str(REPO_ROOT.resolve()),
            "runtime_v2": str(RUNTIME_V2.resolve()),
            "input_files": [str(path) for path in inputs],
            "input_hashes_at_request": {str(path): sha256(path) for path in inputs},
            "source_solver_receipt": str(paths["solver_receipt"].resolve()),
            "source_solver_receipt_sha256": sha256(paths["solver_receipt"]),
            "source_partout": str(paths["partout"].resolve()),
            "source_partout_sha256": sha256(paths["partout"]),
            "source_terminal_audit": str(paths["terminal_audit"].resolve()),
            "source_terminal_audit_sha256": sha256(paths["terminal_audit"]),
            "native_exclusion_contract": {
                "expected_npout": 1,
                "expected_npoutpos": 1,
                "expected_npoutrho": 0,
                "expected_npoutmov": 0,
                "unknown_position_policy": "retain row and typed ID/position/rho/velocity evidence; do not assign wall, density, motion, or zero mass before full lifecycle audit",
            },
            "purpose": "bounded official PartVTKOut typed audit of the single terminal repair002 NpOutPos exclusion",
            "required_outputs": ["excluded.csv", "excluded-resume.csv", "excluded.vtk", "execution-receipt.json"],
            "gpu_launch": False,
            "solver_launch_forbidden": True,
            "qualification_claim": "none; exclusion attribution evidence only",
            "q_n_status": "pending complete native H5 and independent review",
            "production_claim": "none",
        }
        path = REQUEST_ROOT / f"{key}_partvtkout.json"
        write_immutable(path, request)
        rows.append({"path": str(path.resolve()), "sha256": sha256(path), "attempt_id": attempt, "mechanism_id": key})
    result = {
        "schema": "ds-data-02.f6.dp020.repair002.partvtkout.manifest.v1",
        "family_id": "F6",
        "scope": str(SCOPE.relative_to(FAMILY_ROOT)),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "requests": rows,
        "gpu_launch": False,
        "solver_launch": False,
        "qualification_claim": "none",
        "q_n_status": "pending actual bounded CPU diagnostics",
    }
    write_immutable(REQUEST_ROOT / "request_manifest.json", result)
    return result


def _csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        return [], []
    with path.open(newline="", encoding="utf-8", errors="replace") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def audit() -> dict[str, Any]:
    results = []
    for key, row in CASES.items():
        attempt = f"{row['case_id']}_PARTVTKOUT_UNKNOWN_POSITION_001"
        output = RAW_ROOT / row["case_id"] / attempt
        receipt_path = output / "execution-receipt.json"
        if not receipt_path.is_file():
            raise FileNotFoundError(receipt_path)
        receipt = read_json(receipt_path)
        csv_path = output / "excluded.csv"
        resume_path = output / "excluded-resume.csv"
        vtk_path = output / "excluded.vtk"
        fields, rows = _csv_rows(csv_path)
        resume_fields, resume_rows = _csv_rows(resume_path)
        typed_keys = [name for name in fields if any(token in name.lower() for token in ("idp", "type", "mk", "pos", "rhop", "vel"))]
        typed_rows = [{key: item.get(key) for key in typed_keys} for item in rows]
        result = {
            "schema": "ds-data-02.f6.dp020.repair002.partvtkout-audit.v1",
            "family_id": "F6",
            "mechanism_id": key,
            "case_id": row["case_id"],
            "attempt_id": attempt,
            "execution_receipt": {"path": str(receipt_path.resolve()), "sha256": sha256(receipt_path), "status": receipt.get("status"), "returncode": receipt.get("returncode"), "bytes": receipt.get("bytes")},
            "outputs": {"csv": {"path": str(csv_path.resolve()), "sha256": sha256(csv_path) if csv_path.is_file() else None, "fields": fields, "rows": len(rows), "typed_rows": typed_rows}, "resume": {"path": str(resume_path.resolve()), "sha256": sha256(resume_path) if resume_path.is_file() else None, "fields": resume_fields, "rows": len(resume_rows)}, "vtk": {"path": str(vtk_path.resolve()), "sha256": sha256(vtk_path) if vtk_path.is_file() else None, "bytes": vtk_path.stat().st_size if vtk_path.is_file() else None}},
            "unknown_position_policy": "the typed row remains an unknown native exclusion until its Idp/position/rho/velocity is reconciled with the full native H5 lifecycle; no physical destination is inferred from this diagnostic alone",
            "qualification_claim": "none",
            "q_n_status": "pending H5/PartVTK lifecycle reconciliation",
        }
        path = AUDIT_ROOT / f"{key}_partvtkout_audit_001.json"
        write_immutable(path, result)
        results.append({"path": str(path.resolve()), "sha256": sha256(path), "mechanism_id": key, "rows": len(rows), "status": receipt.get("status")})
    manifest = {"schema": "ds-data-02.f6.dp020.repair002.partvtkout-audit-manifest.v1", "family_id": "F6", "created_at_utc": datetime.now(timezone.utc).isoformat(), "audits": results, "qualification_claim": "none", "q_n_status": "pending H5 review"}
    write_immutable(AUDIT_ROOT / "audit_manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "audit"])
    args = parser.parse_args()
    result = prepare() if args.action == "prepare" else audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
