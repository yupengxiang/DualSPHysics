#!/usr/bin/env python3
"""Run an isolated F5 WaveRunup observation-path probe.

The official WaveRunup example ships a CIEMito reference table and four
external wave-gauge locations, but its stock definition only emits the
run-up-line gauges.  This script copies the official example into the lab's
ignored generated/run directories, adds fixed vertical SWL gauges at the
external locations, and records exactly what was prepared or run.

This is an observation-path probe, not a production-data generator.  Every
report is explicitly candidate-only and keeps solver, gauge, and reference
tracks separate.  No file under the upstream checkout is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Any, Iterable

import numpy as np


LAB = Path(__file__).resolve().parents[1]
OFFICIAL = LAB / "vendor" / "official" / "DualSPHysics_v5.4"
SOURCE = OFFICIAL / "examples" / "main" / "17_WaveRunup"
BIN = OFFICIAL / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
INVENTORY = LAB / "campaigns" / "v0.1-candidate" / "w00-inventory.json"
WORK_ROOT = LAB / "campaigns" / "v0.1-candidate" / "cases" / "r3-f5-wave-runup"
RUN_ROOT = LAB / "campaigns" / "v0.1-candidate" / "runs" / "r3-f5-wave-runup"
DEFAULT_REPORT = LAB / "campaigns" / "v0.1-candidate" / "r3-f5-wave-runup.json"
DEFAULT_CONCLUSION = LAB / "campaigns" / "v0.1-candidate" / "R3-F5-WAVE-RUNUP-CONCLUSION.md"

RESOLUTIONS: dict[str, float] = {
    "coarse": 0.040,
    "medium": 0.025,
    "fine": 0.0125,
}
EXTERNAL_GAUGES: tuple[tuple[str, float, float, float], ...] = (
    ("WG1", 3.10, 0.18, 0.075),
    ("WG2", 3.20, 0.18, 0.075),
    ("WG3", 3.34, 0.18, 0.075),
    ("WG4", 3.63, 0.18, 0.075),
)
GAUGE_CADENCE_S = 0.02
DEFAULT_TMAX_S = 16.0
DEFAULT_TOUT_S = 0.02


def sha256(path: Path) -> str | None:
    if not Path(path).is_file():
        return None
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _set_or_rename(parent: ET.Element, old_name: str, new_name: str) -> ET.Element:
    node = parent.find(old_name)
    if node is None:
        node = parent.find(new_name)
    if node is None:
        node = ET.SubElement(parent, new_name)
    else:
        node.tag = new_name
    return node


def configure_definition(
    source_xml: Path,
    target_xml: Path,
    *,
    gauge_cadence_s: float = GAUGE_CADENCE_S,
    tmax_s: float = DEFAULT_TMAX_S,
) -> dict[str, Any]:
    """Copy the official definition and add externally aligned SWL gauges.

    The stock file uses underscore-prefixed gauge options, which are template
    comments in the v5.4 gauge schema.  The probe deliberately emits the
    active, documented names so the cadence is an executable contract.
    """

    tree = ET.parse(source_xml)
    root = tree.getroot()
    gauges = root.find("./execution/special/gauges")
    if gauges is None:
        raise ValueError("WaveRunup definition has no execution/special/gauges")
    default = gauges.find("default")
    if default is None:
        raise ValueError("WaveRunup definition has no gauges/default block")

    computedt = _set_or_rename(default, "_computedt", "computedt")
    computedt.set("value", f"{gauge_cadence_s:.9g}")
    computetime = _set_or_rename(default, "_computetime", "computetime")
    computetime.set("start", "0")
    computetime.set("end", f"{tmax_s:.9g}")
    outputdt = _set_or_rename(default, "_outputdt", "outputdt")
    outputdt.set("value", f"{gauge_cadence_s:.9g}")
    outputtime = _set_or_rename(default, "_outputtime", "outputtime")
    outputtime.set("start", "0")
    outputtime.set("end", f"{tmax_s:.9g}")

    existing = {node.get("name") for node in gauges.findall("swl")}
    added: list[dict[str, Any]] = []
    for name, x, y, z in EXTERNAL_GAUGES:
        if name in existing:
            raise ValueError(f"external gauge name already exists: {name}")
        node = ET.SubElement(gauges, "swl", {"name": name})
        ET.SubElement(node, "masslimit", {"coef": "0.4"})
        ET.SubElement(node, "pointdp", {"coefdp": "0.5"})
        # A vertical line crosses the external sensor elevation.  The SWL
        # result is an Eulerian free-surface estimate, not a particle label.
        ET.SubElement(node, "point0", {
            "x": f"{x:.9g}", "y": f"{y:.9g}", "z": "0",
        })
        ET.SubElement(node, "point2", {
            "x": f"{x:.9g}", "y": f"{y:.9g}", "z": "0.6",
        })
        added.append({"name": name, "position_m": [x, y, z], "measurement_axis": "z"})

    for parameter in root.findall("./execution/parameters/parameter"):
        if parameter.get("key") == "TimeMax":
            parameter.set("value", f"{tmax_s:.9g}")
        elif parameter.get("key") == "TimeOut":
            parameter.set("value", f"{DEFAULT_TOUT_S:.9g}")

    target_xml.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target_xml, encoding="utf-8", xml_declaration=True)
    return {
        "source_xml": str(source_xml),
        "source_sha256": sha256(source_xml),
        "configured_xml": str(target_xml),
        "configured_sha256": sha256(target_xml),
        "gauge_cadence_s": gauge_cadence_s,
        "tmax_s": tmax_s,
        "active_gauge_option_names": ["computedt", "computetime", "outputdt", "outputtime"],
        "external_gauges": added,
    }


def _restore_input_assets(source: Path, destination: Path) -> None:
    """Restore files consumed by GenCase after an in-place generation.

    GenCase writes its generated XML beside the input definition.  When an
    input asset (for example ``Mov_piston.dat`` or an STL) is in that same
    directory, v5.4 attempts to copy the file onto itself and leaves a
    zero-byte placeholder after reporting a warning.  Restoring the copied
    source tree makes the generated case self-contained without touching the
    upstream checkout.
    """

    for source_file in source.rglob("*"):
        if not source_file.is_file():
            continue
        target = destination / source_file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target)


def prepare_case(label: str, dp_m: float, *, gauge_cadence_s: float, tmax_s: float) -> dict[str, Any]:
    if not SOURCE.is_dir() or not GENCASE.is_file():
        raise FileNotFoundError(f"official WaveRunup source or GenCase missing under {SOURCE}")
    work = WORK_ROOT / label / "generated"
    shutil.copytree(SOURCE, work, dirs_exist_ok=True)
    source_xml = work / "CaseWaveRunup_Def.xml"
    configured_xml = work / f"CaseWaveRunup_{label}_External_Def.xml"
    definition = configure_definition(
        source_xml,
        configured_xml,
        gauge_cadence_s=gauge_cadence_s,
        tmax_s=tmax_s,
    )
    prefix = work / f"F5_wave_runup_{label}"
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    started = time.monotonic()
    proc = subprocess.run(
        [str(GENCASE), str(configured_xml.with_suffix("")), str(prefix), f"-dp:{dp_m:.9g}", "-save:all"],
        cwd=work,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # GenCase can truncate same-directory input assets while constructing the
    # case.  Restore authoritative copies before the solver is launched.
    _restore_input_assets(SOURCE, work)
    elapsed = time.monotonic() - started
    log = work / "gencase_external.log"
    log.write_text(proc.stdout)
    fluid = re.search(r"Fluid\.\.\.\.:\s+([0-9,]+)", proc.stdout)
    total = re.search(r"Total particles:\s+([0-9,]+)", proc.stdout)
    result = {
        "label": label,
        "dp_m": dp_m,
        "status": "prepared" if proc.returncode == 0 and prefix.with_suffix(".xml").is_file() else "prepare_failed",
        "returncode": proc.returncode,
        "elapsed_seconds": round(elapsed, 4),
        "fluid_particles": int(fluid.group(1).replace(",", "")) if fluid else None,
        "total_particles": int(total.group(1).replace(",", "")) if total else None,
        "case_prefix": str(prefix.relative_to(LAB)),
        "definition": definition,
        "log": str(log.relative_to(LAB)),
    }
    return result


def run_case(prepared: dict[str, Any], gpu: int, *, tmax_s: float, tout_s: float) -> dict[str, Any]:
    if prepared.get("status") != "prepared":
        raise ValueError(f"cannot run unprepared case {prepared.get('label')}")
    label = str(prepared["label"])
    prefix = LAB / prepared["case_prefix"]
    output = RUN_ROOT / label
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    command = [str(SOLVER), f"-gpu:{gpu}", str(prefix), str(output),
               f"-tmax:{tmax_s:.9g}", f"-tout:{tout_s:.9g}"]
    started = time.monotonic()
    proc = subprocess.run(command, cwd=prefix.parent, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - started
    log = output / "solver.stdout.log"
    log.write_text(proc.stdout)
    parts = sorted(output.glob("data*/Part_*.bi4"))
    finished = "Finished execution (code=0)" in proc.stdout
    status = "completed" if proc.returncode == 0 and finished and parts else "run_failed"
    excluded = re.search(r"Excluded particles\.\.\.:\s*([0-9,]+)", proc.stdout)
    return {
        **prepared,
        "status": status,
        "returncode": proc.returncode,
        "gpu": gpu,
        "elapsed_seconds": round(elapsed, 4),
        "frames": len(parts),
        "excluded_particles": int(excluded.group(1).replace(",", "")) if excluded else None,
        "output_bytes": sum(path.stat().st_size for path in output.rglob("*") if path.is_file()),
        "log": str(log.relative_to(LAB)),
        "command": command,
    }


def _read_gauge(path: Path) -> dict[str, Any]:
    lines = path.read_text(errors="replace").splitlines()
    if not lines:
        return {"path": str(path), "rows": 0, "issues": ["empty gauge output"]}
    rows: list[list[float]] = []
    for line in lines[1:]:
        fields = line.replace(";", " ").split()
        try:
            values = [float(value) for value in fields]
        except ValueError:
            continue
        if len(values) >= 4:
            rows.append(values)
    data = np.asarray(rows, dtype=np.float64)
    issues: list[str] = []
    if data.ndim != 2 or data.shape[1] < 4 or len(data) < 2 or not np.all(np.isfinite(data[:, :4])):
        issues.append("gauge output has fewer than two finite rows with time and SWL fields")
    time_values = data[:, 0] if len(data) else np.empty(0)
    z_values = data[:, 3] if len(data) else np.empty(0)
    dt = np.diff(time_values) if len(time_values) > 1 else np.empty(0)
    if len(dt) and not np.all(dt > 0):
        issues.append("model gauge time is not strictly increasing")
    return {
        "path": str(path),
        "rows": int(len(data)),
        "time_start_s": float(time_values[0]) if len(data) else None,
        "time_end_s": float(time_values[-1]) if len(data) else None,
        "dt_median_s": float(np.median(dt)) if len(dt) else None,
        "swl_z_min_m": float(z_values.min()) if len(data) else None,
        "swl_z_max_m": float(z_values.max()) if len(data) else None,
        "swl_dynamic": bool(len(data) > 1 and np.ptp(z_values) > 1e-6),
        "issues": issues,
    }


def summarize_gauges(run: dict[str, Any]) -> dict[str, Any]:
    directory = RUN_ROOT / str(run["label"])
    gauges = {
        path.stem.removeprefix("GaugesSWL_"): _read_gauge(path)
        for path in sorted(directory.glob("GaugesSWL_WG*.csv"))
    }
    return {
        "directory": str(directory),
        "gauge_count": len(gauges),
        "gauges": gauges,
        "all_structural_pass": bool(gauges) and all(not item["issues"] for item in gauges.values()),
    }


def _gpu_inventory() -> dict[str, Any]:
    if not INVENTORY.is_file():
        return {"allowed_gpu_indices": [4, 5, 6, 7], "gpu_uuids": {}}
    payload = json.loads(INVENTORY.read_text())
    allowed = set(payload.get("execution_policy", {}).get("allowed_gpu_uuids", []))
    mapping = {
        str(item["physical_index"]): item["uuid"]
        for item in payload.get("host", {}).get("gpus", [])
        if item.get("uuid") in allowed
    }
    return {"allowed_gpu_indices": sorted(int(key) for key in mapping), "gpu_uuids": mapping}


def build_report(
    prepared: Iterable[dict[str, Any]],
    runs: Iterable[dict[str, Any]],
    *,
    gauge_cadence_s: float,
    tmax_s: float,
    tout_s: float,
) -> dict[str, Any]:
    prepared = list(prepared)
    runs = list(runs)
    report_runs = []
    for run in runs:
        report_run = dict(run)
        report_run["external_gauge_summary"] = summarize_gauges(run)
        report_runs.append(report_run)
    return {
        "schema_version": 1,
        "scope": "R3 F5 official WaveRunup external-gauge execution probe",
        "status": "candidate_only",
        "formal_release_authorized": False,
        "upstream_source": {
            "case_definition": str((SOURCE / "CaseWaveRunup_Def.xml").relative_to(LAB)),
            "case_definition_sha256": sha256(SOURCE / "CaseWaveRunup_Def.xml"),
            "reference_table": str((SOURCE / "EXP_CaseWaveRunup_CIEMito.txt").relative_to(LAB)),
            "reference_table_sha256": sha256(SOURCE / "EXP_CaseWaveRunup_CIEMito.txt"),
            "external_gauge_layout": str((SOURCE / "wg1234.txt").relative_to(LAB)),
            "external_gauge_layout_sha256": sha256(SOURCE / "wg1234.txt"),
        },
        "observation_contract": {
            "track": "Eulerian external free-surface observables; not particle-corresponded truth",
            "gauge_cadence_s": gauge_cadence_s,
            "particle_output_cadence_s": tout_s,
            "requested_time_end_s": tmax_s,
            "external_gauges": [
                {"name": name, "position_m": [x, y, z], "measurement": "SWL vertical-line estimate"}
                for name, x, y, z in EXTERNAL_GAUGES
            ],
            "time_alignment": "not yet established; external reference begins before forcing and contains rounded duplicate timestamps",
        },
        "gpu_policy": _gpu_inventory(),
        "prepared_cases": prepared,
        "runs": report_runs,
        "limitations": [
            "This probe does not validate any custom F5 weir case.",
            "A solver return code and dynamic gauge output are not external physical acceptance.",
            "Three resolutions and an independently declared uncertainty/time-alignment procedure are required before admission.",
            "The official reference table uses rounded duplicate timestamps; retain rows or aggregate them by a pre-registered rule.",
        ],
    }


def render_conclusion(report: dict[str, Any]) -> str:
    runs = report.get("runs", [])
    completed = sum(run.get("status") == "completed" for run in runs)
    return f"""# R3 F5 WaveRunup 外部波高计执行探针

