#!/usr/bin/env python3
"""Bounded high-cadence pressure follow-up for SPHERIC Test 02.

This is an event-window experiment, not a replacement for the W05 six-second
anchor.  It reuses the official DualSPHysics Test 02 definition and the W05
spatial resolutions, truncates the physical time window after the documented
first pressure events, and saves particle states at a common 5 ms cadence.
The purpose is to separate temporal sampling from spatial-resolution effects
before a family-level acceptance decision.

All solver attempts are kept in immutable campaign attempt directories.  The
runner only considers the explicitly allow-listed idle GPUs 4--7 and records
the live GPU record before every launch.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np
import pandas as pd

try:
    from scripts.campaign_runner import execute_attempt, require_idle_allowed_gpu
except ModuleNotFoundError:
    from campaign_runner import execute_attempt, require_idle_allowed_gpu


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
OFFICIAL = LAB / "vendor" / "official" / "DualSPHysics_v5.4"
BIN = OFFICIAL / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
MEASURE = BIN / "MeasureTool_linux64"
SOURCE_DIR = OFFICIAL / "examples" / "mdbc" / "04_Dambreak"
SOURCE_DEF = SOURCE_DIR / "CaseDamBreak3D_Def.xml"
CASE_ROOT = CAMPAIGN / "cases" / "r4-f1-test02-event-window"
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "r4-f1-test02-event-window"
RUN_ROOT = CAMPAIGN / "runs"
REPORT = CAMPAIGN / "r4-f1-test02-event-window.json"
EXPERIMENT = CAMPAIGN / "artifacts" / "w05" / "external" / "test2" / "test_case_2_exp_data.xls"

TMAX_S = 2.2
TOUT_S = 0.005
RESOLUTIONS = {
    "coarse": 0.04,
    "medium": 0.03,
    "fine": 0.02,
}
GPU_BY_LEVEL = {"coarse": 4, "medium": 5, "fine": 6}
CASE_IDS = {
    level: f"R4_F1_Test02_event_{level}" for level in RESOLUTIONS
}


def environment() -> dict[str, str]:
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN}:{value.get('LD_LIBRARY_PATH', '')}"
    return value


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def records() -> list[dict[str, Any]]:
    return [
        {
            "case_id": CASE_IDS[level],
            "level": level,
            "family": "F1",
            "source_definition": str(SOURCE_DEF.relative_to(LAB)),
            "dp_m": dp,
            "tmax_s": TMAX_S,
            "tout_s": TOUT_S,
            "gpu": GPU_BY_LEVEL[level],
        }
        for level, dp in RESOLUTIONS.items()
    ]


def set_parameter(root: ET.Element, key: str, value: Any) -> None:
    node = root.find(f".//parameter[@key='{key}']")
    if node is None:
        parameters = root.find(".//execution/parameters")
        if parameters is None:
            raise ValueError(f"definition has no execution parameters: {key}")
        node = ET.SubElement(parameters, "parameter", key=key)
    node.set("value", str(value))


def prepare(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    prepared = []
    for record in selected:
        case_id = record["case_id"]
        generated_dir = ARTIFACT_ROOT / case_id / "generated"
        generated_dir.mkdir(parents=True, exist_ok=True)
        # GenCase writes auxiliary source assets in-place.  Work on a private
        # copy and restore the official point lists after generation.
        shutil.copytree(SOURCE_DIR, generated_dir, dirs_exist_ok=True)
        definition = CASE_ROOT / f"{case_id}_Def.xml"
        tree = ET.parse(SOURCE_DEF)
        root = tree.getroot()
        geometry_definition = root.find(".//geometry/definition")
        if geometry_definition is None:
            raise ValueError(f"missing geometry definition in {SOURCE_DEF}")
        geometry_definition.set("dp", str(record["dp_m"]))
        set_parameter(root, "SavePosDouble", 2)
        set_parameter(root, "TimeMax", TMAX_S)
        set_parameter(root, "TimeOut", TOUT_S)
        ET.indent(tree, space="    ")
        tree.write(definition, encoding="utf-8", xml_declaration=True)
        shutil.copy2(definition, generated_dir / definition.name)
        prefix = generated_dir / case_id
        proc = subprocess.run(
            [str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"],
            cwd=generated_dir,
            env=environment(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        (generated_dir / "gencase.stdout.log").write_text(proc.stdout)
        # GenCase can rewrite same-directory input files; restore the official
        # measurement points so their provenance remains unambiguous.
        for source in SOURCE_DIR.iterdir():
            if source.is_file():
                shutil.copy2(source, generated_dir / source.name)
        if proc.returncode != 0 or not prefix.with_suffix(".xml").is_file():
            raise RuntimeError(f"GenCase failed for {case_id}")
        fluid = re.search(r"Fluid\.{4,}:\s*([\d,]+)", proc.stdout)
        fixed = re.search(r"Fixed\.{4,}:\s*([\d,]+)", proc.stdout)
        prepared.append(
            record
            | {
                "definition": str(definition.relative_to(LAB)),
                "definition_sha256": sha256(definition),
                "generated_prefix": str(prefix.relative_to(LAB)),
                "gencase": {
                    "returncode": proc.returncode,
                    "fluid_particles": int(fluid.group(1).replace(",", "")) if fluid else None,
                    "fixed_particles": int(fixed.group(1).replace(",", "")) if fixed else None,
                },
            }
        )
    return prepared


def allowed_uuids() -> list[str]:
    inventory = json.loads((CAMPAIGN / "w00-inventory.json").read_text())
    return inventory["execution_policy"]["allowed_gpu_uuids"]


def run_one(record: dict[str, Any]) -> dict[str, Any]:
    gpu_record = require_idle_allowed_gpu(record["gpu"], allowed_uuids())
    prefix = ARTIFACT_ROOT / record["case_id"] / "generated" / record["case_id"]
    result = execute_attempt(
        record["case_id"],
        [
            str(SOLVER),
            f"-gpu:{record['gpu']}",
            "-mdbc",
            str(prefix),
            "{output}",
            f"-tmax:{TMAX_S}",
            f"-tout:{TOUT_S}",
        ],
        RUN_ROOT,
        cwd=prefix.parent,
        env=environment(),
        evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
    )
    result["gpu_at_launch"] = gpu_record
    if result["status"] != "completed":
        raise RuntimeError(f"solver failed for {record['case_id']}")
    return result


def run(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # The three records use disjoint explicitly allow-listed GPUs.
    with ThreadPoolExecutor(max_workers=len(selected)) as pool:
        return list(pool.map(run_one, selected))


def latest(case_id: str) -> Path:
    payload = json.loads((RUN_ROOT / case_id / "latest.json").read_text())
    return Path(payload["attempt_directory"])


def postprocess_one(record: dict[str, Any]) -> Path:
    attempt = latest(record["case_id"])
    measure_dir = attempt / "measure"
    measure_dir.mkdir(parents=True, exist_ok=True)
    prefix = measure_dir / "pressure"
    proc = subprocess.run(
        [
            str(MEASURE),
            "-dirdata",
            str(attempt / "data"),
            "-points",
            str(SOURCE_DIR / "pressure.txt"),
            "-onlytype:-all,+fluid",
            "-vars:-all,+press",
            "-kclimit:0.5",
            # A dummy-support fallback silently turns under-supported pressure
            # probes into zero.  W05's usable pressure traces were produced
            # with this fallback disabled, so make the observation semantics
            # explicit for the cadence follow-up.
            "-kcusedummy:0",
            "-savecsv",
            str(prefix),
        ],
        cwd=LAB,
        env=environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    (measure_dir / "pressure.stdout.log").write_text(proc.stdout)
    output = measure_dir / "pressure_Press.csv"
    if proc.returncode != 0 or not output.is_file():
        raise RuntimeError(f"MeasureTool failed for {record['case_id']}")
    return attempt


def read_measure_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=";", skiprows=3)
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame.loc[:, ~frame.columns.str.startswith("Unnamed")]


def _peak(time: np.ndarray, values: np.ndarray) -> dict[str, float | None]:
    finite = np.isfinite(time) & np.isfinite(values)
    if not finite.any():
        return {"value_pa": None, "time_s": None}
    selected_time = time[finite]
    selected_values = values[finite]
    index = int(np.argmax(np.abs(selected_values)))
    return {"value_pa": float(selected_values[index]), "time_s": float(selected_time[index])}


def cadence_peak_audit(time: np.ndarray, values: np.ndarray) -> dict[str, Any]:
    """Measure observation-cadence sensitivity without changing solver state."""

    time = np.asarray(time, dtype=float)
    values = np.asarray(values, dtype=float)
    reference = _peak(time, values)
    result: dict[str, Any] = {}
    for label, stride in (("5ms", 1), ("10ms", 2), ("20ms", 4), ("50ms", 10)):
        indices = np.arange(0, len(time), stride, dtype=int)
        if len(indices) and indices[-1] != len(time) - 1:
            indices = np.append(indices, len(time) - 1)
        observed = _peak(time[indices], values[indices]) if len(indices) else {
            "value_pa": None,
            "time_s": None,
        }
        result[label] = {
            "stride": stride,
            "median_observed_cadence_s": (
                float(np.median(np.diff(time[indices]))) if len(indices) > 1 else None
            ),
            "peak": observed,
            "peak_time_delta_from_5ms_s": (
                abs(float(observed["time_s"]) - float(reference["time_s"]))
                if observed["time_s"] is not None and reference["time_s"] is not None
                else None
            ),
            "peak_value_delta_from_5ms_pa": (
                float(observed["value_pa"]) - float(reference["value_pa"])
                if observed["value_pa"] is not None and reference["value_pa"] is not None
                else None
            ),
        }
    return result


def event_metrics(record: dict[str, Any]) -> dict[str, Any]:
    attempt = latest(record["case_id"])
    simulated = read_measure_csv(attempt / "measure" / "pressure_Press.csv")
    time_col = next(column for column in simulated.columns if "time" in column.lower())
    sim_time = simulated[time_col].to_numpy(dtype=float)
    experiment = pd.read_excel(EXPERIMENT, sheet_name="Experimental_data")
    sim_columns = [column for column in simulated.columns if column.startswith("Press_")]
    probes: dict[str, Any] = {}
    mask = (sim_time >= 0.0) & (sim_time <= TMAX_S + 1.0e-9)
    for index, sim_column in enumerate(sim_columns[:8]):
        name = f"P{index + 1}"
        exp_column = f"{name} (Pa)"
        exp_time = experiment["Time (s)"].to_numpy(dtype=float)
        exp_values = experiment[exp_column].to_numpy(dtype=float)
        exp_finite = np.isfinite(exp_time) & np.isfinite(exp_values)
        exp_time = exp_time[exp_finite]
        exp_values = exp_values[exp_finite]
        sim_values = simulated[sim_column].to_numpy(dtype=float)
        overlap = mask & (sim_time >= exp_time.min()) & (sim_time <= min(TMAX_S, exp_time.max()))
        target = np.interp(sim_time[overlap], exp_time, exp_values)
        error = sim_values[overlap] - target
        sim_peak = _peak(sim_time[mask], sim_values[mask])
        exp_mask = exp_time <= TMAX_S
        exp_peak = _peak(exp_time[exp_mask], exp_values[exp_mask])
        sim_impulse = float(np.trapezoid(np.maximum(sim_values[mask], 0.0), sim_time[mask]))
        exp_impulse = float(np.trapezoid(np.maximum(exp_values[exp_mask], 0.0), exp_time[exp_mask]))
        probes[name] = {
            "rmse_pa": float(np.sqrt(np.mean(error * error))) if len(error) else None,
            "mae_pa": float(np.mean(np.abs(error))) if len(error) else None,
            "samples": int(len(error)),
            "simulated_peak": sim_peak,
            "experimental_peak": exp_peak,
            "peak_time_error_s": (
                abs(float(sim_peak["time_s"]) - float(exp_peak["time_s"]))
                if sim_peak["time_s"] is not None and exp_peak["time_s"] is not None
                else None
            ),
            "positive_pressure_impulse_pa_s": {
                "simulated": sim_impulse,
                "experimental": exp_impulse,
            },
            "observation_cadence_sensitivity": cadence_peak_audit(
                sim_time[mask], sim_values[mask]
            ),
        }
    process_log = (attempt / "process.stdout.log").read_text(errors="replace")
    steps = re.search(r"Steps of simulation\.{4,}:\s*([\d,]+)", process_log)
    times = np.asarray(sim_time[mask], dtype=float)
    return {
        "attempt_directory": str(attempt.relative_to(LAB)),
        "frames_in_event_window": int(mask.sum()),
        "observed_time_min_s": float(times.min()) if len(times) else None,
        "observed_time_max_s": float(times.max()) if len(times) else None,
        "observed_cadence_median_s": float(np.median(np.diff(times))) if len(times) > 1 else None,
        "adaptive_solver_steps": int(steps.group(1).replace(",", "")) if steps else None,
        "mean_internal_dt_s": (
            TMAX_S / int(steps.group(1).replace(",", "")) if steps else None
        ),
        "probes": probes,
    }


def write_report(
    prepared: list[dict[str, Any]],
    run_results: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_run_results = run_results or []
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "SPHERIC Test 02 pressure event-window cadence follow-up",
        "execution_status": "completed" if effective_run_results and all(
            item["status"] == "completed" for item in effective_run_results
        ) and len(effective_run_results) == len(prepared) else "prepared_or_partial",
        "acceptance_status": "diagnostic_only_not_physical_acceptance",
        "validation_scope": [
            "official DualSPHysics 5.4 mDBC Test 02 physical background",
            "three W05 spatial resolutions",
            "0--2.2 s event window",
            "pressure P1--P8 only",
        ],
        "source": {
            "definition": str(SOURCE_DEF.relative_to(LAB)),
            "definition_sha256": sha256(SOURCE_DEF),
            "experimental_workbook": str(EXPERIMENT.relative_to(LAB)),
            "experimental_workbook_sha256": sha256(EXPERIMENT),
        },
        "controls": {
            "spatial_resolution_m": RESOLUTIONS,
            "time_max_s": TMAX_S,
            "requested_output_cadence_s": TOUT_S,
            "measuretool_kc_limit": 0.5,
            "measuretool_use_dummy_support": False,
            "pressure_peak_definition": (
                "signed pressure extremum selected by maximum absolute magnitude; "
                "positive-pressure impulse is reported separately"
            ),
            "boundary": "mDBC",
            "solver_internal_timestep": "adaptive; steps and mean dt are measured per run",
            "gpu_policy": "only live-idle allow-listed GPUs 4--7; no GPU 0--3 use",
        },
        "prepared_cases": prepared,
        "run_results": [
            {
                "case_id": item["case_id"],
                "attempt_id": item["attempt_id"],
                "status": item["status"],
                "elapsed_seconds": item["elapsed_seconds"],
                "frames": item.get("frames", len(item.get("evidence_files", []))),
                "gpu_at_launch": item.get("gpu_at_launch"),
            }
            for item in effective_run_results
        ],
        "event_metrics": metrics or {},
        "interpretation": {
            "purpose": "measure whether 5 ms observation cadence resolves documented Test 02 pressure events",
            "not_a_gold_decision": "event-window pressure agreement cannot qualify the full F1 family or particle-level trajectories",
            "next_gate": "combine event-window pressure, H1--H4 surface elevation, mass/penetration, and three-resolution behavior",
        },
        "open_blockers": [
            "full six-second pressure and elevation acceptance remains separate",
            "no claim is made for self-built F1 topology backgrounds",
            "event-window pressure metrics are not a development tranche admission gate by themselves",
        ],
    }
    REPORT.write_text(json.dumps(payload, indent=2) + "\n")
    markdown = [
        "# R4 F1 Test 02 event-window follow-up",
        "",
        "状态：**仅诊断，不是物理验收或 Gold 标签。**",
        "",
        "本实验复用官方 SPHERIC Test 02 DualSPHysics mDBC 背景，保留 W05 的三档空间分辨率，",
        f"将时域截取为 `0--{TMAX_S:g} s`，请求输出间隔为 `{TOUT_S:g} s`。它只回答输出频率是否足以解析压力冲击。",
        "",
        "| level | dp (m) | GPU | status | frames | median cadence (s) |",
        "|---|---:|---:|---|---:|---:|",
    ]
    metric_by_id = {
        case_id: item for case_id, item in (metrics or {}).items()
    }
    for record in prepared:
        run_info = next((item for item in effective_run_results if item["case_id"] == record["case_id"]), {})
        event = metric_by_id.get(record["case_id"], {})
        markdown.append(
            f"| {record['level']} | {record['dp_m']:.3f} | {record['gpu']} | "
            f"{run_info.get('status', 'not-run')} | {event.get('frames_in_event_window', '—')} | "
            f"{event.get('observed_cadence_median_s', '—')} |"
        )
    markdown.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 不能用本轮首个冲击窗口替代 W05 的完整 6 秒 Test 02 验证。",
            "- 峰值定义为带符号压力的最大绝对值极值；正压冲量单独报告，不能把负压伪峰当作正向冲击。",
            "- 必须逐探针报告峰值、峰时、误差和正压冲量；不能用单一 RMSE 排名。",
            "- 只有在事件窗口、宏观水位、质量/穿透以及三分辨率趋势共同过 gate 后，F1 才能进入 pilot 候选。",
            "",
            f"机器可读结果：`{REPORT.relative_to(LAB)}`。",
        ]
    )
    (CAMPAIGN / "R4-F1-TEST02-EVENT-WINDOW.md").write_text("\n".join(markdown) + "\n")
    print(json.dumps(payload, indent=2))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "postprocess", "analyze", "all"), nargs="?", default="all")
    parser.add_argument("--cases", nargs="*", choices=list(CASE_IDS.values()))
    args = parser.parse_args()
    selected = [record for record in records() if not args.cases or record["case_id"] in args.cases]
    existing: dict[str, Any] = {}
    if REPORT.is_file():
        existing = json.loads(REPORT.read_text())
    prepared_by_id = {item["case_id"]: item for item in existing.get("prepared_cases", [])}
    prepared = [prepared_by_id.get(record["case_id"], record) for record in selected]
    if args.action in {"prepare", "all"}:
        prepared = prepare(selected)
    run_results: list[dict[str, Any]] | None = None
    if args.action in {"run", "all"}:
        run_results = run(selected)
    if args.action in {"postprocess", "all"}:
        for record in selected:
            postprocess_one(record)
    metrics: dict[str, Any] | None = None
    if args.action in {"analyze", "all"}:
        metrics = {}
        for record in selected:
            metrics[record["case_id"]] = event_metrics(record)
    if run_results is None:
        run_results = existing.get("run_results")
    if metrics is None:
        metrics = existing.get("event_metrics")
    if not run_results:
        recovered_runs: list[dict[str, Any]] = []
        for record in selected:
            latest_path = RUN_ROOT / record["case_id"] / "latest.json"
            if not latest_path.is_file():
                continue
            recovered = json.loads(latest_path.read_text())
            recovered["gpu_at_launch"] = {
                "index": record["gpu"],
                "recovered_from_latest": True,
                "uuid_not_persisted_by_legacy_attempt_schema": True,
            }
            recovered_runs.append(recovered)
        run_results = recovered_runs
    write_report(prepared, run_results, metrics)


if __name__ == "__main__":
    main()
