#!/usr/bin/env python3
"""Run the R3 F2 three-background, three-resolution primary matrix."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess

try:
    from scripts.campaign_runner import execute_attempt, require_idle_allowed_gpu
    from scripts.protocol_metrics import mass_fraction_tv
    from scripts.trajectory_io import convert_streaming
    from scripts.w02_semantics import partvtk_csv
    from scripts.w06_rotating_pour import (
        GENCASE, SOLVER, add_control_metadata, allowed_uuids, audit_case,
        definition_text, env, write_motion,
    )
except ModuleNotFoundError:
    from campaign_runner import execute_attempt, require_idle_allowed_gpu
    from protocol_metrics import mass_fraction_tv
    from trajectory_io import convert_streaming
    from w02_semantics import partvtk_csv
    from w06_rotating_pour import (
        GENCASE, SOLVER, add_control_metadata, allowed_uuids, audit_case,
        definition_text, env, write_motion,
    )


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
CASE_ROOT = CAMPAIGN / "cases" / "r3-g2-f2"
ARTIFACT = CAMPAIGN / "artifacts" / "r3-g2-f2"
RUN_ROOT = CAMPAIGN / "runs"
DATA = CAMPAIGN / "data" / "r3-g2-f2"
REPORT = CAMPAIGN / "r3-g2-f2-resolution.json"

BACKGROUNDS = {
    "slow_center": {"duration": 1.20, "receiver_x": 0.45, "receiver_y": 0.0, "angle": -105.0},
    "fast_center": {"duration": 0.50, "receiver_x": 0.45, "receiver_y": 0.0, "angle": -105.0},
    "offset_partial": {"duration": 0.85, "receiver_x": 0.45, "receiver_y": 0.22, "angle": -105.0},
}
RESOLUTIONS = {"coarse_selected": 0.025, "medium_selected": 0.018, "fine_selected": 0.0145}


def records() -> list[dict]:
    output = []
    gpu_cycle = [4, 5, 6, 7]
    for background, control in BACKGROUNDS.items():
        variants = (
            ("coarse_selected", "medium", RESOLUTIONS["coarse_selected"]),
            ("medium_selected", "massmatched_mid", RESOLUTIONS["medium_selected"]),
            ("fine_selected", "massmatched_fine", RESOLUTIONS["fine_selected"]),
        )
        for level, suffix, dp in variants:
            output.append({
                "case_id": f"R3_F2_{background}_{suffix}",
                "family": "F2", "background": background,
                "geometry": "standard", "cup_width": 0.425,
                "level": level, "dp": dp, "tout": 0.01,
                "boundary_method": 1, "solver_flags": [],
                "gpu": gpu_cycle[len(output) % len(gpu_cycle)],
                **control,
            })
    return output


def exploratory_grid_records() -> list[dict]:
    output = []
    variants = (
        ("mass_mismatched_coarse", "coarse", 0.035),
        ("grid_scan_mid", "refined_mid", 0.020),
        ("grid_scan_fine", "fine", 0.0175),
    )
    for background, control in BACKGROUNDS.items():
        for level, suffix, dp in variants:
            output.append({
                "case_id": f"R3_F2_{background}_{suffix}",
                "family": "F2", "background": background,
                "geometry": "standard", "cup_width": 0.425,
                "level": level, "dp": dp, "tout": 0.01,
                "boundary_method": 1, "solver_flags": [],
                "gpu": 4, **control,
            })
    return output


def retry_records() -> list[dict]:
    output = []
    for index, (background, control) in enumerate(BACKGROUNDS.items()):
        output.append({
            "case_id": f"R3_F2_{background}_fine_mdbc",
            "family": "F2", "background": background,
            "geometry": "standard", "cup_width": 0.425,
            "level": "fine_mdbc", "dp": 0.0175, "tout": 0.01,
            "boundary_method": 2, "solver_flags": ["-mdbc"],
            "gpu": [4, 5, 6][index], **control,
        })
    return output


def prepare(selected: list[dict]) -> None:
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    matrix = []
    for record in selected:
        definition = CASE_ROOT / f"{record['case_id']}_Def.xml"
        motion = CASE_ROOT / f"{record['case_id']}_motion.dat"
        definition.write_text(definition_text(record))
        write_motion(motion, record)
        generated = ARTIFACT / record["case_id"] / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        prefix = generated / record["case_id"]
        proc = subprocess.run(
            [str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"],
            cwd=CASE_ROOT, env=env(), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        (generated / "gencase.stdout.log").write_text(proc.stdout)
        (generated / motion.name).write_bytes(motion.read_bytes())
        if proc.returncode or not prefix.with_suffix(".xml").is_file():
            raise RuntimeError(f"GenCase failed for {record['case_id']}")
        match = re.search(r"Fluid\.\.\.\.:\s*([0-9,]+)", proc.stdout)
        matrix.append({
            key: record[key] for key in (
                "case_id", "family", "background", "level", "dp", "tout", "gpu",
                "duration", "receiver_x", "receiver_y", "angle", "cup_width", "boundary_method",
            )
        } | {
            "fluid_particles": int(match.group(1).replace(",", "")) if match else None,
            "execution_kind": "new independent primary run",
        })
    known = {item["case_id"]: item for item in matrix}
    matrix_path = CASE_ROOT / "matrix.json"
    if matrix_path.exists():
        known = {item["case_id"]: item for item in json.loads(matrix_path.read_text())} | known
    matrix_path.write_text(json.dumps(sorted(known.values(), key=lambda item: item["case_id"]), indent=2) + "\n")


def run_one(record: dict) -> dict:
    gpu = require_idle_allowed_gpu(record["gpu"], allowed_uuids())
    prefix = ARTIFACT / record["case_id"] / "generated" / record["case_id"]
    result = execute_attempt(
        record["case_id"],
        [str(SOLVER), f"-gpu:{record['gpu']}", *record["solver_flags"], str(prefix), "{output}"],
        RUN_ROOT, cwd=prefix.parent, env=env(), evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
    )
    result["gpu_at_launch"] = gpu
    if result["status"] != "completed":
        raise RuntimeError(f"{record['case_id']} failed: {result['attempt_directory']}")
    return result


def run(selected: list[dict]) -> list[dict]:
    queues = {gpu: [] for gpu in (4, 5, 6, 7)}
    for record in selected:
        queues[record["gpu"]].append(record)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(lambda queue: [run_one(item) for item in queue], queue) for queue in queues.values()]
        return [item for future in futures for item in future.result()]


def latest(case_id: str) -> Path:
    return Path(json.loads((RUN_ROOT / case_id / "latest.json").read_text())["attempt_directory"])


def normalize(selected: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for record in selected:
        attempt = latest(record["case_id"])
        csvs = partvtk_csv(attempt / "data", attempt / "csv", "-all,+fluid")
        output = DATA / f"{record['case_id']}.h5"
        convert_streaming(
            {"id": record["case_id"], "family": "F2", "mechanism": "rotating cup pour resolution", "shifting": 0},
            csvs, output,
        )
        add_control_metadata(output, record)


def metric_distribution(result: dict) -> dict[str, float]:
    fractions = dict(result["final_mass_fraction"])
    fractions["unavailable"] = fractions.pop("numerically_missing")
    return fractions


def analyze(run_results: list[dict] | None = None) -> dict:
    grouped = {}
    all_records = records()
    for background in BACKGROUNDS:
        grouped[background] = {}
        for record in [item for item in all_records if item["background"] == background]:
            result = audit_case(record, DATA / f"{record['case_id']}.h5")
            grouped[background][record["level"]] = {"dp_m": record["dp"], **result}
        coarse = metric_distribution(grouped[background]["coarse_selected"])
        medium = metric_distribution(grouped[background]["medium_selected"])
        fine = metric_distribution(grouped[background]["fine_selected"])
        grouped[background]["resolution_change"] = {
            "coarse_to_medium_mass_fraction_tv": mass_fraction_tv(coarse, medium),
            "medium_to_fine_mass_fraction_tv": mass_fraction_tv(medium, fine),
            "captured_absolute_change_medium_to_fine": abs(medium["captured"] - fine["captured"]),
            "median_exit_time_absolute_change_medium_to_fine_s": abs(
                grouped[background]["medium_selected"]["median_first_exit_time_s"]
                - grouped[background]["fine_selected"]["median_first_exit_time_s"]),
            "initial_mass_relative_range": (
                max(grouped[background][level]["initial_mass_kg"] for level in RESOLUTIONS)
                - min(grouped[background][level]["initial_mass_kg"] for level in RESOLUTIONS)
            ) / grouped[background]["fine_selected"]["initial_mass_kg"],
        }
    if run_results is None:
        run_results = [json.loads((RUN_ROOT / record["case_id"] / "latest.json").read_text()) for record in all_records]
    compact = [{
        "case_id": item["case_id"], "attempt_id": item["attempt_id"],
        "status": item["status"], "elapsed_seconds": item["elapsed_seconds"],
        "frames": len(item["evidence_files"]),
    } for item in run_results]
    payload = {
        "schema_version": 1,
        "scope": "F2 three-background by three-selected-resolution primary matrix",
        "acceptance_status": "rejected_current_numerics_no_resolution_stability",
        "causal_axes": {
            "physics": "fixed weakly-compressible water configuration",
            "geometry": "fixed standard cup and receiver",
            "control_backgrounds": list(BACKGROUNDS),
            "numerics_particle_spacing_m": list(RESOLUTIONS.values()),
            "observation_saved_cadence_s": 0.01,
            "solver_internal_timestep": "adaptive and recorded in solver logs; not equated with output cadence",
        },
        "backgrounds": grouped,
        "run_results": compact,
        "resource_summary": {
            "successful_runs": len(compact),
            "successful_solver_gpu_seconds": sum(item["elapsed_seconds"] for item in compact),
        },
        "validation_claim": "same-solver resolution sensitivity; F2 still lacks an external observation anchor",
        "gencase_dp_scan": [
            {"dp_m": dp, "fluid_particles": count, "initial_discrete_mass_kg": count * dp ** 3 * 1000}
            for dp, count in (
                (0.035, 770), (0.025, 1764), (0.023, 2250), (0.020, 3672),
                (0.018, 4693), (0.0175, 4940), (0.015, 8096), (0.0145, 8832),
            )
        ],
        "selection_rationale": "0.025/0.018/0.0145 spans 1.72x in dp while limiting initial discrete-mass range to about 2.4%",
    }
    available_preflight = [
        record for record in exploratory_grid_records()
        if (DATA / f"{record['case_id']}.h5").is_file()
    ]
    if available_preflight:
        payload["excluded_exploratory_grid"] = {
            "particle_spacing_m": sorted({record["dp"] for record in available_preflight}, reverse=True),
            "reason": "pre-run dp scan selected a wider 1.72x resolution range with only about 2.4% initial discrete-mass variation",
            "excluded_from_primary_matrix": True,
            "cases": {
                record["case_id"]: {"dp_m": record["dp"], **audit_case(record, DATA / f"{record['case_id']}.h5")}
                for record in available_preflight
            },
        }
    available_retries = [record for record in retry_records() if (DATA / f"{record['case_id']}.h5").is_file()]
    if available_retries:
        payload["diagnostic_retry"] = {
            "hypothesis": "fine-resolution discontinuity is caused by DBC leakage around the moving cup",
            "changed_axis": "boundary formulation DBC to mDBC at fixed fine dp",
            "not_part_of_primary_resolution_series": True,
            "acceptance_status": "inconclusive_invalid_boundary_normals",
            "solver_warning": "12232 to 16012 boundary particles lacked mDBC normal data",
            "backgrounds": {
                record["background"]: audit_case(record, DATA / f"{record['case_id']}.h5")
                for record in available_retries
            },
        }
    evidence_records = all_records + available_preflight + available_retries
    evidence_runs = [
        json.loads((RUN_ROOT / record["case_id"] / "latest.json").read_text())
        for record in evidence_records
    ]
    payload["all_evidence_resource_summary"] = {
        "unique_completed_cases": len(evidence_runs),
        "successful_solver_gpu_seconds": sum(item["elapsed_seconds"] for item in evidence_runs),
        "scope": "selected matrix plus executed excluded-grid and mDBC diagnostic cases",
    }
    payload["open_blockers"] = [
        "current DBC moving-cup results are not resolution stable",
        "mDBC route requires complete verified normal geometry before it can be compared",
        "no independent experimental F2 observation anchor is available",
        "saved-cadence convergence remains separate from this fixed-0.01-s spatial study",
    ]
    REPORT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "normalize", "analyze", "all"), nargs="?", default="all")
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--include-retries", action="store_true")
    args = parser.parse_args()
    known = {record["case_id"]: record for record in records() + exploratory_grid_records() + retry_records()}
    unknown = set(args.cases or ()) - set(known)
    if unknown:
        parser.error(f"unknown cases: {sorted(unknown)}")
    if args.cases:
        selected = [known[name] for name in args.cases]
    else:
        selected = records() + (retry_records() if args.include_retries else [])
    results = None
    if args.action in ("prepare", "all"):
        prepare(selected)
    if args.action in ("run", "all"):
        results = run(selected)
    if args.action in ("normalize", "all"):
        normalize(selected)
    if args.action in ("analyze", "all"):
        analyze(results)


if __name__ == "__main__":
    main()