状态：**candidate-only；不授权正式数据发布**。

本探针从官方 `main/17_WaveRunup` 定义复制出隔离副本，增加与 `wg1234.txt` 对齐的 WG1–WG4 垂直 SWL 测量线，并把 gauge 与粒子输出 cadence 声明为 {report['observation_contract']['gauge_cadence_s']} s。已准备 {len(report.get('prepared_cases', []))} 个分辨率，实际完成 {completed} 个运行。

这条路径验证的是“外部观测能否被同一套 DualSPHysics 输出链读取和记录”，不是验证波高或 run-up 的物理正确性。正式对齐仍需：覆盖参考主要事件的至少 16 s 运行、三分辨率、外部参考与模型时间偏移、重复时间戳处理规则，以及不确定度感知的全时程/首达/峰值/回流指标。

粗分辨率版本保留为失败或压力测试对照；自建 F5 堰案例在获得相容外部观测前仍只能作为机制探针。机器可读详情见 `r3-f5-wave-runup.json`。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolutions", nargs="+", choices=sorted(RESOLUTIONS), default=["medium"])
    parser.add_argument("--gpus", nargs="+", type=int, default=[4])
    parser.add_argument("--tmax", type=float, default=DEFAULT_TMAX_S)
    parser.add_argument("--tout", type=float, default=DEFAULT_TOUT_S)
    parser.add_argument("--gauge-cadence", type=float, default=GAUGE_CADENCE_S)
    parser.add_argument("--run", action="store_true", help="run prepared cases on the explicitly listed GPUs")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--conclusion", type=Path, default=DEFAULT_CONCLUSION)
    args = parser.parse_args()
    if args.tmax <= 0 or args.tout <= 0 or args.gauge_cadence <= 0:
        parser.error("tmax, tout, and gauge-cadence must be positive")
    policy = _gpu_inventory()
    disallowed = sorted(set(args.gpus) - set(policy["allowed_gpu_indices"]))
    if disallowed:
        parser.error(f"GPU indices are outside the physical allowlist: {disallowed}")

    prepared = [
        prepare_case(label, RESOLUTIONS[label], gauge_cadence_s=args.gauge_cadence, tmax_s=args.tmax)
        for label in args.resolutions
    ]
    runs: list[dict[str, Any]] = []
    if args.run:
        for index, item in enumerate(prepared):
            runs.append(run_case(item, args.gpus[index % len(args.gpus)], tmax_s=args.tmax, tout_s=args.tout))
    report = build_report(
        prepared,
        runs,
        gauge_cadence_s=args.gauge_cadence,
        tmax_s=args.tmax,
        tout_s=args.tout,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    args.conclusion.parent.mkdir(parents=True, exist_ok=True)
    args.conclusion.write_text(render_conclusion(report))
    print(json.dumps({
        "status": report["status"],
        "formal_release_authorized": report["formal_release_authorized"],
        "prepared": len(prepared),
        "run_count": len(runs),
        "completed": sum(item.get("status") == "completed" for item in runs),
        "allowed_gpu_indices": policy["allowed_gpu_indices"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
