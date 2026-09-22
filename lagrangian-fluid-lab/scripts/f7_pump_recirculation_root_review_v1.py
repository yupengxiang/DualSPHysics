#!/usr/bin/env python3
"""Freeze a read-only F7 pump candidate for future root review.

The official DualSPHysics Pump example is a plausible new physical family:
closed single-phase recirculation driven by a prescribed rotating internal
pump body.  This module records that hypothesis and its source hashes only.
It deliberately does not create a Definition, materialize a matrix, invoke
GenCase/native tools/solver/GPU/queue, or mutate the Core registry, ledger,
completion record, or denominator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
NAMESPACE = LAB / "campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922"
CANDIDATE = NAMESPACE / "candidate-card-v1.json"
SOURCE_AUDIT = NAMESPACE / "source-audit-v1.json"
INTERFACE_REVIEW = NAMESPACE / "interface-review-v1.json"
ROOT_RECEIPT = NAMESPACE / "root-review-receipt-v1.json"
REPORT = LAB / "reports/F7-PUMP-RECIRCULATION-ROOT-REVIEW-2026-09-22.zh-CN.md"
TEST = LAB / "tests/test_f7_pump_recirculation_root_review_v1.py"

ADAPTER_SCRIPT = "scripts/f7_pump_geometry_adapter_v1.py"
ADAPTER_TEST = "tests/test_f7_pump_geometry_adapter_v1.py"
OBSERVER_SCRIPT = "scripts/f7_pump_transport_observer_v1.py"
OBSERVER_TEST = "tests/test_f7_pump_transport_observer_v1.py"
CORE_ADAPTER_TEST = "tests/test_f7_core_cfd_adapter_v1.py"
ROOT_CONTRACT_V2_SCRIPT = "scripts/f7_pump_root_review_contract_v2.py"
ROOT_CONTRACT_V2_TEST = "tests/test_f7_pump_root_review_contract_v2.py"
CAUSAL_SIDECAR_SCRIPT = "scripts/f7_pump_causal_sidecar_v1.py"
CAUSAL_SIDECAR_TEST = "tests/test_f7_pump_causal_sidecar_v1.py"

PUMP_DIR = "vendor/official/DualSPHysics_v5.4/examples/main/13_Pump"
PUMP_XML = f"{PUMP_DIR}/CasePump_Def.xml"
PUMP_FIXED = f"{PUMP_DIR}/pump_fixed.vtk"
PUMP_MOVING = f"{PUMP_DIR}/pump_moving.vtk"
PUMP_CPU = f"{PUMP_DIR}/xCasePump_linux64_CPU.sh"
PUMP_GPU = f"{PUMP_DIR}/xCasePump_linux64_GPU.sh"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def local(relative: str) -> Path:
    path = LAB / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def binding(relative: str, role: str) -> dict[str, Any]:
    path = local(relative)
    return {
        "path": relative,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def _float_attr(node: ET.Element, name: str) -> float:
    value = node.get(name)
    if value is None:
        raise AssertionError(f"missing XML attribute {name}")
    return float(value)


def parse_pump_definition() -> dict[str, Any]:
    root = ET.parse(local(PUMP_XML)).getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise AssertionError("official Pump definition is missing geometry")
    draw_files = root.findall("./casedef/geometry/commands/mainlist/drawfilevtk")
    draw_names = [item.get("file") for item in draw_files]
    if draw_names != ["pump_fixed.vtk", "pump_moving.vtk"]:
        raise AssertionError(f"unexpected Pump VTK sources: {draw_names}")

    mainlist = root.findall("./casedef/geometry/commands/mainlist/*")
    setmk = [item.get("mk") for item in mainlist if item.tag == "setmkbound"]
    if setmk != ["0", "2"]:
        raise AssertionError(f"unexpected Pump boundary labels: {setmk}")
    fill = root.find("./casedef/geometry/commands/mainlist/fillbox")
    fluid_labels = [item.get("mk") for item in mainlist if item.tag == "setmkfluid"]
    if fill is None or fluid_labels != ["1"]:
        raise AssertionError("official Pump fluid fill is not preceded by setmkfluid mk=1")

    object_node = root.find("./casedef/motion/objreal[@ref='2']")
    if object_node is None:
        raise AssertionError("official Pump has no moving ref=2 object")
    rotations = object_node.findall("./mvrotace")
    if len(rotations) != 2:
        raise AssertionError("official Pump motion schedule is not two-stage")
    axes = []
    schedule = []
    for rotation in rotations:
        p1 = rotation.find("./axisp1")
        p2 = rotation.find("./axisp2")
        if p1 is None or p2 is None:
            raise AssertionError("Pump rotation axis is incomplete")
        axis_p1 = [_float_attr(p1, key) for key in ("x", "y", "z")]
        axis_p2 = [_float_attr(p2, key) for key in ("x", "y", "z")]
        ace = rotation.find("./ace")
        velini = rotation.find("./velini")
        axes.append({"p1": axis_p1, "p2": axis_p2})
        schedule.append({
            "id": rotation.get("id"),
            "duration_s": _float_attr(rotation, "duration"),
            "acceleration_deg_s2": None if ace is None else _float_attr(ace, "ang"),
            "initial_velocity_deg_s": None if velini is None else _float_attr(velini, "ang"),
        })

    parameters = {
        item.get("key"): item.get("value")
        for item in root.findall("./execution/parameters/parameter")
    }
    axis_delta = [axes[0]["p2"][i] - axes[0]["p1"][i] for i in range(3)]
    axis_length = sum(value * value for value in axis_delta) ** 0.5
    return {
        "fluid_mk": 1,
        "fixed_boundary_mk": 0,
        "moving_boundary_mk": 2,
        "moving_object_ref": 2,
        "drawfilevtk": draw_names,
        "fluid_fillbox": {
            "origin": [float(fill.get(key)) for key in ("x", "y", "z")],
            "size": [float(fill.find("./size").get(key)) for key in ("x", "y", "z")],
            "point": [float(fill.find("./point").get(key)) for key in ("x", "y", "z")],
        },
        "rotation_axis": axes[0],
        "rotation_axis_length_m": axis_length,
        "rotation_schedule": schedule,
        "time_max_s": float(parameters["TimeMax"]),
        "time_out_s": float(parameters["TimeOut"]),
        "parts_out_max": float(parameters["PartsOutMax"]),
        "gravity_z_m_s2": float(root.find("./casedef/constantsdef/gravity").get("z")),
        "viscosity_treatment": parameters["ViscoTreatment"],
        "viscosity_value": float(parameters["Visco"]),
    }


def parse_vtk_header(relative: str) -> dict[str, Any]:
    data = local(relative).read_bytes()
    prefix = data[:4096].decode("ascii", errors="replace")
    dataset = re.search(r"DATASET\s+(\w+)", prefix)
    points = re.search(r"POINTS\s+(\d+)\s+(\w+)", prefix)
    polygons = re.search(rb"POLYGONS\s+(\d+)\s+(\d+)", data)
    if dataset is None or points is None or polygons is None:
        raise AssertionError(f"incomplete VTK header: {relative}")
    return {
        "format": "ASCII" if re.search(r"\nASCII\s*\n", prefix) else "BINARY",
        "dataset": dataset.group(1),
        "points": int(points.group(1)),
        "point_type": points.group(2),
        "polygons": int(polygons.group(1)),
        "polygon_integer_count": int(polygons.group(2)),
    }


def pump_sources() -> list[dict[str, Any]]:
    return [
        binding(PUMP_XML, "official Pump Definition source; immutable reference only"),
        binding(PUMP_FIXED, "official fixed geometry source; immutable reference only"),
        binding(PUMP_MOVING, "official moving pump geometry source; immutable reference only"),
        binding(PUMP_CPU, "official CPU wrapper; inspected but never invoked"),
        binding(PUMP_GPU, "official GPU wrapper; inspected but never invoked"),
        binding(
            "vendor/official/DualSPHysics_v5.4/src/source/JMotionObj.cpp",
            "official prescribed motion implementation reference",
        ),
        binding(
            "vendor/official/DualSPHysics_v5.4/src/source/JDsMotion.cpp",
            "official moving-body dispatch reference",
        ),
        binding(
            "vendor/official/DualSPHysics_v5.4/src/source/JSphCpuSingle.cpp",
            "official moving-particle runtime reference",
        ),
        binding(
            "vendor/official/DualSPHysics_v5.4/src/source/JPartsLoad4.cpp",
            "official fixed/moving/floating particle loading reference",
        ),
    ]


def isolated_implementation_bindings() -> list[dict[str, Any]]:
    return [
        binding(ROOT_CONTRACT_V2_SCRIPT, "fail-closed F7 root-review contract v2"),
        binding(ROOT_CONTRACT_V2_TEST, "root-review contract v2 synthetic regression tests"),
        binding(CAUSAL_SIDECAR_SCRIPT, "read-only hash-bound causal control sidecar producer"),
        binding(CAUSAL_SIDECAR_TEST, "causal control sidecar producer regression tests"),
        binding(ADAPTER_SCRIPT, "isolated read-only F7 Pump geometry adapter"),
        binding(ADAPTER_TEST, "geometry adapter synthetic regression tests"),
        binding(CORE_ADAPTER_TEST, "read-only Core F7 adapter contract regression tests"),
        binding(OBSERVER_SCRIPT, "isolated closed-lifecycle F7 Pump material observer"),
        binding(OBSERVER_TEST, "material observer synthetic regression tests"),
    ]


def matrix_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index = 0
    for q in (0.0, 0.5, 1.0):
        for dp in (0.010, 0.0075, 0.005):
            rows.append({
                "index": index,
                "kind": "spatial_anchor",
                "q": q,
                "dp_m": dp,
                "acceleration_deg_s2": 250.0 + 500.0 * q,
                "case_id": f"F7_PUMP_RECIRCULATION_q{q:.2f}_dp{dp:.4f}".replace(".", "p"),
                "status": "proposal_only_unmaterialized",
            })
            index += 1
    for q in (0.25, 0.75):
        for dp in (0.0075, 0.005):
            rows.append({
                "index": index,
                "kind": "held_out",
                "q": q,
                "dp_m": dp,
                "acceleration_deg_s2": 250.0 + 500.0 * q,
                "case_id": f"F7_PUMP_RECIRCULATION_q{q:.2f}_dp{dp:.4f}_heldout".replace(".", "p"),
                "status": "proposal_only_unmaterialized",
            })
            index += 1
    for kind in ("internal_time", "native_output"):
        row = {
            "index": index,
            "kind": kind,
            "q": 0.5,
            "dp_m": 0.0075,
            "acceleration_deg_s2": 500.0,
            "case_id": f"F7_PUMP_RECIRCULATION_q0p50_dp0p0075_{kind}",
            "status": "proposal_only_unmaterialized",
        }
        if kind == "internal_time":
            row["control_change"] = {
                "parameter": "cflnumber",
                "baseline": 0.2,
                "variant": 0.1,
                "actual_gate": {
                    "max_actual_dt_ratio_to_baseline": 0.8,
                    "min_actual_step_count_ratio_to_baseline": 1.25,
                },
            }
        else:
            row["control_change"] = {
                "parameter": "TimeOut",
                "baseline_s": 0.02,
                "variant_s": 0.01,
                "actual_gate": {
                    "min_saved_frame_ratio_to_baseline": 1.5,
                    "max_actual_cadence_s": 0.011,
                },
            }
        rows.append(row)
        index += 1
    assert len(rows) == 15
    return rows


def build_candidate() -> dict[str, Any]:
    completion = load(local("campaigns/core-v1/completion.json"))
    registry = load(local("campaigns/core-v1/registry.json"))
    assert completion["can_finalize"] is False
    assert completion["t1_families"] == ["F3", "F4"]
    assert not any(item.get("family") == "F7" for item in registry.get("scope_studies", []))
    parsed = parse_pump_definition()
    sources = pump_sources()
    isolated = isolated_implementation_bindings()
    return {
        "schema": "core.f7.pump_recirculation.candidate_card.v1",
        "status": "root_review_only_not_admitted",
        "family": "F7",
        "scope_id": "F7_pump_recirculation_x_v1",
        "revision_id": "F7_pump_recirculation_root_review_20260922",
        "candidate_id": "F7_pump_prescribed_internal_rotor_recirculation_v1",
        "mechanism_class": "closed_single_phase_prescribed_internal_pump_recirculation",
        "qualification_claim": "none",
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "matrix_credit": 0,
        "hypothesis": {
            "statement": (
                "A prescribed rotating internal pump body injects angular momentum into a closed fluid volume, "
                "producing a measurable recirculation/return path distinct from transfer, impact, sloshing, "
                "runup, or fluid-rigid-body coupling families."
            ),
            "changed_control": "prescribed_angular_acceleration_deg_s2",
            "axis_range": [250.0, 750.0],
            "baseline_value": 500.0,
            "all_geometry_and_initial_fluid_controls_frozen": True,
            "falsifiable": True,
        },
        "topology": {
            "lifecycle_model": "closed",
            "fluid": "single phase mk=1",
            "fixed_boundary": "pump_fixed.vtk, mk=0",
            "moving_boundary": "pump_moving.vtk, mk=2, prescribed rotation",
            "open_boundary": False,
            "source_destination_transfer": False,
            "internal_driver": "prescribed rotating pump body",
        },
        "independence_screen": {
            "F1_dam_break_fixed_obstacle": "distinct: no dam-break release or fixed-obstacle primary event",
            "F2_transfer_catch_orifice": "distinct: no source-to-receiver transfer, aperture, crest, or moving cup",
            "F3_impulse_baffle_slosh": "distinct: no initial impulse or baffle exchange as primary driver",
            "F4_drop_impact_pool": "distinct: no falling source slug or impact event as primary driver",
            "F5_piston_wave_runup": "distinct: no piston/runup shoreline event",
            "F6_fluid_rigid_body": "distinct_if_prescribed_torque_is_observed: pump is not freely coupled",
            "adversarial_condition": (
                "Root review must reject the family if the proposed observer only detects generic moving-wall "
                "motion and cannot demonstrate pump-driven recirculation/return."
            ),
        },
        "fresh_input_contract": {
            "new_scope_id": True,
            "new_revision_id": True,
            "new_case_ids": True,
            "new_literal_definition_required": True,
            "new_generated_xml_required": True,
            "new_native_bi4_required": True,
            "official_pump_assets_reused_as_immutable_sources": True,
            "existing_f1_f6_trajectory_reused": False,
            "existing_qualification_inherited": False,
            "same_input_retry": False,
            "central_registry_mutation": 0,
            "central_ledger_mutation": 0,
        },
        "planned_matrix": {
            "design": "13 spatial rows + 2 temporal/output comparator rows",
            "proposed_rows": 15,
            "rows": matrix_rows(),
            "temporal_comparator_contract": {
                "internal_time": "CFL 0.20 -> 0.10; require actual dt and step-count separation",
                "native_output": "TimeOut 0.02 s -> 0.01 s; require independent saved-frame/cadence separation",
            },
            "executed": 0,
            "passed": 0,
            "failed": 0,
            "unattempted": 15,
            "credit": 0,
            "survivor_renormalization": False,
            "formal_t1_denominator_mutation": 0,
        },
        "preflight_gates_to_freeze_before_any_runtime": {
            "native_particle_identity_unique_and_xml_aligned": True,
            "all_decoded_arrays_finite": True,
            "fluid_mass_relative_error_max": 0.025,
            "excluded_fluid_particles": 0,
            "fixed_and_moving_wall_chord_crossings": 0,
            "prescribed_motion_axis_and_schedule_hash_match": True,
            "actual_time_axis_covers_declared_window": True,
            "moving_internal_body_pose_is_finite_and_rigid": True,
        },
        "t2_interface_gates_to_freeze_before_material_data": {
            "initial_source_region_in_world_coordinates": "not yet frozen",
            "destination_region_or_return_section": "not yet frozen",
            "body_frame_transform_dataset": "required control/frame or equivalent causal dataset",
            "source_mass_denominator": "all initial fluid particles; no survivor renormalization",
            "return_and_residence_observer": "isolated read-only observer implemented and tested; no trajectory evidence or Core admission",
            "unknown_exit_bound": "required for closed lifecycle; no evidence yet",
        },
        "root_review_blockers": [
            "The F7 geometry adapter is now wired through a read-only Core CFD adapter boundary, but its Core pose/gradient velocity is a bounded sample approximation, not runtime evidence or a Definition/trajectory producer.",
            "The adapter's analytic finish clamp is source-faithful, but Core sampled gradient velocity is not certified exact at the finish boundary.",
            "The isolated F7 observer has no solver trajectory or provenance-verified torque runtime evidence; the new causal sidecar is interface-only and cannot certify runtime motion.",
            "No generated Definition, XML, BI4, trajectory, or solver evidence exists.",
            "The official CPU/GPU wrappers contain destructive cleanup and execution commands and are reference-only.",
            "The physical distinction must survive adversarial review with a finite torque/control gate against generic moving-boundary and F6 overlap.",
        ],
        "source_bindings": sources,
        "isolated_implementation": {
            "status": "implemented_read_only_not_admitted",
            "bindings": isolated,
            "geometry_adapter": {
                "official_fixed_encoding": "BINARY POLYDATA",
                "official_moving_encoding": "ASCII POLYDATA",
                "returns_core_prescribed_geometry_in_memory": True,
                "xml_motion_schedule_hash_bound": True,
                "analytic_xml_finish_boundary_enforced": True,
                "core_finish_velocity_exact": False,
                "source_directory_binding_strict": True,
                "official_source_allowlist_hash_bound": True,
                "analytic_motion_evaluators_present": True,
                "core_pose_and_gradient_velocity_are_sampled_approximations": True,
                "default_linear_angle_interpolation_error_bound_deg": 0.00625,
                "degenerate_source_triangles_explicitly_counted_and_dropped": True,
                "core_adapter_wired": True,
            },
                "material_observer": {
                    "all_initial_fluid_denominator": True,
                    "survivor_renormalization": False,
                    "body_frame_and_angular_control_hash_bound": True,
                    "frame_control_semantics_and_trajectory_time_bound": True,
                    "cross_frame_identity_history_required": True,
                    "region_contract_hash_bound": True,
                    "event_window_applied_to_events": True,
                    "linear_segment_crossing_detection": True,
                    "unknown_exit_accounted": True,
                "return_and_residence_classification": True,
                "residence_is_terminal_mass_category": False,
                "finite_torque_independence_contract_gate": True,
                "physical_independence_claim": False,
                "trajectory_evidence_present": False,
                "core_observer_wired": False,
            },
        },
        "current_core_snapshot": {
            "completion": binding("campaigns/core-v1/completion.json", "read-only current Core gate"),
            "registry": binding("campaigns/core-v1/registry.json", "read-only current Core registry"),
            "can_finalize": completion["can_finalize"],
            "t1_families": completion["t1_families"],
            "missing_t1_case_runs": completion["missing_t1_case_runs"],
            "missing_material_case_runs": completion["missing_material_case_runs"],
        },
        "official_source_observation": parsed,
        "execution_controls": {
            "read_only_source_audit": True,
            "definition_writer_invoked": False,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "t1_denominator_mutation": 0,
            "t2_denominator_mutation": 0,
            "qualification_credit": 0,
        },
    }


def build_source_audit(candidate: dict[str, Any]) -> dict[str, Any]:
    cpu = local(PUMP_CPU).read_text(encoding="utf-8")
    gpu = local(PUMP_GPU).read_text(encoding="utf-8")
    return {
        "schema": "core.f7.pump_recirculation.source_audit.v1",
        "status": "official_source_and_isolated_contract_bound_read_only",
        "candidate_id": candidate["candidate_id"],
        "candidate_card": binding(str(CANDIDATE.relative_to(LAB)), "F7 candidate card"),
        "official_source_bindings": candidate["source_bindings"],
        "isolated_implementation_bindings": candidate["isolated_implementation"]["bindings"],
        "vtk_headers": {
            "pump_fixed": parse_vtk_header(PUMP_FIXED),
            "pump_moving": parse_vtk_header(PUMP_MOVING),
        },
        "wrapper_static_audit": {
            "cpu_contains_recursive_cleanup": "rm -r" in cpu,
            "cpu_contains_gencase": "gencase" in cpu,
            "cpu_contains_cpu_solver": "dualsphysicscpu" in cpu,
            "gpu_contains_gpu_solver": "dualsphysicsgpu" in gpu,
            "wrapper_invoked": False,
            "interpretation": "reference wrappers are not an execution authorization",
        },
        "lineage": {
            "official_example_is_source_reference_only": True,
            "f1_f6_trajectory_reused": False,
            "qualification_inherited": False,
            "same_input_retry": False,
        },
        "protected_state_mutation": {
            "registry": 0,
            "ledger": 0,
            "matrix": 0,
            "denominator": 0,
            "queue": 0,
            "solver_invoked": False,
            "gpu_started": False,
        },
    }


def build_interface_review(candidate: dict[str, Any]) -> dict[str, Any]:
    dataset_source = local("scripts/core_cfd_dataset.py").read_text(encoding="utf-8")
    transport_source = local("scripts/transport_metrics.py").read_text(encoding="utf-8")
    physics_source = local("scripts/core_physics.py").read_text(encoding="utf-8")
    supported_family_match = re.search(r"family not in \{([^}]+)\}", dataset_source)
    supported_families = [] if supported_family_match is None else re.findall(
        r"\"([A-Z0-9]+)\"", supported_family_match.group(1)
    )
    return {
        "schema": "core.f7.pump_recirculation.interface_review.v1",
        "status": "blocked_after_core_adapter_before_runtime_admission",
        "candidate_id": candidate["candidate_id"],
        "implementation_bindings": [
            binding("scripts/core_cfd_dataset.py", "current CFD-to-Core adapter"),
            binding("scripts/transport_metrics.py", "current mass transport observer"),
            binding("scripts/core_physics.py", "current finite moving-wall physics observer"),
            *candidate["isolated_implementation"]["bindings"],
        ],
        "static_findings": {
            "current_cfd_adapter_supported_families": supported_families,
            "f7_family_is_currently_supported": "F7" in supported_families,
            "f7_core_adapter_wired": "_f7_pump_geometry_from_config" in dataset_source and "family=F7" in dataset_source,
            "f2_specific_geometry_branch_present": "_f2_geometry_from_config" in dataset_source,
            "drawfilevtk_pump_reader_present": "drawfilevtk" in dataset_source,
            "moving_wall_saved_chord_operator_present": "def moving_wall_crossings" in physics_source,
            "moving_affine_material_frame_present": "moving_affine" in transport_source,
            "f7_transform_dataset_producer_present": "control/frame" in dataset_source,
            "f7_causal_sidecar_producer_present": local(CAUSAL_SIDECAR_SCRIPT).is_file(),
            "f7_return_observer_present": "recirculation" in transport_source.lower(),
            "isolated_f7_geometry_adapter_present": True,
            "isolated_f7_material_observer_present": True,
            "isolated_f7_return_observer_present": True,
        },
        "what_can_be_reused_after_root_admission": [
            "the Pump POLYDATA parser and XML motion contract already exposed through the read-only Core adapter, after generated-input and runtime binding",
            "the isolated closed-lifecycle source-mass denominator, no-survivor-renormalization policy, and conservative unknown-exit handling, after trajectory review",
            "finite moving-wall saved-chord operators only after F7 geometry snapshots and public motion schedule are adapted",
        ],
        "blocking_gaps": [
            "Resolve or explicitly certify the Core sampled pose/gradient-velocity behavior at start and finish knots before runtime use.",
            "The F7 causal sidecar producer is interface-only: no solver trajectory producer currently certifies that runtime motion followed the schedule.",
            "Emit a causal body-pose/frame and angular-control dataset hash-bound to every trajectory.",
            "Freeze source, discharge/return, residence, and unknown-exit regions before material data.",
            "Produce real trajectory evidence and a hash/semantic/time-bound nonzero torque dataset, then verify its producer/geometry provenance and energy consistency; the isolated observer intentionally cannot claim independence without root provenance review.",
            "Have root review decide whether pump torque/recirculation is physically independent enough from F6.",
        ],
        "authorization": {
            "adapter_write": False,
            "definition_writer": False,
            "cpu_gencase": False,
            "native_decode": False,
            "solver": False,
            "gpu": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_credit": 0,
        },
    }


def render_report(candidate: dict[str, Any], source: dict[str, Any], interface: dict[str, Any]) -> str:
    parsed = candidate["official_source_observation"]
    return "\n".join([
        "# F7 预设旋转内泵循环路线根审查材料（2026-09-22）",
        "",
        "本文件记录官方 DualSPHysics `main/13_Pump` 的只读源绑定、隔离适配器/观测器合约和候选判断；没有生成 Definition、BI4、trajectory，没有运行 GenCase/native solver/GPU/queue，也没有修改 Core registry、ledger、matrix 或 denominator。",
        "",
        "## 候选结论",
        "",
        "官方 Pump 例子可提出一个物理上有区别的 F7：封闭单相流体由预设旋转内部泵体输入角动量，研究循环、回流和驻留，而不是 F1 的溃坝绕流、F2 的源到接收器转移、F3 的冲量/挡板交换、F4 的落体碰撞、F5 的活塞爬坡或 F6 的自由刚体耦合。当前结论是 **root-review-only、未准入、零 credit**。",
        "",
        f"- 官方 Definition SHA-256：`{next(item['sha256'] for item in candidate['source_bindings'] if item['path'] == PUMP_XML)}`。",
        f"- 几何为 fixed `mk=0` + moving pump `mk=2`，fluid `mk=1`，运动对象 `ref=2`；官方轴长约 `{parsed['rotation_axis_length_m']:.6f} m`。",
        f"- 官方运动是两段旋转：前段 `{parsed['rotation_schedule'][0]['duration_s']} s`、角加速度 `{parsed['rotation_schedule'][0]['acceleration_deg_s2']} deg/s²`、初速 `{parsed['rotation_schedule'][0]['initial_velocity_deg_s']} deg/s`；后段角加速度为 0 并保持转速，官方示例时域 `{parsed['time_max_s']} s`。",
        "- 新候选拟把唯一研究轴冻结为预设角加速度 `250--750 deg/s²`，15 行仍是 13 个空间格 + 2 个时间/输出对照；15/15 未物化、0 执行、0 credit。",
        "- 两个对照已明确为真实控制变化：`internal_time` 的 CFL `0.20→0.10`（须检查实际 dt/步数分离），`native_output` 的 `TimeOut 0.02→0.01 s`（须检查实际帧数/间隔分离）。",
        "",
        "## 隔离合约与必须保持的阻塞",
        "",
        "1. 已实现隔离的只读 F7 geometry adapter：解析 allowlisted 官方 binary fixed / ASCII moving POLYDATA、XML mk 标签和两段旋转，并在内存中返回 Core `PrescribedGeometry`；源三角形退化项被显式计数并过滤，不能把这个清理结果当成物理证据。XML 解析器还校验 degree 单位、1→2 链和 finish 截止；Core pose/gradient velocity 仍是有误差界的采样近似，不能称为 exact runtime motion。",
        "2. 已实现隔离的只读 F7 material observer：固定 all-initial-fluid 分母、不做 survivor renormalization、校验 body-frame/angular-control/region hash、报告 unknown exit，并把 residence 作为事件指标而非终态质量桶；显式 torque contract 仍只形成待根审查的合约，不宣称物理独立性。",
        "3. F7 geometry 已通过只读 public Core CFD adapter 接入，但尚未接入 Definition writer 或 trajectory producer；没有与 trajectory 绑定的真实 `control/frame` 和 torque 产物，因此不能开始材料 T2。",
        "4. root-review contract v2 已绑定 F1/F2、F5、F6 的路线关闭收据和官方 Pump 源哈希；它只增加静态完整性证据，不改变阻塞或授权。",
        "5. 官方 CPU/GPU wrapper 含清理和求解命令，只能作为哈希绑定的参考，绝不是执行授权。",
        "6. 对抗性 root review 必须确认“泵驱动循环”不是把普通 moving-wall 或 F6 运动换名；若不能观测扭矩输入和回流，候选应关闭。",
        "",
        "## 状态与授权",
        "",
        f"当前 Core 仍为 `t1_families={candidate['current_core_snapshot']['t1_families']}`、`missing_t1_case_runs={candidate['current_core_snapshot']['missing_t1_case_runs']}`、`missing_material_case_runs={candidate['current_core_snapshot']['missing_material_case_runs']}`。",
        "",
        "本包只授权后续人工/root review 讨论：不授权 Definition writer、不授权 CPU/native preflight、不授权 solver/GPU/queue，不产生 T1/T2 分母或资格变化。接口审查状态为 `blocked_after_core_adapter_before_runtime_admission`。",
        "",
        "机器可读文件：",
        "- `campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/candidate-card-v1.json`",
        "- `campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/source-audit-v1.json`",
        "- `campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/interface-review-v1.json`",
        "- `campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/root-review-receipt-v1.json`",
        "",
        "定向回归：`pytest -q tests/test_f7_pump_recirculation_root_review_v1.py tests/test_f7_pump_geometry_adapter_v1.py tests/test_f7_pump_transport_observer_v1.py`。",
        "",
    ])


def build_root_receipt(candidate: dict[str, Any], source: dict[str, Any], interface: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "core.f7.pump_recirculation.root_review_receipt.v1",
        "status": "root_review_only_blocked",
        "decision": "retain_candidate_for_future_root_review_without_materialization",
        "candidate_id": candidate["candidate_id"],
        "physical_novelty_plausible": True,
        "interface_ready": False,
        "admission_granted": False,
        "definition_authorized": False,
        "preflight_authorized": False,
        "solver_authorized": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "protected_state_mutation": source["protected_state_mutation"],
        "authorization": interface["authorization"],
        "artifact_bindings": [
            binding(str(CANDIDATE.relative_to(LAB)), "candidate card"),
            binding(str(SOURCE_AUDIT.relative_to(LAB)), "source audit"),
            binding(str(INTERFACE_REVIEW.relative_to(LAB)), "interface review"),
            binding(str(REPORT.relative_to(LAB)), "human-readable report"),
            binding("scripts/f7_pump_recirculation_root_review_v1.py", "read-only implementation"),
            binding(str(TEST.relative_to(LAB)), "targeted regression test"),
            *candidate["isolated_implementation"]["bindings"],
        ],
        "forbidden_materialization": [
            "no Definition XML in the F7 namespace",
            "no generated XML/BI4/trajectory/HDF5 in the F7 namespace",
            "no registry/ledger/matrix/completion edit",
            "no GenCase/native solver/GPU/queue action",
        ],
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_outputs() -> dict[str, Any]:
    candidate = build_candidate()
    write_json(CANDIDATE, candidate)
    source = build_source_audit(candidate)
    write_json(SOURCE_AUDIT, source)
    interface = build_interface_review(candidate)
    write_json(INTERFACE_REVIEW, interface)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render_report(candidate, source, interface), encoding="utf-8")
    receipt = build_root_receipt(candidate, source, interface)
    write_json(ROOT_RECEIPT, receipt)
    return receipt


def _verify_binding(item: dict[str, Any]) -> None:
    path = local(item["path"])
    if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
        raise AssertionError(f"stale binding: {item['path']}")


def verify() -> dict[str, Any]:
    candidate = load(CANDIDATE)
    source = load(SOURCE_AUDIT)
    interface = load(INTERFACE_REVIEW)
    receipt = load(ROOT_RECEIPT)
    assert candidate["schema"] == "core.f7.pump_recirculation.candidate_card.v1"
    assert candidate["status"] == "root_review_only_not_admitted"
    assert candidate["qualification_claim"] == "none"
    assert candidate["matrix_credit"] == 0
    assert candidate["planned_matrix"]["proposed_rows"] == 15
    assert candidate["planned_matrix"]["executed"] == 0
    assert candidate["planned_matrix"]["unattempted"] == 15
    assert candidate["execution_controls"]["qualification_credit"] == 0
    for key in ("definition_writer_invoked", "gencase_invoked", "native_decoder_invoked", "solver_invoked", "gpu_started"):
        assert candidate["execution_controls"][key] is False
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "t1_denominator_mutation", "t2_denominator_mutation"):
        assert candidate["execution_controls"][key] == 0
    for item in candidate["source_bindings"]:
        _verify_binding(item)
    _verify_binding(candidate["current_core_snapshot"]["completion"])
    _verify_binding(candidate["current_core_snapshot"]["registry"])
    assert candidate["current_core_snapshot"]["can_finalize"] is False
    assert candidate["current_core_snapshot"]["t1_families"] == ["F3", "F4"]

    assert source["schema"] == "core.f7.pump_recirculation.source_audit.v1"
    assert source["status"] == "official_source_and_isolated_contract_bound_read_only"
    _verify_binding(source["candidate_card"])
    for item in source["official_source_bindings"]:
        _verify_binding(item)
    for item in source["isolated_implementation_bindings"]:
        _verify_binding(item)
    assert candidate["isolated_implementation"]["status"] == "implemented_read_only_not_admitted"
    assert candidate["isolated_implementation"]["geometry_adapter"]["core_adapter_wired"] is True
    assert candidate["isolated_implementation"]["material_observer"]["core_observer_wired"] is False
    assert candidate["isolated_implementation"]["material_observer"]["trajectory_evidence_present"] is False
    assert source["wrapper_static_audit"]["wrapper_invoked"] is False
    assert source["protected_state_mutation"]["registry"] == 0
    assert source["protected_state_mutation"]["solver_invoked"] is False
    assert source["vtk_headers"]["pump_fixed"]["points"] > source["vtk_headers"]["pump_moving"]["points"]

    assert interface["schema"] == "core.f7.pump_recirculation.interface_review.v1"
    assert interface["status"] == "blocked_after_core_adapter_before_runtime_admission"
    assert interface["static_findings"]["f7_family_is_currently_supported"] is True
    assert interface["static_findings"]["f7_core_adapter_wired"] is True
    assert interface["static_findings"]["drawfilevtk_pump_reader_present"] is False
    assert interface["static_findings"]["isolated_f7_geometry_adapter_present"] is True
    assert interface["static_findings"]["isolated_f7_material_observer_present"] is True
    assert interface["static_findings"]["isolated_f7_return_observer_present"] is True
    assert interface["authorization"]["definition_writer"] is False
    assert interface["authorization"]["solver"] is False
    for item in interface["implementation_bindings"]:
        _verify_binding(item)

    assert receipt["schema"] == "core.f7.pump_recirculation.root_review_receipt.v1"
    assert receipt["status"] == "root_review_only_blocked"
    assert receipt["admission_granted"] is False
    assert receipt["qualification_credit"] == 0
    for item in receipt["artifact_bindings"]:
        _verify_binding(item)
    forbidden = [
        *NAMESPACE.glob("*.xml"),
        *NAMESPACE.glob("*.bi4"),
        *NAMESPACE.glob("*.vtk"),
        *NAMESPACE.glob("*.h5"),
    ]
    assert forbidden == [], f"unexpected materialized F7 products: {forbidden}"
    return {
        "status": receipt["status"],
        "candidate_id": receipt["candidate_id"],
        "physical_novelty_plausible": receipt["physical_novelty_plausible"],
        "interface_ready": receipt["interface_ready"],
        "qualification_credit": receipt["qualification_credit"],
        "protected_state_mutation": receipt["protected_state_mutation"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("write", "verify"),
        nargs="?",
        default="verify",
        help="verify is the safe default; use write only to regenerate the isolated package",
    )
    args = parser.parse_args()
    if args.command == "write":
        result = write_outputs()
        print(json.dumps({"written": str(ROOT_RECEIPT), "status": result["status"]}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(verify(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
