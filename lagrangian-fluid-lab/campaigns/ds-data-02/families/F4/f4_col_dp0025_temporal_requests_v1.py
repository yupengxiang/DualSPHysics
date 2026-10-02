#!/usr/bin/env python3
"""Prepare root-review-only temporal views for the F4 finest COL reference.

The source is the completed 1.2 s, 0.001 s-save F4 COL centered DP0025
reference.  This additive study creates two fresh co-located input copies:

* ``HALF_DT`` keeps the 0.001 s save cadence and explicitly sets
  ``DtFixed=DtIni=DtMin`` to half of the completed baseline's minimum positive
  native ``RunPARTs`` timestep;
* ``DENSE_SAVE`` keeps the adaptive numerical recipe and changes only
  ``TimeOut`` from 0.001 s to 0.0005 s (2401 expected frames).

The generated requests bind the original physical binding, two 6.336 kg
source columns, fixed DBC support, the source BI4 and every baseline audit
byte.  They are numerical controls only: this module never launches a solver,
GenCase, conversion, PartVTKOut or labels and grants no Q-I/Q-N status.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from typing import Any


FAMILY_ROOT = Path(__file__).resolve().parent
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F4_DATA_ROOT = DATA_ROOT / "families/F4"
BASELINE_CASE_ID = "F4_COL_CENTERED_REFERENCE_001_DP0025"
PHYSICAL_CASE_ID = "F4_COL_gap0p52000_vy0p25000_yoff0p00000_lx0p22000"
PHYSICAL_BINDING_SHA256 = "dbc97c0081fa8622c1f5da4348e2b78a56eca55bdcdcc39f1e601976dbdcca85"
BASELINE_DIR = F4_DATA_ROOT / BASELINE_CASE_ID
BASELINE_GENCASE_DIR = BASELINE_DIR / "gencase-centered-reference-002"
BASELINE_SOLVER_DIR = BASELINE_DIR / "qualification-centered-fullwindow-001"
BASELINE_OUTPUT = BASELINE_SOLVER_DIR / "solver_output"
BASELINE_XML = BASELINE_GENCASE_DIR / f"{BASELINE_CASE_ID}.xml"
BASELINE_BI4 = BASELINE_GENCASE_DIR / f"{BASELINE_CASE_ID}.bi4"
GENCASE_RECEIPT = BASELINE_GENCASE_DIR / "execution-receipt.json"
SOLVER_RECEIPT = BASELINE_SOLVER_DIR / "execution-receipt.json"
RUN_CSV = BASELINE_OUTPUT / "Run.csv"
RUN_OUT = BASELINE_OUTPUT / "Run.out"
RUNPARTS = BASELINE_OUTPUT / "RunPARTs.csv"
SOURCE_METADATA = INTEGRATION_ROOT / "campaigns/ds-data-02/families/F4/handoff_20261002/centered_reference_matrix_001/F4_COL_CENTERED_REFERENCE_001_DP0025.metadata.json"
SOURCE_DEF = INTEGRATION_ROOT / "campaigns/ds-data-02/families/F4/handoff_20261002/centered_reference_matrix_001/F4_COL_CENTERED_REFERENCE_001_DP0025_Def.xml"
BASELINE_SOLVER_REQUEST = INTEGRATION_ROOT / "campaigns/ds-data-02/families/F4/handoff_20261002/centered_reference_matrix_001/F4_COL_CENTERED_REFERENCE_001_DP0025_solver_request.json"
BASELINE_OWNER = INTEGRATION_ROOT / "campaigns/ds-data-02/families/F4/handoff_20261002/centered_reference_matrix_001/F4_COL_CENTERED_REFERENCE_001_DP0025_fullstate_owner_001.json"
NATIVE_AUDIT = BASELINE_DIR / "root-centered-initial-audit-001/native-preflight-audit.json"
NATIVE_AUDIT_RECEIPT = BASELINE_DIR / "root-centered-initial-audit-001/execution-receipt.json"
FROZEN_OBSERVABLES = INTEGRATION_ROOT / "campaigns/ds-data-02/families/F4/handoff_20261002/centered_reference_matrix_001/frozen_observables_001.json"
FAMILY_CARD = INTEGRATION_ROOT / "campaigns/ds-data-02/families/F4/family_card.json"
CASE_REGISTRY = INTEGRATION_ROOT / "campaigns/ds-data-02/families/F4/case_registry.jsonl"
SAVE_PLAN = INTEGRATION_ROOT / "campaigns/ds-data-02/families/F4/integration_save_plan.json"
RUNTIME_V2 = INTEGRATION_ROOT / "scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH = INTEGRATION_ROOT / "scripts/ds_data02_strict_dispatch_v1.py"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
OUTPUT_ROOT = F4_DATA_ROOT / "F4_COL_CENTERED_REFERENCE_001_DP0025_TEMPORAL_INPUTS_20261002"
REQUEST_ROOT = FAMILY_ROOT / "temporal_studies_dp0025_v1"
RECIPE_ID = "F4_COL_DP0025_TEMPORAL_STUDY_V1"
SCOPE_ID = "F4_SCOPE_COL_CENTERED_REFERENCE_001_DP0025"
BASELINE_PHYSICAL_MASS_KG = 12.672
SOURCE_MASS_KG = 6.336
TIME_MAX_S = 1.2
BASELINE_SAVE_S = 0.001
DENSE_SAVE_S = 0.0005
BASELINE_FRAMES = 1201
DENSE_FRAMES = 2401
BYTES_PER_PARTICLE_FRAME = 64
STORAGE_MARGIN = 1.40
HALF_DT_WALL_SECONDS = 6000
DENSE_SAVE_WALL_SECONDS = 9000
EXPECTED_BASELINE_RUN_OUT_DT_MIN_S = 8.203647063057792e-06
EXPECTED_BASELINE_RUN_OUT_DT_INI_S = 0.0001640729388162785
NUMERICAL_KEYS = {"TimeOut", "DtFixed", "DtIni", "DtMin"}


def require(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with require(path, "hash input").open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path) -> dict[str, Any]:
    path = require(path, "input binding")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def replace_parameter(text: str, key: str, value: str) -> str:
    pattern = rf'(<parameter\s+key="{re.escape(key)}"\s+value=")[^"]+("\s*/>)'
    rewritten, count = re.subn(pattern, rf"\g<1>{value}\g<2>", text, count=1)
    if count != 1:
        raise ValueError(f"expected one XML execution parameter {key}, found {count}")
    return rewritten


def xml_parameters(path: Path) -> dict[str, str]:
    import xml.etree.ElementTree as ET

    root = ET.parse(require(path, "generated XML")).getroot()
    return {
        str(node.attrib["key"]): str(node.attrib.get("value", ""))
        for node in root.findall(".//execution/parameters/parameter")
        if node.attrib.get("key") is not None
    }


def physical_projection(path: Path) -> dict[str, Any]:
    import xml.etree.ElementTree as ET

    root = ET.parse(require(path, "XML physical projection")).getroot()

    def normalized(node: ET.Element) -> Any:
        attrs = dict(node.attrib)
        if node.tag == "parameter" and attrs.get("key") in NUMERICAL_KEYS:
            attrs["value"] = "<numerical-view>"
        return (
            str(node.tag),
            tuple(sorted((str(k), str(v)) for k, v in attrs.items())),
            (node.text or "").strip(),
            tuple(normalized(child) for child in node),
        )

    return {
        "physical_projection_sha256": canonical_hash(normalized(root)),
        "full_xml_sha256": sha256(path),
        "parameters": xml_parameters(path),
    }


def parse_runparts(path: Path) -> dict[str, Any]:
    path = require(path, "baseline RunPARTs.csv")
    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = [item.strip() for item in line.split(";")]
        if header is None:
            header = fields
            continue
        if len(fields) == len(header):
            rows.append(dict(zip(header, fields)))
    if not rows or header is None:
        raise ValueError(f"no RunPARTs rows: {path}")

    def number(row: dict[str, str], key: str) -> float:
        return float(row[key].replace(",", ""))

    parts = [int(number(row, "Part")) for row in rows]
    if parts != list(range(len(rows))):
        raise ValueError(f"RunPARTs parts are not contiguous: {path}")
    dts = [number(row, "DtMin [s]") for row in rows if number(row, "DtMin [s]") > 0.0]
    if not dts:
        raise ValueError(f"no positive RunPARTs DtMin values: {path}")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "rows": len(rows),
        "first_time_s": number(rows[0], "TimeStep [s]"),
        "last_time_s": number(rows[-1], "TimeStep [s]"),
        "global_min_positive_dt_s": min(dts),
        "global_max_positive_dt_s": max(dts),
        "initial_particles": int(number(rows[0], "NpSim")),
        "initial_fluid_particles": int(number(rows[0], "NpfSim")),
        "final_fluid_particles": int(number(rows[-1], "NpfSim")),
        "np_out_sum": int(sum(number(row, "NpOut") for row in rows)),
        "np_out_pos_sum": int(sum(number(row, "NpOutPos") for row in rows)),
    }


def parse_run_out(path: Path) -> dict[str, Any]:
    path = require(path, "baseline Run.out")
    text = path.read_text(encoding="utf-8", errors="replace")

    def scalar(key: str) -> float:
        matches = re.findall(rf"(?m)^\s*{re.escape(key)}=\s*([-+0-9.eE]+)\s*$", text)
        if len(matches) != 1:
            raise ValueError(f"expected one {key}= line in {path}, found {len(matches)}")
        return float(matches[0])

    steps_match = re.search(r"(?m)^Steps of simulation\.*:\s*([0-9,]+)\s*$", text)
    adjusted_match = re.search(r"(?m)^DTs adjusted to DtMin\.*:\s*([0-9,]+)\s*$", text)
    if not steps_match or not adjusted_match:
        raise ValueError(f"missing completed Run.out totals: {path}")
    values = {
        "DtIni_s": scalar("DtIni"),
        "DtMin_s": scalar("DtMin"),
        "TimeMax_s": scalar("TimeMax"),
        "steps": int(steps_match.group(1).replace(",", "")),
        "dts_adjusted_to_dtmin": int(adjusted_match.group(1).replace(",", "")),
    }
    if not math.isclose(values["DtMin_s"], EXPECTED_BASELINE_RUN_OUT_DT_MIN_S, rel_tol=0.0, abs_tol=1e-18):
        raise ValueError(f"unexpected Run.out DtMin: {values['DtMin_s']}")
    if not math.isclose(values["DtIni_s"], EXPECTED_BASELINE_RUN_OUT_DT_INI_S, rel_tol=0.0, abs_tol=1e-18):
        raise ValueError(f"unexpected Run.out DtIni: {values['DtIni_s']}")
    if values["TimeMax_s"] != TIME_MAX_S:
        raise ValueError(f"unexpected Run.out TimeMax: {values['TimeMax_s']}")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, **values}


def parse_run_csv(path: Path) -> dict[str, Any]:
    path = require(path, "baseline Run.csv")
    lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError(f"Run.csv has no row: {path}")
    header = lines[0].split(";")
    values = lines[1].split(";")
    if len(values) != len(header):
        raise ValueError(f"Run.csv row/header mismatch: {path}")
    row = dict(zip(header, values))
    return {
        "path": str(path),
        "sha256": sha256(path),
        "physical_time_s": float(row["PhysicalTime"]),
        "part_files": int(row["PartFiles"].replace(",", "")),
        "parts_out": int(row["PartsOut"].replace(",", "")),
    }


def load_source() -> dict[str, Any]:
    for path in (BASELINE_XML, BASELINE_BI4, GENCASE_RECEIPT, SOLVER_RECEIPT, RUN_CSV, RUN_OUT, RUNPARTS, SOURCE_METADATA, SOURCE_DEF, BASELINE_SOLVER_REQUEST, BASELINE_OWNER, NATIVE_AUDIT, NATIVE_AUDIT_RECEIPT, FROZEN_OBSERVABLES, FAMILY_CARD, CASE_REGISTRY, SAVE_PLAN, RUNTIME_V2, STRICT_DISPATCH, SOLVER):
        require(path, "F4 source")
    metadata = json.loads(SOURCE_METADATA.read_text(encoding="utf-8"))
    if metadata.get("physical_binding_sha256") != PHYSICAL_BINDING_SHA256:
        raise ValueError("F4 COL metadata physical binding changed")
    if metadata.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("F4 COL physical case changed")
    if metadata.get("continuous_mass_by_source_kg") != {"left_column": SOURCE_MASS_KG, "right_column": SOURCE_MASS_KG}:
        raise ValueError("F4 COL source mass binding changed")
    gencase = json.loads(GENCASE_RECEIPT.read_text(encoding="utf-8"))
    if gencase.get("returncode", gencase.get("gencase_returncode")) != 0 or gencase.get("status") != "completed":
        raise ValueError("F4 COL GenCase receipt is not completed")
    if gencase.get("total_particles") != 1195649 or gencase.get("fluid_particles") != 811008 or gencase.get("solver_dimension_from_gencase") != 3:
        raise ValueError("F4 COL GenCase actual population is not the registered 3D source")
    baseline_parameters = xml_parameters(BASELINE_XML)
    for key, value in {"TimeMax": "1.2", "TimeOut": "0.001", "DtFixed": "0", "DtIni": "0", "DtMin": "0", "CoefDtMin": "0.05"}.items():
        if baseline_parameters.get(key) != value:
            raise ValueError(f"unexpected baseline XML {key}: {baseline_parameters.get(key)}")
    projection = physical_projection(BASELINE_XML)
    runparts = parse_runparts(RUNPARTS)
    runout = parse_run_out(RUN_OUT)
    runcsv = parse_run_csv(RUN_CSV)
    if runparts["rows"] != BASELINE_FRAMES or runout["steps"] != 77671 or runcsv["part_files"] != BASELINE_FRAMES:
        raise ValueError("F4 COL baseline frame/step evidence changed")
    if not math.isclose(runparts["global_min_positive_dt_s"], EXPECTED_BASELINE_RUN_OUT_DT_MIN_S, rel_tol=0.0, abs_tol=1e-18):
        raise ValueError("RunPARTs minimum does not bind the completed Run.out floor")
    receipt = json.loads(SOLVER_RECEIPT.read_text(encoding="utf-8"))
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("F4 COL baseline solver receipt is not completed code 0")
    return {
        "metadata": metadata,
        "gencase": gencase,
        "baseline_parameters": baseline_parameters,
        "projection": projection,
        "runparts": runparts,
        "runout": runout,
        "runcsv": runcsv,
        "solver_receipt_data": receipt,
    }


def make_variant(source: dict[str, Any], name: str, stage_root: Path) -> dict[str, Any]:
    if name == "half_dt":
        suffix = "HALF_DT_SAVE001_FLOORSAFE001"
        time_out = BASELINE_SAVE_S
        dt = source["runparts"]["global_min_positive_dt_s"] / 2.0
        frames = BASELINE_FRAMES
        max_wall = HALF_DT_WALL_SECONDS
        floor_safe = True
    elif name == "dense_save":
        suffix = "DENSE_SAVE0005_ADAPTIVE001"
        time_out = DENSE_SAVE_S
        dt = 0.0
        frames = DENSE_FRAMES
        max_wall = DENSE_SAVE_WALL_SECONDS
        floor_safe = False
    else:
        raise ValueError(f"unknown F4 COL variant: {name}")
    variant_case_id = f"{BASELINE_CASE_ID}_{suffix}"
    variant_stage = stage_root / variant_case_id
    if variant_stage.exists():
        raise FileExistsError(f"fresh F4 temporal staging already exists: {variant_stage}")
    variant_stage.mkdir(parents=True)
    prefix = variant_stage / variant_case_id
    xml_path = prefix.with_suffix(".xml")
    xml_text = BASELINE_XML.read_text(encoding="utf-8")
    xml_text = replace_parameter(xml_text, "TimeOut", format(time_out, ".17g"))
    if floor_safe:
        for key in ("DtFixed", "DtIni", "DtMin"):
            xml_text = replace_parameter(xml_text, key, format(dt, ".17g"))
    xml_path.write_text(xml_text, encoding="utf-8")
    bi4_path = prefix.with_suffix(".bi4")
    shutil.copyfile(BASELINE_BI4, bi4_path)
    if sha256(bi4_path) != sha256(BASELINE_BI4):
        raise ValueError(f"{variant_case_id}: BI4 changed during staging")
    new_projection = physical_projection(xml_path)
    if new_projection["physical_projection_sha256"] != source["projection"]["physical_projection_sha256"]:
        raise ValueError(f"{variant_case_id}: physical XML projection changed")
    params = new_projection["parameters"]
    if params.get("TimeMax") != "1.2" or params.get("CoefDtMin") != "0.05":
        raise ValueError(f"{variant_case_id}: physical control changed")
    if floor_safe:
        for key in ("DtFixed", "DtIni", "DtMin"):
            if not math.isclose(float(params[key]), dt, rel_tol=0.0, abs_tol=1e-18):
                raise ValueError(f"{variant_case_id}: {key} does not equal requested half dt")
    else:
        for key in ("DtFixed", "DtIni", "DtMin"):
            if params.get(key) != "0":
                raise ValueError(f"{variant_case_id}: dense adaptive dt control changed")
    numerical_fields = {
        "recipe_id": RECIPE_ID,
        "variant": name,
        "source_reference_case_id": BASELINE_CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "physical_binding_sha256": PHYSICAL_BINDING_SHA256,
        "dp_m": 0.0025,
        "time_max_s": TIME_MAX_S,
        "time_out_s": time_out,
        "DtFixed_s": dt,
        "DtIni_s": dt if floor_safe else 0.0,
        "DtMin_s": dt if floor_safe else 0.0,
        "CoefDtMin": 0.05,
        "expected_frames": frames,
        "baseline_global_min_positive_dt_s": source["runparts"]["global_min_positive_dt_s"],
        "baseline_Run_out_default_DtMin_s": source["runout"]["DtMin_s"],
        "baseline_Run_out_default_DtIni_s": source["runout"]["DtIni_s"],
        "half_native_dt_definition": "0.5 * completed baseline RunPARTs global minimum positive DtMin" if floor_safe else None,
        "source_masses_kg": {"left_column": SOURCE_MASS_KG, "right_column": SOURCE_MASS_KG},
        "fixed_support": True,
        "motion_control": "none; fixed finite DBC tank support",
    }
    numerical_hash = canonical_hash(numerical_fields)
    total_particles = source["runparts"]["initial_particles"]
    raw_bytes = total_particles * frames * BYTES_PER_PARTICLE_FRAME
    storage_bytes = math.ceil(raw_bytes * STORAGE_MARGIN)
    expected_steps = math.ceil(TIME_MAX_S / dt) if floor_safe else source["runout"]["steps"]
    step_ratio = expected_steps / source["runout"]["steps"]
    predicted_wall = float(source["solver_receipt_data"]["elapsed_seconds"]) * step_ratio
    return {
        "variant_case_id": variant_case_id,
        "variant": name,
        "staging": {
            "directory": str(variant_stage),
            "prefix": str(prefix),
            "generated_xml": binding(xml_path),
            "copied_bi4": binding(bi4_path),
            "motion": None,
        },
        "physical_condition_hash": PHYSICAL_BINDING_SHA256,
        "numerical_fields": numerical_fields,
        "numerical_recipe_hash": numerical_hash,
        "physical_equivalence": {
            "physical_binding_sha256": PHYSICAL_BINDING_SHA256,
            "physical_xml_projection_sha256": new_projection["physical_projection_sha256"],
            "allowed_xml_changes": ["TimeOut", "DtFixed", "DtIni", "DtMin"] if floor_safe else ["TimeOut"],
            "source_bi4_hash_equal": sha256(bi4_path) == sha256(BASELINE_BI4),
            "fixed_support": True,
            "motion_file": None,
        },
        "floor_safe_override": {
            "enabled": floor_safe,
            "default_run_out_DtMin_s": source["runout"]["DtMin_s"],
            "default_run_out_DtIni_s": source["runout"]["DtIni_s"],
            "observed_RunPARTs_min_positive_DtMin_s": source["runparts"]["global_min_positive_dt_s"],
            "explicit_DtFixed_s": dt if floor_safe else None,
            "explicit_DtIni_s": dt if floor_safe else None,
            "explicit_DtMin_s": dt if floor_safe else None,
            "target_below_default_Run_out_DtMin": floor_safe and dt < source["runout"]["DtMin_s"],
            "solver_realized_timestep_review_pending": True,
        },
        "resource_estimate": {
            "actual_initial_particles": total_particles,
            "expected_frames": frames,
            "bytes_per_particle_frame": BYTES_PER_PARTICLE_FRAME,
            "raw_trajectory_bytes_lower_bound": raw_bytes,
            "storage_margin_fraction": STORAGE_MARGIN - 1.0,
            "estimated_storage_bytes": storage_bytes,
            "estimated_storage_gib": storage_bytes / 1024**3,
            "baseline_elapsed_seconds": float(source["solver_receipt_data"]["elapsed_seconds"]),
            "baseline_steps": source["runout"]["steps"],
            "estimated_steps": expected_steps,
            "estimated_step_ratio": step_ratio,
            "predicted_wall_seconds": predicted_wall,
            "requested_wall_seconds": max_wall,
        },
        "timing_and_study_role": {
            "time_window_s": [0.0, TIME_MAX_S],
            "baseline_save_s": BASELINE_SAVE_S,
            "candidate_save_s": time_out,
            "candidate_save_half_width_s": time_out / 2.0,
            "frozen_event_time_budget_s": 0.0031044560004650622,
            "frozen_temporal_share_fraction": 0.2,
            "frozen_temporal_share_budget_s": 0.0006208912000930125,
            "save_cadence_within_frozen_temporal_share": time_out / 2.0 <= 0.0006208912000930125,
            "timing_qualification_candidate": True,
            "independent_numerical_view_only": True,
        },
    }


def make_request(source: dict[str, Any], record: dict[str, Any], common_inputs: list[Path], definition_copy: Path) -> dict[str, Any]:
    staging = record["staging"]
    baseline_inputs = [BASELINE_XML, BASELINE_BI4, GENCASE_RECEIPT, SOLVER_RECEIPT, RUN_CSV, RUN_OUT, RUNPARTS, SOURCE_METADATA, SOURCE_DEF, BASELINE_SOLVER_REQUEST, BASELINE_OWNER, NATIVE_AUDIT, NATIVE_AUDIT_RECEIPT, FROZEN_OBSERVABLES]
    temporal_inputs = [Path(staging["generated_xml"]["path"]), Path(staging["copied_bi4"]["path"]), definition_copy]
    all_inputs = list(dict.fromkeys([*common_inputs, *baseline_inputs, *temporal_inputs]))
    input_files = [str(path.expanduser().resolve()) for path in all_inputs]
    input_hashes = {path: sha256(Path(path)) for path in input_files}
    numerical = record["numerical_fields"]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "kind": "qualification",
        "family_id": "F4",
        "case_id": record["variant_case_id"],
        "attempt_id": f"qualification-{record['variant_case_id'].lower()}-native-fullstate-v1",
        "command": [SOLVER.as_posix(), staging["prefix"], "{attempt_root}/solver_output"],
        "cwd": staging["directory"],
        "worktree_root": str(FAMILY_ROOT.parents[4]),
        "max_wall_seconds": record["resource_estimate"]["requested_wall_seconds"],
        "cpu_threads": 4,
        "estimated_peak_gpu_mib": 12288,
        "estimated_storage_bytes": record["resource_estimate"]["estimated_storage_bytes"],
        "event_window_s": TIME_MAX_S,
        "physical_case_id": PHYSICAL_CASE_ID,
        "source_reference_case_id": BASELINE_CASE_ID,
        "physical_condition_hash": PHYSICAL_BINDING_SHA256,
        "physical_geometry_control_hash": PHYSICAL_BINDING_SHA256,
        "numerical_recipe_hash": record["numerical_recipe_hash"],
        "recipe_id": RECIPE_ID,
        "scope_id": SCOPE_ID,
        "mechanism_id": "oblique_finite_columns",
        "resolution": "dp0025",
        "new_independent_physical_case_count": 0,
        "registry_role": "independent_time_study_outside_original_f4_registry",
        "gencase_prefix": staging["prefix"],
        "gencase_receipt": str(GENCASE_RECEIPT),
        "gencase_receipt_sha256": sha256(GENCASE_RECEIPT),
        "gencase_artifacts": {
            "source_prefix": str(BASELINE_XML.with_suffix("")),
            "source_generated_xml": binding(BASELINE_XML),
            "source_bi4": binding(BASELINE_BI4),
            "gencase_receipt": binding(GENCASE_RECEIPT),
            "temporal_generated_xml": record["staging"]["generated_xml"],
            "temporal_bi4": record["staging"]["copied_bi4"],
            "motion": None,
            "fixed_support": True,
        },
        "source_binding": {
            "physical_binding_sha256": PHYSICAL_BINDING_SHA256,
            "physical_case_id": PHYSICAL_CASE_ID,
            "source_reference_case_id": BASELINE_CASE_ID,
            "continuous_mass_total_kg": BASELINE_PHYSICAL_MASS_KG,
            "continuous_mass_by_source_kg": {"left_column": SOURCE_MASS_KG, "right_column": SOURCE_MASS_KG},
            "source_region_phase_exact": True,
            "fixed_support": True,
            "motion_control": "none; fixed finite DBC tank support",
            "baseline_xml": binding(BASELINE_XML),
            "baseline_bi4": binding(BASELINE_BI4),
            "baseline_solver_receipt": binding(SOLVER_RECEIPT),
            "baseline_run_out": binding(RUN_OUT),
            "baseline_runparts": binding(RUNPARTS),
            "baseline_projection_sha256": source["projection"]["physical_projection_sha256"],
            "physical_xml_allowed_changes": record["physical_equivalence"]["allowed_xml_changes"],
            "same_bi4_bytes": record["physical_equivalence"]["source_bi4_hash_equal"],
        },
        "numerical_recipe_fields": numerical,
        "floor_safe_override": record["floor_safe_override"],
        "resource_estimate": record["resource_estimate"],
        "timing_and_study_role": record["timing_and_study_role"],
        "thresholds_apply_before_results": True,
        "quality_thresholds": {
            "continuous_initial_mass_kg": BASELINE_PHYSICAL_MASS_KG,
            "continuous_initial_mass_by_source_kg": {"left_column": SOURCE_MASS_KG, "right_column": SOURCE_MASS_KG},
            "event_time_absolute_budget_s": 0.0031044560004650622,
            "macro_relative_error_threshold": 0.05,
            "temporal_item_allocation_fraction": 0.2,
            "unknown_native_fate_is_not_physical_spill": True,
            "q_i_q_n_production_claim": "none",
        },
        "input_files": input_files,
        "input_sha256": input_hashes,
        "dispatch_guard": {"path": str(STRICT_DISPATCH.resolve()), "sha256": sha256(STRICT_DISPATCH)},
        "gpu_launch": {"family_owner_launch": False, "requested_by": "primary_process"},
        "qualification_launch_authority": "shared_ds_data_02_runner_only_primary_process",
        "solver_launch_forbidden_in_this_module": True,
        "status": "ready_for_root_gpu_review_only",
        "qualification_claim": "none; independent F4 finest COL temporal study",
        "production_claim": "none",
        "request_note": "Additive numerical-only view of the completed F4 COL DP0025 source. Physical binding dbc97c.../12.672 kg, source masses 6.336 kg each, fixed support and complete 1.2 s window are unchanged. Root must review and launch; actual Run.out/realized timestep, native exclusions and Q-I remain pending.",
    }
    return request


def build(output_root: Path = OUTPUT_ROOT, request_root: Path = REQUEST_ROOT) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    request_root = request_root.expanduser().resolve()
    if output_root.exists() or request_root.exists():
        raise FileExistsError(f"fresh F4 temporal output required: {output_root} / {request_root}")
    source = load_source()
    for path in (FAMILY_ROOT / "f4_col_dp0025_temporal_requests_v1.py",):
        require(path, "F4 temporal generator")
    output_root.mkdir(parents=True)
    (request_root / "definitions").mkdir(parents=True)
    requests_root = request_root / "requests"
    requests_root.mkdir()
    common_inputs = [SOLVER, RUNTIME_V2, STRICT_DISPATCH, FAMILY_ROOT / "f4_col_dp0025_temporal_requests_v1.py", SOURCE_METADATA, SOURCE_DEF, BASELINE_SOLVER_REQUEST, BASELINE_OWNER, NATIVE_AUDIT, NATIVE_AUDIT_RECEIPT, FROZEN_OBSERVABLES, FAMILY_CARD, CASE_REGISTRY, SAVE_PLAN]
    records: list[dict[str, Any]] = []
    for name in ("half_dt", "dense_save"):
        stage_root = output_root / name
        stage_root.mkdir()
        record = make_variant(source, name, stage_root)
        definition_copy = request_root / "definitions" / record["variant_case_id"] / f"{record['variant_case_id']}.xml"
        definition_copy.parent.mkdir(parents=True)
        shutil.copyfile(record["staging"]["generated_xml"]["path"], definition_copy)
        request = make_request(source, record, common_inputs, definition_copy)
        request_path = requests_root / f"{record['variant_case_id']}_request.json"
        dump(request_path, request)
        record["definition_copy"] = binding(definition_copy)
        record["request"] = binding(request_path)
        records.append(record)
    manifest = {
        "schema": "ds02.f4.col-dp0025-temporal-study.v1",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": "F4",
        "recipe_id": RECIPE_ID,
        "scope_id": SCOPE_ID,
        "source_reference_case_id": BASELINE_CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "physical_binding_sha256": PHYSICAL_BINDING_SHA256,
        "physical_binding": {
            "continuous_mass_total_kg": BASELINE_PHYSICAL_MASS_KG,
            "source_masses_kg": {"left_column": SOURCE_MASS_KG, "right_column": SOURCE_MASS_KG},
            "fixed_support": True,
            "motion_control": "none",
            "complete_window_s": [0.0, TIME_MAX_S],
        },
        "source_baseline": {
            "xml": binding(BASELINE_XML),
            "bi4": binding(BASELINE_BI4),
            "gencase_receipt": binding(GENCASE_RECEIPT),
            "solver_receipt": binding(SOLVER_RECEIPT),
            "run_out": binding(RUN_OUT),
            "runparts": binding(RUNPARTS),
            "run_csv": binding(RUN_CSV),
            "baseline_run_out_DtMin_s": source["runout"]["DtMin_s"],
            "baseline_RunPARTs_min_positive_DtMin_s": source["runparts"]["global_min_positive_dt_s"],
            "baseline_steps": source["runout"]["steps"],
            "baseline_frames": BASELINE_FRAMES,
        },
        "variants": records,
        "new_independent_physical_case_count": 0,
        "gpu_launch": "primary process/root only",
        "solver_launch": False,
        "qualification_claim": "none",
        "production_claim": "none",
    }
    manifest_path = request_root / "temporal_study_manifest_v1.json"
    dump(manifest_path, manifest)
    return {"manifest": binding(manifest_path), "records": records}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--request-root", type=Path, default=REQUEST_ROOT)
    args = parser.parse_args()
    result = build(args.output_root, args.request_root)
    print(json.dumps({"manifest": result["manifest"], "requests": len(result["records"]), "solver_launch": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
