#!/usr/bin/env python3
"""DS-DATA-02 F2 definition generator, audit and runner-request builder.

F2 keeps the useful part of the historical W06 rotating-pour implementation
(a real finite cup, prescribed ``mvrotfile`` motion, finite receiver and spill
tray) and gives it an explicit DS-DATA-02 contract.  The two backgrounds are

``center_catch``
    The receiver is centred on the cup mouth.  The cup holds still, rotates
    with a cosine-ramped control and remains at the final angle long enough
    for catch, return and retention events to be observed.

``offset_spill``
    The same initial fluid and cup control are paired with a transverse
    receiver offset and a wider finite tray.  The offset is a physical change
    in the destination geometry, so miss/spill is measured as a destination
    event rather than as an omitted particle.

This module only writes definitions, contracts, pre-registrations and runner
requests.  It never starts GenCase or DualSPHysics.  CPU GenCase requests are
submitted separately through the shared DS-DATA-02 runtime; GPU qualification
requests are registered for the primary process and are intentionally not
launched here.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ds-data-02.f2.generator.v1"
FAMILY_ID = "F2"
GENERATOR_VERSION = "ds_data02_f2.v1"
G = 9.81
RHO0 = 1000.0

SCRIPT_PATH = Path(__file__).resolve()
LAB_ROOT = SCRIPT_PATH.parents[1]
CURRENT_WORKTREE = SCRIPT_PATH.parents[2]
HISTORICAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
if not HISTORICAL_ROOT.is_dir():
    HISTORICAL_ROOT = LAB_ROOT
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F2"
RAW_OUTPUT_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/case/attempt")
W06_ROOT = HISTORICAL_ROOT / "campaigns/v0.1-candidate/cases/w06"
W06_MATRIX = HISTORICAL_ROOT / "campaigns/v0.1-candidate/cases/w06/matrix.json"
W06_REPORT = HISTORICAL_ROOT / "campaigns/v0.1-candidate/w06-rotating-pour.json"
W06_CONCLUSION = HISTORICAL_ROOT / "campaigns/v0.1-candidate/W06-CONCLUSION.md"
W06_REUSE = HISTORICAL_ROOT / "campaigns/ds-data-01/D02_F2_W06_REUSE_RECEIPT.json"
W06_D05 = HISTORICAL_ROOT / "campaigns/ds-data-01/d05/B05_F2_w06_candidate_bundle"
GENCASE = HISTORICAL_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
SOLVER = HISTORICAL_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"

RESOLUTION_ORDER = ("coarse", "medium", "fine")
DP_BY_BACKGROUND = {
    "center_catch": {"coarse": 0.025, "medium": 0.020, "fine": 0.015},
    "offset_spill": {"coarse": 0.025, "medium": 0.020, "fine": 0.015},
}
EVENT_WINDOW_S = 4.0
REFERENCE_SAVE_INTERVAL_S = 0.01
EVENT_CONTROL_SAVE_INTERVAL_S = 0.001
ROTATION_HOLD_START_S = 0.50
ROTATION_ANGLE_DEG = -105.0
ROTATION_DURATION_S = 1.20
PIVOT = (0.0, 0.0, 0.65)

BACKGROUND_SPECS: dict[str, dict[str, Any]] = {
    "center_catch": {
        "mechanism_id": "center_catch",
        "name_zh": "中心接液：缓启动/停止的真实旋转杯",
        "geometry_family_id": "F2_GEOM_CUP_RECEIVER_CENTER_V1",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
        "recipe_id": "F2_DBC_ROTATING_CUP_CENTER_CATCH_V1",
        "source_case": "W06_standard_slow_center",
        "receiver_y_m": 0.0,
        "receiver_x_m": 0.45,
        "tray_y_m": -0.60,
        "tray_width_m": 1.30,
        "description": "Finite 3-D cup rotates about its Y axis over a centred catch vessel; final angle is held for return and retention.",
    },
    "offset_spill": {
        "mechanism_id": "offset_spill",
        "name_zh": "横向偏置接液/洒落：同源水量的目的地对照",
        "geometry_family_id": "F2_GEOM_CUP_RECEIVER_OFFSET_V1",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
        "recipe_id": "F2_DBC_ROTATING_CUP_OFFSET_SPILL_V1",
        "source_case": "W06_standard_offset_partial",
        "receiver_y_m": 0.22,
        "receiver_x_m": 0.45,
        "tray_y_m": -0.60,
        "tray_width_m": 1.30,
        "description": "The cup and source layers match center_catch; the receiver is displaced in Y and a finite expanded tray records spill.",
    },
}


def _q(value: float) -> str:
    return f"{float(value):.9f}".rstrip("0").rstrip(".") or "0"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(CURRENT_WORKTREE), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN_GIT_COMMIT"


def _relative(path: Path, root: Path | None = None) -> str:
    path = Path(path).resolve()
    if root is not None:
        try:
            return path.relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return str(path)


def _read_w06_history(*, strict: bool = True) -> dict[str, Any]:
    """Read immutable W06 receipts and classify the old twelve cases.

    The old HDF5 files are intentionally not required: the DS-DATA-01 reuse
    receipt is the binding historical audit, and missing HDF5 files are
    recorded as unavailable rather than silently treated as zero loss.
    """

    required = [W06_MATRIX, W06_REPORT, W06_CONCLUSION, W06_REUSE]
    missing = [str(path) for path in required if not path.is_file()]
    if missing and strict:
        raise FileNotFoundError("historical W06 records missing: " + ", ".join(missing))
    matrix = _json(W06_MATRIX) if W06_MATRIX.is_file() else []
    report = _json(W06_REPORT) if W06_REPORT.is_file() else {}
    reuse = _json(W06_REUSE) if W06_REUSE.is_file() else {}
    report_cases = report.get("cases", {}) if isinstance(report, dict) else {}
    rows: list[dict[str, Any]] = []
    for item in reuse.get("cases", []) if isinstance(reuse, dict) else []:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("case_id", ""))
        audit = item.get("hdf5_audit") if isinstance(item.get("hdf5_audit"), dict) else {}
        missing_at_final = int(audit.get("initial_missing_at_final", 0) or 0)
        status = "zero_missing_historical_candidate" if missing_at_final == 0 else "historical_missing_classified"
        hdf5_rel = item.get("hdf5")
        hdf5_path = (HISTORICAL_ROOT / hdf5_rel) if isinstance(hdf5_rel, str) else None
        source_xml = W06_ROOT / f"{case_id}_Def.xml"
        source_motion = W06_ROOT / f"{case_id}_motion.dat"
        rows.append(
            {
                "case_id": case_id,
                "source_definition": str(source_xml),
                "source_definition_sha256": sha256_file(source_xml) if source_xml.is_file() else None,
                "source_motion": str(source_motion),
                "source_motion_sha256": sha256_file(source_motion) if source_motion.is_file() else None,
                "historical_hdf5": str(hdf5_path) if hdf5_path is not None else None,
                "historical_hdf5_exists": bool(hdf5_path and hdf5_path.is_file()),
                "historical_hdf5_declared_sha256": audit.get("sha256"),
                "initial_missing_at_final": missing_at_final,
                "identity_retention": audit.get("identity_retention"),
                "historical_status": item.get("status"),
                "classification": status,
                "formal_reuse": False,
                "reuse_reason": "W06 is a historical mechanism audit; it is never promoted to this new recipe without fresh native event evidence.",
                "control": item.get("control", {}),
            }
        )
    # Preserve the matrix order if the receipt ever omits a case row.
    known = {row["case_id"] for row in rows}
    for item in matrix if isinstance(matrix, list) else []:
        if not isinstance(item, dict) or item.get("case_id") in known:
            continue
        case_id = str(item.get("case_id", ""))
        rows.append(
            {
                "case_id": case_id,
                "source_definition": str(W06_ROOT / f"{case_id}_Def.xml"),
                "source_definition_sha256": None,
                "source_motion": str(W06_ROOT / f"{case_id}_motion.dat"),
                "source_motion_sha256": None,
                "historical_hdf5": None,
                "historical_hdf5_exists": False,
                "historical_hdf5_declared_sha256": None,
                "initial_missing_at_final": None,
                "identity_retention": None,
                "historical_status": "matrix_only",
                "classification": "historical_unresolved",
                "formal_reuse": False,
                "reuse_reason": "Historical matrix row lacks the DS-DATA-01 lifecycle receipt.",
                "control": {},
            }
        )
    zero = [row for row in rows if row["classification"] == "zero_missing_historical_candidate"]
    missing_rows = [row for row in rows if row["classification"] == "historical_missing_classified"]
    if strict and (len(rows) != 12 or len(zero) != 5 or len(missing_rows) != 7):
        raise ValueError(f"W06 classification drift: total={len(rows)}, zero={len(zero)}, missing={len(missing_rows)}")
    return {
        "schema": "ds-data-02.f2.w06-history-audit.v1",
        "historical_root": str(HISTORICAL_ROOT),
        "records": rows,
        "counts": {
            "total": len(rows),
            "zero_missing": len(zero),
            "missing_classified": len(missing_rows),
            "formal_reuse": sum(bool(row["formal_reuse"]) for row in rows),
        },
        "source_files": {
            "matrix": {"path": str(W06_MATRIX), "sha256": sha256_file(W06_MATRIX) if W06_MATRIX.is_file() else None},
            "report": {"path": str(W06_REPORT), "sha256": sha256_file(W06_REPORT) if W06_REPORT.is_file() else None},
            "conclusion": {"path": str(W06_CONCLUSION), "sha256": sha256_file(W06_CONCLUSION) if W06_CONCLUSION.is_file() else None},
            "reuse_receipt": {"path": str(W06_REUSE), "sha256": sha256_file(W06_REUSE) if W06_REUSE.is_file() else None},
            "d05_bundle": {
                "path": str(W06_D05),
                "exists": W06_D05.is_dir(),
                "prepare_receipt_sha256": sha256_file(W06_D05 / "prepare-receipt.json") if (W06_D05 / "prepare-receipt.json").is_file() else None,
                "run_receipt_sha256": sha256_file(W06_D05 / "run-receipt.json") if (W06_D05 / "run-receipt.json").is_file() else None,
                "conversion_receipt_sha256": sha256_file(W06_D05 / "conversion-receipt.json") if (W06_D05 / "conversion-receipt.json").is_file() else None,
            },
        },
        "interpretation": {
            "five_zero_missing": "Five old W06 cases have zero initial IDs missing at the recorded final frame; they remain historical candidates only.",
            "seven_missing": "Seven old W06 cases have positive initial_missing_at_final and stay explicitly classified as numerical missing/lifecycle gaps; no row is renamed as spill.",
            "no_model_revival": "No W06 model, tracer, or old D05 reference reuse is used as a qualification or production result.",
        },
    }


def _solver_parameters(time_max_s: float = EVENT_WINDOW_S, time_out_s: float = REFERENCE_SAVE_INTERVAL_S) -> dict[str, Any]:
    # This is the W06 successful DBC control recipe, with the event window and
    # save cadence made explicit.  The generator never claims it is qualified.
    return {
        "SavePosDouble": 2,
        "Boundary": 1,
        "SlipMode": 1,
        "StepAlgorithm": 2,
        "Kernel": 2,
        "ViscoTreatment": 1,
        "Visco": 0.03,
        "ViscoBoundFactor": 1,
        "DensityDT": 3,
        "DensityDTvalue": 0.1,
        "Shifting": 0,
        "RigidAlgorithm": 1,
        "FtPause": 0,
        "CoefDtMin": 0.05,
        "DtIni": 0,
        "DtMin": 0,
        "DtFixed": 0,
        "DtAllParticles": 0,
        "TimeMax": _q(time_max_s),
        "TimeOut": _q(time_out_s),
        "PartsOutMax": 1,
        "RhopOutMin": 700,
        "RhopOutMax": 1300,
        "MinFluidStop": 0,
    }


def motion_angle(time_s: float, duration_s: float = ROTATION_DURATION_S, angle_deg: float = ROTATION_ANGLE_DEG) -> float:
    if time_s <= ROTATION_HOLD_START_S:
        return 0.0
    if time_s >= ROTATION_HOLD_START_S + duration_s:
        return angle_deg
    phase = (time_s - ROTATION_HOLD_START_S) / duration_s
    return angle_deg * 0.5 * (1.0 - math.cos(math.pi * phase))


def write_motion(path: Path, *, duration_s: float = ROTATION_DURATION_S, event_window_s: float = EVENT_WINDOW_S, angle_deg: float = ROTATION_ANGLE_DEG) -> None:
    steps = int(round(event_window_s / 0.005))
    lines = ["#Time;Degrees"]
    for index in range(steps + 1):
        time_s = index * 0.005
        lines.append(f"{time_s:.6f};{motion_angle(time_s, duration_s, angle_deg):.9f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parameter_xml(parameters: Mapping[str, Any]) -> str:
    return "\n".join(f'      <parameter key="{key}" value="{value}" />' for key, value in parameters.items())


def _definition_xml(case: Mapping[str, Any]) -> str:
    geometry = case["geometry"]
    dp = float(case["dp_m"])
    receiver_x = float(geometry["receiver_x_m"])
    receiver_y = float(geometry["receiver_y_m"])
    cup_width = float(geometry["cup_width_m"])
    fluid_height = float(geometry["fluid_height_m"])
    layer_height = fluid_height / 3.0
    tray_y = float(geometry["tray_y_m"])
    tray_width = float(geometry["tray_width_m"])
    event_window = float(case["event_window"]["complete_event_window_s"])
    motion_file = case["motion_filename"]
    p = _parameter_xml(case["solver_parameters"])
    return f'''<?xml version="1.0" encoding="UTF-8" ?>
<!-- DS-DATA-02 F2 generated definition; GenCase/solver has not run. -->
<!-- mechanism={case["background"]}; physical_case_id={case["physical_case_id"]}; resolution={case["resolution"]} -->
<!-- cup is a finite moving 3-D body; receiver and spill tray are fixed physical geometry. -->
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81" />
      <rhop0 value="1000" />
      <rhopgradient value="2" />
      <hswl value="0" auto="true" />
      <gamma value="7" />
      <speedsystem value="0" auto="true" />
      <coefsound value="25" />
      <speedsound value="0" auto="true" />
      <hdp value="1.3" />
      <cflnumber value="0.2" />
    </constantsdef>
    <mkconfig boundcount="220" fluidcount="16" />
    <geometry>
      <definition dp="{_q(dp)}">
        <pointmin x="-0.80" y="-0.80" z="-0.45" />
        <pointmax x="2.30" y="1.05" z="1.80" />
      </definition>
      <commands>
        <mainlist>
          <setshapemode>dp | bound</setshapemode>
          <setdrawmode mode="full" />
          <setmkbound mk="0" />
          <drawbox>
            <boxfill>bottom | left | right | front | back</boxfill>
            <point x="0" y="-0.15" z="0.65" />
            <size x="{_q(cup_width)}" y="0.30" z="0.45" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkbound mk="1" />
          <drawbox>
            <boxfill>bottom | left | right | front | back</boxfill>
            <point x="{_q(receiver_x)}" y="{_q(receiver_y - 0.30)}" z="0" />
            <size x="1.10" y="0.60" z="0.45" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkbound mk="2" />
          <drawbox>
            <boxfill>bottom</boxfill>
            <point x="-0.60" y="{_q(tray_y)}" z="-0.20" />
            <size x="2.60" y="{_q(tray_width)}" z="0.10" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkfluid mk="0" />
          <drawbox><boxfill>solid</boxfill>
            <point x="0.05" y="-0.11" z="0.70" />
            <size x="{_q(cup_width - 0.10)}" y="0.22" z="{_q(layer_height)}" />
          </drawbox>
          <setmkfluid mk="1" />
          <drawbox><boxfill>solid</boxfill>
            <point x="0.05" y="-0.11" z="{_q(0.70 + layer_height)}" />
            <size x="{_q(cup_width - 0.10)}" y="0.22" z="{_q(layer_height)}" />
          </drawbox>
          <setmkfluid mk="2" />
          <drawbox><boxfill>solid</boxfill>
            <point x="0.05" y="-0.11" z="{_q(0.70 + 2.0 * layer_height)}" />
            <size x="{_q(cup_width - 0.10)}" y="0.22" z="{_q(layer_height)}" />
          </drawbox>
        </mainlist>
      </commands>
    </geometry>
    <motion>
      <objreal ref="0">
        <begin mov="1" start="0" finish="{_q(event_window)}" />
        <mvrotfile id="1" duration="{_q(event_window)}" anglesunits="degrees">
          <file name="{motion_file}" />
          <axisp1 x="0" y="-1" z="0.65" />
          <axisp2 x="0" y="1" z="0.65" />
        </mvrotfile>
      </objreal>
    </motion>
  </casedef>
  <execution>
    <parameters>
{p}
      <simulationdomain>
        <posmin x="-0.70" y="-0.75" z="-0.40" />
        <posmax x="2.20" y="1.00" z="1.80" />
      </simulationdomain>
    </parameters>
  </execution>
</case>
'''


def _event_window(background: str, *, h_ratio: float = 1.0) -> dict[str, Any]:
    h0 = 0.33 * h_ratio
    t_char = math.sqrt(h0 / G)
    return {
        "complete_event_window_s": EVENT_WINDOW_S,
        "save_interval_s": REFERENCE_SAVE_INTERVAL_S,
        "hold_start_s": ROTATION_HOLD_START_S,
        "rotation_duration_s": ROTATION_DURATION_S,
        "rotation_end_s": ROTATION_HOLD_START_S + ROTATION_DURATION_S,
        "post_rotation_hold_s": EVENT_WINDOW_S - ROTATION_HOLD_START_S - ROTATION_DURATION_S,
        "characteristic_length_m": h0,
        "characteristic_velocity_m_s": math.sqrt(G * h0),
        "characteristic_time_s": t_char,
        "phase_targets_s": {
            "static_hold_end": ROTATION_HOLD_START_S,
            "rotation_start": ROTATION_HOLD_START_S,
            "first_cup_mouth_departure": "observed_threshold_crossing_after_rotation_start",
            "first_receiver_entry": "observed_finite_receiver_crossing",
            "spill_or_tray_entry": "observed_if_any",
            "rotation_stop": ROTATION_HOLD_START_S + ROTATION_DURATION_S,
            "post_stop_return_and_residence": EVENT_WINDOW_S,
        },
        "event_window_basis": "static hold + cosine-ramped prescribed rotation + post-stop catch/spill/return hold; native evidence must observe the markers",
    }


def _quality_contract(background: str, *, h_ratio: float = 1.0) -> dict[str, Any]:
    window = _event_window(background, h_ratio=h_ratio)
    t_char = float(window["characteristic_time_s"])
    return {
        "schema": "ds-data-02.f2.quality-contract.v1",
        "family_id": FAMILY_ID,
        "status": "thresholds_frozen_before_results",
        "background": background,
        "scope_key": f"recipe+{background}+{EVENT_WINDOW_S:.3f}s+native_full_state+resolution",
        "q_i": {
            "required": [
                "solver_dimension_equals_3_from_actual_output",
                "coordinate_components_equals_3",
                "nonzero_fluid_particles_and_positive_active_mass",
                "finite_increasing_time_axis",
                "all_active_position_velocity_density_mass_finite",
                "initial_ids_retained_or_native_lifecycle_classified",
                "finite_cup_receiver_tray_geometry_and_motion_control",
            ],
            "unknown_mass_is_separate_from_spill_or_tray_mass": True,
            "boundary_particles_are_not_fluid_mass": True,
        },
        "q_n": {
            "status_before_native_reference": "pending",
            "macro_relative_error_threshold": 0.05,
            "event_time_fraction_of_characteristic_time": 0.02,
            "event_time_absolute_budget_s": 0.02 * t_char,
            "integration_fraction_of_total_error_budget_max": 0.20,
            "save_fraction_of_total_error_budget_max": 0.20,
            "requires": [
                "same_recipe_geometry_control_and_event_window_across_reference_resolutions",
                "independent_integration_step_comparison",
                "independent_save_frequency_comparison",
                "native_observables_cover_all_registered_event_phases",
            ],
            "three_resolution_interpretation": "nearby resolutions are reference evidence, not automatic convergence",
        },
        "q_e": {
            "status": "optional",
            "blocking": False,
            "external_experiment_or_analytic_match": "not required for Q-N",
        },
        "mass_denominator": "initial_native_fluid_mass_by_source_layer_mk_0_1_2",
        "event_thresholds": {
            "cup_mouth": {
                "surface": "finite moving opening plane at local x=cup_width_m-0.05 with y/z aperture inside cup rim",
                "first_departure": "first interpolated outward crossing of the moving finite opening after static hold",
                "crossing_tolerance_m": 0.5 * 0.025,
            },
            "receiver": {
                "region": "receiver interior after one boundary layer; x/y/z bounds from generated geometry",
                "first_entry": "first interpolated world-space entry; repeated crossings are counted separately",
            },
            "spill_tray": {
                "region": "finite tray interior after one boundary layer and below receiver lip",
                "spill": "native particle reaches tray region after leaving cup and is not inside receiver",
            },
            "residence": {
                "cup_retained": "body-frame cup interior at final frame",
                "destination_time_series": "receiver/tray/cup/inflight/unknown at every native saved frame",
                "unknown": "initial fluid ID absent or outside all declared physical regions at event-window end; unknown mass remains in denominator",
            },
        },
        "qualification_status": "unqualified_until_actual_native_reference_evidence",
    }


def _observables(background: str) -> dict[str, Any]:
    return {
        "primary": [
            "cup_remaining_mass_time_series_by_source_layer",
            "receiver_captured_mass_time_series_and_net_flux",
            "spill_tray_mass_time_series_and_net_flux",
            "inflight_mass_and_unknown_mass_time_series",
            "cup_mouth_first_departure_and_receiver_first_entry_times",
            "fluid_center_of_mass_and_linear_angular_momentum_about_pivot",
            "prescribed_cup_pose_and_angular_velocity_residual",
        ],
        "secondary": [
            "return_or_reentry_count",
            "velocity_and_kinetic_energy_quantiles",
            "initial_volume_mass_and_effective_layer_depth",
        ],
        "source_labels": {
            "definition": "continuous initial fluid depth bands are materialized by native initial Mk=0,1,2 layers",
            "values": ["source_layer_0_bottom", "source_layer_1_middle", "source_layer_2_top"],
        },
        "destination_labels": ["cup_retained", "receiver_captured", "spill_tray", "inflight", "unknown"],
        "finite_surfaces": ["cup_mouth", "receiver_entry", "spill_tray_entry"],
        "background_specific": (
            "center receiver catch and post-stop retention are the main mechanism"
            if background == "center_catch"
            else "transverse receiver offset, finite tray interception and spill/re-entry are the main mechanism"
        ),
    }


def _geometry(background: str, values: Mapping[str, Any]) -> dict[str, Any]:
    spec = BACKGROUND_SPECS[background]
    h_ratio = float(values.get("fill_ratio", 1.0))
    receiver_x = float(values.get("receiver_x_m", spec["receiver_x_m"]))
    receiver_y = float(values.get("receiver_y_m", spec["receiver_y_m"]))
    tray_y = float(values.get("tray_y_m", spec["tray_y_m"]))
    tray_width = float(values.get("tray_width_m", spec["tray_width_m"]))
    cup_width = float(values.get("cup_width_m", 0.425))
    if not 0.55 <= h_ratio <= 1.25:
        raise ValueError("fill_ratio must stay in the resolvable 0.55..1.25 design range")
    if not 0.35 <= receiver_x <= 0.80:
        raise ValueError("receiver_x_m is outside the registered finite-domain range")
    if background == "center_catch" and abs(receiver_y) > 1e-12:
        raise ValueError("center_catch receiver_y_m must be zero")
    if background == "offset_spill" and not 0.10 <= receiver_y <= 0.32:
        raise ValueError("offset_spill receiver_y_m must be a resolvable transverse offset")
    if tray_y + tray_width <= receiver_y + 0.30:
        raise ValueError("spill tray does not cover the receiver's finite transverse footprint")
    if not 0.35 <= cup_width <= 0.50:
        raise ValueError("cup_width_m is outside the W06-derived range")
    fluid_height = 0.33 * h_ratio
    return {
        "domain_extent_m": [3.10, 1.85, 2.25],
        "cup_low_m": [0.0, -0.15, 0.65],
        "cup_size_m": [cup_width, 0.30, 0.45],
        "cup_width_m": cup_width,
        "receiver_low_m": [receiver_x, receiver_y - 0.30, 0.0],
        "receiver_size_m": [1.10, 0.60, 0.45],
        "receiver_x_m": receiver_x,
        "receiver_y_m": receiver_y,
        "tray_low_m": [-0.60, tray_y, -0.20],
        "tray_size_m": [2.60, tray_width, 0.10],
        "tray_y_m": tray_y,
        "tray_width_m": tray_width,
        "fluid_low_m": [0.05, -0.11, 0.70],
        "fluid_height_m": fluid_height,
        "fluid_volume_m3": (cup_width - 0.10) * 0.22 * fluid_height,
        "initial_layer_count": 3,
        "finite_wall_faces": ["cup_bottom", "cup_left", "cup_right", "cup_front", "cup_back", "receiver_bottom", "receiver_left", "receiver_right", "receiver_front", "receiver_back", "tray_bottom"],
        "open_boundary_faces": ["world_top"],
        "motion_axis": "+Y from axisp1=(0,-1,0.65) to axisp2=(0,1,0.65); native mvrotfile sign retained",
    }


def make_case(
    background: str,
    resolution: str,
    *,
    case_id: str | None = None,
    physical_case_id: str | None = None,
    paired_background_id: str | None = None,
    values: Mapping[str, Any] | None = None,
    strict_source: bool = True,
) -> dict[str, Any]:
    if background not in BACKGROUND_SPECS:
        raise ValueError(f"unknown background: {background}")
    if resolution not in RESOLUTION_ORDER:
        raise ValueError(f"resolution must be one of {RESOLUTION_ORDER}")
    values_all = {
        "fill_ratio": 1.0,
        "receiver_x_m": BACKGROUND_SPECS[background]["receiver_x_m"],
        "receiver_y_m": BACKGROUND_SPECS[background]["receiver_y_m"],
        "cup_width_m": 0.425,
        "mouth_geometry": "open_rim",
    }
    values_all.update(dict(values or {}))
    source = _read_w06_history(strict=strict_source)
    source_row = next(row for row in source["records"] if row["case_id"] == BACKGROUND_SPECS[background]["source_case"])
    cid = case_id or f"F2_{background}_{resolution}"
    pid = physical_case_id or f"{cid}_physical"
    event = _event_window(background, h_ratio=float(values_all["fill_ratio"]))
    geometry = _geometry(background, values_all)
    return {
        "schema": SCHEMA,
        "generator_version": GENERATOR_VERSION,
        "family_id": FAMILY_ID,
        "case_id": cid,
        "physical_case_id": pid,
        "lineage_group_id": f"F2_{background}_v1",
        "paired_background_id": paired_background_id or f"{pid}_pair",
        "mechanism_id": background,
        "geometry_family_id": BACKGROUND_SPECS[background]["geometry_family_id"],
        "control_family_id": BACKGROUND_SPECS[background]["control_family_id"],
        "recipe_id": BACKGROUND_SPECS[background]["recipe_id"],
        "view_id": "native_full_state",
        "background": background,
        "resolution": resolution,
        "dp_m": DP_BY_BACKGROUND[background][resolution],
        "feature_scale_m": 0.22,
        "feature_samples": 0.22 / DP_BY_BACKGROUND[background][resolution],
        "parameter_values": values_all,
        "geometry": geometry,
        "event_window": event,
        "observables": _observables(background),
        "quality_contract": _quality_contract(background, h_ratio=float(values_all["fill_ratio"])),
        "solver_parameters": _solver_parameters(event["complete_event_window_s"], event["save_interval_s"]),
        "source_mother": source_row,
        "motion_filename": f"{cid}_motion.dat",
        "generation_status": "definition_only_not_gencase_run",
        "production_status": "not_produced",
        "qualification_status": "unqualified_until_native_reference_evidence",
    }


def write_case(case: Mapping[str, Any], output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    xml_path = out / f"{case['case_id']}_Def.xml"
    motion_path = out / str(case["motion_filename"])
    meta_path = out / f"{case['case_id']}.metadata.json"
    xml_path.write_text(_definition_xml(case), encoding="utf-8")
    write_motion(motion_path, duration_s=ROTATION_DURATION_S, event_window_s=float(case["event_window"]["complete_event_window_s"]))
    result = dict(case)
    result["definition_path"] = str(xml_path)
    result["definition_sha256"] = sha256_file(xml_path)
    result["motion_path"] = str(motion_path)
    result["motion_sha256"] = sha256_file(motion_path)
    result["metadata_path"] = str(meta_path)
    meta_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["metadata_sha256"] = sha256_file(meta_path)
    return result


def _motion_audit(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    times: list[float] = []
    angles: list[float] = []
    if not path.is_file():
        return {"status": "fail", "errors": [f"motion file missing: {path}"], "row_count": 0}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            time_text, angle_text = line.split(";", 1)
            time_s, angle = float(time_text), float(angle_text)
        except ValueError:
            errors.append(f"invalid motion row {line_number}")
            continue
        if not math.isfinite(time_s) or not math.isfinite(angle):
            errors.append(f"nonfinite motion row {line_number}")
        times.append(time_s)
        angles.append(angle)
    if not times:
        errors.append("motion file has no data rows")
    if any(b <= a for a, b in zip(times, times[1:])):
        errors.append("motion times are not strictly increasing")
    if times and (abs(times[0]) > 1e-12 or abs(times[-1] - EVENT_WINDOW_S) > 1e-9):
        errors.append("motion file does not cover the registered complete event window")
    if angles and (abs(angles[0]) > 1e-12 or abs(angles[-1] - ROTATION_ANGLE_DEG) > 1e-6):
        errors.append("motion endpoints do not encode static hold and final rotation")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "row_count": len(times),
        "time_start_s": times[0] if times else None,
        "time_end_s": times[-1] if times else None,
        "angle_min_deg": min(angles) if angles else None,
        "angle_max_deg": max(angles) if angles else None,
        "final_angle_deg": angles[-1] if angles else None,
    }


def preflight_definition(definition_path: str | Path, metadata_path: str | Path | None = None, *, require_source_evidence: bool = True) -> dict[str, Any]:
    path = Path(definition_path).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        return {"schema": "ds-data-02.f2.input-preflight.v1", "status": "fail", "definition_path": str(path), "errors": ["definition missing"], "warnings": []}
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        return {"schema": "ds-data-02.f2.input-preflight.v1", "status": "fail", "definition_path": str(path), "errors": [f"invalid XML: {exc}"], "warnings": []}
    casedef = root.find("casedef")
    geometry = casedef.find("geometry") if casedef is not None else None
    definition = geometry.find("definition") if geometry is not None else None
    commands = geometry.find("commands") if geometry is not None else None
    if definition is None:
        errors.append("missing casedef/geometry/definition")
    dp = None
    extent_ok = False
    if definition is not None:
        try:
            dp = float(definition.attrib["dp"])
            pmin = definition.find("pointmin")
            pmax = definition.find("pointmax")
            if pmin is None or pmax is None:
                errors.append("definition lacks pointmin/pointmax")
            else:
                lower = [float(pmin.attrib[key]) for key in ("x", "y", "z")]
                upper = [float(pmax.attrib[key]) for key in ("x", "y", "z")]
                extent_ok = all(math.isfinite(a) and math.isfinite(b) and b > a for a, b in zip(lower, upper))
                if not extent_ok:
                    errors.append("definition extent is not finite positive 3-D")
        except (KeyError, TypeError, ValueError):
            errors.append("invalid dp or definition extent")
    if dp is None or not math.isfinite(dp) or dp <= 0:
        errors.append("dp must be finite positive")
    command_text = ET.tostring(commands, encoding="unicode") if commands is not None else ""
    required_tokens = ("setmkfluid", "bottom", "left", "right", "front", "back")
    for token in required_tokens:
        if token not in command_text:
            errors.append(f"missing required geometry token: {token}")
    if "periodic" in command_text.lower():
        errors.append("periodic topology is forbidden for finite F2 catchment")
    if "fillbox" in command_text.lower() and "setmkfluid" not in command_text:
        errors.append("fluid construction is not explicit")
    parameters = {}
    for node in root.findall("./execution/parameters/parameter"):
        if "key" in node.attrib and "value" in node.attrib:
            parameters[node.attrib["key"]] = node.attrib["value"]
    try:
        time_max = float(parameters["TimeMax"])
        time_out = float(parameters["TimeOut"])
        if time_max < EVENT_WINDOW_S or time_out <= 0 or time_out >= time_max:
            errors.append("TimeMax/TimeOut do not cover the complete registered event window")
    except (KeyError, ValueError):
        errors.append("missing TimeMax or TimeOut")
    motion = root.find("./casedef/motion/objreal/mvrotfile/file")
    motion_path = path.parent / motion.attrib["name"] if motion is not None and motion.attrib.get("name") else path.with_name(path.stem.replace("_Def", "") + "_motion.dat")
    motion_report = _motion_audit(motion_path)
    errors.extend(motion_report["errors"])
    metadata: dict[str, Any] | None = None
    if metadata_path is None:
        guess = path.with_name(path.name.replace("_Def.xml", ".metadata.json"))
        metadata_path = guess if guess.is_file() else None
    if metadata_path is None:
        errors.append("metadata sidecar missing")
    else:
        try:
            metadata = _json(Path(metadata_path))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"metadata unreadable: {exc}")
        if isinstance(metadata, dict):
            if metadata.get("family_id") != FAMILY_ID:
                errors.append("metadata family_id is not F2")
            if metadata.get("generation_status") != "definition_only_not_gencase_run":
                errors.append("metadata must remain definition-only before runner receipt")
            if metadata.get("production_status") == "produced":
                errors.append("definition metadata claims production")
            if float(metadata.get("feature_samples", 0.0)) < 6.0:
                errors.append("cup opening feature has fewer than six particles at this resolution")
            if metadata.get("solver_parameters", {}).get("Boundary") != 1:
                errors.append("F2 reference recipe must bind the successful W06 DBC control")
            source_mother = metadata.get("source_mother", {})
            if require_source_evidence and not source_mother.get("source_definition_sha256"):
                errors.append("W06 source Definition hash missing")
            if require_source_evidence and not source_mother.get("source_motion_sha256"):
                errors.append("W06 source motion hash missing")
    checks = {
        "three_dimensional_extent": extent_ok and (commands is not None and " y=" in command_text),
        "finite_cup_receiver_tray": all(token in command_text for token in ("mk=\"0\"", "mk=\"1\"", "mk=\"2\"")),
        "finite_wall_faces": all(token in command_text for token in ("bottom", "left", "right", "front", "back")),
        "nonzero_fluid_definition": "setmkfluid" in command_text and "<size" in command_text,
        "motion_control_bound": motion_report["status"] == "pass",
        "complete_event_window_bound": not any("TimeMax" in error for error in errors),
        "no_periodic_topology": "periodic" not in command_text.lower(),
        "official_w06_lineage": not any("W06 source" in error for error in errors),
        "thresholds_precede_results": isinstance(metadata, dict) and metadata.get("quality_contract", {}).get("status") == "thresholds_frozen_before_results",
    }
    return {
        "schema": "ds-data-02.f2.input-preflight.v1",
        "status": "pass" if not errors else "fail",
        "definition_path": str(path),
        "definition_sha256": sha256_file(path),
        "metadata_path": str(metadata_path) if metadata_path else None,
        "motion_path": str(motion_path),
        "motion": motion_report,
        "solver_invoked": False,
        "gencase_invoked": False,
        "solver_dimension_declared": 3,
        "coordinate_components": 3,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "parameter_values": parameters,
    }


def reference_matrix(output_dir: str | Path, *, strict_source: bool = True) -> dict[str, Any]:
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for background in ("center_catch", "offset_spill"):
        pid = f"F2_REF_{'CENTER' if background == 'center_catch' else 'OFFSET'}_NOMINAL"
        for resolution in RESOLUTION_ORDER:
            cid = f"{pid}_{resolution.upper()}"
            case = make_case(background, resolution, case_id=cid, physical_case_id=pid, paired_background_id="F2_REF_PAIR_NOMINAL", strict_source=strict_source)
            rows.append(write_case(case, out))
    preflight = [preflight_definition(row["definition_path"], row["metadata_path"], require_source_evidence=strict_source) for row in rows]
    result = {
        "schema": "ds-data-02.f2.reference-matrix.v1",
        "family_id": FAMILY_ID,
        "generated_at_utc": utc_now(),
        "status": "definitions_written_preflight_only",
        "qualification_claim": "none",
        "matrix": [
            {
                "case_id": row["case_id"],
                "physical_case_id": row["physical_case_id"],
                "paired_background_id": row["paired_background_id"],
                "background": row["background"],
                "resolution": row["resolution"],
                "dp_m": row["dp_m"],
                "feature_scale_m": row["feature_scale_m"],
                "feature_samples": row["feature_samples"],
                "event_window_s": row["event_window"]["complete_event_window_s"],
                "save_interval_s": row["event_window"]["save_interval_s"],
                "definition_path": row["definition_path"],
                "definition_sha256": row["definition_sha256"],
                "motion_path": row["motion_path"],
                "motion_sha256": row["motion_sha256"],
                "metadata_path": row["metadata_path"],
                "metadata_sha256": row["metadata_sha256"],
                "solver_status": "not_run",
                "native_evidence": None,
            }
            for row in rows
        ],
        "resolution_identity_rule": "Three resolutions share a physical_case_id and are numerical views, not independent physical cases.",
        "all_preflight": all(item["status"] == "pass" for item in preflight),
        "preflight": preflight,
    }
    path = out / "reference_matrix.json"
    _write_json(path, result)
    result["path"] = str(path)
    result["sha256"] = sha256_file(path)
    return result


def integration_save_plan(output_dir: str | Path) -> dict[str, Any]:
    plan = {
        "schema": "ds-data-02.f2.integration-save-study.v1",
        "family_id": FAMILY_ID,
        "status": "planned_not_run",
        "qualification_claim": "none",
        "sensitivity_case": {
            "background": "offset_spill",
            "physical_case_id": "F2_REF_OFFSET_NOMINAL",
            "resolution": "medium",
            "reason": "offset destination boundary and moving cup opening are the most event-sensitive registered geometry",
        },
        "controls": [
            {
                "control_id": "offset_native_dt_save010",
                "purpose": "reference adaptive integration and matrix save cadence",
                "solver_parameter_overrides": {"DtFixed": 0, "DtIni": 0, "DtMin": 0},
                "time_out_s": 0.01,
            },
            {
                "control_id": "offset_half_native_dt_save010",
                "purpose": "independent integration-step comparison at half the observed native initial dt",
                "solver_parameter_overrides": {"DtFixed": "runner_bound_half_native_DtIni", "DtIni": 0, "DtMin": 0},
                "time_out_s": 0.01,
            },
            {
                "control_id": "offset_native_dt_save005",
                "purpose": "independent output-save comparison with identical integration control",
                "solver_parameter_overrides": {"DtFixed": 0, "DtIni": 0, "DtMin": 0},
                "time_out_s": 0.005,
            },
            {
                "control_id": "offset_native_dt_event_save001",
                "purpose": "complete-window event timing control before a Q-N event-time claim",
                "solver_parameter_overrides": {"DtFixed": 0, "DtIni": 0, "DtMin": 0},
                "time_out_s": EVENT_CONTROL_SAVE_INTERVAL_S,
                "timing_qualification": True,
                "worst_case_snapshot_quantization_s": EVENT_CONTROL_SAVE_INTERVAL_S / 2.0,
            },
        ],
        "comparison": {
            "same_geometry_initial_state_and_control": True,
            "integrator_and_save_are_separate_factors": True,
            "starting_budget": {"macro_relative": 0.05, "event_time_fraction_of_characteristic_time": 0.02, "integration_fraction_max": 0.20, "save_fraction_max": 0.20},
            "reference_matrix_save_interval_role": "raw macro-observable reference only until native event control is run",
            "downsampling_is_not_integration_study": True,
        },
    }
    path = Path(output_dir).expanduser().resolve() / "integration_save_plan.json"
    _write_json(path, plan)
    plan["path"] = str(path)
    plan["sha256"] = sha256_file(path)
    return plan


def event_definitions(output_dir: str | Path) -> dict[str, Any]:
    value = {
        "schema": "ds-data-02.f2.event-definitions.v1",
        "family_id": FAMILY_ID,
        "thresholds_frozen_at": utc_now(),
        "thresholds_apply_before_native_results": True,
        "common_event_order": ["static_hold", "rotation_start", "cup_mouth_departure", "receiver_or_tray_entry", "rotation_stop", "post_stop_return", "final_residence_or_unknown"],
        "backgrounds": {
            background: {
                "event_window_s": EVENT_WINDOW_S,
                "opening": "finite moving cup-mouth aperture; crossing is interpolated in body coordinates and retains particle ID",
                "receiver": "finite receiver interior excluding one boundary shell; repeated entry/exit contributes signed net and separate recrossings",
                "spill_tray": "finite tray interior excluding one boundary shell; spill only after prior cup-mouth departure",
                "final_categories": ["receiver_captured", "spill_tray", "cup_retained", "inflight", "unknown"],
                "unknown_mass": "initial native mass denominator minus mutually exclusive categories; never relabel as spill",
                "source": "initial Mk layer 0/1/2, continuous z bands from the same initial fluid geometry",
                "control": "motion file at 0.005 s is input control; native saved pose/angle/omega must be compared at output times",
            }
            for background in BACKGROUND_SPECS
        },
        "measurement_rules": {
            "first_passage": "linearly interpolate bracketed finite-region crossing in native consecutive frames; if not bracketed mark right-censored",
            "residence": "sum native time intervals in each region, retaining repeated receiver/tray/cup occupancy",
            "mass": "mass-weight every count; use initial fluid IDs only and keep unknown in denominator",
            "boundary": "fluid mass excludes fixed or moving wall nodes; physical walls are not an open sink",
        },
    }
    path = Path(output_dir).expanduser().resolve() / "event_definitions.json"
    _write_json(path, value)
    value["path"] = str(path)
    value["sha256"] = sha256_file(path)
    return value


def _candidate_records() -> list[dict[str, Any]]:
    """Create 24 paired center/offset physical cases (48 total).

    Each pair shares source water, fill ratio, tilt duration, and longitudinal
    receiver gap.  Only the receiver's transverse placement and mechanism
    background differ, which makes the catch/spill contrast auditable.
    """

    rows: list[dict[str, Any]] = []
    fills = (0.80, 1.00, 1.20)
    durations = (0.65, 1.20)
    receiver_xs = (0.45, 0.65)
    mouth_styles = ("open_rim", "short_spout")
    pair_index = 0
    for fill_ratio in fills:
        for duration_s in durations:
            for receiver_x in receiver_xs:
                for mouth_geometry in mouth_styles:
                    pair_index += 1
                    pair_id = f"F2_PAIR_{pair_index:02d}"
                    common = {
                        "fill_ratio": fill_ratio,
                        "rotation_duration_s": duration_s,
                        "receiver_x_m": receiver_x,
                        "mouth_geometry": mouth_geometry,
                    }
                    for background in ("center_catch", "offset_spill"):
                        values = dict(common)
                        values["receiver_y_m"] = 0.0 if background == "center_catch" else (0.14 if pair_index % 2 else 0.22)
                        pid = f"F2_{'CENTER' if background == 'center_catch' else 'OFFSET'}_P{pair_index:02d}"
                        geometry_family = BACKGROUND_SPECS[background]["geometry_family_id"]
                        if mouth_geometry == "short_spout":
                            geometry_family = "F2_GEOM_CUP_SHORT_SPOUT_HOLDOUT_V1"
                        role = (
                            "train" if pair_index <= 12 else
                            "validation" if pair_index <= 15 else
                            "id_test" if pair_index <= 18 else
                            "parameter_ood" if pair_index <= 21 else
                            "geometry_control_ood"
                        )
                        rows.append(
                            {
                                "schema": "ds-data-02.case-registration.v1",
                                "case_id": pid,
                                "physical_case_id": pid,
                                "lineage_group_id": f"F2_{background}_v1",
                                "paired_background_id": pair_id,
                                "family_id": FAMILY_ID,
                                "mechanism_id": background,
                                "geometry_family_id": geometry_family,
                                "control_family_id": BACKGROUND_SPECS[background]["control_family_id"],
                                "recipe_id": BACKGROUND_SPECS[background]["recipe_id"],
                                "view_id": "native_full_state",
                                "attempt_id": None,
                                "status": "pre_registered",
                                "split": role,
                                "production": False,
                                "qualification": "none",
                                "requested_resolution_set": list(RESOLUTION_ORDER),
                                "parameter_values": values,
                                "event_window_s": EVENT_WINDOW_S,
                                "source_evidence_required": True,
                                "native_hdf5": None,
                                "labels": None,
                                "preview": None,
                                "old_w06_reuse": False,
                                "holdout": "short_spout_geometry" if mouth_geometry == "short_spout" else None,
                            }
                        )
    if len(rows) != 48:
        raise AssertionError(f"expected 48 F2 physical cases, got {len(rows)}")
    return rows


def preregister(output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows = _candidate_records()
    counts = Counter(row["mechanism_id"] for row in rows)
    split_counts = Counter(row["split"] for row in rows)
    pair_roles = {row["paired_background_id"]: row["split"] for row in rows}
    if counts != Counter({"center_catch": 24, "offset_spill": 24}):
        raise AssertionError(f"background count drift: {counts}")
    if split_counts != Counter({"train": 24, "validation": 6, "id_test": 6, "parameter_ood": 6, "geometry_control_ood": 6}):
        raise AssertionError(f"split count drift: {split_counts}")
    if len(pair_roles) != 24 or any(len({row["split"] for row in rows if row["paired_background_id"] == pair}) != 1 for pair in pair_roles):
        raise AssertionError("paired backgrounds leak across split roles")
    path = out / "case_registry.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    result = {
        "schema": "ds-data-02.f2.pre-registration.v1",
        "family_id": FAMILY_ID,
        "status": "candidate_physics_registered_only",
        "qualification_claim": "none",
        "production_claim": "none",
        "independent_physical_case_count": len(rows),
        "background_counts": dict(counts),
        "split_counts": dict(split_counts),
        "paired_background_count": len(pair_roles),
        "nested_batches": {"batch_8": "first 8 pair-preserving physical rows from the frozen registry", "batch_24": "first 24 rows in each background after pair-preserving ordering", "batch_48": "all 48 rows"},
        "resolution_views_are_not_independent_cases": True,
        "old_w06_cases_added": 0,
        "path": str(path),
        "sha256": sha256_file(path),
        "records_have_no_solver_or_hdf5_receipts": True,
    }
    return result


def split_plan(output_dir: str | Path) -> dict[str, Any]:
    rows = _candidate_records()
    groups: dict[str, list[str]] = {}
    for row in rows:
        groups.setdefault(row["paired_background_id"], []).append(row["case_id"])
    value = {
        "schema": "ds-data-02.f2.split-plan.v1",
        "family_id": FAMILY_ID,
        "status": "planned_no_cases_assigned_to_native_outputs",
        "grouping_key": "paired_background_id/physical_case_id/lineage_group_id",
        "split_counts": dict(Counter(row["split"] for row in rows)),
        "assignments": {role: sorted(row["case_id"] for row in rows if row["split"] == role) for role in ("train", "validation", "id_test", "parameter_ood", "geometry_control_ood")},
        "pair_groups": groups,
        "holdouts": {
            "parameter": "fill_ratio, rotation_duration_s and receiver_x_m combinations outside train support but inside the frozen numerical recipe range",
            "geometry_control": "short_spout geometry family and offset control combinations; requires a fresh 2x3 reference before qualification",
        },
        "leakage_rule": "all resolutions, restarts, windows, labels, previews and HDF5 copies stay with their physical case and paired background",
        "hidden_test_claim": "none; this is a public development/test candidate split",
    }
    path = Path(output_dir).expanduser().resolve() / "split_plan.json"
    _write_json(path, value)
    value["path"] = str(path)
    value["sha256"] = sha256_file(path)
    return value


def write_case_manifests(output_dir: str | Path) -> list[str]:
    root = Path(output_dir).expanduser().resolve() / "case_manifests"
    root.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for row in _candidate_records():
        value = {
            "schema": "ds-data-02.f2.case-manifest.v1",
            "family_id": FAMILY_ID,
            "case_id": row["case_id"],
            "physical_case_id": row["physical_case_id"],
            "lineage_group_id": row["lineage_group_id"],
            "paired_background_id": row["paired_background_id"],
            "mechanism_id": row["mechanism_id"],
            "geometry_family_id": row["geometry_family_id"],
            "control_family_id": row["control_family_id"],
            "recipe_id": row["recipe_id"],
            "view_id": row["view_id"],
            "split": row["split"],
            "requested_resolutions": list(RESOLUTION_ORDER),
            "event_window_s": EVENT_WINDOW_S,
            "status": "pre_registered_no_native_output",
            "attempt_id": None,
            "hdf5": None,
            "labels": None,
            "preview": None,
            "q_i": "pending_native_output",
            "q_n": "pending_reference_matrix_and_controls",
            "q_e": "optional_not_required",
            "old_w06_reuse": False,
        }
        path = root / f"{row['case_id']}.json"
        _write_json(path, value)
        paths.append(str(path))
    return paths


def write_labels_and_preview(output_dir: str | Path) -> dict[str, str]:
    out = Path(output_dir).expanduser().resolve()
    labels = out / "labels"
    labels.mkdir(parents=True, exist_ok=True)
    label_schema = {
        "schema": "ds-data-02.f2.native-label-schema.v1",
        "family_id": FAMILY_ID,
        "material_tracer": False,
        "source_label": "initial native Mk layer (0,1,2) and continuous initial z-band definition",
        "required_arrays": ["source_label", "destination_time_series", "first_passage_interval", "residence_time", "final_category", "failure_reason", "unknown_mass"],
        "final_category_enum": ["receiver_captured", "spill_tray", "cup_retained", "inflight", "unknown"],
        "mass_policy": "initial native fluid mass remains denominator; unknown and numerical loss are separate from physical spill",
        "first_passage": "bracketed finite-surface crossing in native frames, right-censored when event is not observed",
        "repeated_crossing": "signed net flux plus separate ingress/egress counts; recrossing is not new material",
        "status": "schema_ready_no_native_arrays_yet",
    }
    _write_json(labels / "label_schema.json", label_schema)
    (labels / "README.md").write_text("# F2 native labels\n\nLabels are computed from native fluid IDs and initial Mk source layers after a solver receipt exists. This directory contains the frozen schema only; no material tracer is used.\n", encoding="utf-8")
    preview = out / "preview"
    preview.mkdir(parents=True, exist_ok=True)
    (preview / "README.md").write_text("# F2 preview\n\nPreview generation is pending native full-window outputs. A release preview must contain static hold, cup-mouth departure, first receiver/tray entry, rotation stop, and post-stop residence frames plus one animation. Metadata alone is not a flow preview.\n", encoding="utf-8")
    return {"label_schema": str(labels / "label_schema.json"), "preview_readme": str(preview / "README.md")}


def write_family_design(family_dir: str | Path, *, strict_source: bool = True) -> dict[str, Any]:
    family = Path(family_dir).expanduser().resolve()
    family.mkdir(parents=True, exist_ok=True)
    history = _read_w06_history(strict=strict_source)
    _write_json(family / "history_reuse_inventory.json", history)
    matrix = reference_matrix(family / "definitions", strict_source=strict_source)
    save_plan = integration_save_plan(family)
    events = event_definitions(family)
    registration = preregister(family)
    splits = split_plan(family)
    manifests = write_case_manifests(family)
    label_preview = write_labels_and_preview(family)
    quality = {
        "schema": "ds-data-02.f2.quality-contract-index.v1",
        "family_id": FAMILY_ID,
        "thresholds_frozen_before_results": True,
        "background_contracts": {background: _quality_contract(background) for background in BACKGROUND_SPECS},
        "reference_matrix_status": "pending_native_solver_evidence",
        "q_i_q_n_q_e_separation": True,
        "path_note": "The per-case quality contract is in each definition metadata and is copied into native case manifests after execution.",
    }
    _write_json(family / "quality_contract.json", quality)
    recipes = {
        "schema": "ds-data-02.f2.qualified-recipes.v1",
        "family_id": FAMILY_ID,
        "status": "planned_unqualified",
        "qualification_gate": "actual native 3-D reference evidence plus Q-I and recipe-scoped Q-N; Q-E and material tracers are optional",
        "recipes": [
            {"recipe_id": BACKGROUND_SPECS[background]["recipe_id"], "background": background, "qualified": False, "required_scope": f"recipe+{background}+{EVENT_WINDOW_S}s+primary_observables+resolution+labels"}
            for background in BACKGROUND_SPECS
        ],
    }
    _write_json(family / "qualified_recipes.json", recipes)
    card = {
        "schema": "ds-data-02.f2.family-card.v1",
        "family_id": FAMILY_ID,
        "status": "definition_ready_waiting_shared_runner",
        "qualification_claim": "none",
        "production_claim": "none",
        "mechanisms": [BACKGROUND_SPECS[background]["name_zh"] for background in BACKGROUND_SPECS],
        "background_ids": list(BACKGROUND_SPECS),
        "mother_source": "campaigns/v0.1-candidate/cases/w06 + official motion/mvrotfile interface",
        "historical_w06": {"total": history["counts"]["total"], "zero_missing": history["counts"]["zero_missing"], "missing_classified": history["counts"]["missing_classified"], "formal_reuse": history["counts"]["formal_reuse"]},
        "reference_matrix": "definitions/reference_matrix.json",
        "reference_matrix_shape": "2 backgrounds x 3 resolutions",
        "reference_physical_case_count": 2,
        "candidate_physical_cases": 48,
        "nested_batches": [8, 24, 48],
        "event_windows_s": {background: EVENT_WINDOW_S for background in BACKGROUND_SPECS},
        "quality_contract": "quality_contract.json",
        "event_definitions": "event_definitions.json",
        "integration_save_plan": "integration_save_plan.json",
        "raw_output_root": str(RAW_OUTPUT_ROOT),
        "next_executable_task": "submit gencase_center_request.json and gencase_offset_request.json through the shared CPU runner, then audit actual solver_dimension/fluid count/mass/boundary/control before registering qualification",
        "created_at_utc": utc_now(),
    }
    _write_json(family / "family_card.json", card)
    handoff = f'''# F2 DS-DATA-02 handoff

Status: definitions and contracts ready; two bounded CPU GenCase preflights are
registered for the shared runner. No GPU or solver was launched by this family
owner.

The new physical mechanisms are `center_catch` and `offset_spill`. Both use a
finite three-dimensional cup with explicit bottom/side/front/back walls, a
finite receiver, and a finite spill tray. The cup uses the W06 successful DBC
`mvrotfile` interface about the Y axis: 0--0.5 s static hold, cosine-ramped
rotation to -105 degrees over {ROTATION_DURATION_S:.2f} s, then a post-stop hold
through {EVENT_WINDOW_S:.2f} s. The offset background keeps the same source
fluid and control while moving the receiver to a transverse offset; spill is
classified only after finite cup-mouth departure and remains in the initial
mass denominator.

`definitions/reference_matrix.json` freezes the same continuous geometry and
control at coarse/medium/fine dp = 0.025/0.020/0.015 m for both backgrounds.
`quality_contract.json` and `event_definitions.json` freeze Q-I/Q-N thresholds,
finite-surface crossings, source-layer labels, destination categories, and
unknown-mass rules before native results exist. `integration_save_plan.json`
keeps native-dt, half-native-dt, save-0.005 s, and event-save-0.001 s controls
independent; 0.01 s matrix output cannot by itself qualify event timing.

The historical W06 inventory records 5 cases with zero missing initial IDs and
7 cases with positive missing IDs. All 12 remain historical evidence only;
D05 is recorded as reference reuse and no old model/tracer is revived.

The registry contains 48 independent physical cases (24 paired center/offset
groups), with nested 8/24/48 progression and split counts train 24,
validation 6, ID-test 6, parameter-OOD 6, geometry/control-OOD 6. Resolution
views and integration/save controls never add case count. Short-spout rows are
held out until a fresh geometry reference is generated.

Next executable task: submit the two `gencase_*_request.json` files via
`scripts/ds_data02_runtime.py run --request PATH` from the integration worktree
with CPU threads <=4, max wall <=300 s, and storage <=256 MiB. Use the receipts
to bind actual total/fluid particles, actual 3-D output evidence, initial mass,
finite-boundary/control coverage, and only then register the qualification
requests for the primary process.
'''
    (family / "FAMILY_HANDOFF.md").write_text(handoff, encoding="utf-8")
    return {"family_dir": str(family), "history": str(family / "history_reuse_inventory.json"), "reference_matrix": matrix, "integration_save_plan": save_plan, "event_definitions": events, "registration": registration, "split_plan": splits, "manifests": len(manifests), "labels": label_preview, "family_card": str(family / "family_card.json"), "git_commit": _git_commit()}


def _request_inputs(case_row: Mapping[str, Any], family: Path, history_path: Path) -> list[str]:
    return [
        str(SCRIPT_PATH),
        str(history_path),
        str(family / "quality_contract.json"),
        str(family / "event_definitions.json"),
        str(family / "integration_save_plan.json"),
        str(family / "case_registry.jsonl"),
        str(family / "definitions/reference_matrix.json"),
        str(case_row["definition_path"]),
        str(case_row["motion_path"]),
        str(case_row["metadata_path"]),
    ]


def _gencase_request(*, family: Path, row: Mapping[str, Any], history_path: Path, attempt_id: str, threads: int, storage: int) -> dict[str, Any]:
    definition = Path(row["definition_path"]).resolve()
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": row["case_id"],
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "command": [str(GENCASE), str(definition.with_suffix("")), f"{{attempt_root}}/{row['case_id']}", "-save:all"],
        "cwd": str(definition.parent),
        "max_wall_seconds": 300,
        "cpu_threads": threads,
        "estimated_storage_bytes": storage,
        "input_files": _request_inputs(row, family, history_path),
        "worktree_root": str(CURRENT_WORKTREE),
        "launch_commit": _git_commit(),
        "source_mother": row["background"],
        "definition_sha256": row["definition_sha256"],
        "motion_sha256": row["motion_sha256"],
        "generation_status": "definition_written_not_gencase_run",
        "solver_launch_forbidden": True,
        "raw_output_root": str(RAW_OUTPUT_ROOT),
        "request_note": "Submit only through the shared DS-DATA-02 runtime; do not execute this argv directly. CPU preflight only.",
    }


def _qualification_request(*, family: Path, row: Mapping[str, Any], history_path: Path, gencase_receipt: Path, attempt_id: str) -> dict[str, Any]:
    receipt = _json(gencase_receipt)
    if receipt.get("status") != "completed" or int(receipt.get("returncode", 1)) != 0 or int(receipt.get("total_particles", 0)) <= 0:
        raise ValueError("qualification request requires a completed shared-runner GenCase receipt with nonzero particles")
    definition = Path(row["definition_path"]).resolve()
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": row["case_id"],
        "attempt_id": attempt_id,
        "kind": "qualification",
        "command": [str(SOLVER), f"{{attempt_root}}/{row['case_id']}", "{attempt_root}/solver_output"],
        "cwd": str(SOLVER.parent),
        "max_wall_seconds": 300,
        "cpu_threads": 4,
        "estimated_storage_bytes": 5 * 1024 * 1024 * 1024,
        "estimated_peak_gpu_mib": 2048,
        "gencase_receipt": str(gencase_receipt.resolve()),
        "input_files": [str(SCRIPT_PATH), str(history_path), str(family / "quality_contract.json"), str(family / "event_definitions.json"), str(family / "integration_save_plan.json"), str(family / "case_registry.jsonl"), str(family / "definitions/reference_matrix.json"), str(definition), str(Path(row["motion_path"]).resolve()), str(Path(row["metadata_path"]).resolve()), str(gencase_receipt.resolve())],
        "worktree_root": str(CURRENT_WORKTREE),
        "launch_commit": _git_commit(),
        "recipe_id": row["recipe_id"],
        "mechanism_id": row["background"],
        "solver_dimension_required": 3,
        "event_window_s": EVENT_WINDOW_S,
        "observables": ["cup_remaining", "receiver_capture", "spill_tray", "inflight_unknown", "first_departure", "first_receiver_entry", "control_pose", "mass_boundary_audit"],
        "qualification_scope": "recipe+geometry/control+complete_event_window+native_observables; Q-E optional; no model/tracer gate",
        "qualification_launch_authority": "shared_ds_data_02_runner_only_primary_process",
        "raw_output_root": str(RAW_OUTPUT_ROOT),
        "request_note": "Registered for the primary process after GenCase audit; family owner does not launch GPU.",
    }


def write_runner_requests(family_dir: str | Path, *, launch_commit: str | None = None) -> dict[str, Any]:
    family = Path(family_dir).expanduser().resolve()
    matrix_path = family / "definitions/reference_matrix.json"
    if not matrix_path.is_file():
        raise FileNotFoundError("run design first")
    matrix = _json(matrix_path)
    if not matrix.get("all_preflight"):
        raise ValueError("reference matrix preflight failed")
    history_path = family / "history_reuse_inventory.json"
    rows = matrix["matrix"]
    requests: dict[str, str] = {}
    for background, filename, attempt_id, threads in (
        ("center_catch", "gencase_center_request.json", "gencase-f2-center-coarse-v1", 4),
        ("offset_spill", "gencase_offset_request.json", "gencase-f2-offset-coarse-v1", 4),
    ):
        row = next(item for item in rows if item["background"] == background and item["resolution"] == "coarse")
        request = _gencase_request(family=family, row=row, history_path=history_path, attempt_id=attempt_id, threads=threads, storage=256 * 1024 * 1024)
        if launch_commit:
            request["launch_commit"] = launch_commit
        path = family / filename
        _write_json(path, request)
        requests[filename] = str(path)
    index = {
        "schema": "ds-data-02.f2.runner-request-index.v1",
        "family_id": FAMILY_ID,
        "launch_commit": launch_commit or _git_commit(),
        "resource_guard": {"solver_invoked_by_generator": False, "gpu_launch_allowed_here": False, "cpu_threads_max": 4, "max_wall_seconds": 300, "storage_bytes_max": 256 * 1024 * 1024, "shared_runner_required": True, "foreign_processes_protected": True},
        "cpu_preflight_requests": requests,
        "qualification_requests": "registered after each completed GenCase receipt using the qualification-request command; no GPU launch here",
        "reference_matrix": {"background_count": 2, "resolution_count_per_background": 3, "case_count": 6, "physical_case_count": 2, "resolution_views_are_not_independent": True},
        "qualification_scope_claim": "none until native receipts and Q-I/Q-N evidence",
        "production_claim": "none",
    }
    _write_json(family / "runner_request.json", index)
    index["path"] = str(family / "runner_request.json")
    index["sha256"] = sha256_file(family / "runner_request.json")
    return index


def write_qualification_request(family_dir: str | Path, background: str, gencase_receipt: str | Path, *, attempt_id: str | None = None) -> dict[str, Any]:
    family = Path(family_dir).expanduser().resolve()
    matrix = _json(family / "definitions/reference_matrix.json")
    row = next(item for item in matrix["matrix"] if item["background"] == background and item["resolution"] == "coarse")
    request = _qualification_request(family=family, row=row, history_path=family / "history_reuse_inventory.json", gencase_receipt=Path(gencase_receipt), attempt_id=attempt_id or f"qualification-f2-{background}-coarse-v1")
    path = family / f"qualification_{background}_request.json"
    _write_json(path, request)
    request["path"] = str(path)
    request["sha256"] = sha256_file(path)
    return request


def record_gencase_receipts(family_dir: str | Path, center_receipt: str | Path, offset_receipt: str | Path) -> dict[str, Any]:
    """Bind the two actual shared-runner receipts without copying raw output."""

    family = Path(family_dir).expanduser().resolve()
    matrix_path = family / "definitions/reference_matrix.json"
    matrix = _json(matrix_path)
    receipt_rows = []
    for background, path in (("center_catch", Path(center_receipt)), ("offset_spill", Path(offset_receipt))):
        receipt = _json(path)
        row = {
            "background": background,
            "case_id": receipt.get("request", {}).get("case_id"),
            "attempt_id": receipt.get("request", {}).get("attempt_id"),
            "receipt_path": str(path.resolve()),
            "receipt_sha256": sha256_file(path),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "solver_dimension_from_gencase": receipt.get("solver_dimension_from_gencase"),
            "total_particles": receipt.get("total_particles"),
            "fluid_particles": receipt.get("fluid_particles"),
            "elapsed_seconds": receipt.get("elapsed_seconds"),
            "cpu_core_seconds": receipt.get("cpu_core_seconds"),
            "bytes": receipt.get("bytes"),
            "stdout_sha256": receipt.get("stdout_sha256"),
            "quality_interpretation": {"three_dimensional": receipt.get("solver_dimension_from_gencase") == 3, "nonzero_fluid": int(receipt.get("fluid_particles", 0) or 0) > 0, "boundary_and_control": "definition and motion hashes are bound by request; native boundary/control coverage remains solver qualification evidence"},
        }
        receipt_rows.append(row)
        for item in matrix["matrix"]:
            if item["case_id"] == row["case_id"]:
                item["solver_status"] = receipt.get("status")
                item["native_evidence"] = row
    evidence = {
        "schema": "ds-data-02.f2.gencase-preflight-evidence.v1",
        "family_id": FAMILY_ID,
        "recorded_at_utc": utc_now(),
        "qualification_claim": "none",
        "production_claim": "none",
        "receipts": receipt_rows,
        "checks": {"both_completed": all(row["status"] == "completed" and row["returncode"] == 0 for row in receipt_rows), "both_3d": all(row["quality_interpretation"]["three_dimensional"] for row in receipt_rows), "both_nonzero_fluid": all(row["quality_interpretation"]["nonzero_fluid"] for row in receipt_rows), "mass_boundary_control_next": "native solver qualification required; GenCase receipt alone does not grant Q-I/Q-N"},
        "raw_output_policy": "stdout/GenCase products remain under external data_root; this committed file stores receipt paths, hashes and parsed facts only",
    }
    _write_json(family / "gencase_preflight_evidence.json", evidence)
    matrix["status"] = "gencase_preflight_bound_pending_solver"
    _write_json(matrix_path, matrix)
    evidence["path"] = str(family / "gencase_preflight_evidence.json")
    evidence["sha256"] = sha256_file(family / "gencase_preflight_evidence.json")
    return evidence


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("source-audit")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--allow-missing", action="store_true")
    p = sub.add_parser("generate")
    p.add_argument("--background", choices=sorted(BACKGROUND_SPECS), required=True)
    p.add_argument("--resolution", choices=RESOLUTION_ORDER, required=True)
    p.add_argument("--case-id", default=None)
    p.add_argument("--physical-case-id", default=None)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--allow-missing", action="store_true")
    p = sub.add_parser("preflight")
    p.add_argument("definition", type=Path)
    p.add_argument("--metadata", type=Path, default=None)
    p.add_argument("--allow-missing-source", action="store_true")
    p = sub.add_parser("design")
    p.add_argument("--family-dir", type=Path, default=FAMILY_ROOT)
    p.add_argument("--allow-missing", action="store_true")
    p = sub.add_parser("runner-request")
    p.add_argument("--family-dir", type=Path, default=FAMILY_ROOT)
    p.add_argument("--launch-commit", default=None)
    p = sub.add_parser("qualification-request")
    p.add_argument("--family-dir", type=Path, default=FAMILY_ROOT)
    p.add_argument("--background", choices=sorted(BACKGROUND_SPECS), required=True)
    p.add_argument("--gencase-receipt", type=Path, required=True)
    p.add_argument("--attempt-id", default=None)
    p = sub.add_parser("record-gencase")
    p.add_argument("--family-dir", type=Path, default=FAMILY_ROOT)
    p.add_argument("--center-receipt", type=Path, required=True)
    p.add_argument("--offset-receipt", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "source-audit":
        result = _read_w06_history(strict=not args.allow_missing)
        _write_json(args.output, result)
        print(json.dumps({"status": "ok", "path": str(args.output), "sha256": sha256_file(args.output), "counts": result["counts"]}, ensure_ascii=False))
        return 0
    if args.command == "generate":
        case = make_case(args.background, args.resolution, case_id=args.case_id, physical_case_id=args.physical_case_id, strict_source=not args.allow_missing)
        result = write_case(case, args.output)
        print(json.dumps({"status": "definition_written", "case_id": result["case_id"], "definition": result["definition_path"], "motion": result["motion_path"], "sha256": result["definition_sha256"]}, ensure_ascii=False))
        return 0
    if args.command == "preflight":
        result = preflight_definition(args.definition, args.metadata, require_source_evidence=not args.allow_missing_source)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] == "pass" else 1
    if args.command == "design":
        result = write_family_design(args.family_dir, strict_source=not args.allow_missing)
        print(json.dumps({"status": "design_written", "family_dir": result["family_dir"], "matrix": result["reference_matrix"]["path"], "registry": result["registration"]["path"]}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "runner-request":
        result = write_runner_requests(args.family_dir, launch_commit=args.launch_commit)
        print(json.dumps({"status": "request_written", "path": result["path"], "sha256": result["sha256"], "cpu_preflight_requests": result["cpu_preflight_requests"]}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "qualification-request":
        result = write_qualification_request(args.family_dir, args.background, args.gencase_receipt, attempt_id=args.attempt_id)
        print(json.dumps({"status": "qualification_request_registered", "path": result["path"], "sha256": result["sha256"], "attempt_id": result["attempt_id"]}, ensure_ascii=False, indent=2))
        return 0
    result = record_gencase_receipts(args.family_dir, args.center_receipt, args.offset_receipt)
    print(json.dumps({"status": "gencase_evidence_recorded", "path": result["path"], "sha256": result["sha256"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
