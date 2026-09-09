#!/usr/bin/env python3
"""Run one bounded W2-A boundary-control experiment for the L1 campaign.

The primary L1 space ladder uses the original DBC recipe.  Its fine cases
showed small closed-wall excursions and, at h11, native position exclusions.
This module makes one controlled comparison at the hardest registered point:
the physical geometry, resolution, CFL, time horizon, and numerical constants
remain fixed while the boundary representation changes to mDBC with explicit
normal geometry.  It is a diagnostic hypothesis test, not a new qualification
ladder and never authorizes a release.

The solver is run serially through the same co-run policy as L1:
6 GiB free at launch, abort below 4 GiB, and GPU 0--3 are protected.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

try:
    from scripts import l1_f1_qualification as l1
    from scripts import r6_n2_campaign as r6
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import l1_f1_qualification as l1
    import r6_n2_campaign as r6


CASE_ID = "L1_W2_A_BOUNDARY_MDBC_h11_fine_dp0p01_cfl005"
PHASE = "W2_controls_fallback"
RECIPE_REVISION = "L1_W2_A_mDBC_explicit_normals_h11_fine_cfl005_v1"
CASE_ROOT = l1.CAMPAIGN / "cases" / CASE_ID
ARTIFACT_ROOT = l1.CAMPAIGN / "artifacts" / "W2-A-boundary-mdbc" / CASE_ID / "generated"
RUN_ROOT = l1.CAMPAIGN / "runs" / "W2-A-boundary-mdbc"
DATA_ROOT = l1.CAMPAIGN / "data" / "W2-A-boundary-mdbc"
AUDIT_ROOT = l1.CAMPAIGN / "audits"
SIDECAR_ROOT = l1.CAMPAIGN / "sidecars"
PREFLIGHT_ROOT = l1.PREFLIGHT_ROOT
REPORT = l1.CAMPAIGN / "l1-w2-boundary-control.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(l1.LAB.resolve()))
    except ValueError:
        return str(path.resolve())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _append_normal_geometry(commands: ET.Element) -> None:
    """Add a planar normal source matching the five closed tank faces."""
    normal_list = ET.Element("list", {"name": "GeometryForNormals"})
    ET.SubElement(normal_list, "setactive", {"drawpoints": "0", "drawshapes": "1"})
    mode = ET.SubElement(normal_list, "setshapemode")
    mode.text = "actual | bound"
    ET.SubElement(normal_list, "setnormalinvert", {"invert": "true"})
    ET.SubElement(normal_list, "setmkbound", {"mk": "0"})
    draw = ET.SubElement(normal_list, "drawbox")
    ET.SubElement(draw, "boxfill").text = "bottom | left | right | front | back"
    ET.SubElement(draw, "point", {"x": "0", "y": "0", "z": "0"})
    ET.SubElement(draw, "size", {"x": "1.2", "y": "0.4", "z": "0.6"})
    ET.SubElement(draw, "layers", {"vdp": "-0.5"})
    ET.SubElement(normal_list, "shapeout", {"file": "hdp"})
    ET.SubElement(normal_list, "resetdraw")
    commands.insert(0, normal_list)

    mainlist = commands.find("mainlist")
    if mainlist is None:
        raise ValueError("source geometry has no mainlist")
    mainlist.insert(0, ET.Element("runlist", {"name": "GeometryForNormals"}))


def build_record() -> dict[str, object]:
    source_record = next(
        item for item in l1.space_records(l1.TIME_PRIMARY_CFL)
        if item["height_label"] == "h11" and item["resolution"] == "fine"
    )
    return {
        **source_record,
        "id": CASE_ID,
        "case_id": CASE_ID,
        "phase": PHASE,
        "recipe_revision": RECIPE_REVISION,
        "boundary_method": "mDBC",
        "normal_geometry": "five closed planar tank faces; open top omitted",
        "hypothesis": "W2-A boundary representation / explicit normal geometry",
        "development_authorized": False,
        "formal_release": False,
    }


def prepare(record: dict[str, object]) -> dict[str, object]:
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    candidate = CASE_ROOT / f"{CASE_ID}_Def.xml"
    tree = ET.parse(l1.SOURCE_DEFINITION)
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("source definition has no geometry definition")
    definition.set("dp", str(record["dp_m"]))
    fluid = l1._fluid_drawbox(root)
    size = fluid.find("size")
    if size is None:
        raise ValueError("source definition fluid drawbox has no size")
    size.set("z", str(record["height_m"]))
    cfl = root.find(".//constantsdef/cflnumber")
    if cfl is None:
        raise ValueError("source definition has no cflnumber")
    cfl.set("value", str(record["cfl_number"]))
    for key, value in (
        ("SavePosDouble", 2), ("StepAlgorithm", 1), ("VerletSteps", 40),
        ("Boundary", 2), ("SlipMode", 1), ("Shifting", 0),
        ("TimeMax", l1.TIME_MAX_S), ("TimeOut", l1.TIME_OUT_S),
    ):
        l1._set_parameter(root, key, value)
    geometry = root.find(".//geometry")
    commands = geometry.find("commands") if geometry is not None else None
    if commands is None:
        raise ValueError("source definition has no geometry commands")
    _append_normal_geometry(commands)
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

    prefix = ARTIFACT_ROOT / CASE_ID
    started = time.perf_counter()
    process = subprocess.run(
        [str(l1.GENCASE), str(candidate.with_suffix("")), str(prefix), "-save:all"],
        cwd=ARTIFACT_ROOT,
        env=l1.environment(cpu=True),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed = time.perf_counter() - started
    stdout_path = ARTIFACT_ROOT / "gencase.stdout.log"
    stdout_path.write_text(process.stdout, encoding="utf-8")
    required = [prefix.with_suffix(".xml"), prefix.with_suffix(".bi4")]
    if process.returncode != 0 or not all(path.is_file() for path in required):
        raise RuntimeError(f"GenCase failed for {CASE_ID}: {process.stdout[-2000:]}")
    record = {
        **record,
        "candidate_definition": relpath(candidate),
        "candidate_definition_sha256": sha256(candidate),
        "generated_prefix": relpath(prefix),
        "generated_xml_sha256": sha256(prefix.with_suffix(".xml")),
        "generated_bi4_sha256": sha256(prefix.with_suffix(".bi4")),
        "normal_geometry_vtk": relpath(prefix.with_name(prefix.name + "_hdp_Actual.vtk")),
        "gencase": {
            "returncode": process.returncode,
            "elapsed_seconds": elapsed,
            "stdout": relpath(stdout_path),
        },
    }
    record["record_hash"] = l1.record_hash(record)
    return record


def preflight() -> tuple[dict[str, object], int]:
    snapshot = {
        "label": "W2-A-boundary-mdbc-launch-1",
        "captured_at_utc": utc_now(),
        "requested_gpu_indices": [4, 5, 6, 7],
        "protected_gpu_indices": list(l1.PROTECTED_GPU_IDS),
        "gpu_snapshot": l1.cohost_gpu_snapshot(),
    }
    PREFLIGHT_ROOT.mkdir(parents=True, exist_ok=True)
    atomic_json(PREFLIGHT_ROOT / "W2-A-boundary-mdbc-launch-1.json", snapshot)
    actual = l1.choose_headroom_gpu({}, snapshot, set())
    return snapshot, actual


def run_solver(record: dict[str, object], gpu: int) -> dict[str, object]:
    prefix = l1.lab_path(str(record["generated_prefix"]))
    case_root = RUN_ROOT / CASE_ID
    command = [str(l1.SOLVER), f"-gpu:{gpu}", str(prefix), "{output}"]
    result = l1.execute_attempt(
        CASE_ID,
        command,
        RUN_ROOT,
        cwd=prefix.parent,
        env=l1.environment(),
        evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
        timeout_seconds=l1.DEFAULT_TIMEOUT_S,
        resource_guard=lambda: l1.cohost_memory_guard(gpu),
        resource_poll_seconds=1.0,
    )
    payload = {
        **result,
        "case_id": CASE_ID,
        "record_hash": record["record_hash"],
        "execution_status": "completed" if result.get("status") == "completed" else "solver_failed",
        "execution_mode": "gpu",
        "gpu_index_requested": gpu,
        "gpu_launch_policy": "cohost_headroom",
        "protected_gpu_indices": list(l1.PROTECTED_GPU_IDS),
        "input_generated_xml_sha256": record["generated_xml_sha256"],
        "input_generated_bi4_sha256": record["generated_bi4_sha256"],
        "solver_sha256": sha256(l1.SOLVER),
        "phase": PHASE,
        "recipe_revision": RECIPE_REVISION,
    }
    case_root.mkdir(parents=True, exist_ok=True)
    atomic_json(case_root / "latest.json", payload)
    return payload


def latest_attempt(payload: dict[str, object]) -> Path | None:
    attempt_id = payload.get("attempt_id")
    if not attempt_id:
        return None
    path = RUN_ROOT / CASE_ID / "attempts" / f"{attempt_id}.complete"
    if path.is_dir():
        return path
    partial = RUN_ROOT / CASE_ID / "attempts" / f"{attempt_id}.partial"
    return partial if partial.is_dir() else None


def normalize(record: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    attempt = latest_attempt(payload)
    if attempt is None:
        return {"case_id": CASE_ID, "normalization_status": "blocked_missing_attempt"}
    output = DATA_ROOT / f"{CASE_ID}.h5"
    csv_dir = attempt / "csv"
    started = time.perf_counter()
    csv_paths = l1.partvtk_csv(attempt / "data", csv_dir, "-all,+fluid")
    l1.convert_streaming(record, csv_paths, output)
    import h5py
    with h5py.File(output, "r+") as h5:
        h5.attrs["l1_record_hash"] = record["record_hash"]
        h5.attrs["recipe_revision"] = RECIPE_REVISION
        h5.attrs["source_definition_sha256"] = sha256(l1.SOURCE_DEFINITION)
        h5.attrs["solver_sha256"] = sha256(l1.SOLVER)
        h5.attrs["cfl_number"] = float(record["cfl_number"])
        h5.attrs["height_m"] = float(record["height_m"])
        h5.attrs["dp_m"] = float(record["dp_m"])
        h5.attrs["time_out_s"] = float(record["time_out_s"])
    prefix = l1.lab_path(str(record["generated_prefix"]))
    vtk = prefix.with_name(prefix.name + "_MkCells.vtk")
    sidecar = SIDECAR_ROOT / f"{CASE_ID}.h5"
    sidecar_summary = l1.write_sidecar(
        sidecar, CASE_ID, output, l1.read_binary_vtk_polydata(vtk),
        source_vtk_label=relpath(vtk), source_hdf5_label=relpath(output),
    )
    return {
        "case_id": CASE_ID,
        "normalization_status": "completed",
        "elapsed_seconds": time.perf_counter() - started,
        "hdf5": relpath(output),
        "hdf5_sha256": sha256(output),
        "frames": len(csv_paths),
        "sidecar": relpath(sidecar),
        "sidecar_sha256": sha256(sidecar),
        "sidecar_audit": sidecar_summary,
    }


def audit(record: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    import h5py
    h5_path = DATA_ROOT / f"{CASE_ID}.h5"
    attempt = latest_attempt(payload)
    if not h5_path.is_file() or attempt is None:
        return {
            "case_id": CASE_ID,
            "r6_full_time_audit_status": "missing_input",
            "r6_hard_failures": ["normalized_hdf5_or_attempt_missing"],
        }
    started = time.perf_counter()
    result = r6.full_time_audit(record, h5_path, attempt)
    result.update({
        "case_id": CASE_ID,
        "l1_phase": PHASE,
        "l1_recipe_revision": RECIPE_REVISION,
        "l1_record_hash": record["record_hash"],
        "audit_elapsed_seconds": time.perf_counter() - started,
    })
    atomic_json(AUDIT_ROOT / f"{CASE_ID}.json", result)
    return {
        "case_id": CASE_ID,
        "r6_full_time_audit_status": result.get("r6_full_time_audit_status"),
        "r6_hard_failures": result.get("r6_hard_failures", []),
        "audit_artifact": relpath(AUDIT_ROOT / f"{CASE_ID}.json"),
        "audit_elapsed_seconds": result.get("audit_elapsed_seconds"),
        "hdf5": relpath(h5_path),
        "hdf5_sha256": sha256(h5_path),
        "identity_retention_first_to_last": result.get("identity_retention_first_to_last"),
        "excluded_particles_from_solver_log": result.get("excluded_particles_from_solver_log"),
        "penetration": result.get("penetration"),
        "missing_identity_classification": result.get("missing_identity_classification"),
    }


def audit_existing() -> int:
    """Finish evidence processing for an already completed solver attempt.

    This recovery path is intentionally separate from ``main``: a large
    normalized trajectory must not be regenerated or the GPU solver relaunched
    merely because a post-processing audit was interrupted.
    """
    latest_path = RUN_ROOT / CASE_ID / "latest.json"
    preflight_path = PREFLIGHT_ROOT / "W2-A-boundary-mdbc-launch-1.json"
    if not latest_path.is_file() or not preflight_path.is_file():
        raise RuntimeError("completed W2-A solver metadata or preflight snapshot is missing")
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    record = build_record()
    record["record_hash"] = payload.get("record_hash")
    candidate = CASE_ROOT / f"{CASE_ID}_Def.xml"
    prefix = ARTIFACT_ROOT / CASE_ID
    record.update({
        "candidate_definition": relpath(candidate),
        "candidate_definition_sha256": sha256(candidate),
        "generated_prefix": relpath(prefix),
        "generated_xml_sha256": sha256(prefix.with_suffix(".xml")),
        "generated_bi4_sha256": sha256(prefix.with_suffix(".bi4")),
        "normal_geometry_vtk": relpath(prefix.with_name(prefix.name + "_hdp_Actual.vtk")),
    })
    h5_path = DATA_ROOT / f"{CASE_ID}.h5"
    sidecar = SIDECAR_ROOT / f"{CASE_ID}.h5"
    import h5py
    with h5py.File(h5_path, "r") as h5:
        frames = int(h5["time"].shape[0])
    from scripts.boundary_sidecars import audit_sidecar
    normalization = {
        "case_id": CASE_ID,
        "normalization_status": "completed",
        "elapsed_seconds": None,
        "hdf5": relpath(h5_path),
        "hdf5_sha256": sha256(h5_path),
        "frames": frames,
        "sidecar": relpath(sidecar),
        "sidecar_sha256": sha256(sidecar),
        "sidecar_audit": audit_sidecar(sidecar),
    }
    report: dict[str, object] = {
        "schema_version": "l1-w2-boundary-control.v1",
        "campaign_id": "L1_AUTONOMOUS_FLUID_QUALIFICATION",
        "phase": PHASE,
        "hypothesis": record["hypothesis"],
        "case_id": CASE_ID,
        "scope": "one h11 fine diagnostic; no qualification or release claim",
        "gpu_policy": {
            "minimum_free_mib_at_launch": l1.COHOST_MIN_FREE_MIB,
            "abort_below_free_mib": l1.COHOST_ABORT_FREE_MIB,
            "max_l1_jobs_per_gpu": l1.MAX_COHOST_JOBS_PER_GPU,
            "protected_gpu_indices": list(l1.PROTECTED_GPU_IDS),
        },
        "record": record,
        "execution_status": "solver_completed",
        "evidence_status": "solver_outputs_available",
        "acceptance_status": "diagnostic_pending",
        "development_authorized": False,
        "formal_release": False,
        "preflight": json.loads(preflight_path.read_text(encoding="utf-8")),
        "actual_gpu": payload.get("gpu_index_requested"),
        "solver": payload,
        "normalization": normalization,
    }
    report["audit"] = audit(record, payload)
    audit_status = report["audit"].get("r6_full_time_audit_status")
    report["acceptance_status"] = "diagnostic_pass" if audit_status == "pass" else "diagnostic_failed_or_unknown"
    report["interpretation"] = (
        "mDBC boundary control passed the full audit at the single hardest point; "
        "this is evidence for a follow-up expansion only, not a T1 qualification."
        if audit_status == "pass" else
        "The single mDBC boundary control did not close the registered audit gates; "
        "do not expand this hypothesis without a new owner decision."
    )
    atomic_json(REPORT, report)
    return 0 if audit_status == "pass" else 4


def main() -> int:
    record = build_record()
    report: dict[str, object] = {
        "schema_version": "l1-w2-boundary-control.v1",
        "campaign_id": "L1_AUTONOMOUS_FLUID_QUALIFICATION",
        "phase": PHASE,
        "hypothesis": record["hypothesis"],
        "case_id": CASE_ID,
        "scope": "one h11 fine diagnostic; no qualification or release claim",
        "gpu_policy": {
            "minimum_free_mib_at_launch": l1.COHOST_MIN_FREE_MIB,
            "abort_below_free_mib": l1.COHOST_ABORT_FREE_MIB,
            "max_l1_jobs_per_gpu": l1.MAX_COHOST_JOBS_PER_GPU,
            "protected_gpu_indices": list(l1.PROTECTED_GPU_IDS),
        },
        "record": record,
        "execution_status": "not_started",
        "evidence_status": "not_started",
        "acceptance_status": "diagnostic_pending",
        "development_authorized": False,
        "formal_release": False,
    }
    report["record"] = prepare(record)
    report["execution_status"] = "prepared_only"
    report["evidence_status"] = "inputs_prepared"
    snapshot, gpu = preflight()
    report["preflight"] = snapshot
    report["actual_gpu"] = gpu
    payload = run_solver(report["record"], gpu)
    report["solver"] = payload
    if payload.get("status") != "completed":
        report["execution_status"] = "solver_failed_with_evidence"
        report["evidence_status"] = "solver_failure_recorded"
        report["acceptance_status"] = "blocked_solver_failure"
        atomic_json(REPORT, report)
        return 2
    report["execution_status"] = "solver_completed"
    report["evidence_status"] = "solver_outputs_available"
    report["normalization"] = normalize(report["record"], payload)
    if report["normalization"].get("normalization_status") != "completed":
        report["acceptance_status"] = "blocked_normalization"
        atomic_json(REPORT, report)
        return 3
    report["audit"] = audit(report["record"], payload)
    audit_status = report["audit"].get("r6_full_time_audit_status")
    report["acceptance_status"] = "diagnostic_pass" if audit_status == "pass" else "diagnostic_failed_or_unknown"
    report["interpretation"] = (
        "mDBC boundary control passed the full audit at the single hardest point; "
        "this is evidence for a follow-up expansion only, not a T1 qualification."
        if audit_status == "pass" else
        "The single mDBC boundary control did not close the registered audit gates; "
        "do not expand this hypothesis without a new owner decision."
    )
    atomic_json(REPORT, report)
    return 0 if audit_status == "pass" else 4


if __name__ == "__main__":
    raise SystemExit(audit_existing() if "--audit-existing" in sys.argv[1:] else main())
