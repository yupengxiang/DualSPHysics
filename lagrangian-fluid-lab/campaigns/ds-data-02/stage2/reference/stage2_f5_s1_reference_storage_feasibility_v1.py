#!/usr/bin/env python3
"""Build a source-bound F5-S1 storage feasibility plan.

This is a metadata-only study.  It reads the small current F5 generated XML
and GenCase receipts, one completed source-matched coarse solver receipt and
its small ``RunPARTs.csv``.  It stats, but never reads, native ``Part_*.bi4``
payloads.  It does not read VTK, BI4, HDF5 or typed data, and it never starts
GenCase or a solver.

The exact coarse frame size is measured from the completed M095/T090 source
run.  Resolutions below dp=.02 and full-window/output-cadence variants are
explicit linear-Np planning proxies; they are not solver reservations or
scientific results.  The current dp=.01/.005 source runs only have GenCase
metadata, so their CFD output costs remain unmeasured.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SCHEMA = "ds02.stage2.f5-s1.reference-storage-feasibility.v1"
FAMILY = "F5"
PHYSICAL_CASE = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT_ROOT = DATA_ROOT / "families/F5"
CURRENT_DP010_ROOT = CURRENT_ROOT / "F5_S1_CLIPPLANE_YHALF_DP010_GENCASE_ROOT_106/f5-s1-yhalf-dp010-gencase-v5-root-106-001-root-forward-030-001"
CURRENT_DP005_ROOT = CURRENT_ROOT / "F5_S1_CLIPPLANE_YHALF_DP005_GENCASE_ROOT_107/f5-s1-yhalf-dp005-gencase-v5-root-107-001-root-forward-030-001"
COARSE_ROOT = CURRENT_ROOT / "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-m095_t090-full801-native-release-131-root808"
COARSE_PREPARED_ROOT = CURRENT_ROOT / "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-m095_t090-genuine-gencase-118-root640/prepared"
LEDGER = DATA_ROOT / "runtime/resource-ledger.json"
CURRENT_MOTION = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f5_s1_clipplane_repair_v5_inputs/F5_S1/dp010/assets/f5_c082s1_motion_m095_t090.dat")

DEFAULTS = {
    "xml_dp010": CURRENT_DP010_ROOT / "generated.xml",
    "receipt_dp010": CURRENT_DP010_ROOT / "execution-receipt.json",
    "xml_dp005": CURRENT_DP005_ROOT / "generated.xml",
    "receipt_dp005": CURRENT_DP005_ROOT / "execution-receipt.json",
    "coarse_xml": COARSE_PREPARED_ROOT / "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1.xml",
    "coarse_receipt": COARSE_ROOT / "execution-receipt.json",
    "coarse_runparts": COARSE_ROOT / "solver_output/RunPARTs.csv",
    "coarse_data": COARSE_ROOT / "solver_output/data",
    "motion": CURRENT_MOTION,
    "ledger": LEDGER,
    "output": HERE / "stage2_f5_s1_reference_storage_feasibility_v1.json",
}


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def directory(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_dir():
        raise FileNotFoundError(f"{label} must be a regular directory: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def small_record(path: Path, label: str, *, read_scope: str = "small_metadata") -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_read": True,
        "read_scope": read_scope,
    }


def stat_record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": "NOT_COMPUTED_NATIVE_PAYLOAD_STAT_ONLY",
        "content_read": False,
        "read_scope": "stat_only_no_native_payload_read",
    }


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def parse_xml(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    root = ET.parse(path).getroot()
    params = {str(e.attrib["key"]): str(e.attrib["value"]) for e in root.iter("parameter") if "key" in e.attrib and "value" in e.attrib}
    execution = root.find("./execution")
    particles = execution.find("./particles") if execution is not None else None
    constants = execution.find("./constants") if execution is not None else None
    definition = root.find("./casedef/geometry/definition")
    fluid_blocks: list[dict[str, Any]] = []
    if particles is not None:
        for e in particles.findall("./fluid"):
            if all(k in e.attrib for k in ("begin", "count", "mkfluid", "mk")):
                fluid_blocks.append(dict(sorted(e.attrib.items())))
    massfluid = None
    if constants is not None:
        node = constants.find("./massfluid")
        if node is not None and "value" in node.attrib:
            massfluid = float(node.attrib["value"])
    particle_attrs = dict(particles.attrib) if particles is not None else {}
    motion_files = [dict(sorted(e.attrib.items())) for e in root.iter("file") if "motion" in e.attrib.get("name", "") or "fieldtime" in e.attrib]
    compute = next((e.attrib for e in root.iter("_computetime")), {})
    outputtime = next((e.attrib for e in root.iter("_outputtime")), {})
    outputdt = next((e.attrib for e in root.iter("_outputdt")), {})
    return {
        "record": small_record(path, label, read_scope="small_generated_xml"),
        "case_root_tag": root.tag,
        "dp_m": float(definition.attrib["dp"]) if definition is not None and "dp" in definition.attrib else None,
        "particles": {k: int(v) for k, v in particle_attrs.items() if k in {"np", "nb", "nbf"}},
        "fluid_blocks": fluid_blocks,
        "fluid_count": sum(int(e["count"]) for e in fluid_blocks),
        "massfluid_kg": massfluid,
        "sample_mass_kg": sum(int(e["count"]) for e in fluid_blocks) * massfluid if massfluid is not None else None,
        "cfl": float(next((e.attrib["value"] for e in root.iter("cflnumber") if "value" in e.attrib), "nan")),
        "parameters": {k: params[k] for k in ("TimeMax", "TimeOut", "DtFixed", "DtMin", "SavePosDouble") if k in params},
        "compute_window_s": {k: float(v) for k, v in compute.items() if k in {"start", "end"}},
        "output_window_s": {k: float(v) for k, v in outputtime.items() if k in {"start", "end"}},
        "output_dt_s": float(outputdt["value"]) if "value" in outputdt else None,
        "motion_files": motion_files,
    }


def parse_motion(path: Path) -> dict[str, Any]:
    path = regular(path, "F5 motion table")
    rows: list[tuple[float, float]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.replace(",", " ").split()
        if len(fields) < 2:
            raise ValueError(f"motion line {line_no} has fewer than two fields")
        rows.append((float(fields[0]), float(fields[1])))
    if not rows:
        raise ValueError("empty motion table")
    return {
        "record": small_record(path, "F5 source motion table", read_scope="small_motion_table"),
        "rows": len(rows),
        "first_time_s": rows[0][0],
        "last_time_s": rows[-1][0],
        "first_value": rows[0][1],
        "last_value": rows[-1][1],
        "max_abs_value": max(abs(v) for _, v in rows),
        "active_window_s": [rows[0][0], rows[-1][0]],
        "table_end_scope": "last serialized row; no extrapolation beyond this table",
    }


def parse_runparts(path: Path) -> dict[str, Any]:
    path = regular(path, "F5 coarse RunPARTs.csv")
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")), delimiter=";"):
            if row.get("Part", "").strip().isdigit():
                rows.append({k.strip(): v.strip() for k, v in row.items()})
    if not rows:
        raise ValueError("RunPARTs.csv has no numeric Part rows")

    def integer(row: dict[str, str], key: str) -> int | None:
        value = row.get(key)
        if value is None or not value:
            return None
        return int(value.replace(",", ""))

    def number(row: dict[str, str], key: str) -> float | None:
        value = row.get(key)
        return float(value) if value not in (None, "") else None

    first, last = rows[0], rows[-1]
    return {
        "record": small_record(path, "F5 coarse RunPARTs.csv", read_scope="small_solver_log_csv"),
        "saved_frame_rows": len(rows),
        "first_part": integer(first, "Part"),
        "last_part": integer(last, "Part"),
        "first_time_s": number(first, "TimeStep [s]"),
        "last_time_s": number(last, "TimeStep [s]"),
        "first_npsim": integer(first, "NpSim"),
        "first_npb_sim": integer(first, "NpbSim"),
        "first_npf_sim": integer(first, "NpfSim"),
        "sum_npout": sum(integer(row, "NpOut") or 0 for row in rows),
        "max_dts_min": max(integer(row, "DTsMin") or 0 for row in rows),
        "dt_min_s_min": min((number(row, "DtMin [s]") or 0.0) for row in rows[1:]),
        "dt_max_s_max": max((number(row, "DtMax [s]") or 0.0) for row in rows[1:]),
        "last_row": {key: last.get(key) for key in ("Part", "TimeStep [s]", "Steps", "NpSim", "NpbSim", "NpfSim", "NpOut", "DtMin [s]", "DtMax [s]")},
        "counter_semantics": "saved-window rows and dt min/max summaries; not a complete per-step dt trace",
    }


def native_frame_stats(path: Path) -> dict[str, Any]:
    path = directory(path, "F5 coarse native data directory")
    files = sorted(path.glob("Part_*.bi4"))
    if not files:
        raise FileNotFoundError(f"no Part_*.bi4 under {path}")
    sizes = [int(p.stat().st_size) for p in files]
    return {
        "path": str(path),
        "pattern": "Part_*.bi4",
        "payload_read": False,
        "sha256": "NOT_COMPUTED_NATIVE_PAYLOAD_STAT_ONLY",
        "frame_count": len(files),
        "frame_bytes_sum": sum(sizes),
        "frame_bytes_min": min(sizes),
        "frame_bytes_max": max(sizes),
        "uniform_frame_bytes": len(set(sizes)) == 1,
        "first_frame": stat_record(files[0], "F5 coarse first native frame"),
        "last_frame": stat_record(files[-1], "F5 coarse last native frame"),
        "file_order": [files[0].name, files[-1].name],
    }


def receipt_summary(path: Path, label: str) -> dict[str, Any]:
    receipt = load_json(path, label)
    q = receipt.get("request", {})
    hashes_before = receipt.get("input_hashes_at_launch")
    hashes_after = receipt.get("input_hashes_after_run")
    return {
        "record": small_record(path, label, read_scope="small_receipt_json"),
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "termination_reason": receipt.get("termination_reason"),
        "bytes": int(receipt.get("bytes", 0) or 0),
        "cpu_core_seconds": float(receipt.get("cpu_core_seconds", 0.0) or 0.0),
        "gpu_seconds": float(receipt.get("gpu_seconds", 0.0) or 0.0),
        "elapsed_seconds": float(receipt.get("elapsed_seconds", 0.0) or 0.0),
        "output_root": receipt.get("output_root"),
        "case_id": q.get("case_id"),
        "physical_case_id": q.get("physical_case_id"),
        "attempt_id": q.get("attempt_id"),
        "command": q.get("command"),
        "gencase_prefix": q.get("gencase_prefix"),
        "gencase_receipt": q.get("gencase_receipt"),
        "estimated_storage_bytes": q.get("estimated_storage_bytes"),
        "max_wall_seconds": q.get("max_wall_seconds"),
        "input_hashes_stable": hashes_before == hashes_after if hashes_before is not None and hashes_after is not None else "UNKNOWN",
        "terminal_storage_guard": receipt.get("terminal_storage_guard") or "NOT_RECORDED_IN_RECEIPT",
        "source_preflight": receipt.get("source_preflight"),
        "cfd_invoked": receipt.get("cfd_invoked"),
        "model_invoked": receipt.get("model_invoked"),
    }


def ledger_summary(path: Path, attempt_id: str, case_id: str) -> dict[str, Any]:
    ledger = load_json(path, "resource ledger")
    wanted = f"{FAMILY}/{case_id}/{attempt_id}"
    charge = next((x for x in ledger.get("charges", []) if isinstance(x, dict) and x.get("id") == wanted), None)
    attempt = next((x for x in ledger.get("attempts", []) if isinstance(x, dict) and x.get("id") == wanted), None)
    if charge is None or attempt is None:
        raise ValueError(f"closed resource-ledger records not found for {wanted}")
    keep_charge = {k: charge.get(k) for k in ("id", "status", "new_storage_bytes", "cpu_core_seconds", "gpu_seconds", "finished_at_utc")}
    keep_attempt = {k: attempt.get(k) for k in ("id", "kind", "status", "started_at_utc", "finished_at_utc")}
    return {
        "record": small_record(path, "resource ledger", read_scope="small_ledger_json"),
        "charge": keep_charge,
        "attempt": keep_attempt,
        "closed": charge.get("status") == "completed" and attempt.get("status") == "completed",
        "scope": "ledger charge/attempt terminal status; no scientific qualification implied",
    }


def frame_count(window_s: float, output_dt_s: float) -> int:
    return int(round(window_s / output_dt_s)) + 1


def projected_row(label: str, np_target: int, frame_bytes: int, anchor_np: int, fixed_overhead: int, window_s: float, output_dt_s: float, *, actual: bool = False) -> dict[str, Any]:
    nframes = frame_count(window_s, output_dt_s)
    if actual:
        per_frame = frame_bytes
    else:
        per_frame = frame_bytes * (float(np_target) / float(anchor_np))
    raw = per_frame * nframes
    return {
        "label": label,
        "status": "MEASURED_ACTUAL" if actual else "LINEAR_NP_STORAGE_PROXY",
        "native_particle_count": np_target,
        "window_s": [0.0, window_s],
        "output_dt_s": output_dt_s,
        "saved_frame_count": nframes,
        "frame_bytes_exact_or_proxy": per_frame if actual else round(per_frame, 3),
        "native_part_tree_bytes_exact_or_proxy": raw if actual else round(raw, 3),
        "solver_attempt_bytes_exact_or_proxy": (raw + fixed_overhead) if actual else round(raw + fixed_overhead, 3),
        "fixed_overhead_basis_bytes": fixed_overhead,
        "proxy_formula": "coarse frame bytes * target Np / measured coarse Np; fixed attempt overhead held at measured coarse value",
        "proxy_uncertainties": ["particle-record schema/metadata fixed costs may not scale linearly", "boundary/clip count and particle fate are not inferred", "typed/HDF5/archive bytes are excluded"],
        "ti_bytes": (raw + fixed_overhead) / float(2**40),
        "gib_bytes": (raw + fixed_overhead) / float(2**30),
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    current_xml = {"dp010": parse_xml(args.xml_dp010, "F5 current dp010 generated XML"), "dp005": parse_xml(args.xml_dp005, "F5 current dp005 generated XML")}
    current_receipts = {"dp010": receipt_summary(args.receipt_dp010, "F5 current dp010 GenCase receipt"), "dp005": receipt_summary(args.receipt_dp005, "F5 current dp005 GenCase receipt")}
    coarse_xml = parse_xml(args.coarse_xml, "F5 source-matched coarse generated XML")
    coarse_receipt = receipt_summary(args.coarse_receipt, "F5 source-matched coarse solver receipt")
    if coarse_receipt["status"] != "completed" or coarse_receipt["returncode"] != 0:
        raise ValueError("coarse source-matched solver receipt is not completed zero-return")
    runparts = parse_runparts(args.coarse_runparts)
    frames = native_frame_stats(args.coarse_data)
    motion = parse_motion(args.motion)
    ledger = ledger_summary(args.ledger, str(coarse_receipt["attempt_id"]), str(coarse_receipt["case_id"]))

    anchor_np = int(runparts["first_npsim"])
    frame_bytes = int(frames["frame_bytes_min"])
    fixed_overhead = int(coarse_receipt["bytes"]) - int(frames["frame_bytes_sum"])
    if anchor_np <= 0 or frame_bytes <= 0 or fixed_overhead < 0:
        raise ValueError("invalid coarse storage anchor")

    np_targets = {
        "dp020_measured_anchor": anchor_np,
        "dp010_current_gencase_count": int(current_xml["dp010"]["particles"]["np"]),
        "dp005_current_gencase_count": int(current_xml["dp005"]["particles"]["np"]),
        "dp0025_registered_proxy_count": int(round(int(current_xml["dp005"]["particles"]["np"]) * 8.0)),
    }
    source_tmax = float(current_xml["dp005"]["parameters"]["TimeMax"])
    source_dt = float(current_xml["dp005"]["parameters"]["TimeOut"])
    actual_tmax = float(coarse_receipt["command"][2].split(":", 1)[1]) if False else 16.0
    actual_dt = float(coarse_receipt["command"][3].split(":", 1)[1]) if False else 0.02
    # Use the receipt command explicitly, without assuming it agrees with XML.
    command = list(coarse_receipt["command"] or [])
    for token in command:
        if isinstance(token, str) and token.startswith("-tmax:"):
            actual_tmax = float(token.split(":", 1)[1])
        if isinstance(token, str) and token.startswith("-tout:"):
            actual_dt = float(token.split(":", 1)[1])

    matrix: list[dict[str, Any]] = []
    matrix.append(projected_row("dp020_actual_source_m095_t090_0_16s_tout020", anchor_np, frame_bytes, anchor_np, fixed_overhead, actual_tmax, actual_dt, actual=True))
    for label, np_target in np_targets.items():
        if label == "dp020_measured_anchor":
            continue
        for window, dt, scope in ((actual_tmax, 0.02, "actual-16s-window"), (actual_tmax, 0.01, "same-16s-window-half-output-interval"), (source_tmax, 0.02, "declared-26s-source-window"), (source_tmax, 0.01, "declared-26s-source-window-half-output-interval")):
            matrix.append(projected_row(f"{label}_{scope}", np_target, frame_bytes, anchor_np, fixed_overhead, window, dt))

    source_motion_names = sorted({item.get("name") for item in current_xml["dp005"]["motion_files"] if item.get("name")})
    current_source_binding = {
        "physical_case_id": PHYSICAL_CASE,
        "current_q106_q107_control_motion_name": source_motion_names,
        "current_q106_q107_declared_compute_window_s": current_xml["dp005"]["compute_window_s"],
        "current_q106_q107_declared_output_window_s": current_xml["dp005"]["output_window_s"],
        "current_q106_q107_time_max_s": source_tmax,
        "current_q106_q107_time_out_s": source_dt,
        "current_q106_q107_cfl": current_xml["dp005"]["cfl"],
        "motion_table": motion,
        "actual_coarse_command_window_s": [0.0, actual_tmax],
        "actual_coarse_command_output_dt_s": actual_dt,
        "actual_coarse_saved_window_from_runparts_s": [runparts["first_time_s"], runparts["last_time_s"]],
        "identity_scope": "current q106/q107 generated XML and M095/T090 coarse source share physical case and motion asset name; dp=.02 coarse solver is an output-cost anchor only, not a current q106/q107 scientific qualification",
        "known_difference": "current XML declares TimeMax=26 s while completed coarse command intentionally used -tmax:16 and -tout:0.02; source motion table ends at 14.4 s with zero-valued terminal rows",
    }

    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_METADATA_ONLY_STORAGE_FEASIBILITY",
        "identity": {"family_id": FAMILY, "sentinel_id": "F5-S1", "physical_case_id": PHYSICAL_CASE},
        "scope": {
            "source_xml_read": True,
            "small_receipts_read": True,
            "RunPARTs_read": True,
            "motion_table_read": True,
            "native_part_payload_read": False,
            "native_part_hash_computed": False,
            "vtk_read": False,
            "hdf5_read": False,
            "typed_archive_read": False,
            "gencase_started": False,
            "solver_started": False,
        },
        "source_binding": current_source_binding,
        "current_gencase_only_facts": {"dp010": {"xml": current_xml["dp010"], "receipt": current_receipts["dp010"]}, "dp005": {"xml": current_xml["dp005"], "receipt": current_receipts["dp005"]}},
        "coarse_actual_anchor": {
            "xml": coarse_xml,
            "solver_receipt": coarse_receipt,
            "RunPARTs": runparts,
            "native_frame_stats": frames,
            "resource_ledger_closed_proof": ledger,
            "native_particle_count_basis": anchor_np,
            "measured_frame_bytes": frame_bytes,
            "measured_part_tree_bytes": int(frames["frame_bytes_sum"]),
            "measured_attempt_bytes": int(coarse_receipt["bytes"]),
            "fixed_attempt_overhead_bytes": fixed_overhead,
            "anchor_role": "actual source-bound M095/T090 dp=.02, 0..16 s, 801 native .bi4 frames; storage/runtime anchor only; no QN/QE/QI credit",
        },
        "storage_matrix": {
            "unit_bytes": "binary bytes; GiB=2^30; TiB=2^40",
            "raw_native_scope": "Part_*.bi4 tree only",
            "attempt_scope": "raw native tree plus measured fixed files/receipt overhead proxy",
            "typed_hdf5_archive_scope": "NOT_INCLUDED_UNKNOWN; no free duplicate assumed",
            "rows": matrix,
            "dp0025_proxy_source": "current q107 generated XML Np=6,813,521 multiplied by (0.005/0.0025)^3 = 54,508,168; this is a count/storage proxy, not actual GenCase or solver output",
            "planning_conclusion": "At measured coarse bytes per Np, dp0025 is approximately 1.92e12 bytes (1.75 TiB) for 16 s/.02 s, 3.84e12 bytes (3.49 TiB) for 16 s/.01 s, 3.12e12 bytes (2.84 TiB) for declared 26 s/.02 s, and 6.24e12 bytes (5.67 TiB) for declared 26 s/.01 s. These are linear-Np proxies with explicit uncertainty, not reservations.",
        },
        "time_output_error_separation": {
            "frozen_budget_semantics": {"time_error": "<= one quarter of the registered task time tolerance", "output_error": "<= one quarter of the registered task output tolerance", "quarter_of_total_window": False},
            "integration_time_evidence": "RunPARTs saved-window time and DtMin/DtMax summaries only; no complete per-step dt trace, so integration/time error credit is UNKNOWN",
            "output_error_evidence": "No same-run field deletion/reconstruction comparison was executed here; native saved timestamps are available, but output/interpolation error credit is UNKNOWN",
            "event_scope": "The completed anchor covers 0..16 s and the motion table serializes 0..14.4 s; the current source XML declares 0..26 s. Coverage beyond the selected 16 s window is UNKNOWN",
            "reduced_scope_rule": "A 16 s window or .01/.02 output-cadence branch must remain a separately scoped source-bound study. It cannot retroactively qualify the declared 26 s source or the original 14-sentinel task.",
            "no_neighbor_grid_truth": True,
        },
        "next_executable_scope": {
            "kind": "metadata-only storage decision followed by parent-reviewed bounded source run",
            "actual_next_step": "If parent chooses a run, reserve the exact full native Part tree before launch and register whether the selected window is 0..16 s or the declared 0..26 s; do not use this proxy as a reservation",
            "required_before_solver": ["current q106/q107 V7 support/initial QA closure", "exact UUID/lease and storage reservation by parent", "registered physical window and output cadence", "separate time/output observer calibration contract"],
            "not_authorized": ["dp0025 solver launch from this metadata", "HDF5/typed duplicate assumed free", "mass rescale", "threshold widening", "retroactive qualification of reduced window/cadence"],
        },
        "generator": {"script": str(Path(__file__).resolve()), "script_sha256": sha256(Path(__file__).resolve()), "generated_without_payload_reads": True},
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for key, default in DEFAULTS.items():
        parser.add_argument(f"--{key.replace('_', '-')}", type=Path, default=default)
    args = parser.parse_args()
    if args.self_test:
        assert frame_count(16.0, 0.02) == 801
        assert frame_count(26.0, 0.01) == 2601
        print("PASS stage2_f5_s1_reference_storage_feasibility_v1 self-test")
        return 0
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = build(args)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output), "schema": report["schema"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
