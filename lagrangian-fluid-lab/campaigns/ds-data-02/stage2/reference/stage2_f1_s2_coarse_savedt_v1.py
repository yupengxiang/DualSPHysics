#!/usr/bin/env python3
"""Prepare a source-bound F1-S2 coarse full-window SaveDt request.

The GenCase product is already complete in the shared data root.  This
forward-only builder creates a new logging-only XML overlay and an immutable
hardlink to that exact generated BI4.  It prepares a parent-guard request;
it never starts DualSPHysics or reads H5/native solver output.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DISPATCH_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DISPATCH = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
CURRENT = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
MATRIX = STAGE2 / "review-source/SENTINEL_MATRIX.json"
QUALITY = STAGE2 / "review-source/QUALITY_LABEL_SPLIT_ZH.md"
BUILDER = REFERENCE / "stage2_f1_s2_coarse_savedt_v1.py"
CONTRACT = REFERENCE / "stage2_f1_s2_reference_contract_v5.json"
CALIBRATION = REFERENCE / "stage2_f1_s2_reference_calibration_v5.json"

SOURCE_ROOT = DATA_ROOT / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027"
SOURCE_XML = SOURCE_ROOT / "prepared/F1_STAGE1_DUAL_H340_DP020.xml"
SOURCE_BI4 = SOURCE_ROOT / "prepared/F1_STAGE1_DUAL_H340_DP020.bi4"
SOURCE_GENCASE_RECEIPT = SOURCE_ROOT / "execution-receipt.json"
SOURCE_SOLVER_ROOT = DATA_ROOT / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-physical-endpoint-full-native-gpu-lease-retry-034"
SOURCE_SOLVER_RECEIPT = SOURCE_SOLVER_ROOT / "execution-receipt.json"
SOURCE_RUNPARTS = SOURCE_SOLVER_ROOT / "solver_output/RunPARTs.csv"
SOURCE_PART0 = SOURCE_SOLVER_ROOT / "solver_output/data/Part_0000.bi4"

CANDIDATE_ROOT = DATA_ROOT / "families/F1/F1_S2_SPATIAL_COARSE_DP0p022500/f1-s2-spatial-coarse-dp0p022500-v5-primary-001"
CANDIDATE_XML = CANDIDATE_ROOT / "generated.xml"
CANDIDATE_BI4 = CANDIDATE_ROOT / "generated.bi4"
CANDIDATE_GENCASE_RECEIPT = CANDIDATE_ROOT / "execution-receipt.json"

INPUT_ROOT = REFERENCE / "stage2_f1_s2_reference_inputs_v6/F1_S2/dp0p0225/same_cfl"
OVERLAY_XML = INPUT_ROOT / "F1_S2_SPATIAL_COARSE_DP0p022500_SAVEDT_SAME_CFL.xml"
OVERLAY_BI4 = INPUT_ROOT / "F1_S2_SPATIAL_COARSE_DP0p022500_SAVEDT_SAME_CFL.bi4"
REQUEST_ROOT = STAGE2 / "requests/stage2-f1-s2-reference-v6"
REQUEST = REQUEST_ROOT / "f1_s2_coarse_dp0p0225_same_cfl_savedt_full4s.json"

FAMILY_ID = "F1"
SENTINEL_ID = "F1-S2"
PHYSICAL_CASE_ID = "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1"
TMAX = 4.000064410707409
TMAX_TEXT = "4.000064410707409"
TOUT = 0.005
TOUT_TEXT = "0.005"
GIB = 1024**3
PROTECTED_GPU = {
    "index": 6,
    "uuid": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec",
    "pid": 601689,
    "action": "do_not_touch",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def record(path: Path, *, hash_file: bool = True) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    st = path.stat()
    item: dict[str, Any] = {
        "path": str(path.resolve()),
        "bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
    }
    if hash_file:
        item["sha256"] = sha256_file(path)
    return item


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_file() and path.read_bytes() == data:
            return
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode())


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()


def add_savedt_overlay(text: str) -> str:
    if "<savedt" in text:
        raise ValueError("candidate generated XML already contains a savedt node")
    marker = "</execution>"
    close = text.find(marker)
    if close < 0:
        raise ValueError("candidate generated XML lacks execution close")
    line_start = text.rfind("\n", 0, close) + 1
    indent = text[line_start:close]
    child = indent + "    "
    block = (
        f"{indent}<special>\n"
        f"{child}<savedt active=\"true\">\n"
        f"{child}    <start value=\"0\" comment=\"per-step dt starts at initial time\" />\n"
        f"{child}    <finish value=\"0\" comment=\"official v5.4 zero means no finish limit\" />\n"
        f"{child}    <interval value=\"{TOUT_TEXT}\" comment=\"explicit positive interval\" />\n"
        f"{child}    <fullinfo value=\"0\" comment=\"compact statistics\" />\n"
        f"{child}    <alldt value=\"1\" comment=\"all final-step dt rows\" />\n"
        f"{child}</savedt>\n"
        f"{indent}</special>\n"
    )
    return text[:line_start] + block + text[line_start:]


def make_overlay() -> dict[str, Any]:
    source_text = CANDIDATE_XML.read_text(encoding="utf-8")
    overlay_text = add_savedt_overlay(source_text)
    atomic_bytes(OVERLAY_XML, overlay_text.encode("utf-8"))
    INPUT_ROOT.mkdir(parents=True, exist_ok=True)
    if OVERLAY_BI4.exists():
        if sha256_file(OVERLAY_BI4) != sha256_file(CANDIDATE_BI4):
            raise FileExistsError("existing overlay BI4 differs from exact GenCase BI4")
    else:
        os.link(CANDIDATE_BI4, OVERLAY_BI4)
    return {
        "source_generated_xml": record(CANDIDATE_XML),
        "overlay_xml": record(OVERLAY_XML),
        "source_generated_bi4": record(CANDIDATE_BI4),
        "overlay_bi4": record(OVERLAY_BI4),
        "declared_xml_change": ["insert execution/special/savedt only"],
        "savedt": {"active": True, "start_s": 0.0, "finish_s": 0.0, "interval_s": TOUT, "fullinfo": 0, "alldt": 1},
        "physical_input_preserved": OVERLAY_BI4.stat().st_ino == CANDIDATE_BI4.stat().st_ino,
    }


def parse_generated_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = root.find("./casedef/geometry/definition")
    constants = root.find("./execution/constants")
    particles = root.find("./execution/particles")
    fluid = [e for e in root.findall("./execution/particles/fluid") if "mkfluid" in e.attrib and "count" in e.attrib]
    massfluid_node = constants.find("massfluid") if constants is not None else None
    dp_node = constants.find("dp") if constants is not None else None
    h_node = constants.find("h") if constants is not None else None
    cfl_node = constants.find("cflnumber") if constants is not None else None
    massfluid = float(massfluid_node.attrib["value"])
    fluid_count = sum(int(e.attrib["count"]) for e in fluid)
    total = int(particles.attrib["np"]) if particles is not None else fluid_count
    params = {
        e.attrib["key"]: e.attrib.get("value", "")
        for e in root.findall("./execution/parameters/parameter")
        if "key" in e.attrib
    }
    return {
        "definition_dp_m": None if definition is None else float(definition.attrib["dp"]),
        "h_m": None if h_node is None else float(h_node.attrib["value"]),
        "cfl": None if cfl_node is None else float(cfl_node.attrib["value"]),
        "massfluid_kg": massfluid,
        "fluid_blocks": [{"mkfluid": e.attrib["mkfluid"], "count": int(e.attrib["count"]), "mk": e.attrib.get("mk")} for e in fluid],
        "fluid_particles": fluid_count,
        "total_particles": total,
        "parameters": params,
    }


def actual_gencase_receipt() -> dict[str, Any]:
    d = json.loads(CANDIDATE_GENCASE_RECEIPT.read_text())
    return {
        "file": record(CANDIDATE_GENCASE_RECEIPT),
        "status": d.get("status"),
        "returncode": d.get("returncode"),
        "termination_reason": d.get("termination_reason"),
        "total_particles": d.get("total_particles"),
        "fluid_particles": d.get("fluid_particles"),
        "bytes": d.get("bytes"),
        "elapsed_seconds": d.get("elapsed_seconds"),
        "cpu_core_seconds": d.get("cpu_core_seconds"),
        "runner_sha256": d.get("runner_sha256"),
        "request_sha256": d.get("request_sha256"),
        "request_source_binding": d.get("request", {}).get("source_binding"),
    }


def main() -> None:
    for path in (SOURCE_XML, SOURCE_BI4, SOURCE_GENCASE_RECEIPT, SOURCE_SOLVER_RECEIPT, SOURCE_RUNPARTS, SOURCE_PART0, CANDIDATE_XML, CANDIDATE_BI4, CANDIDATE_GENCASE_RECEIPT):
        if not path.is_file():
            raise FileNotFoundError(path)
    candidate = parse_generated_xml(CANDIDATE_XML)
    source = parse_generated_xml(SOURCE_XML)
    if candidate["total_particles"] != 98364 or candidate["fluid_particles"] != 29700:
        raise ValueError(f"unexpected candidate counts: {candidate}")
    if not math.isclose(candidate["massfluid_kg"] * candidate["fluid_particles"], 338.3015625, rel_tol=0, abs_tol=1e-9):
        raise ValueError("candidate mass does not match independently reported 338.3015625 kg")
    overlay = make_overlay()
    candidate_receipt = actual_gencase_receipt()
    if candidate_receipt["status"] != "completed" or candidate_receipt["returncode"] != 0:
        raise ValueError("candidate GenCase receipt is not completed successfully")
    source_particles = source["total_particles"]
    source_part0_bytes = SOURCE_PART0.stat().st_size
    particle_ratio = candidate["total_particles"] / source_particles
    planned_frames = math.ceil(TMAX / TOUT) + 1
    raw_proxy = source_part0_bytes * particle_ratio * planned_frames
    input_paths = [
        DISPATCH,
        STRICT,
        RUNTIME,
        SOLVER,
        BUILDER,
        CONTRACT,
        CALIBRATION,
        CURRENT,
        MATRIX,
        QUALITY,
        SOURCE_XML,
        SOURCE_BI4,
        SOURCE_GENCASE_RECEIPT,
        SOURCE_SOLVER_RECEIPT,
        SOURCE_RUNPARTS,
        CANDIDATE_XML,
        CANDIDATE_BI4,
        CANDIDATE_GENCASE_RECEIPT,
        OVERLAY_XML,
        OVERLAY_BI4,
    ]
    input_hashes: dict[str, Any] = {}
    input_records: list[dict[str, Any]] = []
    for path in input_paths:
        if path == SOLVER:
            input_hashes[str(path)] = "PARENT_V4_GUARD_REQUIRED"
            input_records.append(record(path, hash_file=False))
        else:
            rec = record(path)
            input_hashes[rec["path"]] = rec["sha256"]
            input_records.append(rec)
    request = {
        "schema": "ds02.request.v1",
        "family_id": FAMILY_ID,
        "sentinel_id": SENTINEL_ID,
        "case_id": "F1_S2_SPATIAL_COARSE_DP0p022500_FULL4S_SAMECFL_SAVEDT",
        "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": "f1-s2-spatial-coarse-dp0p022500-v5-full4s-savedt-root-001",
        "kind": "qualification_candidate",
        "qualification_stage": "stage2_f1_s2_coarse_full_window_source_bound_pending_primary_dispatch",
        "cpu_task_kind": "solver",
        "cpu_threads": 2,
        "omp_threads": 2,
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": 16 * GIB,
        "estimated_peak_gpu_mib": 4096,
        "worktree_root": str(DISPATCH_ROOT),
        "cwd": str(INPUT_ROOT),
        "command": [str(SOLVER), str(INPUT_ROOT / "F1_S2_SPATIAL_COARSE_DP0p022500_SAVEDT_SAME_CFL"), "{attempt_root}/solver_output", f"-tmax:{TMAX_TEXT}", f"-tout:{TOUT_TEXT}"],
        "gencase_receipt": str(CANDIDATE_GENCASE_RECEIPT),
        "gencase_receipt_sha256": candidate_receipt["file"]["sha256"],
        "expected_particles": candidate["total_particles"],
        "expected_fluid_particles": candidate["fluid_particles"],
        "expected_native_frames": planned_frames,
        "expected_dimension": 3,
        "physical_window_s": [0.0, TMAX],
        "save_interval_s": TOUT,
        "source_binding": {
            "schema": "ds02.stage2.f1-s2-coarse-full-window-binding.v1",
            "sentinel_id": SENTINEL_ID,
            "family_id": FAMILY_ID,
            "physical_case_id": PHYSICAL_CASE_ID,
            "grid_role": "actual_gencase_dp0p0225_ge10pct_spacing",
            "baseline_dp_m": 0.02,
            "candidate_dp_m": candidate["definition_dp_m"],
            "spacing_separation_fraction": candidate["definition_dp_m"] / source["definition_dp_m"] - 1.0,
            "current_source": {
                "xml": record(SOURCE_XML),
                "bi4": record(SOURCE_BI4),
                "gencase_receipt": record(SOURCE_GENCASE_RECEIPT),
                "solver_receipt": record(SOURCE_SOLVER_RECEIPT),
                "runparts": record(SOURCE_RUNPARTS),
                "sample_mass_target_kg": 340.0,
            },
            "candidate_grid": {
                "generated_xml": record(CANDIDATE_XML),
                "generated_bi4": record(CANDIDATE_BI4),
                "gencase_receipt": record(CANDIDATE_GENCASE_RECEIPT),
                "whole_initial_sample_mass_kg": candidate["massfluid_kg"] * candidate["fluid_particles"],
                "whole_initial_error_pct": (candidate["massfluid_kg"] * candidate["fluid_particles"] / 340.0 - 1.0) * 100.0,
                "mass_gate": "TARGET_WITHIN_1PCT_BUT_SCIENTIFIC_UNKNOWN",
                "counts_and_mass_from_actual_generated_xml": candidate,
            },
            "solver_input": {
                "overlay_xml": overlay["overlay_xml"],
                "overlay_bi4": overlay["overlay_bi4"],
                "overlay_changes": overlay["declared_xml_change"],
                "cfl_mode": "same_cfl",
                "source_cfl": source["cfl"],
                "effective_cfl": candidate["cfl"],
                "command_tmax_text": TMAX_TEXT,
                "command_tout_text": TOUT_TEXT,
            },
            "continuous_geometry_control": "candidate XML is the completed exact GenCase product from the source-bound .0225 Def; the solver overlay inserts savedt only",
        },
        "dt_contract": {
            "requested": True,
            "savedt": overlay["savedt"],
            "RunPARTs_DTsMin": "count only, not seconds or a per-step trace",
            "clamp": "aggregate only unless actual source exposes per-row flag; do not infer",
            "full_step_sequence_status": "UNKNOWN_UNTIL_TERMINAL_GUARDED_RECEIPT",
        },
        "output_plan": {
            "native_raw": f"{{attempt_root}}/solver_output/data/Part_*.bi4; retain every saved frame over [0,{TMAX_TEXT}]",
            "typed": {
                "mode": "selected query-time anchors after raw retention",
                "query_times_s": [0.0, 1.0, 2.0, 3.0, 4.0],
                "time_policy": "EXACT/EXACT_OR_LEFT/BRACKETED from actual saved times; no frame indices or extrapolation",
            },
            "observer": {"status": "PENDING_PARENT_TYPED_CONVERSION_AND_FIELD_CALIBRATION"},
            "downsample": "derived only after retaining complete raw; not a solver replacement",
        },
        "cost": {
            "source_part0_bytes": source_part0_bytes,
            "source_particles": source_particles,
            "candidate_particles": candidate["total_particles"],
            "candidate_particle_ratio": particle_ratio,
            "planned_frames": planned_frames,
            "raw_native_scaled_proxy_bytes": raw_proxy,
            "raw_native_scaled_proxy_gib": raw_proxy / GIB,
            "reservation_bytes": 16 * GIB,
            "proxy_warning": "particle scaling is planning only; parent v4 terminal tree/receipt is authoritative",
            "typed_and_archive": "not reserved in this solver request; plan after actual terminal bytes",
        },
        "input_files": input_records,
        "input_hashes": input_hashes,
        "deferred_parent_hashes": [
            {"path": str(SOLVER), "reason": "official solver hash and UUID lease must be checked by parent v4 immediately before launch"},
            {"path": str(OVERLAY_BI4), "reason": "parent v4 must rehash the binary input immediately before launch"},
        ],
        "launch_policy": {
            "launch_disabled": True,
            "execution_allowed": False,
            "solver_launch_owner": "root",
            "primary_gpu_dispatch_required": True,
            "gpu_uuid_authorization": "PENDING_PRIMARY_LEDGER",
            "protected_external_gpu": PROTECTED_GPU,
            "parent_guard": str(DISPATCH),
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(REQUEST, request)
    print(json.dumps({"status": "PREPARED_SOURCE_BOUND_F1_S2_COARSE_FULL_WINDOW_REQUEST", "request": str(REQUEST), "overlay": str(OVERLAY_XML), "commit": git_head()}, sort_keys=True))


if __name__ == "__main__":
    main()
