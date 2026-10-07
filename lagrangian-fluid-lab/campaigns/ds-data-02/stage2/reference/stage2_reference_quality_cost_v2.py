#!/usr/bin/env python3
"""Audit Stage2 spatial inputs and prepare a 14-sentinel storage matrix.

This module is deliberately read-only with respect to the data root.  It
joins the exact CURRENT336 row, review recipe, generated GenCase XML and
guarded receipt for each candidate.  A successful GenCase receipt is reported
as an input/preflight result; the mass gate is a diagnostic and never grants
QI/QN/QE or solver qualification.

The cost projection uses the measured per-sentinel lossless canary ratio and
Part_0000 size.  It keeps the complete registered physical window for every
sentinel (the cross-family [0, 1] query intersection is only metadata), and
emits separate native, typed, archive and temporary-peak estimates.  All
solver rows remain ``PLANNED_NO_SOLVER``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable
import xml.etree.ElementTree as ET


SCHEMA = "ds02.stage2.reference-quality-cost.v2"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json"
REVIEW = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
CANARY = DATA_ROOT / "families/infra/STAGE2_NATIVE_LOSSLESS_CANARY_V2/stage2-native-lossless-canary-v2-001/lossless-canary-v2.json"
COMMON_QUERY = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_common_physical_query_plan_v1.json"
OLD_MANIFEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_sentinel_spatial_preflight_inputs_v1/manifest.json"
F3_MANIFEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_sentinel_spatial_preflight_inputs_v2/manifest.json"
REMAINING_MANIFEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_remaining_sentinel_spatial_preflight_inputs_v1/manifest.json"
F2_PHASE_MANIFEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/f2_s1_coarse_phase_probe_inputs_v2/manifest.json"
F2_PREFLIGHT_MANIFEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/f2_s1_preflight_inputs/manifest.json"
OUTPUT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_reference_quality_cost_v2.json"

GIB = 2**30
MASS_TARGET_PCT = 1.0
MASS_HARD_PCT = 2.0
# These are planning safety factors, deliberately exposed in the output.
SAFETY = {
    "native_raw_frame": 1.15,
    "typed_uncompressed": 2.0,
    "typed_temporary": 1.20,
    "lossless_archive": 1.25,
    "temporary_peak": 1.20,
}

SENTINEL_ORDER = [f"F{family}-S{slot}" for family in range(1, 8) for slot in (1, 2)]
PHYSICAL_IDS = {
    "F1-S1": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
    "F1-S2": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
    "F2-S1": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
    "F2-S2": "F2_STAGE1_OFFSET_P03_OPEN_RIM_RX065_RY014_FILL080",
    "F3-S1": "F3_TWOAXIS_AY0P50_PITCH_NOMINAL",
    "F3-S2": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
    "F4-S1": "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
    "F4-S2": "F4_DROP_gap0p18000_xoffm0p08000_yoff0p04000_uz0p60000",
    "F5-S1": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
    "F5-S2": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M115_T080",
    "F6-S1": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
    "F6-S2": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
    "F7-S1": "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1",
    "F7-S2": "F7_OBSTACLE_QUINTIC_B08_A065",
}

# F3-S2's first original attempt is retained as a failed historical attempt;
# the recovery has a new identity and is the usable generated input.
RECOVERY_CASE = {"F3-S2": "F3_S2_SPATIAL_V2_1_ORIGINAL_DP0p006000"}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def record(path: Path, *, digest: bool = False) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "status": "MISSING"}
    stat = path.stat()
    out: dict[str, Any] = {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if digest:
        out["sha256"] = sha256_file(path)
    return out


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def all_named(root: ET.Element, name: str) -> list[ET.Element]:
    return [node for node in root.iter() if local(node.tag).lower() == name.lower()]


def first_attr(root: ET.Element, name: str, attr: str) -> str | None:
    for node in all_named(root, name):
        if attr in node.attrib:
            return node.attrib[attr]
    return None


def parameter_map(root: ET.Element) -> dict[str, str]:
    return {
        node.attrib["key"]: node.attrib.get("value", "")
        for node in all_named(root, "parameter")
        if "key" in node.attrib
    }


def parse_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    params = parameter_map(root)
    cfl_values = [node.attrib.get("value") for node in all_named(root, "cflnumber") if "value" in node.attrib]
    dp_values = [node.attrib.get("value") for node in all_named(root, "dp") if "value" in node.attrib]
    h_values = [node.attrib.get("value") for node in all_named(root, "h") if "value" in node.attrib]
    particles = next((node for node in all_named(root, "particles") if "np" in node.attrib), None)
    fluid_nodes = [node for node in all_named(root, "fluid") if "mkfluid" in node.attrib and "count" in node.attrib]
    counts = []
    for node in fluid_nodes:
        try:
            counts.append({"mkfluid": node.attrib.get("mkfluid"), "mk": node.attrib.get("mk"), "count": int(node.attrib["count"])})
        except ValueError:
            counts.append({"mkfluid": node.attrib.get("mkfluid"), "mk": node.attrib.get("mk"), "count": "UNKNOWN"})
    mass_values = []
    for node in all_named(root, "massfluid"):
        if "value" in node.attrib and number(node.attrib["value"]) is not None:
            mass_values.append(float(node.attrib["value"]))
    # A generated XML normally has one global massfluid.  If there are several,
    # only a one-to-one mapping to fluid blocks is accepted.
    fluid_mass_kg: float | None = None
    if counts and all(isinstance(item["count"], int) for item in counts):
        if len(mass_values) == 1:
            fluid_mass_kg = sum(item["count"] for item in counts) * mass_values[0]
        elif len(mass_values) == len(counts):
            fluid_mass_kg = sum(item["count"] * mass for item, mass in zip(counts, mass_values))
    floating_nodes = all_named(root, "floating")
    massbody: list[float] = []
    inertia: list[dict[str, float]] = []
    for node in all_named(root, "massbody"):
        if number(node.attrib.get("value")) is not None:
            massbody.append(float(node.attrib["value"]))
    for node in all_named(root, "inertia"):
        values = {axis: number(node.attrib.get(axis)) for axis in ("x", "y", "z")}
        if all(value is not None for value in values.values()):
            inertia.append({axis: float(values[axis]) for axis in ("x", "y", "z")})
    motion_refs = []
    for node in all_named(root, "file"):
        name = node.attrib.get("name")
        if name and ("motion" in name.lower() or "filetime" in node.attrib or "fieldtime" in node.attrib):
            motion_refs.append(name)
    return {
        "path": str(path.resolve()),
        "file": record(path, digest=True),
        "dp_m": number(dp_values[0]) if dp_values else None,
        "h_m": number(h_values[0]) if h_values else None,
        "cfl": number(cfl_values[-1]) if cfl_values else None,
        "parameters": params,
        "particles": int(particles.attrib["np"]) if particles is not None and particles.attrib.get("np", "").isdigit() else None,
        "fluid_blocks": counts,
        "fluid_particle_count": sum(item["count"] for item in counts if isinstance(item["count"], int)),
        "massfluid_values_kg": mass_values,
        "sample_mass_kg": fluid_mass_kg,
        "rigid_body_massbody_kg": massbody[0] if massbody else None,
        "rigid_body_inertia": inertia[0] if inertia else None,
        "motion_refs": motion_refs,
    }


def command_from_receipt(receipt: dict[str, Any]) -> list[str]:
    request = receipt.get("request")
    if isinstance(request, dict) and isinstance(request.get("command"), list):
        return [str(item) for item in request["command"]]
    if isinstance(receipt.get("command"), list):
        return [str(item) for item in receipt["command"]]
    return []


def cli_value(command: Iterable[str], flag: str) -> float | None:
    for arg in command:
        if arg.startswith(flag + ":"):
            return number(arg.split(":", 1)[1])
    return None


def solver_controls(receipt_path: Path) -> dict[str, Any]:
    if not receipt_path.is_file():
        return {"status": "UNKNOWN", "receipt": record(receipt_path)}
    receipt = load(receipt_path)
    command = command_from_receipt(receipt)
    return {
        "status": receipt.get("status", "UNKNOWN"),
        "receipt": record(receipt_path),
        "command": command,
        "tmax_s": cli_value(command, "-tmax"),
        "tout_s": cli_value(command, "-tout"),
        "returncode": receipt.get("returncode"),
        "termination_reason": receipt.get("termination_reason"),
        "bytes": receipt.get("bytes"),
        "input_hashes_at_launch": receipt.get("input_hashes_at_launch", {}),
    }


def source_part_stats(raw_root: Path) -> dict[str, Any]:
    parts = sorted(raw_root.glob("Part_*.bi4"), key=lambda p: int(p.stem.split("_")[-1]) if p.stem.split("_")[-1].isdigit() else -1)
    if not parts:
        return {"status": "UNKNOWN", "raw_root": str(raw_root)}
    first, last = parts[0], parts[-1]
    return {
        "raw_root": str(raw_root),
        "frame_count_from_parts": len(parts),
        "first_frame": record(first),
        "last_frame": record(last),
        "frame0_bytes": first.stat().st_size,
        "last_frame_bytes": last.stat().st_size,
        "observed_frame_size_ratio_last_over_first": last.stat().st_size / first.stat().st_size,
    }


def compare_number(a: Any, b: Any, tol: float = 1e-12) -> bool | None:
    if a is None or b is None:
        return None
    try:
        return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    except (TypeError, ValueError):
        return None


def mass_gate(deviation_pct: float | None) -> str:
    if deviation_pct is None:
        return "UNKNOWN"
    magnitude = abs(deviation_pct)
    if magnitude <= MASS_TARGET_PCT:
        return "PASS_TARGET_1PCT_DIAGNOSTIC"
    if magnitude <= MASS_HARD_PCT:
        return "MARGINAL_1_TO_2PCT_DIAGNOSTIC"
    return "HARD_FAIL_GT2PCT"


def candidate_receipts(family: str, case_id: str) -> list[Path]:
    root = DATA_ROOT / "families" / family / case_id
    return sorted(root.glob("*/execution-receipt.json")) if root.is_dir() else []


def generated_xml_for(receipt: dict[str, Any], receipt_path: Path) -> Path | None:
    out = receipt.get("output_root")
    candidates = []
    if out:
        root = Path(out)
        candidates.extend([root / "generated.xml", root / "generated" / "generated.xml"])
        candidates.extend(sorted(root.glob("*.xml")))
        candidates.extend(sorted(root.glob("generated/*.xml")))
    candidates.extend([receipt_path.parent / "generated.xml", receipt_path.parent / "generated" / "generated.xml"])
    return next((path for path in candidates if path.is_file()), None)


def current_row(current: dict[str, Any], sentinel_id: str) -> dict[str, Any]:
    physical = PHYSICAL_IDS[sentinel_id]
    rows = [row for row in current.get("cases", []) if row.get("physical_case_id") == physical]
    if len(rows) != 1:
        raise ValueError(f"{sentinel_id} exact CURRENT row count={len(rows)}")
    return rows[0]


def review_row(review: dict[str, Any], sentinel_id: str) -> dict[str, Any]:
    rows = [row for row in review.get("sentinels", []) if row.get("sentinel_id") == sentinel_id]
    if len(rows) != 1:
        raise ValueError(f"{sentinel_id} exact review row count={len(rows)}")
    return rows[0]


def manifest_candidates() -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for path in (OLD_MANIFEST, F3_MANIFEST, REMAINING_MANIFEST):
        data = load(path)
        for sentinel in data.get("sentinels", []):
            sid = sentinel.get("sentinel_id")
            if sid not in SENTINEL_ORDER:
                continue
            # F3 v2 supersedes the old F3 v1 preparation.  F4-F7 have only
            # the remaining manifest; F1/F2 use the original v1 manifest.
            if path == OLD_MANIFEST and sid.startswith("F3-"):
                continue
            if path == F3_MANIFEST and not sid.startswith("F3-"):
                continue
            if path == REMAINING_MANIFEST and not sid.startswith(("F4-", "F5-", "F6-", "F7-")):
                continue
            output[sid] = sentinel.get("candidates", [])
    # F2-S1 has its own source-bound phase probe.  Use the measured .01258
    # candidate as the coarse grid, the exact dp0 GenCase preflight as the
    # original grid, and the separate fine .008 preflight.  The .01236 probe
    # remains in its own immutable manifest/receipt but is not a member of
    # this three-grid ladder because its mass gate is a hard failure.
    phase = load(F2_PHASE_MANIFEST)
    phase_cases = {item["case_id"]: item for item in phase.get("cases", [])}
    preflight = load(F2_PREFLIGHT_MANIFEST)
    preflight_cases = {item["case_id"]: item for item in preflight.get("cases", [])}
    coarse = dict(phase_cases["F2_S1_COARSE_PHASE_PROBE_DP01258"])
    coarse.update({"sentinel_id": "F2-S1", "family_id": "F2", "label": "coarse", "source_dp_m": 0.01, "continuous_geometry_control": {"phase_policy": coarse.get("phase_policy", "UNKNOWN"), "draw_fill_geometry_changed": False, "motion_or_acceleration_changed": False}})
    original = dict(preflight_cases["F2_S1_PREFLIGHT_NATIVE_DP010_DENSE_CFL020"])
    original.update({"sentinel_id": "F2-S1", "family_id": "F2", "label": "original", "source_dp_m": 0.01, "dp_m": 0.01, "continuous_geometry_control": {"draw_fill_geometry_changed": False, "motion_or_acceleration_changed": False}})
    fine = dict(preflight_cases["F2_S1_PREFLIGHT_FINE_DP008"])
    fine.update({"sentinel_id": "F2-S1", "family_id": "F2", "label": "fine", "source_dp_m": 0.01, "continuous_geometry_control": {"draw_fill_geometry_changed": False, "motion_or_acceleration_changed": False}})
    output["F2-S1"] = [coarse, original, fine]
    if set(output) != set(SENTINEL_ORDER):
        raise ValueError(f"candidate manifest coverage mismatch: {sorted(set(SENTINEL_ORDER) - set(output))}")
    return output


def motion_audit(sid: str, xml_path: Path, controls: dict[str, Any], manifest_candidate: dict[str, Any]) -> dict[str, Any] | None:
    if not sid.startswith("F5-"):
        return None
    xml = parse_xml(xml_path)
    refs = xml["motion_refs"]
    resolved: list[dict[str, Any]] = []
    for ref in refs:
        path = (xml_path.parent / ref).resolve()
        times: list[float] = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                fields = line.replace(",", " ").split()
                try:
                    times.append(float(fields[0]))
                except (IndexError, ValueError):
                    continue
        resolved.append({
            "xml_ref": ref,
            "path": str(path),
            "file": record(path, digest=True),
            "rows": len(times),
            "first_time_s": times[0] if times else None,
            "last_time_s": times[-1] if times else None,
            "effective_tmax_s": controls.get("tmax_s"),
            "xml_time_max_s": xml["parameters"].get("TimeMax"),
            "coverage": (
                "MOTION_END_BEFORE_EFFECTIVE_TMAX"
                if times and controls.get("tmax_s") is not None and times[-1] + 1e-9 < controls["tmax_s"]
                else "COVERS_EFFECTIVE_TMAX"
                if times and controls.get("tmax_s") is not None
                else "UNKNOWN"
            ),
        })
    return {
        "xml_refs": refs,
        "resolved": resolved,
        "cli_overrides_xml_timemax": (
            controls.get("tmax_s") is not None
            and number(xml["parameters"].get("TimeMax")) is not None
            and not math.isclose(controls["tmax_s"], number(xml["parameters"]["TimeMax"]), rel_tol=0, abs_tol=1e-12)
        ),
        "terminal": "MOTION_INPUT_HASH_MATCH_BUT_DURATION_GAP" if any(item["coverage"] == "MOTION_END_BEFORE_EFFECTIVE_TMAX" for item in resolved) else "MOTION_INPUT_RESOLUTION_UNKNOWN",
        "source_dependency_manifest": manifest_candidate.get("source_binding", {}).get("relative_dependencies", []),
    }


def control_terminal(source_xml: dict[str, Any], solver: dict[str, Any], candidate_xml: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    # h and dp are intentional resolution changes.  The remaining controls
    # are expected to remain source-bound at the GenCase stage.
    keys = ("cfl", "DtIni", "DtMin", "DtFixed", "CoefDtMin", "TimeMax", "TimeOut")
    checks = {}
    for key in keys:
        left = source_xml.get("cfl") if key == "cfl" else source_xml.get("parameters", {}).get(key)
        right = candidate_xml.get("cfl") if key == "cfl" else candidate_xml.get("parameters", {}).get(key)
        checks[key] = compare_number(left, right) if (number(left) is not None and number(right) is not None) else (left == right if left is not None and right is not None else None)
    required = [value for key, value in checks.items() if key not in ("TimeMax", "TimeOut") and value is not None]
    return {
        "candidate_xml_vs_source_xml": checks,
        "candidate_xml_control_match_except_intentional_dp_h": all(required) if required else "UNKNOWN",
        "intentional_resolution": {
            "source_dp_m": source_xml.get("dp_m"),
            "candidate_dp_m": candidate_xml.get("dp_m"),
            "source_h_m": source_xml.get("h_m"),
            "candidate_h_m": candidate_xml.get("h_m"),
            "dp_h_are_intentional_changes": True,
        },
        "source_effective_solver_controls": {
            "tmax_s": solver.get("tmax_s"),
            "tout_s": solver.get("tout_s"),
            "xml_timemax_s": source_xml.get("parameters", {}).get("TimeMax"),
            "xml_timeout_s": source_xml.get("parameters", {}).get("TimeOut"),
            "xml_vs_cli_time_control": (
                "CLI_OVERRIDES_XML"
                if solver.get("tmax_s") is not None and source_xml.get("parameters", {}).get("TimeMax") is not None and not math.isclose(float(solver["tmax_s"]), float(source_xml["parameters"]["TimeMax"]), rel_tol=0, abs_tol=1e-12)
                else "MATCH_OR_UNKNOWN"
            ),
        },
        "continuous_geometry_control": candidate.get("continuous_geometry_control", "UNKNOWN"),
        "source_dependencies": candidate.get("source_binding", {}).get("relative_dependencies", []),
        "solver_candidate_status": "PLANNED_NO_SOLVER",
    }


def candidate_audit(sid: str, source_xml: dict[str, Any], source_solver: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    family = candidate.get("family_id", sid.split("-", 1)[0])
    case_id = str(candidate.get("case_id"))
    receipts = candidate_receipts(family, case_id)
    recovery = RECOVERY_CASE.get(sid) if candidate.get("label") == "original" else None
    recovery_receipts = candidate_receipts(family, recovery) if recovery else []
    selected = recovery_receipts if recovery_receipts and any(load(p).get("status") == "completed" for p in recovery_receipts) else receipts
    historical = []
    for path in receipts:
        r = load(path)
        historical.append({"receipt": record(path, digest=True), "status": r.get("status"), "returncode": r.get("returncode"), "termination_reason": r.get("termination_reason"), "output_root": r.get("output_root"), "bytes": r.get("bytes")})
    for path in recovery_receipts:
        if path not in receipts:
            r = load(path)
            historical.append({"receipt": record(path, digest=True), "status": r.get("status"), "returncode": r.get("returncode"), "termination_reason": r.get("termination_reason"), "output_root": r.get("output_root"), "bytes": r.get("bytes"), "role": "forward_recovery"})
    if not selected:
        return {"case_id": case_id, "label": candidate.get("label"), "status": "UNKNOWN_RECEIPT", "scientific_qualification": "UNKNOWN"}
    selected_path = next((p for p in selected if load(p).get("status") == "completed"), selected[0])
    receipt = load(selected_path)
    xml_path = generated_xml_for(receipt, selected_path)
    candidate_xml = parse_xml(xml_path) if xml_path else {}
    source_mass = source_xml.get("sample_mass_kg")
    candidate_mass = candidate_xml.get("sample_mass_kg")
    deviation = ((candidate_mass - source_mass) / source_mass * 100.0) if source_mass and candidate_mass is not None else None
    gencase_status = receipt.get("status")
    return {
        "case_id": case_id,
        "label": candidate.get("label"),
        "requested_dp_m": candidate.get("dp_m"),
        "source_dp_m": candidate.get("source_dp_m"),
        "receipt_path": str(selected_path.resolve()),
        "historical_attempts": historical,
        "receipt_terminal": {
            "status": gencase_status,
            "returncode": receipt.get("returncode"),
            "termination_reason": receipt.get("termination_reason"),
            "total_particles": receipt.get("total_particles"),
            "fluid_particles": receipt.get("fluid_particles"),
            "output_root": receipt.get("output_root"),
            "actual_output_tree_bytes": receipt.get("bytes"),
        },
        "generated_xml": {"path": str(xml_path.resolve()) if xml_path else None, "metadata": candidate_xml or {"status": "UNKNOWN"}},
        "mass_diagnostic": {
            "source_sample_mass_kg": source_mass,
            "candidate_sample_mass_kg": candidate_mass,
            "deviation_pct_vs_source": deviation,
            "gate": mass_gate(deviation),
            "meaning": "initial fluid particle mass diagnostic only; not QI/QN/QE or scientific qualification",
        },
        "control_terminal": control_terminal(source_xml, source_solver, candidate_xml, candidate),
        "continuous_vs_intentional": candidate.get("continuous_geometry_control", "UNKNOWN"),
        "solver_started": False,
        "scientific_qualification": "UNKNOWN",
        "QI": "NOT_ASSESSED",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
    }


def frame_count(end_s: float, cadence_s: float) -> int:
    # Preserve the actual terminal time window without extrapolating.  A tiny
    # epsilon avoids turning 4.0000009/.01 into an extra frame from print noise.
    return max(1, math.floor(end_s / cadence_s + 1e-9) + 1)


def gib(value: int | float | None) -> float | None:
    return value / GIB if value is not None else None


def cost_scenario(source: dict[str, Any], candidate: dict[str, Any], cfl_mode: str, cadence_kind: str, cadence_s: float) -> dict[str, Any]:
    source_particles = source.get("source_particles")
    candidate_particles = candidate.get("receipt_terminal", {}).get("total_particles") or candidate.get("generated_xml", {}).get("metadata", {}).get("particles")
    frame0 = source.get("part_stats", {}).get("frame0_bytes")
    if not frame0 or not source_particles or not candidate_particles:
        return {"status": "UNKNOWN", "grid_label": candidate.get("label"), "cfl_mode": cfl_mode, "cadence_kind": cadence_kind, "cadence_s": cadence_s, "reason": "missing frame0 or particle count"}
    scale = float(candidate_particles) / float(source_particles)
    frames = frame_count(source["window_end_s"], cadence_s)
    raw_unreserved = frame0 * scale * frames
    native_reserved = math.ceil(raw_unreserved * SAFETY["native_raw_frame"])
    typed_proxy = math.ceil(native_reserved * SAFETY["typed_uncompressed"])
    typed_reserved = math.ceil(typed_proxy * SAFETY["typed_temporary"])
    ratio = source.get("canary_pair_ratio")
    archive_proxy = math.ceil(raw_unreserved * ratio) if ratio is not None else None
    archive_reserved = math.ceil(archive_proxy * SAFETY["lossless_archive"]) if archive_proxy is not None else None
    temp = None
    if archive_reserved is not None:
        temp = math.ceil((native_reserved + typed_reserved + archive_reserved + frame0) * SAFETY["temporary_peak"])
    return {
        "status": "PLANNED_NO_SOLVER",
        "grid_label": candidate.get("label"),
        "requested_dp_m": candidate.get("requested_dp_m"),
        "candidate_particles": int(candidate_particles),
        "particle_scale_vs_source": scale,
        "cfl_mode": cfl_mode,
        "cfl_value": source.get("source_cfl") if cfl_mode == "same_cfl" else (source.get("half_cfl")),
        "cadence_kind": cadence_kind,
        "cadence_s": cadence_s,
        "full_physical_window_s": [0.0, source["window_end_s"]],
        "planned_frames": frames,
        "source_part0_bytes": frame0,
        "raw_native_unreserved_bytes": math.ceil(raw_unreserved),
        "raw_native_reserved_bytes": native_reserved,
        "typed_uncompressed_proxy_bytes": typed_proxy,
        "typed_reserved_bytes": typed_reserved,
        "archive_ratio_measured_pair": ratio,
        "archive_native_proxy_bytes": archive_proxy,
        "archive_native_reserved_bytes": archive_reserved,
        "temporary_peak_proxy_bytes": temp,
        "persistent_total_reserved_bytes": (native_reserved + typed_reserved + archive_reserved) if archive_reserved is not None else None,
        "safety_factors": SAFETY,
        "storage_policy": "retain raw native; typed and lossless archive are separate projections; no deletion or overwrite",
        "cpu_wall_time": "UNKNOWN_UNTIL_GUARDED_SOLVER",
        "dt_clamp": "UNKNOWN_UNTIL_GUARDED_SOLVER",
    }


def build_source(sid: str, current: dict[str, Any], review: dict[str, Any], canary: dict[str, Any]) -> dict[str, Any]:
    row = current_row(current, sid)
    xml_path = Path(row["source_bindings"]["generated_xml"]["path"])
    xml = parse_xml(xml_path)
    solver_path = Path(row["source_bindings"]["solver_receipt"]["path"])
    solver = solver_controls(solver_path)
    raw = Path(row["raw_root"]["path"])
    part_stats = source_part_stats(raw)
    actual_end = float(row["actual_time_window_s"][1])
    canary_row = canary.get("per_sentinel", {}).get(sid, {})
    review_row_data = review_row(review, sid)
    effective_tout = solver.get("tout_s") or number(xml["parameters"].get("TimeOut"))
    dense = number(review_row_data.get("proposed_dense_cadence_s"))
    if effective_tout is None or dense is None:
        cadence_status = "UNKNOWN"
    else:
        cadence_status = "AVAILABLE"
    return {
        "sentinel_id": sid,
        "family_id": row.get("family_id"),
        "physical_case_id": row.get("physical_case_id"),
        "runtime_case_alias": row.get("runtime_case_alias"),
        "current_row_binding": {
            "trajectory": row.get("trajectory"),
            "conversion_report": row.get("conversion_report"),
            "generated_xml": record(xml_path, digest=True),
            "solver_receipt": record(solver_path, digest=True),
        },
        "source_xml": xml,
        "source_solver_controls": solver,
        "effective_time_window_s": [0.0, actual_end],
        "window_end_s": actual_end,
        "source_particles": row.get("particles") or xml.get("particles"),
        "source_fluid_particles": xml.get("fluid_particle_count"),
        "source_sample_mass_kg": xml.get("sample_mass_kg"),
        "source_cfl": xml.get("cfl"),
        "half_cfl": review_row_data.get("proposed_half_cfl"),
        "effective_output_cadence_s": effective_tout,
        "review_dense_cadence_s": dense,
        "cadence_status": cadence_status,
        "part_stats": part_stats,
        "canary": {
            "source_pair_bytes": canary_row.get("source_pair_bytes"),
            "compressed_pair_bytes": canary_row.get("compressed_pair_bytes"),
            "pair_ratio": canary_row.get("pair_ratio"),
            "roundtrip_scope": "two exact source frames; ratio is a measured archive planning basis, not a full-time guarantee",
        },
        "canary_pair_ratio": canary_row.get("pair_ratio"),
        "review_recipe": {
            "actual_dp_m": review_row_data.get("actual_dp_m"),
            "proposed_spacing_m": review_row_data.get("proposed_spacing_m"),
            "existing_native_time_window_s": review_row_data.get("existing_native_time_window_s"),
            "nominal_tmax_s": review_row_data.get("nominal_tmax_s"),
            "nominal_cadence_s": review_row_data.get("nominal_cadence_s"),
            "dense_cadence_s": dense,
            "baseline_cfl": review_row_data.get("baseline_cfl"),
            "half_cfl": review_row_data.get("proposed_half_cfl"),
        },
        "physical_query_scope": {
            "cross_family_intersection_s": [0.0, 1.0],
            "full_sentinel_window_retained": True,
            "query_policy": "common [0,1] is only a cross-family intersection; per-sentinel full window and late-event/reference tasks remain required",
        },
        "motion_audit": None,
    }


def build_output() -> dict[str, Any]:
    current = load(CURRENT)
    review = load(REVIEW)
    canary = load(CANARY)
    candidates_by_sid = manifest_candidates()
    sources: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    for sid in SENTINEL_ORDER:
        source = build_source(sid, current, review, canary)
        source_xml = source["source_xml"]
        source_solver = source["source_solver_controls"]
        source["motion_audit"] = motion_audit(sid, Path(source_xml["path"]), source_solver, candidates_by_sid[sid][0])
        sources.append(source)
        candidates = []
        for candidate in candidates_by_sid[sid]:
            audited = candidate_audit(sid, source_xml, source_solver, candidate)
            candidates.append(audited)
            # The cost scenarios are kept nested under each actual grid so a
            # total cannot be mistaken for one baseline run multiplied by 14.
            scenarios = []
            downsample = source.get("effective_output_cadence_s")
            dense = source.get("review_dense_cadence_s")
            if downsample is not None:
                scenarios.extend(cost_scenario(source, {**audited, "requested_dp_m": candidate.get("dp_m")}, mode, "downsample", downsample) for mode in ("same_cfl", "half_cfl"))
            if dense is not None:
                scenarios.extend(cost_scenario(source, {**audited, "requested_dp_m": candidate.get("dp_m")}, mode, "dense", dense) for mode in ("same_cfl", "half_cfl"))
            audited["campaign_cost_scenarios"] = scenarios
            candidate_rows.append({"sentinel_id": sid, **audited})
    totals: dict[str, dict[str, Any]] = {}
    for row in candidate_rows:
        for scenario in row.get("campaign_cost_scenarios", []):
            if scenario.get("status") == "UNKNOWN":
                continue
            key = f"{row['sentinel_id']}/{scenario['grid_label']}/{scenario['cfl_mode']}/{scenario['cadence_kind']}"
            totals[key] = scenario
    aggregate_by_variant: dict[str, dict[str, Any]] = {}
    for row in candidate_rows:
        for scenario in row.get("campaign_cost_scenarios", []):
            if scenario.get("status") == "UNKNOWN":
                continue
            key = f"{scenario['grid_label']}/{scenario['cfl_mode']}/{scenario['cadence_kind']}"
            agg = aggregate_by_variant.setdefault(key, {"variant": key, "sentinel_count": 0, "planned_frames": 0, "raw_native_reserved_bytes": 0, "typed_reserved_bytes": 0, "archive_native_reserved_bytes": 0, "temporary_peak_proxy_bytes": 0, "persistent_total_reserved_bytes": 0, "status": "PLANNED_NO_SOLVER"})
            agg["sentinel_count"] += 1
            for field in ("planned_frames", "raw_native_reserved_bytes", "typed_reserved_bytes", "archive_native_reserved_bytes", "temporary_peak_proxy_bytes", "persistent_total_reserved_bytes"):
                if scenario.get(field) is not None:
                    agg[field] += scenario[field]
    for agg in aggregate_by_variant.values():
        for field in ("raw_native_reserved_bytes", "typed_reserved_bytes", "archive_native_reserved_bytes", "temporary_peak_proxy_bytes", "persistent_total_reserved_bytes"):
            agg[field.replace("_bytes", "_gib")] = gib(agg[field])
    home = shutil.disk_usage("/home/jade")
    audit_code = Path(__file__).resolve()
    audit_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()
    return {
        "schema": SCHEMA,
        "status": "PREPARED_DIAGNOSTIC_ONLY",
        "generated_at": "runtime_read_only_audit",
        "audit_code": {**record(audit_code, digest=True), "git_commit": audit_commit},
        "source_inputs": {
            "current": record(CURRENT, digest=True),
            "review": record(REVIEW, digest=True),
            "lossless_canary": record(CANARY, digest=True),
            "common_physical_query_plan": record(COMMON_QUERY, digest=True),
            "spatial_manifests": [record(path, digest=True) for path in (OLD_MANIFEST, F3_MANIFEST, REMAINING_MANIFEST)],
        },
        "scientific_status_contract": {
            "gencase_receipt_success": "source-bound input/preflight only",
            "mass_gate": "diagnostic only; <=1% target and <=2% hard upper bound are not QI/QN/QE",
            "continuous_region_and_dynamics": "UNKNOWN until guarded solver and independent observer calibration",
            "solver_started": False,
            "gpu_dispatch": "NOT_REQUESTED_BY_THIS_AUDIT",
        },
        "error_budget_registration": {
            "position": "2% L scale; 5% near event",
            "velocity_ke": "5% nonzero scale",
            "regional_mass": "3 percentage points",
            "event_time": "1% characteristic time",
            "time_output": "each <= one quarter of total gate",
            "status": "pre_registered_before results; consumer calibration still required to freeze final observer thresholds",
        },
        "storage_planning_policy": {
            "basis": "actual Part_0000 bytes, actual candidate particle counts, actual per-sentinel two-frame gzip ratio",
            "full_window": "CURRENT actual endpoint retained per sentinel; no [0,1] truncation and no extrapolation",
            "native_raw_frame_safety": SAFETY["native_raw_frame"],
            "typed_uncompressed_multiplier": SAFETY["typed_uncompressed"],
            "typed_temporary_safety": SAFETY["typed_temporary"],
            "lossless_archive_safety": SAFETY["lossless_archive"],
            "temporary_peak_safety": SAFETY["temporary_peak"],
            "archive_ratio_limit": "measured pair ratio is only a planning proxy; full-time archive must be measured after guarded output",
            "raw_preservation": "retain raw native and never overwrite/delete consumed source",
            "cpu_wall_time": "UNKNOWN_UNTIL_GUARDED_SOLVER; storage does not imply wall-time upper bound",
        },
        "resource_snapshot": {
            "home_free_bytes": home.free,
            "home_free_gib": gib(home.free),
            "home_floor_gib": 500.0,
            "spare_above_floor_gib": gib(home.free - 500 * GIB),
            "scheduler_authority": "primary parent; no lease or GPU reservation created",
        },
        "sources": sources,
        "candidate_quality_and_controls": candidate_rows,
        "aggregate_campaign_variants": sorted(aggregate_by_variant.values(), key=lambda row: row["variant"]),
        "aggregate_variant_policy": "Each row is sentinel × grid × CFL mode × output cadence; totals are sums of those actual variants, never 14× one baseline.",
        "unknowns": [
            "actual solver dt/clamp and wall time for every new grid/control pair",
            "full-time native frame byte variation and full-time compression ratio",
            "typed reader/observer conversion cost for each new grid",
            "scientific spatial/temporal equivalence and all QI/QN/QE labels",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    value = build_output()
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if args.write:
        if args.output.exists():
            raise FileExistsError(f"refuse to overwrite existing output: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                fd = -1
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if fd >= 0:
                os.close(fd)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
