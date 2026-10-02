#!/usr/bin/env python3
"""Prepare additive DP005 dense-save and reduced-native-dt solver requests.

The source BI4 population and motion control are copied byte-for-byte from the
completed RV4EQ DP005 solver inputs.  Only the numerical XML recipe changes:

* ``dense_save001`` changes ``TimeOut`` from 0.01 s to 0.001 s and expects
  4001 native frames over the same 4 s window;
* ``reduced_dt_save010`` keeps ``TimeOut=0.01`` and sets ``DtFixed`` to one
  half of that background's measured global minimum positive native ``DtMin``.

This module materialises fresh co-located XML/BI4/motion input directories and
solver request JSON.  It never runs GenCase, DualSPHysics, conversion, or
PartVTKOut.  The two variants remain numerical views of the same physical
mother and are not Q-I/Q-N or production approvals.
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
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA_ROOT = DATA_ROOT / "families/F2"
V3_REQUEST_ROOT = FAMILY_ROOT / "rv4_equivalent_dp005/postprocess_handoff_v3_terminal_bound/conversion_requests"
OUTPUT_ROOT = F2_DATA_ROOT / "F2_RV4EQ_DP005_TEMPORAL_INPUTS_20261002"
REQUEST_ROOT = FAMILY_ROOT / "rv4_equivalent_dp005/temporal_studies_v1"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
RUNTIME_V2 = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
GOAL = FAMILY_ROOT.parents[1] / "GOAL_ZH.md"
QUALITY = FAMILY_ROOT / "quality_contract.json"
EVENTS = FAMILY_ROOT / "event_definitions.json"
SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"
CASE_REGISTRY = FAMILY_ROOT / "case_registry.jsonl"
REFERENCE_MATRIX = FAMILY_ROOT / "definitions/reference_matrix.json"
SCOPE_ID = "F2_SCOPE_RV4_EQUIVALENT_DP005_PRECHECK_20261002"
RECIPE_ID = "F2_RV4EQ_DP005_TEMPORAL_STUDY_V1"
CONTINUOUS_MASS_KG = 24.576
FLUID_PARTICLE_MASS_KG = 0.000125
EVENT_TIME_BUDGET_S = 0.0036681953999691376
SAVE_HALF_WIDTH_BUDGET_S = 0.0007336390799938275
MACRO_RELATIVE_BUDGET = 0.05
STORAGE_MARGIN = 1.40
BYTES_PER_PARTICLE_FRAME = 64
BASELINE_FRAMES = 401
DENSE_FRAMES = 4001
TIME_MAX_S = 4.0
VARIANTS = {
    "dense_save001": {
        "time_out_s": 0.001,
        "expected_frames": DENSE_FRAMES,
        "max_wall_seconds": 9000,
        "timing_candidate": True,
        "integration_candidate": False,
    },
    "reduced_dt_save010": {
        "time_out_s": 0.01,
        "expected_frames": BASELINE_FRAMES,
        "max_wall_seconds": 6000,
        "timing_candidate": False,
        "integration_candidate": True,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def require(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def load(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(require(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def binding(path: Path) -> dict[str, Any]:
    path = require(path, "input binding")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def replace_parameter(text: str, key: str, value: str) -> str:
    pattern = rf'(<parameter\s+key="{re.escape(key)}"\s+value=")[^"]+("\s*/>)'
    rewritten, count = re.subn(pattern, rf"\g<1>{value}\g<2>", text, count=1)
    if count != 1:
        raise ValueError(f"expected one execution parameter {key}, found {count}")
    return rewritten


def xml_parameters(path: Path) -> dict[str, str]:
    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()
    return {
        str(node.attrib["key"]): str(node.attrib.get("value", ""))
        for node in root.findall(".//execution/parameters/parameter")
        if node.attrib.get("key") is not None
    }


def xml_physical_projection(path: Path) -> dict[str, Any]:
    """Return XML fields that must remain equal across numerical views."""
    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()

    def node_projection(node: ET.Element) -> Any:
        return (
            str(node.tag),
            tuple(sorted((str(k), str(v)) for k, v in node.attrib.items())),
            (node.text or "").strip(),
            tuple(node_projection(child) for child in node),
        )

    allowed = {"TimeOut", "DtFixed"}

    def normalized(node: ET.Element) -> Any:
        attrs = dict(node.attrib)
        if node.tag == "parameter" and attrs.get("key") in allowed:
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
    path = require(path, "terminal RunPARTs.csv")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if header is None:
            header = [item.strip() for item in line.split(";")]
            continue
        values = [item.strip() for item in line.split(";")]
        if len(values) == len(header):
            rows.append(dict(zip(header, values)))
    if not rows:
        raise ValueError(f"no numeric RunPARTs rows: {path}")

    def number(row: dict[str, str], key: str) -> float:
        return float(row[key].replace(",", ""))

    rows.sort(key=lambda row: int(number(row, "Part")))
    parts = [int(number(row, "Part")) for row in rows]
    if parts != list(range(len(rows))):
        raise ValueError(f"RunPARTs rows are not contiguous: {path}")
    positive_dt = [number(row, "DtMin [s]") for row in rows if number(row, "DtMin [s]") > 0.0]
    if not positive_dt:
        raise ValueError(f"no positive native DtMin in {path}")
    time_values = [number(row, "TimeStep [s]") for row in rows]
    return {
        "path": str(path),
        "sha256": sha256(path),
        "rows": len(rows),
        "first_time_s": time_values[0],
        "last_time_s": time_values[-1],
        "positive_dt_rows": len(positive_dt),
        "global_min_positive_dt_s": min(positive_dt),
        "global_max_positive_dt_s": max(positive_dt),
        "initial_fluid_particles": int(number(rows[0], "NpfSim")),
        "final_fluid_particles": int(number(rows[-1], "NpfSim")),
        "np_out_sum": int(sum(number(row, "NpOut") for row in rows)),
    }


def parse_run_csv(path: Path) -> dict[str, Any]:
    """Read the one-row Run.csv total-step field, not per-save Steps."""
    path = require(path, "terminal Run.csv")
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        raise ValueError(f"no Run.csv data row: {path}")
    values = [item.strip() for item in lines[0].split(";")]
    if len(values) < 17:
        raise ValueError(f"Run.csv row is unexpectedly short: {path}")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "total_steps": int(values[10].replace(",", "")),
        "physical_time_s": float(values[12]),
        "part_files": int(values[13].replace(",", "")),
        "parts_out": int(values[14].replace(",", "")),
    }


def source_case(background: str) -> dict[str, Any]:
    case = f"F2_RV4EQ_DP005_{background}_V1_BASELINE_SAVE001"
    request = load(V3_REQUEST_ROOT / f"{case}_conversion_request_v3_terminal_bound.json", f"{background} baseline request")
    baseline_xml = require(Path(str(request["generated_xml"]["path"])), f"{background} baseline XML")
    baseline_bi4 = require(Path(str(request["source_bindings"]["copied_bi4"]["path"])), f"{background} source BI4")
    baseline_motion = require(Path(str(request["source_bindings"]["copied_motion"]["path"])), f"{background} motion")
    runparts = require(Path(next(path for path in request["terminal_source_bindings"] if path.endswith("RunPARTs.csv"))), f"{background} RunPARTs")
    receipt = require(Path(next(path for path in request["terminal_source_bindings"] if path.endswith("execution-receipt.json"))), f"{background} solver receipt")
    run_csv = require(Path(next(path for path in request["terminal_source_bindings"] if path.endswith("Run.csv"))), f"{background} Run.csv")
    gencase = require(Path(str(request["gencase_receipt"])), f"{background} GenCase receipt")
    receipt_data = load(receipt, f"{background} solver receipt")
    runparts_summary = parse_runparts(runparts)
    run_csv_summary = parse_run_csv(run_csv)
    runparts_summary["baseline_steps"] = run_csv_summary["total_steps"]
    baseline_parameters = xml_parameters(baseline_xml)
    if baseline_parameters.get("TimeOut") != "0.01" or baseline_parameters.get("DtFixed") != "0":
        raise ValueError(f"{background} baseline XML is not the expected adaptive .01 recipe")
    total_particles = int(request["actual_source"]["expected_total_particles"])
    return {
        "background": background,
        "case_id": case,
        "physical_case_id": f"F2H10V2_{background}_V1",
        "mechanism_id": "center_catch" if background == "CENTER" else "offset_spill",
        "request": request,
        "baseline_xml": baseline_xml,
        "baseline_bi4": baseline_bi4,
        "baseline_motion": baseline_motion,
        "gencase_receipt": gencase,
        "solver_receipt": receipt,
        "run_csv": run_csv,
        "run_csv_summary": run_csv_summary,
        "runparts": runparts,
        "receipt_data": receipt_data,
        "runparts_summary": runparts_summary,
        "baseline_parameters": baseline_parameters,
        "baseline_projection": xml_physical_projection(baseline_xml),
        "total_particles": total_particles,
        "physical_condition_hash": str(request["physical_condition_hash"]),
        "baseline_elapsed_seconds": float(receipt_data["elapsed_seconds"]),
    }


def make_variant(case: dict[str, Any], variant: str, stage_root: Path) -> dict[str, Any]:
    config = VARIANTS[variant]
    background = case["background"]
    source_case = case["case_id"].replace("_BASELINE_SAVE001", "")
    variant_case_id = f"{source_case}_{variant.upper()}"
    variant_stage = stage_root / variant_case_id
    if variant_stage.exists():
        raise FileExistsError(f"variant staging already exists: {variant_stage}")
    variant_stage.mkdir(parents=True)
    prefix = variant_stage / variant_case_id
    xml_path = prefix.with_suffix(".xml")
    xml_text = case["baseline_xml"].read_text(encoding="utf-8")
    xml_text = replace_parameter(xml_text, "TimeOut", format(config["time_out_s"], ".17g"))
    baseline_min = float(case["runparts_summary"]["global_min_positive_dt_s"])
    half_dt = baseline_min / 2.0 if variant == "reduced_dt_save010" else 0.0
    xml_text = replace_parameter(xml_text, "DtFixed", format(half_dt, ".17g"))
    xml_path.write_text(xml_text, encoding="utf-8")
    bi4_path = prefix.with_suffix(".bi4")
    motion_path = variant_stage / case["baseline_motion"].name
    shutil.copyfile(case["baseline_bi4"], bi4_path)
    shutil.copyfile(case["baseline_motion"], motion_path)
    if sha256(bi4_path) != sha256(case["baseline_bi4"]):
        raise ValueError(f"{variant_case_id}: copied BI4 hash differs")
    if sha256(motion_path) != sha256(case["baseline_motion"]):
        raise ValueError(f"{variant_case_id}: copied motion hash differs")
    new_projection = xml_physical_projection(xml_path)
    if new_projection["physical_projection_sha256"] != case["baseline_projection"]["physical_projection_sha256"]:
        raise ValueError(f"{variant_case_id}: physical XML projection changed")
    params = new_projection["parameters"]
    if params.get("TimeMax") != "4" or params.get("DtIni") != "0" or params.get("DtMin") != "0":
        raise ValueError(f"{variant_case_id}: unexpected time or floor parameter change: {params}")
    numerical_fields = {
        "recipe_id": RECIPE_ID,
        "variant": variant,
        "physical_case_id": case["physical_case_id"],
        "background": background,
        "dp_m": float(params["Dp"]) if "Dp" in params else 0.005,
        "time_max_s": TIME_MAX_S,
        "time_out_s": config["time_out_s"],
        "DtFixed_s": half_dt,
        "DtIni_s": float(params["DtIni"]),
        "DtMin_s": float(params["DtMin"]),
        "CoefDtMin": float(params["CoefDtMin"]),
        "expected_frames": config["expected_frames"],
        "baseline_global_min_positive_dt_s": baseline_min,
        "half_native_dt_definition": "0.5 * actual completed baseline RunPARTs global minimum positive DtMin" if variant == "reduced_dt_save010" else None,
        "physical_condition_hash": case["physical_condition_hash"],
    }
    numerical_hash = canonical_hash(numerical_fields)
    raw_bytes = case["total_particles"] * config["expected_frames"] * BYTES_PER_PARTICLE_FRAME
    storage_bytes = math.ceil(raw_bytes * STORAGE_MARGIN)
    baseline_frames = BASELINE_FRAMES
    baseline_steps = int(case["runparts_summary"]["baseline_steps"])
    expected_steps = math.ceil(TIME_MAX_S / half_dt) if variant == "reduced_dt_save010" else baseline_steps
    step_ratio = expected_steps / baseline_steps if baseline_steps else None
    if variant == "dense_save001":
        predicted_wall = case["baseline_elapsed_seconds"] * config["expected_frames"] / baseline_frames
    else:
        predicted_wall = case["baseline_elapsed_seconds"] * float(step_ratio)
    return {
        "case_id": case["case_id"],
        "variant_case_id": variant_case_id,
        "background": background,
        "mechanism_id": case["mechanism_id"],
        "physical_case_id": case["physical_case_id"],
        "physical_condition_hash": case["physical_condition_hash"],
        "variant": variant,
        "staging": {
            "directory": str(variant_stage),
            "prefix": str(prefix),
            "generated_xml": binding(xml_path),
            "copied_bi4": binding(bi4_path),
            "copied_motion": binding(motion_path),
        },
        "source_baseline": {
            "generated_xml": binding(case["baseline_xml"]),
            "bi4": binding(case["baseline_bi4"]),
            "motion": binding(case["baseline_motion"]),
            "gencase_receipt": binding(case["gencase_receipt"]),
            "solver_receipt": binding(case["solver_receipt"]),
            "run_csv": binding(case["run_csv"]),
            "runparts": binding(case["runparts"]),
        },
        "physical_equivalence": {
            "baseline_physical_condition_hash": case["physical_condition_hash"],
            "physical_xml_projection_sha256": new_projection["physical_projection_sha256"],
            "allowed_xml_changes": ["TimeOut", "DtFixed"],
            "geometry_control_source_bytes_unchanged": True,
            "motion_hash_equal": sha256(motion_path) == sha256(case["baseline_motion"]),
            "bi4_hash_equal": sha256(bi4_path) == sha256(case["baseline_bi4"]),
        },
        "numerical_fields": numerical_fields,
        "numerical_recipe_hash": numerical_hash,
        "resource_estimate": {
            "actual_total_particles": case["total_particles"],
            "expected_frames": config["expected_frames"],
            "bytes_per_particle_frame": BYTES_PER_PARTICLE_FRAME,
            "raw_trajectory_bytes_lower_bound": raw_bytes,
            "storage_margin_fraction": STORAGE_MARGIN - 1.0,
            "estimated_storage_bytes": storage_bytes,
            "estimated_storage_gib": storage_bytes / 1024**3,
            "baseline_elapsed_seconds": case["baseline_elapsed_seconds"],
            "baseline_steps": baseline_steps,
            "estimated_steps": expected_steps,
            "estimated_step_ratio": step_ratio,
            "predicted_wall_seconds": predicted_wall,
            "requested_wall_seconds": config["max_wall_seconds"],
        },
        "timing_and_study_role": {
            "same_event_window_s": [0.0, TIME_MAX_S],
            "timing_qualification_candidate": config["timing_candidate"],
            "worst_case_save_quantization_s": config["time_out_s"] / 2.0,
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
            "save_budget_candidate_satisfied_by_cadence": config["time_out_s"] / 2.0 <= SAVE_HALF_WIDTH_BUDGET_S,
            "integration_study_candidate": config["integration_candidate"],
            "macro_save_is_not_event_qualification": config["time_out_s"] > 0.001,
        },
    }


def request_for(case: dict[str, Any], variant: dict[str, Any], common_inputs: list[Path], output_root: Path) -> dict[str, Any]:
    variant_case_id = variant["variant_case_id"]
    staging = variant["staging"]
    xml_path = Path(staging["generated_xml"]["path"])
    bi4_path = Path(staging["copied_bi4"]["path"])
    motion_path = Path(staging["copied_motion"]["path"])
    baseline_inputs = [
        Path(str(variant["source_baseline"][key]["path"]))
        for key in ("generated_xml", "bi4", "motion", "gencase_receipt", "solver_receipt", "run_csv", "runparts")
    ]
    all_inputs = list(dict.fromkeys([*common_inputs, *baseline_inputs, xml_path, bi4_path, motion_path]))
    input_hashes = {str(path.resolve()): sha256(require(path, "solver request input")) for path in all_inputs}
    cfg = VARIANTS[variant["variant"]]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "kind": "qualification",
        "family_id": "F2",
        "case_id": variant_case_id,
        "attempt_id": f"qualification-{variant_case_id.lower()}-native-fullstate-v1",
        "command": [str(SOLVER), staging["prefix"], "{attempt_root}/solver_output"],
        "cwd": staging["directory"],
        "worktree_root": str(FAMILY_ROOT.parents[4]),
        "max_wall_seconds": cfg["max_wall_seconds"],
        "cpu_threads": 4,
        "estimated_peak_gpu_mib": 16384,
        "estimated_storage_bytes": variant["resource_estimate"]["estimated_storage_bytes"],
        "event_window_s": TIME_MAX_S,
        "physical_case_id": case["physical_case_id"],
        "physical_condition_hash": case["physical_condition_hash"],
        "physical_geometry_control_hash": case["physical_condition_hash"],
        "numerical_recipe_hash": variant["numerical_recipe_hash"],
        "recipe_id": RECIPE_ID,
        "scope_id": SCOPE_ID,
        "mechanism_id": case["mechanism_id"],
        "resolution": "dp005",
        "new_independent_physical_case_count": 0,
        "registry_role": "numerical_temporal_reference_outside_original_48_registry",
        "gencase_prefix": staging["prefix"],
        "gencase_receipt": variant["source_baseline"]["gencase_receipt"]["path"],
        "gencase_receipt_sha256": variant["source_baseline"]["gencase_receipt"]["sha256"],
        "gencase_artifacts": {
            "source_gencase_receipt": variant["source_baseline"]["gencase_receipt"],
            "source_gencase_prefix": str(case["baseline_xml"].with_suffix("")),
            "copied_source_bi4": variant["source_baseline"]["bi4"],
            "copied_source_motion": variant["source_baseline"]["motion"],
            "temporal_xml": variant["staging"]["generated_xml"],
            "temporal_bi4": variant["staging"]["copied_bi4"],
            "temporal_motion": variant["staging"]["copied_motion"],
        },
        "source_binding": {
            "physical_condition_hash": case["physical_condition_hash"],
            "baseline_solver_receipt": variant["source_baseline"]["solver_receipt"],
            "baseline_runparts": variant["source_baseline"]["runparts"],
            "baseline_global_min_positive_dt_s": variant["numerical_fields"]["baseline_global_min_positive_dt_s"],
            "same_bi4_bytes": variant["physical_equivalence"]["bi4_hash_equal"],
            "same_motion_bytes": variant["physical_equivalence"]["motion_hash_equal"],
            "xml_allowed_changes": variant["physical_equivalence"]["allowed_xml_changes"],
            "physical_xml_projection_sha256": variant["physical_equivalence"]["physical_xml_projection_sha256"],
        },
        "numerical_recipe_fields": variant["numerical_fields"],
        "resource_estimate": variant["resource_estimate"],
        "timing_and_study_role": variant["timing_and_study_role"],
        "thresholds_apply_before_results": True,
        "quality_thresholds": {
            "continuous_initial_mass_kg": CONTINUOUS_MASS_KG,
            "native_mass_relative_budget_fraction": 1e-12,
            "event_time_absolute_budget_s": EVENT_TIME_BUDGET_S,
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
            "macro_relative_error_threshold": MACRO_RELATIVE_BUDGET,
            "unknown_mass_remains_in_initial_denominator": True,
            "timing_claim_requires_actual_finer_full_window_and_pose": True,
        },
        "input_files": [str(path.resolve()) for path in all_inputs],
        "input_sha256": input_hashes,
        "gpu_launch": {"family_owner_launch": False, "requested_by": "primary_process"},
        "qualification_launch_authority": "shared_ds_data_02_runner_only_primary_process",
        "solver_launch_forbidden_in_this_module": True,
        "status": "ready_for_root_gpu_review_only",
        "qualification_claim": "none; numerical temporal request only",
        "production_claim": "none",
        "request_note": "Fresh co-located XML/BI4/motion staging. Same RV4 physical mother/control/source population; only registered TimeOut or explicit DtFixed changes. Root must review and launch. This request grants no Q-I/Q-N or production status.",
    }
    return request


def build(output_root: Path = OUTPUT_ROOT, request_root: Path = REQUEST_ROOT) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    request_root = request_root.expanduser().resolve()
    if output_root.exists() or request_root.exists():
        raise FileExistsError(f"fresh temporal output required: {output_root} / {request_root}")
    for path in (SOLVER, RUNTIME_V2, GOAL, QUALITY, EVENTS, SAVE_PLAN, CASE_REGISTRY, REFERENCE_MATRIX, FAMILY_ROOT / "f2_rv4eq_dp005_temporal_requests_v1.py"):
        require(path, "common source")
    output_root.mkdir(parents=True)
    request_root.mkdir(parents=True)
    definitions_root = request_root / "definitions"
    requests_root = request_root / "requests"
    definitions_root.mkdir()
    requests_root.mkdir()
    common_inputs = [SOLVER, RUNTIME_V2, GOAL, QUALITY, EVENTS, SAVE_PLAN, CASE_REGISTRY, REFERENCE_MATRIX, FAMILY_ROOT / "f2_rv4eq_dp005_temporal_requests_v1.py"]
    records: list[dict[str, Any]] = []
    for background in ("CENTER", "OFFSET"):
        case = source_case(background)
        stage_root = output_root / background.lower()
        stage_root.mkdir()
        for variant_name in VARIANTS:
            variant = make_variant(case, variant_name, stage_root)
            # Keep a committed, inspectable XML definition copy beside the
            # request while the actual solver command uses the co-located
            # data-root staging bytes.
            definition_copy = definitions_root / variant["variant_case_id"] / f"{variant['variant_case_id']}.xml"
            definition_copy.parent.mkdir(parents=True)
            shutil.copyfile(variant["staging"]["generated_xml"]["path"], definition_copy)
            variant["definition_copy"] = binding(definition_copy)
            request = request_for(case, variant, [*common_inputs, definition_copy], output_root)
            request_path = requests_root / f"{variant['variant_case_id']}_request.json"
            dump(request_path, request)
            variant["request"] = binding(request_path)
            records.append(variant)
    manifest = {
        "schema": "ds-data-02.f2.rv4eq-dp005-temporal-study.v1",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": "F2",
        "recipe_id": RECIPE_ID,
        "scope_id": SCOPE_ID,
        "source_policy": "same physical mother/control/source BI4 as completed RV4EQ DP005; only numerical XML view fields vary",
        "physical_case_count": 2,
        "new_independent_physical_case_count": 0,
        "variants": {
            name: {
                **config,
                "launch": "root review only",
                "qualification_claim": "none",
            }
            for name, config in VARIANTS.items()
        },
        "frozen_thresholds": {
            "continuous_initial_mass_kg": CONTINUOUS_MASS_KG,
            "native_mass_relative_budget_fraction": 1e-12,
            "event_time_absolute_budget_s": EVENT_TIME_BUDGET_S,
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
            "macro_relative_error_threshold": MACRO_RELATIVE_BUDGET,
            "thresholds_apply_before_results": True,
            "unknown_mass_separate_from_physical_spill": True,
        },
        "records": records,
        "solver_launch": False,
        "gpu_launch": "primary process/root only",
        "conversion_launch": False,
        "qualification_claim": "none",
        "production_claim": "none",
    }
    manifest_path = request_root / "temporal_study_manifest_v1.json"
    dump(manifest_path, manifest)
    manifest["manifest"] = binding(manifest_path)
    dump(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--request-root", type=Path, default=REQUEST_ROOT)
    args = parser.parse_args()
    manifest = build(args.output_root, args.request_root)
    print(json.dumps({"manifest": manifest["manifest"], "requests": len(manifest["records"]), "solver_launch": manifest["solver_launch"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
