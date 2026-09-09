#!/usr/bin/env python3
"""Inventory and execute the untouched same-version official mDBC controls.

Q1 is deliberately separate from the L1 candidate campaign.  The source XML
and vendor binaries are read and hashed in place; GenCase writes resolved
products into the ignored ``campaigns/l1-resume/artifacts`` tree, and the
official solver writes immutable attempts into the ignored resume run tree.
The compact manifest under ``campaigns/l1-resume/q1`` is the reviewable
record.  Only the official 3-D dam-break control is selected by default for a
GPU run; the two small StillWedge cases are static/CPU diagnostics that can
be requested explicitly.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Sequence
import xml.etree.ElementTree as ET

try:
    from scripts import l1_f1_qualification as l1
    from scripts.campaign_runner import execute_attempt
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import l1_f1_qualification as l1
    from campaign_runner import execute_attempt


LAB = Path(__file__).resolve().parents[1]
OFFICIAL_ROOT = LAB / "vendor" / "official" / "DualSPHysics_v5.4"
EXAMPLES_ROOT = OFFICIAL_ROOT / "examples" / "mdbc"
BIN = OFFICIAL_ROOT / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER_GPU = BIN / "DualSPHysics5.4_linux64"
SOLVER_CPU = BIN / "DualSPHysics5.4CPU_linux64"
MANIFEST_ROOT = LAB / "campaigns" / "l1-resume" / "q1"
REPORT = MANIFEST_ROOT / "Q1-OFFICIAL-RESULTS.json"
RAW_ROOT = LAB / "campaigns" / "l1-resume" / "artifacts" / "q1-official"
RUN_ROOT = LAB / "campaigns" / "l1-resume" / "runs" / "q1-official"
INVENTORY = l1.CAMPAIGN / "L1-W00-INVENTORY.json"

GPU_IDS = (4, 5, 6, 7)
PROTECTED_GPU_IDS = (0, 1, 2, 3)
LAUNCH_MIN_FREE_MIB = 6144
ABORT_MIN_FREE_MIB = 4096
SOLVER_TIMEOUT_S = 7200
MAX_CPU_PROBES = 2

CASE_SPECS: dict[str, dict[str, Any]] = {
    "official_dambreak3d_mdbc": {
        "source": EXAMPLES_ROOT / "04_Dambreak" / "CaseDamBreak3D_Def.xml",
        "gpu_shell": EXAMPLES_ROOT / "04_Dambreak" / "xCaseDamBreak3D_mDBC_linux64_GPU.sh",
        "cpu_shell": EXAMPLES_ROOT / "04_Dambreak" / "xCaseDamBreak3D_mDBC_linux64_CPU.sh",
        "prefix_name": "CaseDamBreak3D",
        "label": "official same-version 3-D mDBC dam-break raw positive control",
        "default_gpu": True,
    },
    "official_stillwedge_lr_mdbc": {
        "source": EXAMPLES_ROOT / "01_StillWedge" / "CaseStillWedgeLR_Def.xml",
        "gpu_shell": EXAMPLES_ROOT / "01_StillWedge" / "xCaseStillWedgeLR_mDBC_linux64_GPU.sh",
        "cpu_shell": EXAMPLES_ROOT / "01_StillWedge" / "xCaseStillWedgeLR_mDBC_linux64_CPU.sh",
        "prefix_name": "CaseStillWedgeLR",
        "label": "official same-version 2-D mDBC StillWedge low-resolution diagnostic",
        "default_gpu": False,
    },
    "official_stillwedge_hr_mdbc": {
        "source": EXAMPLES_ROOT / "01_StillWedge" / "CaseStillWedgeHR_Def.xml",
        "gpu_shell": EXAMPLES_ROOT / "01_StillWedge" / "xCaseStillWedgeHR_mDBC_linux64_GPU.sh",
        "cpu_shell": EXAMPLES_ROOT / "01_StillWedge" / "xCaseStillWedgeHR_mDBC_linux64_CPU.sh",
        "prefix_name": "CaseStillWedgeHR",
        "label": "official same-version 2-D mDBC StillWedge high-resolution diagnostic",
        "default_gpu": False,
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(LAB.resolve()))
    except ValueError:
        return str(path.resolve())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": relpath(path),
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else None,
        "sha256": sha256(path) if path.is_file() else None,
    }
    return result


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def environment(*, cpu: bool = False) -> dict[str, str]:
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN}:{value.get('LD_LIBRARY_PATH', '')}"
    value["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    if cpu:
        value["CUDA_VISIBLE_DEVICES"] = ""
        value["NVIDIA_VISIBLE_DEVICES"] = "void"
    return value


def _read_inventory_uuids() -> list[str]:
    if not INVENTORY.is_file():
        raise RuntimeError(f"L1 GPU inventory is missing: {INVENTORY}")
    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    policy = payload.get("execution_policy") or payload.get("gpu_policy")
    if not policy or "allowed_gpu_uuids" not in policy:
        raise RuntimeError(f"GPU allowlist is missing from {INVENTORY}")
    return list(policy["allowed_gpu_uuids"])


def gpu_snapshot() -> list[dict[str, Any]]:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,uuid,memory.used,memory.total,memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
        cwd=LAB, check=True, text=True, stdout=subprocess.PIPE,
    ).stdout
    rows = []
    for line in output.splitlines():
        index, uuid, used, total, free, utilization = [item.strip() for item in line.split(",")]
        rows.append({
            "index": int(index), "uuid": uuid, "memory_used_mib": int(used),
            "memory_total_mib": int(total), "memory_free_mib": int(free),
            "utilization_percent": int(utilization),
        })
    return rows


def _xml_summary(source: Path) -> dict[str, Any]:
    tree = ET.parse(source)
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    parameters = {
        node.get("key"): node.get("value")
        for node in root.findall(".//execution/parameters/parameter")
        if node.get("key")
    }
    geometry_lists = []
    for node in root.findall(".//geometry/commands/list"):
        geometry_lists.append({
            "name": node.get("name"),
            "drawbox_count": len(node.findall(".//drawbox")),
            "shapeout_files": [item.get("file") for item in node.findall(".//shapeout")],
            "layer_values": [item.get("vdp") for item in node.findall(".//layers")],
        })
    normals = root.find(".//normals")
    mainlist = root.find(".//geometry/commands/mainlist")
    mainlist_summary = None if mainlist is None else {
        "drawbox_count": len(mainlist.findall(".//drawbox")),
        "drawextrude_count": len(mainlist.findall(".//drawextrude")),
        "runlists": [item.get("name") for item in mainlist.findall(".//runlist")],
        "layer_values": [item.get("vdp") for item in mainlist.findall(".//layers")],
        "shapeout_files": [item.get("file") for item in mainlist.findall(".//shapeout")],
    }
    return {
        "definition_dp": None if definition is None else definition.get("dp"),
        "execution_parameters": parameters,
        "geometry_lists": geometry_lists,
        "mainlist": mainlist_summary,
        "normals_active": None if normals is None else normals.get("active"),
        "normal_geometry_files": [item.get("file") for item in root.findall(".//normals//geometryfile")],
        "normal_distance_h": [item.get("v") for item in root.findall(".//normals//distanceh")],
        "normal_shape_debug": [item.get("v") for item in root.findall(".//normals//svshapes")],
    }


def inventory_payload() -> dict[str, Any]:
    binary_names = ["GenCase_linux64", "DualSPHysics5.4_linux64", "DualSPHysics5.4CPU_linux64", "PartVTK_linux64", "PartVTKOut_linux64", "MeasureTool_linux64"]
    cases = {}
    for case_id, spec in CASE_SPECS.items():
        source = spec["source"]
        cases[case_id] = {
            "label": spec["label"],
            "source": fingerprint(source),
            "source_xml_summary": _xml_summary(source) if source.is_file() else None,
            "official_gpu_script": fingerprint(spec["gpu_shell"]),
            "official_cpu_script": fingerprint(spec["cpu_shell"]),
        }
    return {
        "schema_version": "l1r.q1.official-inventory.v1",
        "captured_at_utc": utc_now(),
        "same_version_root": relpath(OFFICIAL_ROOT),
        "version_info": fingerprint(BIN / "VERSION_INFO.txt"),
        "binaries": {name: fingerprint(BIN / name) for name in binary_names},
        "cases": cases,
        "execution_policy": {
            "allowed_gpu_indices": list(GPU_IDS),
            "protected_gpu_indices": list(PROTECTED_GPU_IDS),
            "launch_min_free_mib": LAUNCH_MIN_FREE_MIB,
            "abort_min_free_mib": ABORT_MIN_FREE_MIB,
            "max_concurrent_solver_processes": 1,
            "source_modified": False,
        },
    }


def _parse_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return int(match.group(1).replace(",", "")) if match else None


def _parse_gencase_counts(text: str) -> dict[str, Any]:
    total = _parse_int(text, r"Total particles:\s*([0-9,]+)")
    bound = _parse_int(text, r"Total particles:\s*[0-9,]+\s*\(bound=([0-9,]+)")
    fluid = _parse_int(text, r"Total particles:\s*[0-9,]+\s*\(bound=.*?\bfluid=([0-9,]+)\)")
    normal_match = re.search(r"Non-zero particle normals:\s*([0-9,]+)/([0-9,]+)", text, re.IGNORECASE)
    zero_match = re.search(r"Final zero normals:\s*([0-9,]+)/([0-9,]+)", text, re.IGNORECASE)
    return {
        "total_particles": total,
        "bound_particles": bound,
        "fluid_particles": fluid,
        "nonzero_normals": int(normal_match.group(1).replace(",", "")) if normal_match else None,
        "normal_evaluation_particles": int(normal_match.group(2).replace(",", "")) if normal_match else None,
        "final_zero_normals": int(zero_match.group(1).replace(",", "")) if zero_match else None,
        "normal_particles_total": int(zero_match.group(2).replace(",", "")) if zero_match else None,
    }


def _raw_directory(case_id: str) -> Path:
    return RAW_ROOT / case_id


def prepare_one(case_id: str, inventory: dict[str, Any]) -> dict[str, Any]:
    spec = CASE_SPECS[case_id]
    source = Path(spec["source"])
    raw_dir = _raw_directory(case_id)
    raw_dir.mkdir(parents=True, exist_ok=True)
    prefix = raw_dir / str(spec["prefix_name"])
    stdout_path = raw_dir / "gencase.stdout.log"
    required = [prefix.with_suffix(".xml"), prefix.with_suffix(".bi4")]
    started = time.perf_counter()
    if not all(path.is_file() for path in required):
        process = subprocess.run(
            [str(GENCASE), str(source.with_suffix("")), str(prefix), "-save:all"],
            cwd=source.parent, env=environment(cpu=True), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
            timeout=600,
        )
        stdout_path.write_text(process.stdout, encoding="utf-8")
        returncode = process.returncode
    else:
        process = None
        returncode = 0
    text = ""
    if stdout_path.is_file():
        text += stdout_path.read_text(encoding="utf-8", errors="replace")
    out_path = prefix.with_suffix(".out")
    if out_path.is_file():
        text += "\n" + out_path.read_text(encoding="utf-8", errors="replace")
    counts = _parse_gencase_counts(text)
    generated_suffixes = (".xml", ".bi4", ".out", "_All.vtk", "_Bound.vtk", "_Fluid.vtk", "_MkCells.vtk", "_hdp_Actual.vtk")
    generated_files = {
        suffix: fingerprint(prefix.with_suffix(suffix) if suffix.startswith(".") else prefix.with_name(prefix.name + suffix))
        for suffix in generated_suffixes
    }
    row: dict[str, Any] = {
        "case_id": case_id,
        "label": spec["label"],
        "source": fingerprint(source),
        "source_modified": False,
        "generated_prefix": relpath(prefix),
        "generated_files": generated_files,
        "gencase": {
            "returncode": returncode,
            "elapsed_seconds": time.perf_counter() - started,
            "stdout": relpath(stdout_path),
            "finished_text_found": "Finished execution (code=0)" in text,
            **counts,
        },
        "source_xml_summary": inventory["cases"][case_id]["source_xml_summary"],
    }
    if returncode != 0 or not all(path.is_file() for path in required):
        row["preparation_status"] = "failed"
        row["error_tail"] = text[-4000:]
    else:
        row["preparation_status"] = "completed"
    return row


def _estimated_peak_mib(total_particles: int | None) -> int:
    # Scheduling estimate only: reserve a 1 MiB/particle envelope plus 1 GiB
    # for grids and solver overhead.  The live 4 GiB guard remains mandatory.
    return max(1024, int(math.ceil((total_particles or 0) * 0.001 + 1024)))


def _choose_gpu(total_particles: int | None) -> tuple[int | None, dict[str, Any]]:
    allowed = set(_read_inventory_uuids())
    estimate = _estimated_peak_mib(total_particles)
    snapshot = gpu_snapshot()
    candidates = [
        row for row in snapshot
        if row["index"] in GPU_IDS
        and row["uuid"] in allowed
        and row["memory_free_mib"] >= LAUNCH_MIN_FREE_MIB
        and row["memory_free_mib"] - estimate >= ABORT_MIN_FREE_MIB
    ]
    selected = max(candidates, key=lambda row: row["memory_free_mib"])["index"] if candidates else None
    return selected, {
        "captured_at_utc": utc_now(),
        "snapshot": snapshot,
        "allowed_gpu_indices": list(GPU_IDS),
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
        "launch_min_free_mib": LAUNCH_MIN_FREE_MIB,
        "abort_min_free_mib": ABORT_MIN_FREE_MIB,
        "estimated_peak_mib": estimate,
        "selected_gpu_index": selected,
        "candidate_indices": [row["index"] for row in candidates],
    }


def _gpu_guard(index: int) -> dict[str, Any]:
    snapshot = gpu_snapshot()
    row = next((item for item in snapshot if item["index"] == index), None)
    if row is None:
        return {"ok": False, "gpu_index": index, "error": "gpu_disappeared"}
    return {
        "ok": row["memory_free_mib"] >= ABORT_MIN_FREE_MIB,
        "gpu_index": index,
        "memory_free_mib": row["memory_free_mib"],
        "memory_used_mib": row["memory_used_mib"],
        "memory_total_mib": row["memory_total_mib"],
        "utilization_percent": row["utilization_percent"],
        "abort_below_mib": ABORT_MIN_FREE_MIB,
    }


def _attempt_path(case_id: str, payload: dict[str, Any]) -> Path | None:
    attempt_directory = payload.get("attempt_directory")
    if not attempt_directory:
        return None
    path = Path(attempt_directory)
    return path if path.is_dir() else None


def run_one(case_id: str, prepared: dict[str, Any], *, cpu: bool = False, rerun: bool = False) -> dict[str, Any]:
    if prepared.get("preparation_status") != "completed":
        return {"case_id": case_id, "execution_status": "blocked_preparation", "preparation_status": prepared.get("preparation_status")}
    prefix = LAB / prepared["generated_prefix"]
    if not prefix.with_suffix(".xml").is_file() or not prefix.with_suffix(".bi4").is_file():
        return {"case_id": case_id, "execution_status": "blocked_missing_generated_input"}
    if cpu:
        if sum(item.get("execution_mode") == "cpu" for item in load_report().get("solver_runs", [])) >= MAX_CPU_PROBES:
            return {"case_id": case_id, "execution_status": "blocked_cpu_probe_cap", "max_cpu_probes": MAX_CPU_PROBES}
        solver = SOLVER_CPU
        command_template = [str(solver), "-mdbc", str(prefix), "{output}"]
        launch = {"mode": "cpu", "cpu_threads": os.cpu_count()}
        resource_guard = None
    else:
        gpu, launch = _choose_gpu(prepared.get("gencase", {}).get("total_particles"))
        if gpu is None:
            return {
                "case_id": case_id,
                "execution_status": "blocked_resource",
                "execution_mode": "gpu",
                "resource_preflight": launch,
            }
        solver = SOLVER_GPU
        command_template = [str(solver), f"-gpu:{gpu}", "-mdbc", str(prefix), "{output}"]
        launch["mode"] = "gpu"
        launch["gpu_index"] = gpu
        resource_guard = lambda: _gpu_guard(gpu)
    latest_path = RUN_ROOT / case_id / "latest.json"
    if latest_path.is_file() and not rerun:
        try:
            previous = json.loads(latest_path.read_text(encoding="utf-8"))
            if previous.get("status") == "completed":
                return {
                    **previous,
                    "case_id": case_id,
                    "execution_status": "reused_completed",
                    "gpu_index_requested": previous.get("gpu_index_requested") or (None if cpu else launch.get("gpu_index")),
                    "resource_preflight": launch,
                }
        except json.JSONDecodeError:
            pass
    result = execute_attempt(
        case_id, command_template, RUN_ROOT, cwd=prefix.parent,
        env=environment(cpu=cpu), evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)", timeout_seconds=SOLVER_TIMEOUT_S,
        resource_guard=resource_guard, resource_poll_seconds=1.0,
    )
    payload = {
        **result,
        "case_id": case_id,
        "execution_status": "completed" if result.get("status") == "completed" else "solver_failed",
        "execution_mode": "cpu" if cpu else "gpu",
        "gpu_index_requested": None if cpu else launch.get("gpu_index"),
        "solver": relpath(solver),
        "solver_sha256": sha256(solver),
        "input_generated_xml_sha256": prepared["generated_files"][".xml"]["sha256"],
        "input_generated_bi4_sha256": prepared["generated_files"][".bi4"]["sha256"],
        "resource_preflight": launch,
        "source_modified": False,
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
    }
    atomic_json(RUN_ROOT / case_id / "latest.json", payload)
    return payload


def load_report() -> dict[str, Any]:
    if REPORT.is_file():
        try:
            return json.loads(REPORT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "schema_version": "l1r.q1.official-results.v1",
        "source_modified": False,
        "inventory": None,
        "prepared_cases": {},
        "solver_runs": [],
        "resource_ledger": {"gpu_hours": 0.0, "cpu_core_hours": 0.0, "solver_attempts": 0},
    }


def write_report(report: dict[str, Any]) -> dict[str, Any]:
    runs = report.get("solver_runs", [])
    report["resource_ledger"] = {
        "gpu_hours": sum(float(item.get("elapsed_seconds", 0.0) or 0.0) / 3600.0 for item in runs if item.get("execution_mode") == "gpu" and item.get("status") in {"completed", "failed"}),
        "cpu_core_hours": sum(float(item.get("elapsed_seconds", 0.0) or 0.0) * max(1, int(item.get("resource_preflight", {}).get("cpu_threads") or 1)) / 3600.0 for item in runs if item.get("execution_mode") == "cpu" and item.get("status") in {"completed", "failed"}),
        "solver_attempts": len([item for item in runs if item.get("status") in {"completed", "failed"}]),
        "solver_runs_completed": len([item for item in runs if item.get("execution_status") in {"completed", "reused_completed"}]),
    }
    report["updated_at_utc"] = utc_now()
    atomic_json(REPORT, report)
    return report


def inventory_stage() -> dict[str, Any]:
    report = load_report()
    inventory = inventory_payload()
    report["inventory"] = inventory
    report["source_modified"] = False
    return write_report(report)


def prepare_stage(case_ids: Sequence[str]) -> dict[str, Any]:
    report = load_report()
    if report.get("inventory") is None:
        report = inventory_stage()
    prepared = report.setdefault("prepared_cases", {})
    for case_id in case_ids:
        if case_id not in CASE_SPECS:
            raise ValueError(f"unknown official case: {case_id}")
        row = prepare_one(case_id, report["inventory"])
        prepared[case_id] = row
        print(json.dumps({"stage": "prepare", "case_id": case_id, "status": row.get("preparation_status"), "particles": row.get("gencase", {}).get("total_particles")}, ensure_ascii=False), flush=True)
    return write_report(report)


def run_stage(case_ids: Sequence[str], *, cpu: bool = False, rerun: bool = False) -> dict[str, Any]:
    report = load_report()
    if report.get("inventory") is None:
        report = inventory_stage()
    missing = [case_id for case_id in case_ids if case_id not in report.get("prepared_cases", {})]
    if missing:
        report = prepare_stage(missing)
    runs = report.setdefault("solver_runs", [])
    for case_id in case_ids:
        row = run_one(case_id, report["prepared_cases"][case_id], cpu=cpu, rerun=rerun)
        # Keep the latest result for a case in the compact manifest, while the
        # campaign runner retains every immutable attempt directory.
        runs[:] = [item for item in runs if item.get("case_id") != case_id]
        runs.append(row)
        print(json.dumps({"stage": "run", "case_id": case_id, "execution_status": row.get("execution_status"), "status": row.get("status"), "elapsed_seconds": row.get("elapsed_seconds")}, ensure_ascii=False), flush=True)
        report = write_report(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inventory", "prepare", "run", "all", "status"), nargs="?", default="status")
    parser.add_argument("--case-id", action="append", dest="case_ids", choices=tuple(CASE_SPECS), help="select an official case; repeat to select several")
    parser.add_argument("--cpu", action="store_true", help="run selected solver case with the official CPU binary")
    parser.add_argument("--rerun", action="store_true", help="make a fresh immutable solver attempt")
    args = parser.parse_args(argv)
    case_ids = args.case_ids or (["official_dambreak3d_mdbc"] if args.action in {"run", "all"} else list(CASE_SPECS))
    if args.action == "inventory":
        report = inventory_stage()
    elif args.action == "prepare":
        report = prepare_stage(case_ids)
    elif args.action == "run":
        report = run_stage(case_ids, cpu=args.cpu, rerun=args.rerun)
    elif args.action == "all":
        report = prepare_stage(case_ids)
        report = run_stage(["official_dambreak3d_mdbc"], cpu=args.cpu, rerun=args.rerun)
    else:
        report = load_report()
    print(json.dumps({
        "inventory": report.get("inventory") is not None,
        "prepared_cases": {key: value.get("preparation_status") for key, value in report.get("prepared_cases", {}).items()},
        "solver_runs": [{"case_id": item.get("case_id"), "execution_status": item.get("execution_status"), "status": item.get("status")} for item in report.get("solver_runs", [])],
        "resource_ledger": report.get("resource_ledger"),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
