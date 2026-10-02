#!/usr/bin/env python3
"""Prepare additive floor-safe fixed-dt views of the completed F2 RV4EQ DP005 runs.

The earlier ``reduced_dt_save010`` requests deliberately set only ``DtFixed``.
Their ``DtFixed`` values are below the default ``DtMin`` reported by the
completed baseline runs while ``CoefDtMin`` remains 0.05, so those requests
are retained as immutable HOLD records.  This version makes the numerical
override explicit by setting ``DtFixed``, ``DtIni`` and ``DtMin`` to the same
measured half-minimum.  The physical XML projection, BI4 population, motion
file, 4 s window and 0.01 s save cadence remain unchanged.

This module only creates fresh input copies and root-review solver requests.
It never launches GenCase, DualSPHysics, conversion, PartVTKOut or labels.
The request includes the immutable strict-dispatch guard and every registered
input digest so the primary process can validate the source bytes in one pass.
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
import sys
from typing import Any


FAMILY_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(FAMILY_ROOT))
import f2_rv4eq_dp005_temporal_requests_v1 as source  # noqa: E402


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA_ROOT = DATA_ROOT / "families/F2"
V3_REQUEST_ROOT = FAMILY_ROOT / "rv4_equivalent_dp005/postprocess_handoff_v3_terminal_bound/conversion_requests"
OUTPUT_ROOT = F2_DATA_ROOT / "F2_RV4EQ_DP005_FLOORSAFE_INPUTS_20261002"
REQUEST_ROOT = FAMILY_ROOT / "rv4_equivalent_dp005/temporal_studies_floor_safe_v1"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
RUNTIME_V2 = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
STRICT_DISPATCH = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py")
GOAL = FAMILY_ROOT.parents[1] / "GOAL_ZH.md"
QUALITY = FAMILY_ROOT / "quality_contract.json"
EVENTS = FAMILY_ROOT / "event_definitions.json"
SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"
CASE_REGISTRY = FAMILY_ROOT / "case_registry.jsonl"
REFERENCE_MATRIX = FAMILY_ROOT / "definitions/reference_matrix.json"
SOURCE_SCRIPT = FAMILY_ROOT / "f2_rv4eq_dp005_temporal_requests_v1.py"
RECIPE_ID = "F2_RV4EQ_DP005_FLOORSAFE_TEMPORAL_V1"
SCOPE_ID = "F2_SCOPE_RV4_EQUIVALENT_DP005_PRECHECK_20261002"
CONTINUOUS_MASS_KG = 24.576
EVENT_TIME_BUDGET_S = 0.0036681953999691376
SAVE_HALF_WIDTH_BUDGET_S = 0.0007336390799938275
MACRO_RELATIVE_BUDGET = 0.05
STORAGE_MARGIN = 1.40
BYTES_PER_PARTICLE_FRAME = 64
EXPECTED_FRAMES = 401
TIME_MAX_S = 4.0
TIME_OUT_S = 0.01
REQUESTED_WALL_SECONDS = 6000
EXPECTED_RUN_OUT_DT_MIN_S = 7.395262380156267e-06
EXPECTED_RUN_OUT_DT_INI_S = 0.0001479052453991654
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
        raise ValueError(f"expected one execution parameter {key}, found {count}")
    return rewritten


def xml_parameters(path: Path) -> dict[str, str]:
    import xml.etree.ElementTree as ET

    root = ET.parse(require(path, "XML")).getroot()
    return {
        str(node.attrib["key"]): str(node.attrib.get("value", ""))
        for node in root.findall(".//execution/parameters/parameter")
        if node.attrib.get("key") is not None
    }


def physical_projection(path: Path) -> dict[str, Any]:
    """Hash XML while masking only numerical time-step/save fields."""
    import xml.etree.ElementTree as ET

    root = ET.parse(require(path, "XML projection")).getroot()

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


def parse_run_out(path: Path) -> dict[str, Any]:
    path = require(path, "completed baseline Run.out")
    text = path.read_text(encoding="utf-8", errors="replace")

    def one(key: str) -> float:
        matches = re.findall(rf"(?m)^\s*{re.escape(key)}\s*=\s*([-+0-9.eE]+)\s*$", text)
        if len(matches) != 1:
            raise ValueError(f"expected one {key}= line in {path}, found {len(matches)}")
        return float(matches[0])

    values = {"DtIni_s": one("DtIni"), "DtMin_s": one("DtMin")}
    if not math.isclose(values["DtMin_s"], EXPECTED_RUN_OUT_DT_MIN_S, rel_tol=0.0, abs_tol=1e-18):
        raise ValueError(f"unexpected baseline Run.out DtMin in {path}: {values['DtMin_s']}")
    if not math.isclose(values["DtIni_s"], EXPECTED_RUN_OUT_DT_INI_S, rel_tol=0.0, abs_tol=1e-18):
        raise ValueError(f"unexpected baseline Run.out DtIni in {path}: {values['DtIni_s']}")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, **values}


def source_case(background: str) -> dict[str, Any]:
    case = source.source_case(background)
    request_path = V3_REQUEST_ROOT / f"{case['case_id']}_conversion_request_v3_terminal_bound.json"
    request = case["request"]
    actual_source = request["actual_source"]
    run_out = require(Path(str(actual_source["run_out"]["path"])), f"{background} Run.out")
    run_out_summary = parse_run_out(run_out)
    baseline_min = float(case["runparts_summary"]["global_min_positive_dt_s"])
    target = baseline_min / 2.0
    if not target < run_out_summary["DtMin_s"]:
        raise ValueError(f"{background}: half native minimum is not below Run.out default floor")
    terminal_report = require(Path(str(request["terminal_semantics_report"]["path"])), f"{background} terminal semantics")
    return {
        **case,
        "v3_request_path": require(request_path, f"{background} v3 conversion request"),
        "run_out": run_out,
        "run_out_summary": run_out_summary,
        "terminal_report": terminal_report,
        "baseline_min_dt_s": baseline_min,
        "target_dt_s": target,
    }


def make_variant(case: dict[str, Any], stage_root: Path) -> dict[str, Any]:
    background = case["background"]
    source_case_id = case["case_id"].replace("_BASELINE_SAVE001", "")
    variant_case_id = f"{source_case_id}_REDUCED_DT_SAVE010_FLOORSAFE001"
    variant_stage = stage_root / variant_case_id
    if variant_stage.exists():
        raise FileExistsError(f"fresh floor-safe staging already exists: {variant_stage}")
    variant_stage.mkdir(parents=True)
    prefix = variant_stage / variant_case_id
    xml_path = prefix.with_suffix(".xml")
    xml_text = case["baseline_xml"].read_text(encoding="utf-8")
    target = case["target_dt_s"]
    for key in ("DtFixed", "DtIni", "DtMin"):
        xml_text = replace_parameter(xml_text, key, format(target, ".17g"))
    # TimeOut is already 0.01 in the completed RV4 baseline and is kept as-is.
    xml_path.write_text(xml_text, encoding="utf-8")
    bi4_path = prefix.with_suffix(".bi4")
    motion_path = variant_stage / case["baseline_motion"].name
    shutil.copyfile(case["baseline_bi4"], bi4_path)
    shutil.copyfile(case["baseline_motion"], motion_path)
    if sha256(bi4_path) != sha256(case["baseline_bi4"]):
        raise ValueError(f"{variant_case_id}: copied BI4 changed")
    if sha256(motion_path) != sha256(case["baseline_motion"]):
        raise ValueError(f"{variant_case_id}: copied motion changed")
    baseline_projection = physical_projection(case["baseline_xml"])
    new_projection = physical_projection(xml_path)
    if new_projection["physical_projection_sha256"] != baseline_projection["physical_projection_sha256"]:
        raise ValueError(f"{variant_case_id}: physical XML projection changed")
    params = new_projection["parameters"]
    for key in ("TimeMax", "TimeOut", "CoefDtMin"):
        if params.get(key) != case["baseline_parameters"].get(key):
            raise ValueError(f"{variant_case_id}: non-numerical parameter changed: {key}")
    for key in ("DtFixed", "DtIni", "DtMin"):
        if not math.isclose(float(params[key]), target, rel_tol=0.0, abs_tol=1e-18):
            raise ValueError(f"{variant_case_id}: explicit {key} does not equal target")

    numerical_fields = {
        "recipe_id": RECIPE_ID,
        "variant": "reduced_dt_save010_floorsafe001",
        "physical_case_id": case["physical_case_id"],
        "background": background,
        "dp_m": 0.005,
        "time_max_s": TIME_MAX_S,
        "time_out_s": TIME_OUT_S,
        "DtFixed_s": target,
        "DtIni_s": target,
        "DtMin_s": target,
        "CoefDtMin": float(params["CoefDtMin"]),
        "expected_frames": EXPECTED_FRAMES,
        "baseline_global_min_positive_dt_s": case["baseline_min_dt_s"],
        "baseline_Run_out_default_DtMin_s": case["run_out_summary"]["DtMin_s"],
        "baseline_Run_out_default_DtIni_s": case["run_out_summary"]["DtIni_s"],
        "half_native_dt_definition": "0.5 * completed baseline RunPARTs global minimum positive DtMin",
        "physical_condition_hash": case["physical_condition_hash"],
    }
    numerical_hash = canonical_hash(numerical_fields)
    raw_bytes = case["total_particles"] * EXPECTED_FRAMES * BYTES_PER_PARTICLE_FRAME
    storage_bytes = math.ceil(raw_bytes * source.STORAGE_MARGIN)
    baseline_steps = int(case["runparts_summary"]["baseline_steps"])
    expected_steps = math.ceil(TIME_MAX_S / target)
    step_ratio = expected_steps / baseline_steps
    predicted_wall = case["baseline_elapsed_seconds"] * step_ratio
    return {
        "case_id": case["case_id"],
        "variant_case_id": variant_case_id,
        "background": background,
        "mechanism_id": case["mechanism_id"],
        "physical_case_id": case["physical_case_id"],
        "physical_condition_hash": case["physical_condition_hash"],
        "variant": numerical_fields["variant"],
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
            "run_out": binding(case["run_out"]),
            "terminal_report": binding(case["terminal_report"]),
            "v3_request": binding(case["v3_request_path"]),
        },
        "physical_equivalence": {
            "baseline_physical_condition_hash": case["physical_condition_hash"],
            "physical_xml_projection_sha256": new_projection["physical_projection_sha256"],
            "allowed_xml_changes": ["DtFixed", "DtIni", "DtMin"],
            "time_out_unchanged_s": TIME_OUT_S,
            "geometry_control_source_bytes_unchanged": True,
            "motion_hash_equal": sha256(motion_path) == sha256(case["baseline_motion"]),
            "bi4_hash_equal": sha256(bi4_path) == sha256(case["baseline_bi4"]),
        },
        "numerical_fields": numerical_fields,
        "numerical_recipe_hash": numerical_hash,
        "floor_safe_override": {
            "default_run_out_DtMin_s": case["run_out_summary"]["DtMin_s"],
            "default_run_out_DtIni_s": case["run_out_summary"]["DtIni_s"],
            "explicit_DtFixed_s": target,
            "explicit_DtIni_s": target,
            "explicit_DtMin_s": target,
            "target_below_default_run_out_DtMin": True,
            "coef_dtmin_preserved": float(params["CoefDtMin"]) == 0.05,
            "solver_override_semantics": "Root must verify actual Run.out and realized timestep; request does not claim that an explicit DtMin bypass will succeed.",
        },
        "resource_estimate": {
            "actual_total_particles": case["total_particles"],
            "expected_frames": EXPECTED_FRAMES,
            "bytes_per_particle_frame": BYTES_PER_PARTICLE_FRAME,
            "raw_trajectory_bytes_lower_bound": raw_bytes,
            "storage_margin_fraction": source.STORAGE_MARGIN - 1.0,
            "estimated_storage_bytes": storage_bytes,
            "estimated_storage_gib": storage_bytes / 1024**3,
            "baseline_elapsed_seconds": case["baseline_elapsed_seconds"],
            "baseline_steps": baseline_steps,
            "estimated_steps": expected_steps,
            "estimated_step_ratio": step_ratio,
            "predicted_wall_seconds": predicted_wall,
            "requested_wall_seconds": REQUESTED_WALL_SECONDS,
        },
        "timing_and_study_role": {
            "same_event_window_s": [0.0, TIME_MAX_S],
            "timing_qualification_candidate": False,
            "worst_case_save_quantization_s": TIME_OUT_S / 2.0,
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
            "save_budget_candidate_satisfied_by_cadence": False,
            "integration_study_candidate": True,
            "macro_save_is_not_event_qualification": True,
        },
    }


def request_for(case: dict[str, Any], variant: dict[str, Any], common_inputs: list[Path], definition_copy: Path) -> dict[str, Any]:
    staging = variant["staging"]
    baseline_inputs = [
        Path(str(variant["source_baseline"][key]["path"]))
        for key in ("generated_xml", "bi4", "motion", "gencase_receipt", "solver_receipt", "run_csv", "runparts", "run_out", "terminal_report", "v3_request")
    ]
    temporal_inputs = [
        Path(staging["generated_xml"]["path"]),
        Path(staging["copied_bi4"]["path"]),
        Path(staging["copied_motion"]["path"]),
        definition_copy,
    ]
    all_inputs = list(dict.fromkeys([*common_inputs, *baseline_inputs, *temporal_inputs]))
    input_files = [str(path.expanduser().resolve()) for path in all_inputs]
    input_hashes = {path: sha256(Path(path)) for path in input_files}
    variant_case_id = variant["variant_case_id"]
    expected_storage = variant["resource_estimate"]["estimated_storage_bytes"]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "kind": "qualification",
        "family_id": "F2",
        "case_id": variant_case_id,
        "attempt_id": f"qualification-{variant_case_id.lower()}-native-fullstate-v1",
        "command": [SOLVER.as_posix(), staging["prefix"], "{attempt_root}/solver_output"],
        "cwd": staging["directory"],
        "worktree_root": str(FAMILY_ROOT.parents[4]),
        "max_wall_seconds": REQUESTED_WALL_SECONDS,
        "cpu_threads": 4,
        "estimated_peak_gpu_mib": 16384,
        "estimated_storage_bytes": expected_storage,
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
            "baseline_run_out": variant["source_baseline"]["run_out"],
            "baseline_global_min_positive_dt_s": variant["numerical_fields"]["baseline_global_min_positive_dt_s"],
            "baseline_Run_out_default_DtMin_s": variant["numerical_fields"]["baseline_Run_out_default_DtMin_s"],
            "baseline_Run_out_default_DtIni_s": variant["numerical_fields"]["baseline_Run_out_default_DtIni_s"],
            "same_bi4_bytes": variant["physical_equivalence"]["bi4_hash_equal"],
            "same_motion_bytes": variant["physical_equivalence"]["motion_hash_equal"],
            "xml_allowed_changes": variant["physical_equivalence"]["allowed_xml_changes"],
            "physical_xml_projection_sha256": variant["physical_equivalence"]["physical_xml_projection_sha256"],
        },
        "numerical_recipe_fields": variant["numerical_fields"],
        "floor_safe_override": variant["floor_safe_override"],
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
        "input_files": input_files,
        "input_sha256": input_hashes,
        "dispatch_guard": {"path": str(STRICT_DISPATCH.resolve()), "sha256": sha256(STRICT_DISPATCH)},
        "gpu_launch": {"family_owner_launch": False, "requested_by": "primary_process"},
        "qualification_launch_authority": "shared_ds_data_02_runner_only_primary_process",
        "solver_launch_forbidden_in_this_module": True,
        "status": "ready_for_root_gpu_review_only",
        "qualification_claim": "none; floor-safe numerical temporal request only",
        "production_claim": "none",
        "request_note": "Fresh co-located XML/BI4/motion staging. Same RV4 physical mother/control/source population; DtFixed, DtIni and DtMin explicitly set to half the completed baseline RunPARTs minimum while CoefDtMin remains 0.05. Root must verify realized Run.out/timestep and launch. This request grants no Q-I/Q-N or production status.",
    }
    return request


def build(output_root: Path = OUTPUT_ROOT, request_root: Path = REQUEST_ROOT) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    request_root = request_root.expanduser().resolve()
    if output_root.exists() or request_root.exists():
        raise FileExistsError(f"fresh floor-safe output required: {output_root} / {request_root}")
    for path in (SOLVER, RUNTIME_V2, STRICT_DISPATCH, GOAL, QUALITY, EVENTS, SAVE_PLAN, CASE_REGISTRY, REFERENCE_MATRIX, SOURCE_SCRIPT):
        require(path, "common source")
    output_root.mkdir(parents=True)
    (request_root / "definitions").mkdir(parents=True)
    requests_root = request_root / "requests"
    requests_root.mkdir()
    common_inputs = [SOLVER, RUNTIME_V2, STRICT_DISPATCH, GOAL, QUALITY, EVENTS, SAVE_PLAN, CASE_REGISTRY, REFERENCE_MATRIX, SOURCE_SCRIPT, Path(__file__).resolve()]
    records: list[dict[str, Any]] = []
    for background in ("CENTER", "OFFSET"):
        case = source_case(background)
        stage_root = output_root / background.lower()
        stage_root.mkdir()
        variant = make_variant(case, stage_root)
        definition_copy = request_root / "definitions" / variant["variant_case_id"] / f"{variant['variant_case_id']}.xml"
        definition_copy.parent.mkdir(parents=True)
        shutil.copyfile(variant["staging"]["generated_xml"]["path"], definition_copy)
        definition_binding = binding(definition_copy)
        request = request_for(case, variant, common_inputs, definition_copy)
        request_path = requests_root / f"{variant['variant_case_id']}_request.json"
        dump(request_path, request)
        variant["definition_copy"] = definition_binding
        variant["request"] = binding(request_path)
        records.append(variant)
    manifest = {
        "schema": "ds-data-02.f2.rv4eq-dp005-floor-safe-temporal.v1",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": "F2",
        "recipe_id": RECIPE_ID,
        "scope_id": SCOPE_ID,
        "source_policy": "same physical mother/control/source BI4 and completed baseline evidence; explicit DtFixed/DtIni/DtMin numerical override only",
        "physical_case_count": 2,
        "new_independent_physical_case_count": 0,
        "old_reduced_requests": {
            "status": "immutable_hold",
            "reason": "DtFixed below completed Run.out default DtMin while old XML kept DtIni=DtMin=0",
            "paths": [
                str(FAMILY_ROOT / "rv4_equivalent_dp005/temporal_studies_v1/requests/F2_RV4EQ_DP005_CENTER_V1_REDUCED_DT_SAVE010_request.json"),
                str(FAMILY_ROOT / "rv4_equivalent_dp005/temporal_studies_v1/requests/F2_RV4EQ_DP005_OFFSET_V1_REDUCED_DT_SAVE010_request.json"),
            ],
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
    manifest_path = request_root / "floor_safe_temporal_study_manifest_v1.json"
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
