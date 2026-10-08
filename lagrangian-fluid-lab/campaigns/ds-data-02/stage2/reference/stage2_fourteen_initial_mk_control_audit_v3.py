#!/usr/bin/env python3
"""Audit all fourteen CURRENT sentinels from exact XML/receipt metadata.

The audit reads the frozen quality manifest, the exact source/candidate XML
files named by that manifest, and their small GenCase receipts.  It does not
read BI4/H5 payloads or start a solver.  Candidate receipts therefore prove
GenCase preparation only; candidate solver end windows remain UNKNOWN until a
parent-guarded run completes.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
QUALITY = REFERENCE / "stage2_reference_quality_cost_v2.json"
PAIR_BINDING = REFERENCE / "stage2_savedt_cfl_pair_binding_v1.json"
F4_PAIR_BINDING = REFERENCE / "stage2_f4_dp0_savedt_pair_binding_v1.json"
PRIORITY_REPORT = REFERENCE / "stage2_priority_four_savedt_requests_v2.json"
PRIORITY_DIR = STAGE2 / "requests/stage2-priority-four-savedt-v2"
OUTPUT = REFERENCE / "stage2_fourteen_initial_mk_control_audit_v3.json"
SCHEMA = "ds02.stage2.fourteen-initial-mk-control-audit.v3"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path_text: str | Path) -> dict[str, Any]:
    path = Path(path_text).resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256_file(path)}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def float_attr(node: ET.Element | None, name: str) -> float | None:
    if node is None or node.get(name) is None:
        return None
    try:
        return float(node.get(name, ""))
    except ValueError:
        return None


def xml_audit(path_text: str | Path) -> dict[str, Any]:
    path = Path(path_text).resolve()
    root = ET.parse(path).getroot()
    execution = next((n for n in root.iter() if local_tag(n.tag) == "execution"), None)
    casedef = next((n for n in root.iter() if local_tag(n.tag) == "casedef"), None)
    constants = next((n for n in (execution.iter() if execution is not None else []) if local_tag(n.tag) == "constants"), None)
    parameters: dict[str, str] = {}
    for node in (execution.iter() if execution is not None else []):
        if local_tag(node.tag) == "parameter" and node.get("key"):
            parameters[node.get("key", "")] = node.get("value", "")
    constants_values: dict[str, Any] = {}
    for node in (constants.iter() if constants is not None else []):
        key = local_tag(node.tag)
        if key in {"dp", "h", "massfluid", "massbound", "cflnumber", "rhop0"} and node.get("value") is not None:
            try:
                constants_values[key] = float(node.get("value", ""))
            except ValueError:
                constants_values[key] = node.get("value")
    particles = next((n for n in (execution.iter() if execution is not None else []) if local_tag(n.tag) == "particles"), None)
    fluid_blocks: list[dict[str, Any]] = []
    floating_blocks: list[dict[str, Any]] = []
    if particles is not None:
        for node in particles:
            key = local_tag(node.tag)
            if key == "fluid" and node.get("count") is not None and node.get("mkfluid") is not None:
                fluid_blocks.append({
                    "mkfluid": node.get("mkfluid"),
                    "mk": node.get("mk"),
                    "begin": node.get("begin"),
                    "count": int(node.get("count", "0")),
                })
            elif key == "floating" and node.get("count") is not None:
                floating_blocks.append({
                    "mkbound": node.get("mkbound"),
                    "mk": node.get("mk"),
                    "begin": node.get("begin"),
                    "count": int(node.get("count", "0")),
                    "massbody_kg": float_attr(next((x for x in node if local_tag(x.tag) == "massbody"), None), "value"),
                    "masspart_kg": float_attr(next((x for x in node if local_tag(x.tag) == "masspart"), None), "value"),
                    "center_m": _vector(next((x for x in node if local_tag(x.tag) == "center"), None)),
                    "inertia_diag_kg_m2": _vector(next((x for x in node if local_tag(x.tag) == "inertia"), None)),
                })
    # Some source definitions contain the rigid contract only in casedef.
    if not floating_blocks and casedef is not None:
        for node in casedef.iter():
            if local_tag(node.tag) != "floating":
                continue
            massbody = next((x for x in node if local_tag(x.tag) == "massbody"), None)
            center = next((x for x in node if local_tag(x.tag) == "center"), None)
            inertia = next((x for x in node if local_tag(x.tag) == "inertia"), None)
            floating_blocks.append({
                "mkbound": node.get("mkbound"),
                "mk": None,
                "begin": None,
                "count": None,
                "massbody_kg": float_attr(massbody, "value"),
                "masspart_kg": None,
                "center_m": _vector(center),
                "inertia_diag_kg_m2": _vector(inertia),
            })
    massfluid = constants_values.get("massfluid")
    for block in fluid_blocks:
        block["sample_mass_kg"] = None if massfluid is None else block["count"] * massfluid
    return {
        "file": record(path),
        "definition_dp_m": _definition_dp(casedef),
        "h_m": constants_values.get("h"),
        "cfl": constants_values.get("cflnumber"),
        "gravity_m_s2": _gravity(root),
        "parameters": parameters,
        "massfluid_kg": massfluid,
        "fluid_blocks": fluid_blocks,
        "fluid_particle_count": sum(b["count"] for b in fluid_blocks),
        "sample_mass_kg": None if massfluid is None else sum(b["count"] for b in fluid_blocks) * massfluid,
        "floating_blocks": floating_blocks,
        "motion_refs": _motion_refs(root),
    }


def _vector(node: ET.Element | None) -> list[float] | None:
    if node is None:
        return None
    values = []
    for axis in ("x", "y", "z"):
        value = node.get(axis)
        if value is None:
            return None
        try:
            values.append(float(value))
        except ValueError:
            return None
    return values


def _gravity(root: ET.Element) -> list[float] | None:
    node = next((n for n in root.iter() if local_tag(n.tag) == "gravity"), None)
    return _vector(node)


def _definition_dp(casedef: ET.Element | None) -> float | None:
    if casedef is None:
        return None
    node = next((n for n in casedef.iter() if local_tag(n.tag) == "definition"), None)
    return float_attr(node, "dp")


def _motion_refs(root: ET.Element) -> list[str]:
    refs: list[str] = []
    for node in root.iter():
        if local_tag(node.tag) in {"motion", "file"}:
            value = node.get("file") or node.get("name")
            if value:
                refs.append(value)
    return sorted(set(refs))


def source_fluid_by_mk(xml: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(x["mkfluid"]): x for x in xml["fluid_blocks"]}


def compare_float(a: float | None, b: float | None, tol: float = 1e-12) -> bool | str:
    if a is None or b is None:
        return "UNKNOWN"
    return bool(math.isclose(a, b, rel_tol=0.0, abs_tol=tol))


def compare_vector(a: list[float] | None, b: list[float] | None, tol: float = 1e-10) -> dict[str, Any]:
    if a is None or b is None:
        return {"status": "UNKNOWN", "source": a, "candidate": b}
    deltas = [y - x for x, y in zip(a, b)]
    return {"status": all(abs(x) <= tol for x in deltas), "source": a, "candidate": b, "delta": deltas, "tol": tol}


def candidate_row(row: dict[str, Any], source_xml: dict[str, Any], source_controls: dict[str, Any]) -> dict[str, Any]:
    metadata = row["generated_xml"]["metadata"]
    path = metadata["path"]
    parsed = xml_audit(path)
    source_by_mk = source_fluid_by_mk(source_xml)
    candidate_by_mk = source_fluid_by_mk(parsed)
    per_mk: list[dict[str, Any]] = []
    for mkfluid, block in candidate_by_mk.items():
        source_block = source_by_mk.get(mkfluid)
        source_mass = None if source_block is None else source_block["sample_mass_kg"]
        candidate_mass = block["sample_mass_kg"]
        delta = None if source_mass is None else candidate_mass - source_mass
        per_mk.append({
            "mkfluid": mkfluid,
            "source_count": None if source_block is None else source_block["count"],
            "candidate_count": block["count"],
            "source_mass_kg": source_mass,
            "candidate_mass_kg": candidate_mass,
            "delta_kg": delta,
            "delta_pct_of_source_mk": None if not source_mass else 100.0 * delta / source_mass,
            "delta_percentage_points_of_source_whole": None if not source_xml["sample_mass_kg"] else 100.0 * delta / source_xml["sample_mass_kg"],
            "mk_present_in_source": source_block is not None,
        })
    for mkfluid, block in source_by_mk.items():
        if mkfluid not in candidate_by_mk:
            per_mk.append({"mkfluid": mkfluid, "source_count": block["count"], "candidate_count": None, "source_mass_kg": block["sample_mass_kg"], "candidate_mass_kg": None, "delta_kg": None, "delta_pct_of_source_mk": None, "delta_percentage_points_of_source_whole": None, "mk_present_in_source": False})
    source_float = source_xml["floating_blocks"]
    candidate_float = parsed["floating_blocks"]
    rigid: dict[str, Any]
    if not source_float and not candidate_float:
        rigid = {"status": "NOT_APPLICABLE"}
    elif len(source_float) == 1 and len(candidate_float) == 1:
        sf, cf = source_float[0], candidate_float[0]
        rigid = {
            "status": "PASS_EXACT_CONTRACT" if all(x.get("status") is True for x in [
                {"status": compare_float(sf.get("massbody_kg"), cf.get("massbody_kg"))},
                compare_vector(sf.get("center_m"), cf.get("center_m")),
                compare_vector(sf.get("inertia_diag_kg_m2"), cf.get("inertia_diag_kg_m2")),
            ]) else "FAIL_OR_UNKNOWN_CONTRACT",
            "massbody_kg": compare_float(sf.get("massbody_kg"), cf.get("massbody_kg")),
            "center_m": compare_vector(sf.get("center_m"), cf.get("center_m")),
            "inertia_diag_kg_m2": compare_vector(sf.get("inertia_diag_kg_m2"), cf.get("inertia_diag_kg_m2")),
            "sample_mass_semantics": "particle sample mass is separate from rigid physical massbody; no substitution",
        }
    else:
        rigid = {"status": "UNKNOWN_CONTRACT_BLOCK_COUNT", "source_blocks": source_float, "candidate_blocks": candidate_float}
    terminal = row.get("receipt_terminal", {})
    control = row.get("control_terminal", {})
    return {
        "label": row.get("label"),
        "requested_dp_m": row.get("requested_dp_m"),
        "generated_xml": parsed,
        "gencase_receipt": record(row["receipt_path"]),
        "gencase_terminal": terminal,
        "whole_initial_mass": {
            "source_kg": source_xml["sample_mass_kg"],
            "candidate_kg": parsed["sample_mass_kg"],
            "error_pct": row.get("mass_diagnostic", {}).get("deviation_pct_vs_source"),
            "gate": row.get("mass_diagnostic", {}).get("gate", "UNKNOWN"),
            "meaning": "GenCase particle initialization diagnostic only; no scientific qualification",
        },
        "per_mk_mass": per_mk,
        "rigid_contract": rigid,
        "control_match": {
            "xml_vs_source": control.get("candidate_xml_vs_source_xml", "UNKNOWN"),
            "continuous_geometry": control.get("continuous_geometry_control", "UNKNOWN"),
            "motion_or_acceleration_changed": control.get("continuous_geometry_control", {}).get("motion_or_acceleration_changed", "UNKNOWN") if isinstance(control.get("continuous_geometry_control"), dict) else "UNKNOWN",
            "candidate_solver_status": control.get("solver_candidate_status", "UNKNOWN"),
        },
        "candidate_solver_end_window": "UNKNOWN_NO_CANDIDATE_SOLVER_RECEIPT",
    }


def pair_requests() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path, label in ((PAIR_BINDING, "generic_pair"), (F4_PAIR_BINDING, "f4_pair")):
        data = load(path)
        rows = data.get("requests", []) if label == "generic_pair" else [
            {"sentinel_id": "F4-S1", "mode": x.get("mode"), "request_path": x.get("request", {}).get("path"), "launch_disabled": True}
            for x in data.get("modes", [])
        ]
        for row in rows:
            sid = row.get("sentinel_id")
            req = Path(row["request_path"]) if row.get("request_path") else None
            if sid and req and req.is_file():
                request = load(req)
                result.setdefault(sid, {})[row.get("mode", "UNKNOWN")] = {
                    "kind": label,
                    "request": record(req),
                    "launch_disabled": request.get("launch_disabled", request.get("launch_policy", {}).get("launch_disabled", True)),
                    "physical_window_s": request.get("physical_window_s"),
                    "planned_frames": request.get("planned_frames", row.get("planned_frames")),
                    "source_bound_preparation_only": True,
                }
    if PRIORITY_REPORT.is_file():
        report = load(PRIORITY_REPORT)
        for item in report.get("requests", []):
            path = Path(item["path"])
            if not path.is_file():
                continue
            request = load(path)
            result.setdefault(item["sentinel_id"], {})[item["mode"]] = {
                "kind": "priority_v2_forward",
                "request": record(path),
                "launch_disabled": request.get("launch_policy", {}).get("launch_disabled"),
                "physical_window_s": request.get("physical_window_s"),
                "planned_frames": request.get("expected_native_frames"),
                "source_bound_preparation_only": True,
            }
    return result


def main() -> None:
    quality = load(QUALITY)
    sources = {row["sentinel_id"]: row for row in quality["sources"]}
    candidates_by_sid: dict[str, list[dict[str, Any]]] = {}
    for row in quality["candidate_quality_and_controls"]:
        candidates_by_sid.setdefault(row["sentinel_id"], []).append(row)
    pairs = pair_requests()
    sentinels: dict[str, Any] = {}
    all_records = [record(QUALITY), record(PAIR_BINDING), record(F4_PAIR_BINDING)]
    for sid, source in sources.items():
        source_xml = xml_audit(source["source_xml"]["path"])
        source_controls = source["source_solver_controls"]
        source_receipt = record(source_controls["receipt"]["path"])
        all_records.append(source_xml["file"])
        candidates: list[dict[str, Any]] = []
        for row in candidates_by_sid.get(sid, []):
            candidates.append(candidate_row(row, source_xml, source_controls))
            all_records.extend([candidates[-1]["generated_xml"]["file"], candidates[-1]["gencase_receipt"]])
        source_fluid = source_fluid_by_mk(source_xml)
        source_terminal = {
            "receipt": source_receipt,
            "status": source_controls.get("status"),
            "returncode": source_controls.get("returncode"),
            "command": source_controls.get("command"),
            "actual_cli_tmax_s": source_controls.get("tmax_s"),
            "actual_cli_tout_s": source_controls.get("tout_s"),
            "actual_saved_window_s": source.get("effective_time_window_s"),
            "actual_window_end_s": source.get("window_end_s"),
            "source_xml_timemax": source_xml["parameters"].get("TimeMax"),
            "source_xml_timeout": source_xml["parameters"].get("TimeOut"),
            "terminal_control_closure": "ACTUAL_COMPLETED_RECEIPT_AND_XML_BOUND",
            "output_frame_count": source.get("part_stats", {}).get("frame_count_from_parts"),
            "output_bytes_first_frame": source.get("part_stats", {}).get("frame0_bytes"),
            "output_bytes_last_frame": source.get("part_stats", {}).get("last_frame_bytes"),
        }
        pass_candidates = [x for x in candidates if "PASS_TARGET_1PCT" in str(x["whole_initial_mass"]["gate"])]
        sentinels[sid] = {
            "family_id": source["family_id"],
            "physical_case_id": source["physical_case_id"],
            "source_initial_state": {
                "xml": source_xml,
                "fluid_by_mk": source_fluid,
                "sample_mass_kg": source_xml["sample_mass_kg"],
                "rigid_contract": source_xml["floating_blocks"] or "NOT_APPLICABLE",
                "motion_refs": source_xml["motion_refs"],
            },
            "source_terminal_control_and_window": source_terminal,
            "candidate_initial_and_mk_audits": candidates,
            "candidate_mass_gate_summary": {
                "total_candidates": len(candidates),
                "target_within_1pct": len(pass_candidates),
                "candidate_solver_end_window": "UNKNOWN_FOR_ALL_CANDIDATES_UNTIL_PARENT_GUARDED_SOLVER",
            },
            "next_information_gain": {
                "space": "use only candidates with PASS_TARGET_1PCT whole initial mass and intentional dp/h spacing; continuous geometry/control remains prechecked input-copy evidence",
                "time": "use source-bound same/half-CFL Savedt pair with full CURRENT source window; actual dt/clamp/output is UNKNOWN until guarded run",
                "output": "retain complete native window; typed/downsample is derived after raw retention; no frame-index alignment or extrapolation",
                "source_bound_requests": pairs.get(sid, "UNKNOWN_NO_CLOSED_PAIR_REQUEST"),
                "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            },
        }
    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_XML_RECEIPT_INITIAL_MK_CONTROL_AUDIT_ALL_14",
        "generated_at_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip(),
        "source_inputs": {"quality": record(QUALITY), "pair_binding": record(PAIR_BINDING), "f4_pair_binding": record(F4_PAIR_BINDING), "priority_v2": record(PRIORITY_REPORT) if PRIORITY_REPORT.is_file() else "UNKNOWN"},
        "policy": {
            "source_identity": "exact quality manifest source XML/receipt paths; no latest glob",
            "mass": "whole initial fluid mass and per-mk particle sample mass are diagnostics; no rescaling",
            "rigid": "F6 sample particle mass is separate from physical massbody/inertia/COM",
            "window": "source actual completed CLI/RunPART terminal window is recorded; candidate GenCase is not a solver run",
            "geometry": "normalized definition/dependency checks remain prechecked input evidence, not continuous-field equivalence",
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "reads_hdf5": False,
            "reads_native_payloads": False,
            "starts_solver": False,
            "starts_gpu": False,
        },
        "sentinel_count": len(sentinels),
        "families": sentinels,
    }
    # Keep the source list compact and prove only the small XML/receipt files
    # were accessed by this worker; no H5/BI4 path enters this list.
    report["small_file_access_summary"] = {
        "records": len(all_records),
        "file_suffixes": sorted({Path(x["path"]).suffix for x in all_records}),
        "contains_h5": any(str(x["path"]).endswith(".h5") for x in all_records),
        "contains_bi4": any(str(x["path"]).endswith(".bi4") for x in all_records),
    }
    if OUTPUT.exists():
        raise FileExistsError(f"refuse overwrite: {OUTPUT}")
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(OUTPUT), "sentinels": len(sentinels)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
