#!/usr/bin/env python3
"""Run one bounded mDBC boundary-configuration bridge case after Q1.

This is the first Q2 development/diagnostic case, not a replacement for the
old W2-A result.  It keeps the L1 h11/fine geometry and numerical policy,
adds the official mDBC recipe elements (separate finite-face normal source,
normal distance, three boundary layers, and the mDBC execution controls), and
stops at 0.6 s.  The old W2-A files are never overwritten.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Sequence
import xml.etree.ElementTree as ET

try:
    from scripts import l1_f1_qualification as l1
    from scripts import r5_f1_solver_gate as r5
    from scripts.campaign_runner import execute_attempt
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import l1_f1_qualification as l1
    import r5_f1_solver_gate as r5
    from campaign_runner import execute_attempt


LAB = Path(__file__).resolve().parents[1]
CASE_ID = "L1R_Q2_MDBC_BRIDGE_h11_fine_dp0p01_cfl005_t0p6"
PHASE = "Q2_official_recipe_bridge"
RECIPE_REVISION = "L1R_Q2_mDBC_official_complete_recipe_v1"
TIME_MAX_S = 0.6
TIME_OUT_S = 0.001
GPU_IDS = (4, 5, 6, 7)
PROTECTED_GPU_IDS = (0, 1, 2, 3)
LAUNCH_MIN_FREE_MIB = 6144
ABORT_MIN_FREE_MIB = 4096
TIMEOUT_S = 1800
SOURCE = l1.SOURCE_DEFINITION
BIN = l1.BIN
GENCASE = l1.GENCASE
SOLVER = l1.SOLVER
CAMPAIGN = l1.CAMPAIGN.parent / "l1-resume"
CASE_ROOT = CAMPAIGN / "cases" / "q2-mdbc-bridge" / CASE_ID
RAW_ROOT = CAMPAIGN / "artifacts" / "q2-mdbc-bridge" / CASE_ID
RUN_ROOT = CAMPAIGN / "runs" / "q2-mdbc-bridge"
DATA_ROOT = CAMPAIGN / "data" / "q2-mdbc-bridge"
REPORT = CAMPAIGN / "q2" / "Q2-MDBC-BRIDGE-RESULTS.json"


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


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": relpath(path), "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else None,
        "sha256": sha256(path) if path.is_file() else None,
    }


def environment(*, cpu: bool = False) -> dict[str, str]:
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN}:{value.get('LD_LIBRARY_PATH', '')}"
    value["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    if cpu:
        value["CUDA_VISIBLE_DEVICES"] = ""
        value["NVIDIA_VISIBLE_DEVICES"] = "void"
    return value


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


def allowed_gpu_uuids() -> set[str]:
    inventory = l1.CAMPAIGN / "L1-W00-INVENTORY.json"
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    policy = payload.get("execution_policy") or payload.get("gpu_policy")
    return set(policy["allowed_gpu_uuids"])


def choose_gpu(total_particles: int | None) -> tuple[int | None, dict[str, Any]]:
    estimate = max(1024, int((total_particles or 0) * 0.001 + 1024))
    snapshot = gpu_snapshot()
    candidates = [
        row for row in snapshot
        if row["index"] in GPU_IDS and row["uuid"] in allowed_gpu_uuids()
        and row["memory_free_mib"] >= LAUNCH_MIN_FREE_MIB
        and row["memory_free_mib"] - estimate >= ABORT_MIN_FREE_MIB
    ]
    selected = max(candidates, key=lambda row: row["memory_free_mib"])["index"] if candidates else None
    return selected, {
        "captured_at_utc": utc_now(), "snapshot": snapshot,
        "estimated_peak_mib": estimate,
        "launch_min_free_mib": LAUNCH_MIN_FREE_MIB,
        "abort_min_free_mib": ABORT_MIN_FREE_MIB,
        "candidate_indices": [row["index"] for row in candidates],
        "selected_gpu_index": selected,
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
    }


def gpu_guard(index: int, expected_uuid: str | None = None) -> dict[str, Any]:
    row = next((item for item in gpu_snapshot() if item["index"] == index), None)
    if row is None:
        return {"ok": False, "gpu_index": index, "error": "gpu_disappeared"}
    uuid_ok = row["uuid"] in allowed_gpu_uuids() and (expected_uuid is None or row["uuid"] == expected_uuid)
    return {"ok": uuid_ok and row["memory_free_mib"] >= ABORT_MIN_FREE_MIB, "gpu_index": index, **row, "expected_uuid": expected_uuid, "abort_below_mib": ABORT_MIN_FREE_MIB}


def build_record() -> dict[str, Any]:
    base = next(item for item in l1.space_records(l1.TIME_PRIMARY_CFL) if item["height_label"] == "h11" and item["resolution"] == "fine")
    return {
        **base,
        "id": CASE_ID, "case_id": CASE_ID, "phase": PHASE,
        "recipe_revision": RECIPE_REVISION,
        "time_max_s": TIME_MAX_S, "time_out_s": TIME_OUT_S,
        "boundary_method": "mDBC",
        "normal_geometry": "five finite closed planar tank faces; open top omitted",
        "mdbc_recipe": {
            "reference": "vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml",
            "normal_source_layers_vdp": "-0.5",
            "boundary_layers_vdp": "0,1,2",
            "normal_distance_h": 2.0,
            "svshapes": True,
            "boundary": 2,
            "slip_mode": 1,
            "no_penetration": 0,
        },
        "recipe_scope": "official mDBC boundary configuration on retained L1 numerical settings; not the complete official numerical strategy",
        "development_authorized": False, "formal_release": False,
    }


def _face_normal_list() -> ET.Element:
    normal_list = ET.Element("list", {"name": "GeometryForNormals"})
    ET.SubElement(normal_list, "setactive", {"drawpoints": "0", "drawshapes": "1"})
    ET.SubElement(normal_list, "setshapemode").text = "actual | bound"
    ET.SubElement(normal_list, "setnormalinvert", {"invert": "true"})
    ET.SubElement(normal_list, "setmkbound", {"mk": "0"})
    faces = (
        ("bottom", "0", "0", "0", "1.2", "0.4", "0.6"),
        ("left", "0", "0", "0", "1.2", "0.4", "0.6"),
        ("right", "0", "0", "0", "1.2", "0.4", "0.6"),
        ("front", "0", "0", "0", "1.2", "0.4", "0.6"),
        ("back", "0", "0", "0", "1.2", "0.4", "0.6"),
    )
    for face, x, y, z, sx, sy, sz in faces:
        draw = ET.SubElement(normal_list, "drawbox")
        ET.SubElement(draw, "boxfill").text = face
        ET.SubElement(draw, "point", {"x": x, "y": y, "z": z})
        ET.SubElement(draw, "size", {"x": sx, "y": sy, "z": sz})
        ET.SubElement(draw, "layers", {"vdp": "-0.5"})
    ET.SubElement(normal_list, "shapeout", {"file": "hdp"})
    ET.SubElement(normal_list, "resetdraw")
    return normal_list


def prepare() -> dict[str, Any]:
    record = build_record()
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    candidate = CASE_ROOT / f"{CASE_ID}_Def.xml"
    tree = ET.parse(SOURCE)
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("source definition has no geometry definition")
    definition.set("dp", str(record["dp_m"]))
    fluid = l1._fluid_drawbox(root)
    fluid_size = fluid.find("size")
    if fluid_size is None:
        raise ValueError("fluid drawbox has no size")
    fluid_size.set("z", str(record["height_m"]))
    cfl = root.find(".//constantsdef/cflnumber")
    if cfl is None:
        raise ValueError("source definition has no cflnumber")
    cfl.set("value", str(record["cfl_number"]))
    for key, value in (
        ("SavePosDouble", 2), ("StepAlgorithm", 1), ("VerletSteps", 40),
        ("Boundary", 2), ("SlipMode", 1), ("NoPenetration", 0),
        ("Shifting", 0), ("TimeMax", TIME_MAX_S), ("TimeOut", TIME_OUT_S),
    ):
        l1._set_parameter(root, key, value)
    geometry = root.find(".//geometry")
    commands = geometry.find("commands") if geometry is not None else None
    mainlist = commands.find("mainlist") if commands is not None else None
    if commands is None or mainlist is None:
        raise ValueError("source definition has no geometry command lists")
    commands.insert(0, _face_normal_list())
    mainlist.insert(0, ET.Element("runlist", {"name": "GeometryForNormals"}))
    boundary_draw = next((node for node in mainlist.findall("drawbox") if (node.findtext("boxfill") or "").strip() != "solid"), None)
    if boundary_draw is None:
        raise ValueError("could not locate boundary drawbox")
    layers = boundary_draw.find("layers")
    if layers is None:
        layers = ET.SubElement(boundary_draw, "layers")
    layers.set("vdp", "0,1,2")
    boundary_index = list(mainlist).index(boundary_draw)
    if not any(node.tag == "_shapeout" and node.get("file") == "parts" for node in mainlist):
        # The leading underscore is the official command used in the mDBC
        # reference XML for saving the boundary component before fluid fill.
        mainlist.insert(boundary_index + 1, ET.Element("_shapeout", {"file": "parts"}))
    casedef = root.find("casedef")
    if casedef is None:
        raise ValueError("source definition has no casedef")
    normals = ET.Element("normals", {"active": "true"})
    norgeometry = ET.SubElement(normals, "norgeometry")
    ET.SubElement(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    ET.SubElement(norgeometry, "distanceh", {"v": "2.0"})
    ET.SubElement(norgeometry, "svshapes", {"v": "true"})
    casedef.append(normals)
    ET.indent(tree, space="    ")
    tree.write(candidate, encoding="utf-8", xml_declaration=True)

    prefix = RAW_ROOT / CASE_ID
    stdout_path = RAW_ROOT / "gencase.stdout.log"
    started = time.perf_counter()
    process = subprocess.run(
        [str(GENCASE), str(candidate.with_suffix("")), str(prefix), "-save:all"],
        cwd=RAW_ROOT, env=environment(cpu=True), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=600,
    )
    stdout_path.write_text(process.stdout, encoding="utf-8")
    required = [prefix.with_suffix(".xml"), prefix.with_suffix(".bi4")]
    text = process.stdout + (prefix.with_suffix(".out").read_text(errors="replace") if prefix.with_suffix(".out").is_file() else "")
    total_match = re.search(r"Total particles:\s*([0-9,]+)", text)
    fluid_match = re.search(r"Total particles:\s*[0-9,]+\s*\(bound=.*?\bfluid=([0-9,]+)\)", text)
    record.update({
        "source_definition": relpath(SOURCE),
        "source_definition_sha256": sha256(SOURCE),
        "candidate_definition": relpath(candidate),
        "candidate_definition_sha256": sha256(candidate),
        "generated_prefix": relpath(prefix),
        "generated_xml_sha256": sha256(prefix.with_suffix(".xml")) if prefix.with_suffix(".xml").is_file() else None,
        "generated_bi4_sha256": sha256(prefix.with_suffix(".bi4")) if prefix.with_suffix(".bi4").is_file() else None,
        "normal_geometry_vtk": relpath(prefix.with_name(prefix.name + "_hdp_Actual.vtk")),
        "gencase": {
            "returncode": process.returncode, "elapsed_seconds": time.perf_counter() - started,
            "stdout": relpath(stdout_path),
            "total_particles": int(total_match.group(1).replace(",", "")) if total_match else None,
            "fluid_particles": int(fluid_match.group(1).replace(",", "")) if fluid_match else None,
            "nonzero_normals_text_found": "Final zero normals: 0/" in text,
        },
        "candidate_recipe_checks": {
            "normal_face_drawboxes": 5,
            "normal_layers_vdp": "-0.5",
            "boundary_layers_vdp": "0,1,2",
            "normals_active": True,
            "normal_distance_h": 2.0,
            "svshapes": True,
            "source_unmodified": True,
        },
    })
    record["record_hash"] = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    record["preparation_status"] = "completed" if process.returncode == 0 and all(path.is_file() for path in required) else "failed"
    if record["preparation_status"] != "completed":
        record["gencase"]["error_tail"] = text[-4000:]
    return record


def load_report() -> dict[str, Any]:
    if REPORT.is_file():
        try:
            return json.loads(REPORT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"schema_version": "l1r.q2.mdbc-bridge.v1", "prepared": None, "solver": None, "normalization": None, "audit": None}


def run_solver(record: dict[str, Any], *, rerun: bool = False) -> dict[str, Any]:
    if record.get("preparation_status") != "completed":
        return {"case_id": CASE_ID, "execution_status": "blocked_preparation"}
    latest = RUN_ROOT / CASE_ID / "latest.json"
    if latest.is_file() and not rerun:
        previous = json.loads(latest.read_text(encoding="utf-8"))
        if previous.get("status") == "completed" and previous.get("record_hash") == record.get("record_hash"):
            return {**previous, "execution_status": "reused_completed"}
    gpu, preflight = choose_gpu(record.get("gencase", {}).get("total_particles"))
    if gpu is None:
        return {"case_id": CASE_ID, "execution_status": "blocked_resource", "resource_preflight": preflight}
    prefix = LAB / record["generated_prefix"]
    result = execute_attempt(
        CASE_ID, [str(SOLVER), f"-gpu:{gpu}", "-mdbc", str(prefix), "{output}"],
        RUN_ROOT, cwd=prefix.parent, env=environment(), evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)", timeout_seconds=TIMEOUT_S,
        resource_guard=lambda: gpu_guard(gpu, next(row["uuid"] for row in preflight["snapshot"] if row["index"] == gpu)), resource_poll_seconds=1.0,
    )
    payload = {
        **result, "case_id": CASE_ID, "record_hash": record["record_hash"],
        "execution_status": "completed" if result.get("status") == "completed" else "solver_failed",
        "execution_mode": "gpu", "gpu_index_requested": gpu,
        "resource_preflight": preflight, "solver": relpath(SOLVER),
        "solver_sha256": sha256(SOLVER), "protected_gpu_indices": list(PROTECTED_GPU_IDS),
    }
    atomic_json(RUN_ROOT / CASE_ID / "latest.json", payload)
    return payload


def normalize(record: dict[str, Any], solver: dict[str, Any]) -> dict[str, Any]:
    if solver.get("execution_status") not in {"completed", "reused_completed"}:
        return {"case_id": CASE_ID, "normalization_status": "blocked_solver_not_completed"}
    attempt_directory = solver.get("attempt_directory")
    if not attempt_directory:
        return {"case_id": CASE_ID, "normalization_status": "blocked_missing_attempt"}
    attempt = Path(attempt_directory)
    output = DATA_ROOT / f"{CASE_ID}.h5"
    csv_dir = attempt / "csv"
    started = time.perf_counter()
    csv_paths = l1.partvtk_csv(attempt / "data", csv_dir, "-all,+fluid")
    l1.convert_streaming(record, csv_paths, output)
    import h5py
    with h5py.File(output, "r+") as h5:
        h5.attrs["l1r_q2_record_hash"] = record["record_hash"]
        h5.attrs["source_definition_sha256"] = sha256(SOURCE)
        h5.attrs["candidate_definition_sha256"] = sha256(LAB / record["candidate_definition"])
        h5.attrs["generated_input_sha256"] = record["generated_xml_sha256"]
    return {
        "case_id": CASE_ID, "normalization_status": "completed",
        "elapsed_seconds": time.perf_counter() - started, "hdf5": relpath(output),
        "hdf5_sha256": sha256(output), "frames": len(csv_paths),
    }


def audit(record: dict[str, Any], normalization: dict[str, Any], solver: dict[str, Any]) -> dict[str, Any]:
    if normalization.get("normalization_status") != "completed":
        return {"case_id": CASE_ID, "audit_status": "blocked_normalization"}
    h5_path = LAB / normalization["hdf5"]
    attempt = Path(solver["attempt_directory"]) if solver.get("attempt_directory") else None
    started = time.perf_counter()
    result = r5.audit_hdf5(record, h5_path, attempt)
    result.update({
        "case_id": CASE_ID, "phase": PHASE, "recipe_revision": RECIPE_REVISION,
        "bounded_time_horizon_s": TIME_MAX_S,
        "bounded_time_semantics": "Q2 bridge diagnostic stops at 0.6 s; no 1.5 s T1 claim",
        "audit_elapsed_seconds": time.perf_counter() - started,
    })
    artifact = CAMPAIGN / "artifacts" / "q2-mdbc-bridge" / f"{CASE_ID}-audit.json"
    atomic_json(artifact, result)
    return {
        "case_id": CASE_ID, "audit_status": result.get("audit_status"),
        "issues": result.get("issues", []), "unknowns": result.get("unknowns", []),
        "initial_fluid_mass_kg": result.get("initial_fluid_mass_kg"),
        "final_valid_mass_kg": result.get("final_valid_mass_kg"),
        "final_valid_mass_fraction_of_initial": result.get("final_valid_mass_fraction_of_initial"),
        "excluded_particles_from_solver_log": result.get("excluded_particles_from_solver_log"),
        "penetration": result.get("penetration"),
        "hdf5": relpath(h5_path), "hdf5_sha256": sha256(h5_path),
        "audit_artifact": relpath(artifact),
    }


def write(report: dict[str, Any]) -> dict[str, Any]:
    report["updated_at_utc"] = utc_now()
    atomic_json(REPORT, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "normalize", "audit", "all", "status"), nargs="?", default="status")
    parser.add_argument("--rerun", action="store_true")
    args = parser.parse_args(argv)
    report = load_report()
    if args.action == "prepare":
        report["prepared"] = prepare()
        write(report)
    elif args.action == "run":
        if report.get("prepared") is None:
            report["prepared"] = prepare()
        report["solver"] = run_solver(report["prepared"], rerun=args.rerun)
        write(report)
    elif args.action == "normalize":
        if report.get("prepared") is None:
            report["prepared"] = prepare()
        if report.get("solver") is None:
            report["solver"] = run_solver(report["prepared"], rerun=args.rerun)
        report["normalization"] = normalize(report["prepared"], report["solver"])
        write(report)
    elif args.action == "audit":
        if report.get("prepared") is None:
            report["prepared"] = prepare()
        if report.get("solver") is None:
            report["solver"] = run_solver(report["prepared"], rerun=args.rerun)
        if report.get("normalization") is None:
            report["normalization"] = normalize(report["prepared"], report["solver"])
        report["audit"] = audit(report["prepared"], report["normalization"], report["solver"])
        write(report)
    elif args.action == "all":
        report["prepared"] = prepare()
        write(report)
        report["solver"] = run_solver(report["prepared"], rerun=args.rerun)
        write(report)
        report["normalization"] = normalize(report["prepared"], report["solver"])
        write(report)
        report["audit"] = audit(report["prepared"], report["normalization"], report["solver"])
        write(report)
    print(json.dumps({
        "case_id": CASE_ID,
        "prepared": (report.get("prepared") or {}).get("preparation_status"),
        "solver": (report.get("solver") or {}).get("execution_status"),
        "normalization": (report.get("normalization") or {}).get("normalization_status"),
        "audit": (report.get("audit") or {}).get("audit_status"),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
