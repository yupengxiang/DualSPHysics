#!/usr/bin/env python3
"""Prepare F4-S1 original-dp0 same/half-CFL SaveDt pair requests.

Both overlays start from the exact CURRENT F4-S1 generated XML and generated
BI4.  The same-CFL overlay adds only the official XML SaveDt logging node;
the half-CFL overlay adds that node and changes both generated XML CFL
locations from 0.2 to 0.1.  The base XML, BI4, CURRENT GenCase receipt and
historical solver receipt are immutable inputs.  No solver is launched here.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f4-dp0-savedt-pair-requests.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SOURCE_ROOT = DATA_ROOT / "families/F4/F4_DROP_CENTERED_REFERENCE_001_DP010/gencase-centered-reference-002"
SOURCE_STEM = "F4_DROP_CENTERED_REFERENCE_001_DP010"
SOURCE_XML = SOURCE_ROOT / f"{SOURCE_STEM}.xml"
SOURCE_BI4 = SOURCE_ROOT / f"{SOURCE_STEM}.bi4"
GENCASE_RECEIPT = SOURCE_ROOT / "execution-receipt.json"
SOURCE_SOLVER_RECEIPT = DATA_ROOT / "families/F4/F4_DROP_CENTERED_REFERENCE_001_DP010/qualification-centered-fullwindow-001/execution-receipt.json"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
DISPATCH_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DISPATCH = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
RUNTIME_V2 = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
GRAPH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_minimal14_study_graph_v2.json"
AUDIT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_savedt_instrumentation_audit_v1.json"
OVERLAY_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_dp0_savedt_pair_inputs_v1"
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-dp0-savedt-pair-v1"
REPORT_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_dp0_savedt_pair_binding_v1.json"
TMAX = 1.200084396929538
# Keep the exact CURRENT endpoint spelling in the solver argv.  A float
# formatted with a short precision would silently turn this into a different
# requested endpoint even though the binary value is unchanged in this file.
TMAX_TEXT = "1.200084396929538"
TOUT = 0.0005
SAVEDT_INTERVAL = 0.0005
PLANNED_FRAMES = 2402
RAW_NATIVE_RESERVED_BYTES = 7_362_717_289
STORAGE_RESERVATION_BYTES = RAW_NATIVE_RESERVED_BYTES + 256 * 1024 * 1024
QUERY_TIMES = [0.0, 0.3, 0.6, 0.9, 1.2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256_file(path)}


def atomic_bytes(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def parse_xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def strip_savedt(root: ET.Element) -> ET.Element:
    result = copy.deepcopy(root)
    execution = result.find("execution")
    if execution is None:
        raise ValueError("XML lacks execution")
    special = execution.find("special")
    if special is not None:
        execution.remove(special)
    return result


def cfl_values(root: ET.Element) -> list[str]:
    return [str(node.get("value")) for node in root.findall(".//cflnumber")]


def add_savedt(root: ET.Element) -> None:
    execution = root.find("execution")
    if execution is None:
        raise ValueError("XML lacks execution")
    if execution.find("special") is not None:
        raise ValueError("source XML unexpectedly contains execution.special")
    special = ET.Element("special")
    savedt = ET.SubElement(special, "savedt", {"active": "true"})
    ET.SubElement(savedt, "start", {"value": "0", "comment": "per-step dt starts at initial time"})
    ET.SubElement(savedt, "finish", {"value": "0", "comment": "official v5.4 zero means no finish limit"})
    ET.SubElement(savedt, "interval", {"value": str(SAVEDT_INTERVAL), "comment": "explicit positive interval"})
    ET.SubElement(savedt, "fullinfo", {"value": "0", "comment": "compact statistics"})
    ET.SubElement(savedt, "alldt", {"value": "1", "comment": "all final-step dt rows"})
    execution.insert(0, special)


def make_overlay(mode: str) -> tuple[Path, Path, dict[str, Any]]:
    base = parse_xml(SOURCE_XML)
    base_cfl = cfl_values(base)
    if base_cfl != ["0.20000000000000001", "0.2"]:
        raise ValueError(f"unexpected CURRENT F4 CFL values: {base_cfl}")
    root = copy.deepcopy(base)
    changes: list[dict[str, Any]] = []
    if mode == "half_cfl":
        for node in root.findall(".//cflnumber"):
            old = node.get("value")
            node.set("value", "0.1")
            changes.append({"xpath": "//cflnumber", "old": old, "new": "0.1"})
    elif mode != "same_cfl":
        raise ValueError(mode)
    add_savedt(root)
    overlay = OVERLAY_DIR / mode / f"{SOURCE_STEM}_{mode}_savedt.xml"
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    atomic_bytes(overlay, payload)
    # DualSPHysics resolves the BI4 from the XML/prefix stem.  Keep the
    # original CURRENT bytes available beside each overlay as an immutable
    # hardlink, rather than leaving a syntactically valid but unlaunchable
    # overlay prefix.
    overlay_bi4 = overlay.with_suffix(".bi4")
    if overlay_bi4.exists():
        raise FileExistsError(f"refuse to overwrite {overlay_bi4}")
    overlay_bi4.parent.mkdir(parents=True, exist_ok=True)
    os.link(SOURCE_BI4, overlay_bi4)
    if sha256_file(overlay_bi4) != sha256_file(SOURCE_BI4):
        raise ValueError("overlay BI4 hardlink does not match CURRENT BI4")
    if ET.tostring(strip_savedt(base), encoding="utf-8") != ET.tostring(strip_savedt(root), encoding="utf-8"):
        if mode == "same_cfl":
            raise ValueError("same-CFL overlay changed a non-SaveDt XML subtree")
        # For half CFL, the only allowed non-SaveDt changes are the two CFL
        # nodes.  Restore them in a copy and compare all remaining XML.
        restored = copy.deepcopy(root)
        for node, old in zip(restored.findall(".//cflnumber"), base_cfl):
            node.set("value", old)
        if ET.tostring(strip_savedt(base), encoding="utf-8") != ET.tostring(strip_savedt(restored), encoding="utf-8"):
            raise ValueError("half-CFL overlay changed geometry/control XML outside CFL")
    savedt = root.find("execution/special/savedt")
    if savedt is None:
        raise ValueError("SaveDt node missing")
    values = {node.tag: node.get("value") for node in savedt}
    expected = {"start": "0", "finish": "0", "interval": str(SAVEDT_INTERVAL), "fullinfo": "0", "alldt": "1"}
    if values != expected or savedt.get("active") != "true":
        raise ValueError(f"unexpected SaveDt values: {values}")
    return overlay, overlay_bi4, {"mode": mode, "source_cfl_values": base_cfl,
                     "overlay_cfl_values": cfl_values(root), "non_logging_changes": changes,
                     "savedt_values": values,
                     "overlay_bi4_same_inode_as_source": overlay_bi4.stat().st_ino == SOURCE_BI4.stat().st_ino}


def build_request(mode: str, overlay: Path, overlay_bi4: Path, diff: dict[str, Any], commit: str) -> tuple[dict[str, Any], dict[str, Any]]:
    gencase = json.loads(GENCASE_RECEIPT.read_text(encoding="utf-8"))
    if gencase.get("status") != "completed" or gencase.get("returncode") != 0:
        raise ValueError("CURRENT F4 GenCase receipt is not successful")
    case_id = f"F4_S1_DP0_SAVEDT_{mode.upper()}_DENSE_T1P2"
    attempt_id = f"f4-s1-dp0-savedt-{mode}-dense-t1p2-root-001"
    input_paths = [DISPATCH, STRICT, RUNTIME, RUNTIME_V2, SOLVER, SOURCE_XML, SOURCE_BI4,
                   GENCASE_RECEIPT, SOURCE_SOLVER_RECEIPT, overlay, overlay_bi4, GRAPH, AUDIT, Path(__file__)]
    input_files: list[str] = []
    input_hashes: dict[str, str] = {}
    for path in input_paths:
        item = record(path)
        input_files.append(item["path"])
        input_hashes[item["path"]] = item["sha256"]
    request: dict[str, Any] = {
        "schema": "ds02.request.v1",
        "family_id": "F4",
        "case_id": case_id,
        "physical_case_id": "F4_DROP_gap0p22000_xoff0p00000_yoff0p50000_uz0p50000".replace("yoff0p50000", "yoff0p00000"),
        "attempt_id": attempt_id,
        "kind": "qualification",
        "qualification_stage": "stage2_original_dp0_savedt_per_step_dt_probe_pending_parent_gpu_dispatch",
        "cpu_task_kind": "solver",
        "cpu_threads": 2,
        "omp_threads": 2,
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": STORAGE_RESERVATION_BYTES,
        "estimated_peak_gpu_mib": 4096,
        "worktree_root": str(REPO),
        "cwd": str(SOURCE_ROOT),
        "command": [str(SOLVER), str(overlay.with_suffix("")), "{attempt_root}/solver_output",
                     f"-tmax:{TMAX_TEXT}", f"-tout:{TOUT:.15g}"],
        "gencase_receipt": str(GENCASE_RECEIPT),
        "gencase_receipt_sha256": sha256_file(GENCASE_RECEIPT),
        "expected_particles": gencase.get("total_particles"),
        "expected_fluid_particles": gencase.get("fluid_particles"),
        "expected_dimension": 3,
        "physical_window_s": [0.0, TMAX],
        "save_interval_s": TOUT,
        "source_binding": {
            "sentinel_id": "F4-S1",
            "source_dp_m": 0.01,
            "source_xml": record(SOURCE_XML),
            "source_bi4": record(SOURCE_BI4),
            "current_gencase_receipt": record(GENCASE_RECEIPT),
            "historical_solver_receipt": record(SOURCE_SOLVER_RECEIPT),
            "overlay_xml": record(overlay),
            "overlay_bi4": record(overlay_bi4),
            "overlay_diff": diff,
            "full_physical_window_s": [0.0, TMAX],
            "tmax_precision_policy": "exact CURRENT float 1.200084396929538; no shortened 1.20008439693",
            "planned_native_frames": PLANNED_FRAMES,
        },
        "output_plan": {
            "native_output": "full dense native Part tree retained; no typed H5 in this probe",
            "planned_frames": PLANNED_FRAMES,
            "dt_files": {
                "DtAllInfo.csv": "official per-final-step rows Time [s];Dtf [s]; actual row count unknown until run",
                "DtInfo.csv": "official grouped summary; interval 0.0005 s, fullinfo=0",
            },
            "postrun_crosscheck": [
                "count DtAllInfo data rows",
                "last DtAllInfo Time [s] against actual RunPARTs final TimeStep and CLI endpoint",
                "sum RunPARTs Steps against DtAllInfo final-step count (allow documented initialization/terminal conventions)",
                "join Run.out DtMin and aggregate DTs adjusted to DtMin",
            ],
            "clamp_semantics": "no per-row clamp flag is emitted; report aggregate clamp count only and never infer row locations",
            "field_observables": "UNKNOWN",
            "scientific_qualification": "UNKNOWN",
        },
        "input_files": input_files,
        "input_hashes": input_hashes,
        # Keep the explicit singular name requested by the parent review in
        # addition to the v4 dispatcher's canonical input_hashes mapping.
        "input_sha256": dict(input_hashes),
        "resource_guard": {
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "consumed_runtime": str(RUNTIME_V2),
            "gpu_uuid_authorization": "PENDING_PRIMARY_LEDGER",
            "protected_gpu": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec/PID601689 untouched",
            "raw_native_reserved_bytes_basis": RAW_NATIVE_RESERVED_BYTES,
            "storage_reservation_bytes": STORAGE_RESERVATION_BYTES,
            "storage_uncertainty": "graph reserved raw estimate plus 256MiB for Dt CSV/logs; actual terminal guard remains authoritative",
        },
        "scope": {
            "sentinel_id": "F4-S1",
            "grid": "original CURRENT dp=0.01",
            "cfl_mode": mode,
            "cfl_value": 0.2 if mode == "same_cfl" else 0.1,
            "dense_output_cadence_s": TOUT,
            "savedt_interval_s": SAVEDT_INTERVAL,
            "source_geometry_motion_unchanged": True,
        },
        "launch_commit": commit,
        "launch_disabled": True,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "primary_gpu_dispatch_required": True,
        "dispatch_status": "PENDING_PARENT_GPU_REVIEW",
        "do_not_execute_from_preparation_worktree": True,
        "foreign_process_protection_required": True,
    }
    report = {
        "schema": SCHEMA,
        "mode": mode,
        "status": "PREPARED_LAUNCH_DISABLED",
        "request": {"path": str(REQUEST_DIR / f"{mode}.json"), "case_id": case_id, "attempt_id": attempt_id},
        "source": {"xml": record(SOURCE_XML), "bi4": record(SOURCE_BI4),
                   "gencase_receipt": record(GENCASE_RECEIPT), "solver_receipt": record(SOURCE_SOLVER_RECEIPT)},
        "overlay": {"xml": record(overlay), "bi4": record(overlay_bi4), "diff": diff},
        "tmax_s": TMAX,
        "tout_s": TOUT,
        "planned_frames": PLANNED_FRAMES,
        "storage_reservation_bytes": STORAGE_RESERVATION_BYTES,
        "per_step_dt_status": "PENDING_ACTUAL_SOLVER; DtAllInfo.csv is exact source; RunPARTs alone is insufficient",
        "clamp_status": "PENDING; only aggregate Run.out count, no per-row boolean",
        "solver_started_by_preparation": False,
        "hdf5_read_by_preparation": False,
    }
    return request, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-dir", type=Path, default=REQUEST_DIR)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                            capture_output=True, text=True).stdout.strip()
    built: list[dict[str, Any]] = []
    for mode in ("same_cfl", "half_cfl"):
        overlay, overlay_bi4, diff = make_overlay(mode)
        request, report = build_request(mode, overlay, overlay_bi4, diff, commit)
        request_path = args.request_dir / f"{mode}.json"
        atomic_json(request_path, request)
        built.append(report)
    atomic_json(args.report, {"schema": SCHEMA, "status": "PREPARED_LAUNCH_DISABLED_PAIR",
                              "current_head": commit, "source": record(SOURCE_XML),
                              "modes": built, "solver_started_by_preparation": False,
                              "hdf5_read_by_preparation": False})
    print(json.dumps({"status": "PREPARED_LAUNCH_DISABLED_PAIR", "requests": [str(args.request_dir / f'{m}.json') for m in ('same_cfl','half_cfl')],
                      "report": str(args.report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
