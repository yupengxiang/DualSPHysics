#!/usr/bin/env python3
"""Prepare and audit F3 weak-dual independent time studies.

This module is deliberately F3-scoped.  It copies the frozen continuous-case
definition into a new handoff namespace and changes only the registered
numeric time variant:

* ``half_dt`` fixes ``DtIni``, ``DtMin`` and ``DtFixed`` to half of the
  measured native minimum step, while retaining the original ``TimeOut``;
* ``half_save`` retains the adaptive time-step parameters and changes only
  ``TimeOut`` to half the original save interval.

The original XML, acceleration CSV, solver output and consumed reports are
never written.  This module only prepares bounded CPU/GPU requests and has
small read-only helpers for GenCase/PartVTK provenance, native RunPARTs
accounting and fixed physical-window comparisons.  It never starts a solver
or grants Q-N.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping, Sequence

import h5py
import numpy as np


SCHEMA = "ds02.f3.time-study-handoff.v1"
LAB = Path(__file__).resolve().parents[1]
INFRA_ROOT = LAB.parent
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
OFFICIAL_LAB = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
BIN_ROOT = OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux"
GENCASE = BIN_ROOT / "GenCase_linux64"
SOLVER = BIN_ROOT / "DualSPHysics5.4_linux64"
PARTVTK = BIN_ROOT / "PartVTK_linux64"
DECODER = OFFICIAL_LAB / "campaigns/l1-resume/artifacts/bi4_dump"
NATIVE_LABELS = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_native_labels.py")

CASE_ID = "F3_DUAL_AXIS_WEAK_006G_004G"
PHYSICAL_BINDING_SHA = "fdb645e24952ed2f41225ca537d067d0233c9a94746fd4af0c390205736c9b10"
CONTROL_SHA = "98cb5a00395301e4e5561d57b8d56189686f468a16f0b4420c6f96c3e4995e6b"
EXPECTED_FLUID = 34560
EXPECTED_TOTAL = 108000
EXPECTED_MASS_KG = 14.58
BASELINE_DT_MIN_S = 2.212269686706988e-05
BASELINE_SAVE_S = 0.0025
TIME_END_S = 10.0


class F3TimeStudyError(RuntimeError):
    """Raised when a time-study handoff would be ambiguous or unsafe."""


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode()).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def ref(path: Path) -> dict[str, Any]:
    path = Path(path)
    return {"path": str(path.resolve()), "exists": path.is_file(), "sha256": digest(path) if path.is_file() else None,
            "bytes": path.stat().st_size if path.is_file() else None}


def load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise F3TimeStudyError(f"cannot read JSON: {path}") from exc


def usage() -> dict[str, float]:
    out: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        value = resource.getrusage(who)
        out[f"{label}_user_seconds"] = float(value.ru_utime)
        out[f"{label}_system_seconds"] = float(value.ru_stime)
        out[f"{label}_max_rss_kib"] = float(value.ru_maxrss)
    return out


def _usage_delta(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, float]:
    return {key: float(after[key] - before.get(key, 0.0)) for key in after}


def _number(value: str | None, *, label: str) -> float:
    if value is None:
        raise F3TimeStudyError(f"missing {label}")
    try:
        result = float(value)
    except ValueError as exc:
        raise F3TimeStudyError(f"invalid {label}: {value!r}") from exc
    if not math.isfinite(result):
        raise F3TimeStudyError(f"nonfinite {label}: {value!r}")
    return result


def _parameter(root: ET.Element, key: str) -> ET.Element:
    node = root.find(f".//parameter[@key='{key}']")
    if node is None:
        raise F3TimeStudyError(f"definition has no parameter {key}")
    return node


def _parse_runparts(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            try:
                int(row.get("Part", ""))
            except (TypeError, ValueError):
                continue
            rows.append(row)
    if not rows:
        raise F3TimeStudyError(f"RunPARTs has no numeric rows: {path}")

    def f(row: Mapping[str, str], key: str) -> float:
        value = row.get(key)
        if value is None or value == "":
            raise F3TimeStudyError(f"RunPARTs row missing {key}: {path}")
        return float(value.replace(",", ""))

    positive = [row for row in rows if f(row, "TimeStep [s]") > 0]
    if not positive:
        raise F3TimeStudyError("RunPARTs has no positive-time row")
    npout_sum = sum(int(f(row, "NpOut")) for row in positive)
    dt_min = min(f(row, "DtMin [s]") for row in positive)
    dt_max = max(f(row, "DtMax [s]") for row in positive)
    internal_steps = sum(int(f(row, "Steps")) for row in positive)
    if dt_min <= 0 or dt_max < dt_min:
        raise F3TimeStudyError(f"invalid native dt bounds: {dt_min}, {dt_max}")
    if npout_sum:
        raise F3TimeStudyError(f"baseline has native exclusions ({npout_sum})")
    times = [f(row, "TimeStep [s]") for row in rows]
    if not np.all(np.diff(times) > 0):
        raise F3TimeStudyError("RunPARTs save times are not strictly increasing")
    return {
        "source": ref(Path(path)),
        "saved_frames": len(rows),
        "time_start_s": times[0],
        "time_end_s": times[-1],
        "native_minimum_dt_s": dt_min,
        "native_maximum_dt_s": dt_max,
        "internal_step_count": internal_steps,
        "npout_sum": npout_sum,
        "initial_total_particles": int(float(rows[0]["NpSim"].replace(",", ""))),
        "final_total_particles": int(float(rows[-1]["NpSim"].replace(",", ""))),
        "initial_fluid_particles": int(float(rows[0]["NpfSim"].replace(",", ""))),
        "final_fluid_particles": int(float(rows[-1]["NpfSim"].replace(",", ""))),
        "measurement_semantics": "RunPARTs per-save-interval extrema; the every-step distribution is unavailable",
    }


def _parse_run_csv(path: Path) -> dict[str, Any]:
    with Path(path).open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    if len(rows) != 1:
        raise F3TimeStudyError(f"expected one Run.csv summary row: {path}")
    row = rows[0]
    return {
        "source": ref(Path(path)),
        "steps": int(row["Steps"].replace(",", "")),
        "physical_time_s": float(row["PhysicalTime"]),
        "part_files": int(row["PartFiles"]),
        "np": int(row["Np"].replace(",", "")),
        "dp_m": float(row["Dp"]),
        "configuration": row["Configuration"],
    }


def measure_baseline(runparts: Path, run_csv: Path, run_out: Path) -> dict[str, Any]:
    evidence = _parse_runparts(runparts)
    summary = _parse_run_csv(run_csv)
    text = Path(run_out).read_text(errors="replace")
    dt_match = re.search(r"^DtMin=([0-9.eE+-]+)", text, re.MULTILINE)
    # Run.out labels the effective output cadence ``TimePart`` even though
    # the input XML parameter is ``TimeOut``.  Accept both spellings and
    # preserve the source label in the evidence below.
    tout_match = re.search(r"^(TimeOut|TimePart)=([0-9.eE+-]+)", text, re.MULTILINE)
    tmax_match = re.search(r"^TimeMax=([0-9.eE+-]+)", text, re.MULTILINE)
    if dt_match and not math.isclose(float(dt_match.group(1)), evidence["native_minimum_dt_s"], rel_tol=0, abs_tol=2e-12):
        raise F3TimeStudyError("Run.out DtMin disagrees with RunPARTs")
    result = {"runparts": evidence, "run_csv": summary, "run_out": ref(run_out),
              "run_out_parameters": {
                  "dt_min_s": None if not dt_match else float(dt_match.group(1)),
                  "time_out_s": None if not tout_match else float(tout_match.group(2)),
                  "time_out_source_label": None if not tout_match else tout_match.group(1),
                  "time_max_s": None if not tmax_match else float(tmax_match.group(1)),
              }}
    if evidence["saved_frames"] != 4001 or summary["part_files"] != 4001:
        raise F3TimeStudyError("baseline is not the registered 4001-frame F3 reference")
    if evidence["initial_fluid_particles"] != EXPECTED_FLUID or summary["np"] != EXPECTED_TOTAL:
        raise F3TimeStudyError("baseline typed population differs from the registered F3 reference")
    if not math.isclose(evidence["time_start_s"], 0.0, abs_tol=1e-12) or evidence["time_end_s"] < TIME_END_S:
        raise F3TimeStudyError("baseline does not cover the complete 0-10 s window")
    return result


def _copy_control(source_control: Path, output_dir: Path, expected_sha: str) -> Path:
    if digest(source_control) != expected_sha:
        raise F3TimeStudyError("source control hash differs from the frozen owner hash")
    target = output_dir / source_control.name
    if target.exists():
        if digest(target) != expected_sha:
            raise F3TimeStudyError(f"refusing to overwrite divergent control copy: {target}")
    else:
        shutil.copyfile(source_control, target)
    return target


def _write_variant(source_def: Path, source_control: Path, output_dir: Path, variant: str, baseline: Mapping[str, Any], owner: Mapping[str, Any]) -> dict[str, Any]:
    if variant not in {"half_dt", "half_save"}:
        raise F3TimeStudyError(f"unsupported time variant: {variant}")
    source_def_sha = digest(source_def)
    tree = ET.parse(source_def)
    root = tree.getroot()
    baseline_dt = float(baseline["runparts"]["native_minimum_dt_s"])
    half_dt = baseline_dt / 2.0
    patches: dict[str, str]
    if variant == "half_dt":
        patches = {"DtIni": format(half_dt, ".17g"), "DtMin": format(half_dt, ".17g"), "DtFixed": format(half_dt, ".17g"),
                   "DtFixedFile": "NONE", "TimeOut": "0.0025"}
    else:
        patches = {"DtIni": "0", "DtMin": "0", "DtFixed": "0", "DtFixedFile": "NONE", "TimeOut": format(BASELINE_SAVE_S / 2.0, ".17g")}
    for key, value in patches.items():
        _parameter(root, key).set("value", value)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_def = output_dir / f"{CASE_ID}_{variant.upper()}_Def.xml"
    if output_def.exists():
        raise F3TimeStudyError(f"variant already exists; do not overwrite: {output_def}")
    try:
        ET.indent(tree, space="  ")
    except AttributeError:  # pragma: no cover
        pass
    tree.write(output_def, encoding="utf-8", xml_declaration=True)
    control_copy = _copy_control(source_control, output_dir, CONTROL_SHA)
    binding = owner.get("physical_binding")
    if not isinstance(binding, Mapping):
        raise F3TimeStudyError("owner metadata lacks physical_binding")
    physical_hash = canonical_hash(binding)
    if physical_hash != PHYSICAL_BINDING_SHA:
        raise F3TimeStudyError(f"owner physical binding hash changed: {physical_hash}")
    manifest = {
        "schema": "ds02.f3.time-variant-source.v1",
        "variant": variant,
        "family_id": "F3",
        "case_id": f"{CASE_ID}_{variant.upper()}",
        "physical_case_id": CASE_ID,
        "claim_boundary": "numeric time-study source/preflight only; Q-N and production remain unassessed",
        "source_definition": ref(source_def),
        "source_definition_sha256": source_def_sha,
        "variant_definition": ref(output_def),
        "source_control": ref(source_control),
        "variant_control_copy": ref(control_copy),
        "control_sha256": CONTROL_SHA,
        "owner_metadata": ref(Path(owner["_path"])),
        "physical_binding_sha256": physical_hash,
        "continuous_geometry_and_control_unchanged": True,
        "baseline": baseline,
        "numeric_variant": {
            "baseline_native_minimum_dt_s": baseline_dt,
            "half_native_minimum_dt_s": half_dt,
            "original_save_interval_s": BASELINE_SAVE_S,
            "variant_save_interval_s": BASELINE_SAVE_S if variant == "half_dt" else BASELINE_SAVE_S / 2.0,
            "patches": patches,
            "numeric_parameter_hash": canonical_hash(patches),
            "dt_semantics": "DtFixed/DtIni/DtMin are seconds; DtMin is set equal to DtFixed so the solver cannot clamp the half-dt variant back to the baseline minimum",
        },
        "expected_initial_state": {"fluid_particles": EXPECTED_FLUID, "total_particles": EXPECTED_TOTAL, "fluid_mass_kg": EXPECTED_MASS_KG},
        "source_immutable_policy": "original Def/control/Run.csv/RunPARTs/Run.out are read-only inputs; variant files are additive copies",
    }
    manifest_path = output_dir / f"{variant}-source-manifest.json"
    manifest["manifest_path"] = str(manifest_path.resolve())
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=_json_default) + "\n")
    return manifest


def _base_request(*, case_id: str, attempt_id: str, command: list[str], kind: str, cpu_task_kind: str | None,
                  cwd: Path, max_wall: int, cpu_threads: int, storage: int, inputs: Iterable[Path], scope: str) -> dict[str, Any]:
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F3", "case_id": case_id, "attempt_id": attempt_id,
        "kind": kind, **({"cpu_task_kind": cpu_task_kind} if cpu_task_kind else {}),
        "command": command, "cwd": str(cwd), "worktree_root": str(INFRA_ROOT),
        "max_wall_seconds": max_wall, "cpu_threads": cpu_threads,
        "estimated_storage_bytes": storage, "input_files": [str(Path(item).resolve()) for item in inputs],
        "scope": scope, "qualification_claim": "none; request only, Q-N remains not assessed",
    }


def _gencase_request(manifest: Mapping[str, Any], output_dir: Path, script_path: Path, baseline_paths: Sequence[Path]) -> dict[str, Any]:
    variant = str(manifest["variant"])
    case_id = str(manifest["case_id"])
    attempt_id = f"gencase-weak-dual-{variant}-20261002-001"
    source_def = Path(manifest["variant_definition"]["path"])
    control = Path(manifest["variant_control_copy"]["path"])
    manifest_path = Path(manifest["manifest_path"])
    inputs = [source_def, control, manifest_path, script_path, *baseline_paths, Path(manifest["owner_metadata"]["path"]), GENCASE]
    request = _base_request(
        case_id=case_id, attempt_id=attempt_id,
        command=[str(GENCASE), str(source_def.with_suffix("")), f"{{attempt_root}}/{case_id}", "-save:all"],
        kind="cpu", cpu_task_kind="gencase", cwd=BIN_ROOT, max_wall=300, cpu_threads=4,
        storage=512 * 1024**2, inputs=inputs,
        scope="F3 weak dual-axis time-study GenCase initialization only; actual typed initial state and native mass preflight; no solver/GPU/Q-N",
    )
    path = output_dir / f"{variant}-gencase-request.json"
    path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")
    return request


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    source_def = Path(args.source_def).resolve()
    source_control = Path(args.source_control).resolve()
    baseline_runparts = Path(args.baseline_runparts).resolve()
    baseline_run = Path(args.baseline_run).resolve()
    baseline_run_out = Path(args.baseline_run_out).resolve()
    owner_path = Path(args.owner_metadata).resolve()
    for path in (source_def, source_control, baseline_runparts, baseline_run, baseline_run_out, owner_path):
        if not path.is_file():
            raise F3TimeStudyError(f"missing immutable input: {path}")
    owner = load_json(owner_path)
    owner["_path"] = str(owner_path)
    baseline = measure_baseline(baseline_runparts, baseline_run, baseline_run_out)
    out = Path(args.output_dir).resolve()
    if out.exists() and any(path.is_file() for path in out.rglob("*")):
        raise F3TimeStudyError(f"handoff output is nonempty; refusing overwrite: {out}")
    out.mkdir(parents=True, exist_ok=True)
    source_out = out / "source"
    requests_out = out / "requests"
    source_out.mkdir(exist_ok=True)
    requests_out.mkdir(exist_ok=True)
    manifests = []
    requests = []
    for variant in ("half_dt", "half_save"):
        manifest = _write_variant(source_def, source_control, source_out, variant, baseline, owner)
        manifests.append(manifest)
        request = _gencase_request(manifest, requests_out, Path(__file__).resolve(),
                                    [baseline_runparts, baseline_run, baseline_run_out])
        requests.append(str((requests_out / f"{variant}-gencase-request.json").resolve()))
    handoff = {
        "schema": SCHEMA, "handoff_id": "F3_WEAK_DUAL_TIME_STUDY_HANDOFF_20261002",
        "family_id": "F3", "physical_case_id": CASE_ID,
        "claim_boundary": "preflight and runnable request registration only; no solver started and no Q-N/production claim",
        "baseline": baseline, "physical_binding_sha256": PHYSICAL_BINDING_SHA,
        "control_sha256": CONTROL_SHA, "variants": manifests,
        "gencase_requests": requests, "source_immutable": True,
        "resource_plan": {
            "gpu_budget_reserved_by_parent": "96 GPU h upper bound; root is sole GPU launcher",
            "cpu_budget_reserved_by_parent": "384 CPU core h upper bound",
            "home_free_floor": "500 GiB; runner v2 enforces the live floor",
            "estimated_solver": {"half_dt_seconds": 1800, "half_save_seconds": 1200},
            "storage_upper_bound_bytes": {"half_dt": 40 * 1024**3, "half_save": 72 * 1024**3},
        },
    }
    handoff_path = out / "handoff.json"
    handoff_path.write_text(json.dumps(handoff, indent=2, sort_keys=True, default=_json_default) + "\n")
    return {"handoff": str(handoff_path), "gencase_requests": requests, "baseline": baseline}


def _completed_receipt(path: Path) -> dict[str, Any]:
    value = load_json(path)
    if value.get("status") != "completed" or value.get("returncode") != 0:
        raise F3TimeStudyError(f"receipt is not a successful completed runner result: {path}")
    if value.get("solver_dimension_from_gencase") != 3:
        raise F3TimeStudyError(f"GenCase receipt lacks actual 3-D evidence: {path}")
    if value.get("fluid_particles") != EXPECTED_FLUID or value.get("total_particles") != EXPECTED_TOTAL:
        raise F3TimeStudyError(f"GenCase population differs from baseline: {path}")
    return value


def _generated_variant_paths(receipt_path: Path, case_id: str) -> dict[str, Path]:
    receipt = _completed_receipt(receipt_path)
    root = Path(receipt["output_root"])
    prefix = root / case_id
    paths = {"root": root, "prefix": prefix, "xml": prefix.with_suffix(".xml"), "bi4": prefix.with_suffix(".bi4"),
             "out": prefix.with_suffix(".out"), "control": root / "F3_DualAxisPhase_WeakControl.csv", "receipt": receipt_path}
    for key in ("xml", "bi4", "out", "control"):
        if not paths[key].is_file():
            raise F3TimeStudyError(f"GenCase output missing {key}: {paths[key]}")
    return paths


def _generated_numeric_values(xml_path: Path) -> dict[str, str]:
    root = ET.parse(xml_path).getroot()
    return {key: _parameter(root, key).get("value", "") for key in ("DtIni", "DtMin", "DtFixed", "DtFixedFile", "TimeMax", "TimeOut")}


def make_native_accounting(args: argparse.Namespace) -> dict[str, Any]:
    receipt_path = Path(args.solver_receipt).resolve()
    runparts = Path(args.runparts).resolve()
    run_csv = Path(args.run_csv).resolve()
    run_out = Path(args.run_out).resolve()
    for path in (receipt_path, runparts, run_csv, run_out):
        if not path.is_file():
            raise F3TimeStudyError(f"missing solver accounting input: {path}")
    receipt = load_json(receipt_path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise F3TimeStudyError("solver receipt is not completed successfully")
    measurement = _parse_runparts(runparts)
    summary = _parse_run_csv(run_csv)
    if measurement["initial_fluid_particles"] <= 0 or summary["np"] <= 0:
        raise F3TimeStudyError("solver accounting has no particles")
    run_text = run_out.read_text(errors="replace")
    if "**3D-Simulation parameters" not in run_text:
        raise F3TimeStudyError("Run.out lacks actual 3-D banner")
    npout_sum = sum(int(value) for value in (measurement["npout_sum"],))
    facts = {
        "saved_frames": measurement["saved_frames"], "initial_total_particles": summary["np"],
        "final_total_particles": measurement["final_total_particles"],
        "initial_native_npf_particles": measurement["initial_fluid_particles"],
        "final_native_npf_particles": measurement["final_fluid_particles"],
        "initial_fixed_and_moving_particles": summary["np"] - measurement["initial_fluid_particles"],
        "final_fixed_and_moving_particles": summary["np"] - measurement["final_fluid_particles"],
        "native_population_semantics": "NpfSim includes fluid and floating; NpbSim includes fixed and moving (RunPARTs native semantics)",
        "final_time_s": measurement["time_end_s"], "births": 0,
        "excluded_interval_sums": {"NpOut": npout_sum},
        "internal_steps": measurement["internal_step_count"],
        "actual_internal_dt_min_s": measurement["native_minimum_dt_s"],
        "actual_internal_dt_max_s": measurement["native_maximum_dt_s"],
        "native_dt_semantics": measurement["measurement_semantics"],
        "native_exclusion_semantics": "sum all per-save interval NpOut fields; final-row zero is not a full-window proof",
        "initial_fluid_particles": measurement["initial_fluid_particles"],
        "final_fluid_particles": measurement["final_fluid_particles"],
        "final_fluid_count_semantics": "fluid-only without floating; no floating body is expected for this F3 case",
    }
    result = [{
        "schema": "ds02.native-window-accounting.v1", "case_id": args.case_id, "attempt_id": args.attempt_id,
        "receipt": str(receipt_path), "receipt_sha256": digest(receipt_path),
        "runparts": str(runparts), "runparts_sha256": digest(runparts),
        "run_out": str(run_out), "run_out_sha256": digest(run_out), "solver_dimension": 3,
        "gpu_seconds": float(receipt.get("gpu_seconds", 0.0)), "launch_command": receipt.get("command", []),
        "facts": facts, "q_n_status": "not_assessed", "independent_production_case_increment": 0,
    }]
    output = Path(args.output).resolve()
    if output.exists():
        raise F3TimeStudyError(f"refusing to overwrite native accounting: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, default=_json_default) + "\n")
    return {"output": ref(output), "facts": facts, "resource_usage": "wrapper-side accounting only"}


def run_initial_partvtk(args: argparse.Namespace) -> dict[str, Any]:
    before = usage()
    data = Path(args.bi4).resolve()
    xml = Path(args.xml).resolve()
    output = Path(args.output).resolve()
    if not data.is_file() or not xml.is_file():
        raise F3TimeStudyError("PartVTK initial preflight requires generated .bi4 and .xml")
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = output.with_suffix("")
    command = [str(PARTVTK), "-filedata", str(data), "-filexml", str(xml), "-threads:4", "-savecsv", str(prefix),
               "-onlytype:+all", "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1"]
    completed = subprocess.run(command, cwd=str(PARTVTK.parent), capture_output=True, text=True)
    if completed.returncode != 0:
        raise F3TimeStudyError(f"PartVTK initial preflight failed: {completed.stdout[-2000:]} {completed.stderr[-2000:]}")
    csv_path = Path(str(prefix) + ".csv")
    if not csv_path.is_file():
        candidates = sorted(output.parent.glob(prefix.name + "*.csv"))
        if len(candidates) != 1:
            raise F3TimeStudyError(f"PartVTK did not produce one CSV: {prefix}")
        csv_path = candidates[0]
    text = csv_path.read_text(errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]
    # Official PartVTK emits a time line, a summary line, a blank separator,
    # then the particle header.  Keep this parser tied to that actual format.
    header_idx = next((i for i, line in enumerate(lines) if line.lstrip().startswith("Pos.x") or line.lstrip().startswith("TimeStep")), None)
    if header_idx is None:
        raise F3TimeStudyError("PartVTK CSV lacks the particle header")
    header = [item.strip() for item in lines[header_idx].split(",")]
    rows = list(csv.DictReader(lines[header_idx + 1:], fieldnames=header))
    required = {"Idp", "Type", "Mk", "Mass", "Pos.x", "Pos.y", "Pos.z", "Zone"}
    missing = sorted(required - set(header))
    if missing:
        raise F3TimeStudyError(f"PartVTK CSV lacks fields: {missing}")
    identities = set()
    counts: dict[str, int] = {}
    mass_by_type: dict[str, float] = {}
    for row in rows:
        identity = (int(row["Zone"]), int(row["Idp"]))
        if identity in identities:
            raise F3TimeStudyError(f"duplicate typed initial identity: {identity}")
        identities.add(identity)
        kind = str(int(row["Type"]))
        counts[kind] = counts.get(kind, 0) + 1
        mass_by_type[kind] = mass_by_type.get(kind, 0.0) + float(row["Mass"])
        if not all(math.isfinite(float(row[name])) for name in ("Mass", "Pos.x", "Pos.y", "Pos.z")) or float(row["Mass"]) <= 0:
            raise F3TimeStudyError("PartVTK initial state contains nonfinite/nonpositive mass or position")
    fluid_mass = mass_by_type.get("3", 0.0)
    result = {
        "schema": "ds02.f3.initial-partvtk-preflight.v1", "status": "completed_actual_read_only",
        "claim_boundary": "initial typed PartVTK equivalence only; no solver/Q-N/production",
        "command": command, "binary": ref(PARTVTK), "input_bi4": ref(data), "input_xml": ref(xml),
        "csv": ref(csv_path), "typed_identity": {"key": "(Zone,Idp)", "unique": len(identities) == len(rows), "rows": len(rows)},
        "counts_by_type": counts, "mass_by_type_kg": mass_by_type,
        "expected": {"total_particles": EXPECTED_TOTAL, "fluid_particles": EXPECTED_FLUID, "fluid_mass_kg": EXPECTED_MASS_KG},
        "fluid_mass_relative_error": abs(fluid_mass - EXPECTED_MASS_KG) / EXPECTED_MASS_KG,
        "mass_within_1_percent": abs(fluid_mass - EXPECTED_MASS_KG) / EXPECTED_MASS_KG <= 0.01,
        "resource_usage": _usage_delta(before, usage()),
    }
    if len(rows) != EXPECTED_TOTAL or counts.get("3") != EXPECTED_FLUID or not result["mass_within_1_percent"]:
        raise F3TimeStudyError(f"PartVTK initial population/mass differs from baseline: {result}")
    output.write_text(json.dumps(result, indent=2, sort_keys=True, default=_json_default) + "\n")
    return result


def _frame_macro(h5: h5py.File, frame: int, fluid_indices: np.ndarray, chunk: int) -> dict[str, float]:
    active_mass = 0.0
    weighted_position = np.zeros(3, dtype=float)
    kinetic = 0.0
    for begin in range(0, len(fluid_indices), chunk):
        indices = fluid_indices[begin:begin + chunk]
        valid = h5["valid"][frame, indices].astype(bool)
        mass = h5["mass"][frame, indices].astype(float)
        pos = h5["position"][frame, indices].astype(float)
        vel = h5["velocity"][frame, indices].astype(float)
        good = valid & np.isfinite(mass) & (mass > 0) & np.isfinite(pos).all(axis=1) & np.isfinite(vel).all(axis=1)
        m = np.where(good, mass, 0.0)
        active_mass += float(m.sum())
        weighted_position += np.sum(pos * m[:, None], axis=0)
        kinetic += float(0.5 * np.sum(m * np.sum(vel * vel, axis=1)))
    com = weighted_position / active_mass if active_mass else np.full(3, np.nan)
    return {"active_mass_kg": active_mass, "com_x_m": float(com[0]), "com_y_m": float(com[1]), "com_z_m": float(com[2]), "kinetic_energy_j": kinetic}


def _macro_series(path: Path, *, chunk: int = 65536) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    with h5py.File(path, "r") as h5:
        times = np.asarray(h5["time"][:], dtype=float)
        if len(times) < 2 or not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
            raise F3TimeStudyError(f"trajectory times are not finite/increasing: {path}")
        initial_type = np.asarray(h5["initial_type"][:])
        fluid = np.flatnonzero(initial_type == 3)
        if not len(fluid):
            raise F3TimeStudyError(f"trajectory has no initial fluid identities: {path}")
        rows = [_frame_macro(h5, frame, fluid, chunk) for frame in range(len(times))]
    keys = tuple(rows[0])
    return times, {key: np.asarray([row[key] for row in rows], dtype=float) for key in keys}


def _bracket(times: np.ndarray, target: float) -> dict[str, Any]:
    right = int(np.searchsorted(times, target, side="left"))
    if right == 0:
        return {"target_s": target, "left_frame": 0, "right_frame": 0, "left_time_s": float(times[0]), "right_time_s": float(times[0]), "interpolation": 0.0}
    if right >= len(times):
        right = len(times) - 1
    left = right - 1
    span = float(times[right] - times[left])
    fraction = 0.0 if span == 0 else (target - float(times[left])) / span
    return {"target_s": target, "left_frame": left, "right_frame": right, "left_time_s": float(times[left]), "right_time_s": float(times[right]), "interpolation": float(fraction)}


def compare_fixed_window(args: argparse.Namespace) -> dict[str, Any]:
    baseline = Path(args.baseline).resolve()
    variants = [Path(item).resolve() for item in args.variant]
    for path in [baseline, *variants]:
        if not path.is_file():
            raise F3TimeStudyError(f"comparison input missing: {path}")
    grid = np.arange(0.0, TIME_END_S + float(args.grid_step) * 0.5, float(args.grid_step), dtype=float)
    base_times, base_series = _macro_series(baseline)
    if base_times[0] > 0 or base_times[-1] < TIME_END_S:
        raise F3TimeStudyError("baseline does not cover fixed physical window")
    base_interp = {key: np.interp(grid, base_times, values) for key, values in base_series.items()}
    results: dict[str, Any] = {
        "schema": "ds02.f3.fixed-window-time-comparison.v1",
        "claim_boundary": "fixed physical-window macro/time-bracket diagnostic; Q-N and production remain unassessed",
        "physical_case_id": CASE_ID, "physical_binding_sha256": PHYSICAL_BINDING_SHA,
        "window_s": [0.0, TIME_END_S], "grid_step_s": float(args.grid_step), "grid_points": len(grid),
        "operators": {"macro": ["active_mass_kg", "com_x_m", "com_y_m", "com_z_m", "kinetic_energy_j"],
                      "interpolation": "linear interpolation of frame-level macro values at fixed physical times",
                      "time_bracket": "each target is recorded with the source lower/upper frame and actual saved times",
                      "budgets": {"macro_relative_starting_budget": 0.05, "event_time_relative_starting_budget": 0.02,
                                  "save_or_integration_share_cap": 0.20, "status": "diagnostic thresholds are preregistered, not a Q-N grant"}},
        "inputs": {"baseline": ref(baseline), "variants": [ref(path) for path in variants]}, "comparisons": {},
    }
    for path in variants:
        times, series = _macro_series(path)
        if times[0] > 0 or times[-1] < TIME_END_S:
            raise F3TimeStudyError(f"variant does not cover fixed physical window: {path}")
        interp = {key: np.interp(grid, times, values) for key, values in series.items()}
        metric: dict[str, Any] = {}
        for key in base_interp:
            delta = interp[key] - base_interp[key]
            scale = np.maximum(np.abs(base_interp[key]), 1e-12)
            metric[key] = {"max_abs": float(np.max(np.abs(delta))), "rms": float(np.sqrt(np.mean(delta * delta))),
                           "max_relative_to_baseline": float(np.max(np.abs(delta) / scale))}
        brackets = [_bracket(times, float(target)) for target in (0.0, 2.5, 5.0, 7.5, 10.0)]
        results["comparisons"][path.stem] = {
            "times": {"frame_count": len(times), "start_s": float(times[0]), "end_s": float(times[-1]),
                      "save_interval_min_s": float(np.min(np.diff(times))), "save_interval_max_s": float(np.max(np.diff(times)))},
            "macro_error": metric, "time_brackets": brackets,
            "qualification_status": "not_assessed",
        }
    output = Path(args.output).resolve()
    if output.exists():
        raise F3TimeStudyError(f"refusing to overwrite comparison: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2, sort_keys=True, default=_json_default) + "\n")
    return results


def bind_requests(args: argparse.Namespace) -> dict[str, Any]:
    handoff = load_json(Path(args.handoff))
    request_dir = Path(args.request_dir).resolve()
    request_dir.mkdir(parents=True, exist_ok=True)
    output: dict[str, Any] = {"schema": "ds02.f3.time-study-request-bindings.v1", "handoff": str(Path(args.handoff).resolve()), "variants": {}}
    for manifest in handoff["variants"]:
        variant = manifest["variant"]
        case_id = manifest["case_id"]
        gencase_receipt = Path(args.receipts[variant]).resolve()
        generated = _generated_variant_paths(gencase_receipt, case_id)
        variant_save = float(manifest["numeric_variant"]["variant_save_interval_s"])
        solver_attempt = f"qualification-weak-dual-{variant}-20261002-001"
        solver_case_root = DATA_ROOT / "families" / "F3" / case_id / solver_attempt
        solver_request = _base_request(
            case_id=case_id, attempt_id=solver_attempt,
            command=[str(SOLVER), "-mdbc_noslip:1", str(generated["prefix"]), "{attempt_root}/solver_output", "-tmax:10", f"-tout:{variant_save:.17g}"],
            kind="qualification", cpu_task_kind=None, cwd=generated["root"],
            max_wall=1800 if variant == "half_dt" else 1200, cpu_threads=4,
            storage=(40 if variant == "half_dt" else 72) * 1024**3,
            inputs=[gencase_receipt, generated["xml"], generated["bi4"], generated["control"], Path(manifest["manifest_path"]), Path(manifest["owner_metadata"]["path"]),
                    Path(args.baseline_owner), Path(args.operators), Path(args.f3_script), SOLVER],
            scope=f"F3 weak dual {variant} independent time-integration/save-frequency qualification request; same physical binding, root-only GPU launch, no automatic Q-N",
        )
        solver_request.update({"physical_case_id": CASE_ID, "study_role": variant, "output_interval_s": variant_save,
                               "gencase_receipt": str(gencase_receipt), "gencase_receipt_sha256": digest(gencase_receipt),
                               "estimated_peak_gpu_mib": 8192, "gpu_launcher": "root-only via runtime_v2",
                               "physical_binding_sha256": PHYSICAL_BINDING_SHA, "source_control_sha256": CONTROL_SHA,
                               "numeric_parameters": manifest["numeric_variant"]})
        solver_path = request_dir / f"{variant}-solver-request.json"
        solver_path.write_text(json.dumps(solver_request, indent=2, sort_keys=True, default=_json_default) + "\n")

        solver_receipt = solver_case_root / "execution-receipt.json"
        data_root = solver_case_root / "solver_output/data"
        xml_path = generated["xml"]
        native_accounting = solver_case_root / "native-window-accounting.json"
        native_request = _base_request(
            case_id=case_id, attempt_id=f"native-accounting-{variant}-20261002-001",
            command=[str(LAB / ".venv/bin/python"), str(Path(__file__).resolve()), "native-accounting", "--case-id", case_id,
                     "--attempt-id", solver_attempt, "--solver-receipt", str(solver_receipt), "--runparts", str(solver_case_root / "solver_output/RunPARTs.csv"),
                     "--run-csv", str(solver_case_root / "solver_output/Run.csv"), "--run-out", str(solver_case_root / "solver_output/Run.out"), "--output", "{attempt_root}/native-accounting.json"],
            kind="cpu", cpu_task_kind="audit", cwd=LAB, max_wall=180, cpu_threads=2, storage=64 * 1024**2,
            inputs=[Path(__file__).resolve(), solver_receipt, solver_case_root / "solver_output/RunPARTs.csv", solver_case_root / "solver_output/Run.csv", solver_case_root / "solver_output/Run.out", xml_path],
            scope=f"F3 {variant} actual RunPARTs/Run.out native time ledger; no solver/GPU/Q-N",
        )
        native_path = request_dir / f"{variant}-native-accounting-request.json"
        native_path.write_text(json.dumps(native_request, indent=2, sort_keys=True, default=_json_default) + "\n")

        direct_attempt = f"direct-{variant}-20261002-001"
        direct_request = _base_request(
            case_id=case_id, attempt_id=direct_attempt,
            command=[str(LAB / ".venv/bin/python"), str(LAB / "scripts/ds_data02_f3_weak.py"), "--data-root", str(data_root), "--generated-xml", str(xml_path),
                     "--output", "{attempt_root}/trajectory.h5", "--conversion-report", "{attempt_root}/direct-conversion-report.json", "--audit-report", "{attempt_root}/f3-weak-audit-report.json",
                     "--decoder", str(DECODER), "--partvtk", str(PARTVTK), "--validation-dir", "{attempt_root}/partvtk-validation", "--solver-log", str(solver_case_root / "solver_output/Run.out"),
                     "--solver-receipt", str(solver_receipt), "--gencase-receipt", str(gencase_receipt), "--owner-metadata", str(args.baseline_owner),
                     "--native-accounting", str(native_accounting), "--operators", str(args.operators), "--labels", "{attempt_root}/typed-transport-labels.json",
                     "--timeseries", "{attempt_root}/typed-transport-timeseries.csv", "--preview-dir", "{attempt_root}/previews", "--particle-chunk", "65536"],
            kind="cpu", cpu_task_kind="conversion", cwd=LAB, max_wall=2400 if variant == "half_dt" else 3600, cpu_threads=4,
            storage=(28 if variant == "half_dt" else 56) * 1024**3,
            inputs=[Path(__file__).resolve(), LAB / "scripts/ds_data02_f3_weak.py", LAB / "scripts/ds_data02_direct_convert.py", NATIVE_LABELS, DECODER, PARTVTK, xml_path, generated["bi4"], generated["control"], gencase_receipt, solver_receipt,
                    solver_case_root / "solver_output/Run.out", solver_case_root / "solver_output/RunPARTs.csv", data_root / "PartInfo.ibi4", data_root / "Part_0000.bi4", Path(manifest["manifest_path"]), Path(args.operators)],
            scope=f"F3 {variant} streaming BI4 direct conversion plus F3 finite-aperture typed labels/preview; no solver/GPU/Q-N",
        )
        direct_path = request_dir / f"{variant}-direct-conversion-request.json"
        direct_path.write_text(json.dumps(direct_request, indent=2, sort_keys=True, default=_json_default) + "\n")

        labels_attempt = f"native-labels-{variant}-20261002-001"
        labels_request = _base_request(
            case_id=case_id, attempt_id=labels_attempt,
            command=[str(LAB / ".venv/bin/python"), str(NATIVE_LABELS), "--source", str(DATA_ROOT / "families/F3" / case_id / direct_attempt / "trajectory.h5"),
                     "--output", "{attempt_root}/typed-transport-labels.h5", "--config", str(args.labels_config), "--particle-chunk", "65536"],
            kind="cpu", cpu_task_kind="labels", cwd=LAB, max_wall=1800 if variant == "half_dt" else 3000, cpu_threads=4,
            storage=(3 if variant == "half_dt" else 6) * 1024**3,
            inputs=[NATIVE_LABELS, Path(args.labels_config), Path(__file__).resolve(), DATA_ROOT / "families/F3" / case_id / direct_attempt / "trajectory.h5", Path(manifest["manifest_path"])],
            scope=f"F3 {variant} full typed destination/residence/event sidecar over immutable direct H5; no solver/GPU/Q-N",
        )
        labels_path = request_dir / f"{variant}-native-labels-request.json"
        labels_path.write_text(json.dumps(labels_request, indent=2, sort_keys=True, default=_json_default) + "\n")

        # This is the bounded, read-only initial-state check that must happen
        # after each GenCase and before a root-launched solver request.  It
        # uses the full PartVTK binary, never PartVTKOut, so all initial types,
        # typed identities and masses are checked against the registered
        # baseline.  The generated files are external attempt outputs and are
        # immutable inputs to this audit request.
        partvtk_attempt = f"initial-partvtk-{variant}-20261002-001"
        partvtk_request = _base_request(
            case_id=case_id, attempt_id=partvtk_attempt,
            command=[str(LAB / ".venv/bin/python"), str(Path(__file__).resolve()), "initial-partvtk",
                     "--bi4", str(generated["bi4"]), "--xml", str(generated["xml"]),
                     "--output", "{attempt_root}/initial-partvtk.json"],
            kind="cpu", cpu_task_kind="audit", cwd=LAB, max_wall=300, cpu_threads=4,
            storage=512 * 1024**2,
            inputs=[Path(__file__).resolve(), generated["bi4"], generated["xml"], gencase_receipt,
                    PARTVTK, Path(manifest["manifest_path"]), Path(manifest["owner_metadata"]["path"]),
                    Path(args.baseline_owner)],
            scope=f"F3 {variant} actual full-PartVTK initial typed-state/mass preflight; no solver/GPU/Q-N",
        )
        partvtk_request.update({"physical_case_id": CASE_ID, "study_role": variant,
                                "gencase_receipt": str(gencase_receipt),
                                "gencase_receipt_sha256": digest(gencase_receipt),
                                "partvtk_binary": str(PARTVTK),
                                "physical_binding_sha256": PHYSICAL_BINDING_SHA,
                                "source_control_sha256": CONTROL_SHA,
                                "expected_initial_state": {"total_particles": EXPECTED_TOTAL,
                                                            "fluid_particles": EXPECTED_FLUID,
                                                            "fluid_mass_kg": EXPECTED_MASS_KG}})
        partvtk_path = request_dir / f"{variant}-initial-partvtk-request.json"
        partvtk_path.write_text(json.dumps(partvtk_request, indent=2, sort_keys=True, default=_json_default) + "\n")
        output["variants"][variant] = {"solver": str(solver_path), "native_accounting": str(native_path),
                                        "direct": str(direct_path), "labels": str(labels_path),
                                        "initial_partvtk": str(partvtk_path)}

    comparison_case = CASE_ID + "_TIME_STUDY"
    comparison_attempt = "fixed-window-comparison-20261002-001"
    base_h5 = Path(args.baseline_h5).resolve()
    variant_h5s = [DATA_ROOT / "families/F3" / handoff["variants"][i]["case_id"] / f"direct-{handoff['variants'][i]['variant']}-20261002-001/trajectory.h5" for i in range(len(handoff["variants"]))]
    comparison = _base_request(
        case_id=comparison_case, attempt_id=comparison_attempt,
        command=[str(LAB / ".venv/bin/python"), str(Path(__file__).resolve()), "compare", "--baseline", str(base_h5), "--variant", str(variant_h5s[0]), "--variant", str(variant_h5s[1]),
                 "--grid-step", "0.0025", "--output", "{attempt_root}/fixed-window-comparison.json"],
        kind="cpu", cpu_task_kind="audit", cwd=LAB, max_wall=900, cpu_threads=4, storage=512 * 1024**2,
        inputs=[Path(__file__).resolve(), base_h5, *variant_h5s, Path(args.operators), Path(args.labels_config), Path(handoff["handoff"] if "handoff" in handoff else args.handoff)],
        scope="F3 fixed physical 0-10 s macro/time-bracket comparison on preregistered operators; diagnostics only, no Q-N",
    )
    comparison["physical_binding_sha256"] = PHYSICAL_BINDING_SHA
    comparison["fixed_window_s"] = [0.0, TIME_END_S]
    comparison["budget_contract"] = {"macro_relative": 0.05, "event_time_relative": 0.02, "save_or_integration_share": 0.20, "status": "not_assessed"}
    comparison_path = request_dir / "fixed-window-comparison-request.json"
    comparison_path.write_text(json.dumps(comparison, indent=2, sort_keys=True, default=_json_default) + "\n")
    output["comparison"] = str(comparison_path)
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--source-def", type=Path, required=True)
    p.add_argument("--source-control", type=Path, required=True)
    p.add_argument("--baseline-runparts", type=Path, required=True)
    p.add_argument("--baseline-run", type=Path, required=True)
    p.add_argument("--baseline-run-out", type=Path, required=True)
    p.add_argument("--owner-metadata", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.set_defaults(func=prepare)
    p = sub.add_parser("native-accounting")
    p.add_argument("--case-id", required=True)
    p.add_argument("--attempt-id", required=True)
    p.add_argument("--solver-receipt", type=Path, required=True)
    p.add_argument("--runparts", type=Path, required=True)
    p.add_argument("--run-csv", type=Path, required=True)
    p.add_argument("--run-out", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(func=make_native_accounting)
    p = sub.add_parser("initial-partvtk")
    p.add_argument("--bi4", type=Path, required=True)
    p.add_argument("--xml", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(func=run_initial_partvtk)
    p = sub.add_parser("compare")
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--variant", type=Path, action="append", required=True)
    p.add_argument("--grid-step", type=float, default=0.0025)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(func=compare_fixed_window)
    p = sub.add_parser("bind-requests")
    p.add_argument("--handoff", type=Path, required=True)
    p.add_argument("--request-dir", type=Path, required=True)
    p.add_argument("--receipt-half-dt", dest="receipt_half_dt", type=Path, required=True)
    p.add_argument("--receipt-half-save", dest="receipt_half_save", type=Path, required=True)
    p.add_argument("--baseline-owner", type=Path, required=True)
    p.add_argument("--operators", type=Path, required=True)
    p.add_argument("--labels-config", type=Path, required=True)
    p.add_argument("--baseline-h5", type=Path, required=True)
    p.add_argument("--f3-script", type=Path, required=True)
    p.set_defaults(func=lambda args: bind_requests(argparse.Namespace(**vars(args), receipts={"half_dt": args.receipt_half_dt, "half_save": args.receipt_half_save})))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = args.func(args)
    except (F3TimeStudyError, OSError, ValueError, ET.ParseError) as exc:
        print(f"F3 time study failed: {exc}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
