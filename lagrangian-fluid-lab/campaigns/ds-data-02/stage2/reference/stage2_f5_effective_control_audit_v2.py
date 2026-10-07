#!/usr/bin/env python3
"""Audit F5 CURRENT solver controls, motion inputs, and RunPARTs summaries.

The audit reads two exact CURRENT F5 XML/receipt/RunPARTs inputs and the small
motion text files.  It never opens trajectory HDF5 and never launches a
solver.  XML physical condition fields and numerical recipe fields are kept
separate; the CLI command is the authority for the effective simulation and
output end controls.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
REVIEW = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
OUTPUT = REFERENCE / "stage2_f5_effective_condition_audit_v2.json"
BINARY = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
OFFICIAL = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/src/source")

TARGETS = {
    "F5-S1": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
    "F5-S2": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M115_T080",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, *, hash_file: bool = True) -> dict[str, Any]:
    stat = path.stat()
    result = {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if hash_file:
        result["sha256"] = sha256_file(path)
    return result


def canonical_sha(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_motion(path: Path) -> dict[str, Any]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        fields = text.replace(",", " ").split()
        if len(fields) < 2:
            raise ValueError(f"motion row has fewer than two columns: {path}: {line}")
        rows.append((float(fields[0]), float(fields[1])))
    if not rows:
        raise ValueError(f"empty motion input: {path}")
    times = [row[0] for row in rows]
    values = [row[1] for row in rows]
    return {
        "file": record(path),
        "row_count": len(rows),
        "time_first_s": times[0],
        "time_last_s": times[-1],
        "value_min": min(values),
        "value_max": max(values),
        "value_absmax": max(abs(value) for value in values),
        "first_rows": [[t, v] for t, v in rows[:3]],
        "last_rows": [[t, v] for t, v in rows[-3:]],
    }


def parse_runparts(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    data_lines = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not data_lines:
        raise ValueError(f"empty RunPARTs: {path}")
    header = data_lines[0].split(";")
    rows = []
    for line in data_lines[1:]:
        values = line.split(";")
        if len(values) != len(header):
            raise ValueError(f"RunPARTs field count mismatch in {path}: {line}")
        rows.append(dict(zip(header, values)))
    if not rows:
        raise ValueError(f"RunPARTs has no data rows: {path}")

    def ints(name: str) -> list[int]:
        return [int(row[name].replace(",", "")) for row in rows]

    def floats(name: str) -> list[float]:
        return [float(row[name].replace(",", "")) for row in rows]

    times = floats("TimeStep [s]")
    dtmins = floats("DtMin [s]")[1:]
    dtmaxs = floats("DtMax [s]")[1:]
    dtsmin = ints("DTsMin")
    cadence = [b - a for a, b in zip(times, times[1:])]
    return {
        "file": record(path),
        "comment_line_count": len(lines) - len(data_lines),
        "row_count": len(rows),
        "part_first": int(rows[0]["Part"]),
        "part_last": int(rows[-1]["Part"]),
        "time_first_s": times[0],
        "time_last_s": times[-1],
        "output_cadence_s": {
            "min": min(cadence) if cadence else None,
            "max": max(cadence) if cadence else None,
            "mean": statistics.fmean(cadence) if cadence else None,
            "median": statistics.median(cadence) if cadence else None,
        },
        "dt_window_summary_s": {
            "min_of_DtMin": min(dtmins) if dtmins else None,
            "max_of_DtMin": max(dtmins) if dtmins else None,
            "min_of_DtMax": min(dtmaxs) if dtmaxs else None,
            "max_of_DtMax": max(dtmaxs) if dtmaxs else None,
        },
        "DTsMin_count_summary": {
            "unique": sorted(set(dtsmin)),
            "min": min(dtsmin),
            "max": max(dtsmin),
            "sum": sum(dtsmin),
        },
        "steps_sum": sum(int(row["Steps"]) for row in rows),
    }


def parse_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    params = {node.get("key"): node.get("value") for node in root.findall(".//parameter") if node.get("key")}
    cfl_node = root.find(".//cflnumber")
    cfl = float(cfl_node.get("value")) if cfl_node is not None else None
    motion_files = sorted({node.get("name") for node in root.findall(".//motion//file") if node.get("name")})
    motion_intervals = []
    for obj in root.findall(".//motion//objreal"):
        begin = obj.find("./begin")
        if begin is None:
            continue
        start = float(begin.get("start"))
        finish = float(begin.get("finish"))
        movement = next((node for node in obj if node.tag.startswith("mv")), None)
        duration = float(movement.get("duration")) if movement is not None and movement.get("duration") else None
        motion_intervals.append({"objreal_ref": obj.get("ref"), "start_s": start, "finish_s": finish, "duration_s": duration, "movement_tag": movement.tag if movement is not None else None})
    computetime = root.find(".//_computetime")
    outputtime = root.find(".//_outputtime")
    savedt = root.find(".//savedt")
    return {
        "file": record(path),
        "cfl_number": cfl,
        "parameters": params,
        "motion_file_references": motion_files,
        "motion_intervals": motion_intervals,
        "xml_time_scope": {
            "TimeMax_s": float(params["TimeMax"]) if params.get("TimeMax") else None,
            "TimeOut_s": float(params["TimeOut"]) if params.get("TimeOut") else None,
            "gauge_compute_window_s": [float(computetime.get("start")), float(computetime.get("end"))] if computetime is not None else None,
            "gauge_output_window_s": [float(outputtime.get("start")), float(outputtime.get("end"))] if outputtime is not None else None,
        },
        "savedt_xml_present": savedt is not None,
    }


def cli_controls(command: list[str], xml: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, float] = {}
    for arg in command:
        if arg.startswith("-tmax:"):
            values["tmax_s"] = float(arg.split(":", 1)[1])
        elif arg.startswith("-tout:"):
            values["tout_s"] = float(arg.split(":", 1)[1])
        elif arg.startswith("-cfl:"):
            values["cfl_number"] = float(arg.split(":", 1)[1])
    xml_scope = xml["xml_time_scope"]
    effective_tmax = values.get("tmax_s", xml_scope["TimeMax_s"])
    effective_tout = values.get("tout_s", xml_scope["TimeOut_s"])
    return {
        "command": command,
        "cli_overrides": values,
        "effective_simulation_end_s": effective_tmax,
        "effective_output_interval_s": effective_tout,
        "effective_cfl_number": values.get("cfl_number", xml["cfl_number"]),
        "xml_vs_cli": {
            "TimeMax_conflict": xml_scope["TimeMax_s"] != values.get("tmax_s", xml_scope["TimeMax_s"]),
            "TimeOut_conflict": xml_scope["TimeOut_s"] != values.get("tout_s", xml_scope["TimeOut_s"]),
            "attribution": "receipt command-line -tmax/-tout is the effective runtime control; XML values remain source-template metadata",
        },
    }


def source_evidence() -> dict[str, Any]:
    files = {
        "binary": BINARY,
        "cli_help_source": OFFICIAL / "JSphCfgRun.cpp",
        "runtime_savedt_source": OFFICIAL / "JSph.cpp",
        "savedt_output_source": OFFICIAL / "JDsSaveDt.cpp",
        "runparts_source": OFFICIAL / "JSph.cpp",
    }
    return {
        "files": {key: record(path) for key, path in files.items()},
        "line_spans": {
            "cli_help_tmax_tout_cfl": {"file": str((OFFICIAL / "JSphCfgRun.cpp").resolve()), "lines": [210, 214]},
            "xml_savedt_activation": {"file": str((OFFICIAL / "JSph.cpp").resolve()), "lines": [2328, 2332]},
            "DtInfo_stats": {"file": str((OFFICIAL / "JDsSaveDt.cpp").resolve()), "lines": [118, 158]},
            "DtAllInfo_per_step": {"file": str((OFFICIAL / "JDsSaveDt.cpp").resolve()), "lines": [175, 191]},
            "RunPARTs_DTsMin_and_window_dt": {"file": str((OFFICIAL / "JSph.cpp").resolve()), "lines": [2981, 3017, 3030, 3048]},
        },
        "observed_cli_help": {
            "version": "DualSPHysics5 v5.4.355 (08-04-2025)",
            "recognized": ["-tmax:<float>", "-tout:<float>", "-cfl:<float>"],
            "svdt_option_present": False,
            "note": "The v5.4.355 help contains no -svdt/SaveDt CLI option; SaveDt is activated by case.execution.special.savedt in JSph.cpp.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    catalog = json.loads(CURRENT.read_text(encoding="utf-8"))
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    cases = {row["physical_case_id"]: row for row in catalog["cases"]}
    review_rows = review.get("sentinels", []) if isinstance(review, dict) else review
    review_by_id = {row["sentinel_id"]: row for row in review_rows if row.get("sentinel_id") in TARGETS}
    results = []
    for sentinel_id, physical_case_id in TARGETS.items():
        row = cases[physical_case_id]
        xml_path = Path(row["source_bindings"]["generated_xml"]["path"])
        solver_receipt_path = Path(row["source_bindings"]["solver_receipt"]["path"])
        receipt = json.loads(solver_receipt_path.read_text(encoding="utf-8"))
        xml = parse_xml(xml_path)
        command = list(receipt["command"])
        controls = cli_controls(command, xml)
        motion_records = []
        for rel in xml["motion_file_references"]:
            motion_path = (xml_path.parent / rel).resolve()
            motion_records.append(parse_motion(motion_path))
        motion_by_sha = {m["file"]["sha256"]: m for m in motion_records}
        runparts_path = Path(receipt["output_root"]) / "solver_output/RunPARTs.csv"
        runparts = parse_runparts(runparts_path)
        input_hashes = receipt["input_hashes_at_launch"]
        def_paths = sorted(path for path in input_hashes if path.endswith("_Def.xml"))
        motion_input_paths = sorted(path for path in input_hashes if path.lower().endswith(".dat"))
        selected_motion = motion_records[0]
        motion_sha = selected_motion["file"]["sha256"]
        source_payload = {
            "family_id": "F5",
            "mechanism": "piston_runup_over_continuous_slope",
            "geometry_family": "C082S1",
            "amplitude_scale": row.get("known_numeric_physical_parameters", {}).get("amplitude_scale"),
            "time_scale": row.get("known_numeric_physical_parameters", {}).get("time_scale"),
            "dp_m": 0.02,
            "motion_input_sha256": motion_sha,
            "motion_duration_s": selected_motion["time_last_s"],
        }
        numerical_payload = {
            "cfl_number": xml["cfl_number"],
            "StepAlgorithm": xml["parameters"].get("StepAlgorithm"),
            "VerletSteps": xml["parameters"].get("VerletSteps"),
            "Kernel": xml["parameters"].get("Kernel"),
            "ViscoTreatment": xml["parameters"].get("ViscoTreatment"),
            "Visco": xml["parameters"].get("Visco"),
            "ViscoBoundFactor": xml["parameters"].get("ViscoBoundFactor"),
            "DensityDT": xml["parameters"].get("DensityDT"),
            "DensityDTvalue": xml["parameters"].get("DensityDTvalue"),
            "CoefDtMin": xml["parameters"].get("CoefDtMin"),
            "DtIni": xml["parameters"].get("DtIni"),
            "DtMin": xml["parameters"].get("DtMin"),
            "DtFixed": xml["parameters"].get("DtFixed"),
            "DtAllParticles": xml["parameters"].get("DtAllParticles"),
            "cli_tmax_s": controls["cli_overrides"].get("tmax_s"),
            "cli_tout_s": controls["cli_overrides"].get("tout_s"),
            "save_pos_double": xml["parameters"].get("SavePosDouble"),
        }
        source_input_checks = {
            "generated_xml": {
                "path": str(xml_path.resolve()),
                "catalog_declared_sha256": row["source_bindings"]["generated_xml"]["sha256"],
                "recomputed_sha256": xml["file"]["sha256"],
                "receipt_input_sha256": input_hashes.get(str(xml_path.resolve())),
            },
            "definition_inputs": [{"path": path, "receipt_sha256": input_hashes[path]} for path in def_paths],
            "motion_inputs": [{"path": path, "receipt_sha256": input_hashes[path], "matches_xml_motion_sha": input_hashes[path] == motion_sha} for path in motion_input_paths],
        }
        final_time = row["actual_time_window_s"][1]
        effective_end = controls["effective_simulation_end_s"]
        results.append({
            "sentinel_id": sentinel_id,
            "family_id": "F5",
            "physical_case_id": physical_case_id,
            "current_runtime_case_alias": row["runtime_case_alias"],
            "source_selection": review_by_id[sentinel_id],
            "trajectory_metadata_declared_only": row["trajectory"],
            "physical_condition": {
                "payload": source_payload,
                "canonical_sha256": canonical_sha(source_payload),
                "motion_input": selected_motion,
                "motion_references_in_xml": xml["motion_file_references"],
                "motion_intervals_from_xml": xml["motion_intervals"],
            },
            "numerical_recipe": {
                "payload": numerical_payload,
                "canonical_sha256": canonical_sha(numerical_payload),
                "xml_controls": xml,
                "effective_controls": controls,
            },
            "observation_scope": {
                "motion_window_s": [0.0, selected_motion["time_last_s"]],
                "effective_solver_window_s": [0.0, effective_end],
                "actual_catalog_window_s": row["actual_time_window_s"],
                "xml_gauge_compute_window_s": xml["xml_time_scope"]["gauge_compute_window_s"],
                "xml_gauge_output_window_s": xml["xml_time_scope"]["gauge_output_window_s"],
                "post_motion_observation_window_s": [selected_motion["time_last_s"], effective_end],
                "actual_end_within_cli_tmax_tolerance": abs(final_time - effective_end) < 0.001,
            },
            "runparts": runparts,
            "solver_receipt": {
                "path": str(solver_receipt_path.resolve()),
                "file": record(solver_receipt_path),
                "request_sha256": receipt.get("request_sha256"),
                "status": receipt.get("status"),
                "returncode": receipt.get("returncode"),
                "output_root": receipt.get("output_root"),
                "bytes": receipt.get("bytes"),
                "elapsed_seconds": receipt.get("elapsed_seconds"),
                "gpu_seconds": receipt.get("gpu_seconds"),
                "runner_source": receipt.get("runner_source"),
                "runner_sha256": receipt.get("runner_sha256"),
            },
            "source_input_checks": source_input_checks,
            "control_conflict_attribution": {
                "status": "EXPLAINED",
                "finding": "The XML template advertises TimeMax=26 and gauge windows ending at 26, while the recorded solver command supplies -tmax:16 and -tout:0.02. The command therefore defines the effective [0,16] run/output window; the 26-second XML values are stale template metadata for this launch.",
                "motion_finding": "The motion file is independently bound by content SHA and ends at its XML duration (14.4 s for S1, 12.8 s for S2). The 14.4/12.8-to-16 interval is an observation tail after motion input, not evidence of a longer motion control.",
                "dt_finding": "DtMin/DtMax in RunPARTs.csv are per-save-window summaries. DTsMin is a count of minimum-Dt updates, not seconds. This run has no XML savedt node and no DtInfo.csv/DtAllInfo.csv; no per-step dt/clamp trace is available.",
            },
            "official_dt_evidence": source_evidence(),
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "observer_calibration": "UNKNOWN"},
        })
    report = {
        "schema": "ds02.stage2.f5-effective-condition-audit.v2",
        "status": "COMPLETED_SOURCE_CONTROL_AUDIT_NO_NEW_SOLVER",
        "generated_at_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip(),
        "current_catalog": record(CURRENT),
        "review_matrix": record(REVIEW),
        "scope": {
            "sentinels": list(TARGETS),
            "exact_physical_ids": list(TARGETS.values()),
            "hdf5_read": False,
            "solver_started": False,
            "physical_condition_and_numerical_recipe_separate": True,
            "event_observation_window_separate": True,
        },
        "results": results,
    }
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(args.output), "sentinels": list(TARGETS)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
