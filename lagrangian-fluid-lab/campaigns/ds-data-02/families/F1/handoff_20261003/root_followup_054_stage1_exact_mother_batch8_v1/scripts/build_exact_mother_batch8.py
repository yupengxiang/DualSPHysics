#!/usr/bin/env python3
"""Build the source-only F1 Stage 1 exact-mother batch-8 plan.

This module writes request plans and provenance metadata only.  It does not
read source arrays, edit an XML source, invoke GenCase, run DualSPHysics,
decode BI4, convert data, or render ParaView output.  The only planned source
mutation is the z-size of the existing fluid cell-centre ``drawbox``; Root
must materialize and hash that definition before any launch is considered.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCOPE_NAME = "root_followup_054_stage1_exact_mother_batch8_v1"
SCOPE = Path(__file__).resolve().parents[1]
REQUESTS = SCOPE / "requests"

INTEGRATION_ROOT = "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics"
INTEGRATION_LAB = f"{INTEGRATION_ROOT}/lagrangian-fluid-lab"
GENCASE_BINARY = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
INTEGRATION_PYTHON = f"{INTEGRATION_LAB}/.venv/bin/python"
GENCASE_WRAPPER = f"{INTEGRATION_LAB}/campaigns/ds-data-02/handoff_20261003/root_native_source_preflight_tools_001/gencase.py"
RUNTIME_SCRIPT = f"{INTEGRATION_LAB}/scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH = f"{INTEGRATION_LAB}/scripts/ds_data02_strict_dispatch_v1.py"

HASHES = {
    "official_gencase": "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226",
    "integration_python": "a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae",
    "gencase_wrapper": "2be2f604ef130c6f02c0b7c0bf3c9b5da39e354eff9457dccc471bf651d4d3e6",
    "runtime_script": "5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60",
    "strict_dispatch": "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec",
}

COMMON_EOS = {
    "gravity": [0, 0, -9.81],
    "rhop0": 1000,
    "rhopgradient": 2,
    "hswl": {"value": 0, "auto": True},
    "gamma": 7,
    "speedsystem": {"value": 0, "auto": True},
    "coefsound": 20,
    "speedsound": {"value": 0, "auto": True},
    "coefh": 1.0,
    "cflnumber": 0.2,
}

COMMON_STEP_FLAGS = {
    "Boundary": "1",
    "SavePosDouble": "1",
    "StepAlgorithm": "1",
    "VerletSteps": "40",
    "Kernel": "1",
    "ViscoTreatment": "1",
    "Visco": "0.1",
    "ViscoBoundFactor": "1",
    "DensityDT": "2",
    "DensityDTvalue": "0.1",
    "Shifting": "0",
    "RigidAlgorithm": "1",
    "FtPause": "0",
    "CoefDtMin": "0.05",
    "DtIni": "0",
    "DtMin": "0",
    "DtFixed": "0",
    "DtAllParticles": "0",
    "TimeOut": "0.01",
    "MinFluidStop": "0",
    "RhopOutMin": "700",
    "RhopOutMax": "1300",
}

TEMPLATES = {
    "eccentric_obstacle": {
        "contract_id": "F1_ECC_COARSE_TEMPLATE_027",
        "mechanism_label": "ECC",
        "dp_m": 0.01,
        "anchor_height_m": 0.15,
        "time_max_s": 1.6,
        "time_out_s": 0.01,
        "tank": {"low_m": [0, 0, 0], "size_m": [1.6, 0.67, 0.4]},
        "obstacle_or_divider": {"low_m": [0.9, 0.24, 0], "size_m": [0.12, 0.12, 0.45]},
        "fluid_footprint_m": [0.4, 0.67],
        "fluid_low_m": [0, 0, 0],
        "fluid_point_m": [0.005, 0.005, 0.005],
        "fluid_size_anchor_m": [0.39, 0.66, 0.14],
        "fluid_drawbox_comment": "v1 fallback controlled fluid cell centres",
        "source_geometry_definition": {
            "pointref_m": [0.005, 0.005, 0.005],
            "pointmin_m": [-0.025, -0.025, -0.025],
            "pointmax_m": [2.0, 1.0, 1.0],
            "setdrawmode": "full",
        },
        "source_definition": f"{INTEGRATION_LAB}/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_bounded_fallback_three_dp_gencase_027/selected_definitions/F1_FALLBACK_ECC_COARSE_Def.xml",
        "source_definition_sha256": "2b86359cff38e9eea2c0c2d09e84e3647ea25d74e6783105b293e0622a8ec157",
        "source_binding": f"{INTEGRATION_LAB}/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_bounded_fallback_three_dp_gencase_027/ecc_coarse/binding.json",
        "source_binding_sha256": "9e4ed27a71fd6f385fff7dc37ce73aba5bebd0b47fb6877b31ac03c77744effe",
        "source_preparation_request": f"{INTEGRATION_LAB}/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_bounded_fallback_three_dp_gencase_027/ecc_coarse/request.json",
        "source_preparation_request_sha256": "9de164e3e7c7517dd6269a09db0870ade91face5042bc4b82b5f047081d22123",
        "canonical_owner": f"{INTEGRATION_LAB}/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/ecc_coarse/owner.json",
        "canonical_owner_sha256": "7a901cb5c91525529ea87680aabdff0f0b2496fd0db88bacc206004b88520472",
        "canonical_typed_request": f"{INTEGRATION_LAB}/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/ecc_coarse/request.json",
        "canonical_typed_request_sha256": "3182729deea69622e8bf5ec0b5e34bd0e80d9fa2b891366ed47415aa9f027559",
        "canonical_physical_binding": f"{INTEGRATION_LAB}/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/ecc-physical-binding.json",
        "canonical_physical_binding_sha256": "8fd95d61d4bd65546b44767ead3e930c7c45e20a1690f6a1237c5272970c594f",
        "physical_condition_sha256": "687c069f836dd81b3c4c85ea6f977f9f2775debea01d3657b81356801ced71d3",
        "native_weight_float32_kg": 0.0010000000474974513,
        "native_weight_reference": "027 binding prediction only; new BI4/native inventory is absent",
        "source_step_time_max_key": "TimeMax",
    },
    "asymmetric_dual_channel": {
        "contract_id": "F1_DUAL_COARSE_TEMPLATE_027",
        "mechanism_label": "DUAL",
        "dp_m": 0.02,
        "anchor_height_m": 0.30,
        "time_max_s": 4.0,
        "time_out_s": 0.01,
        "tank": {"low_m": [0, 0, 0], "size_m": [3.2, 1.0, 0.8]},
        "obstacle_or_divider": {"low_m": [1.2, 0.34, 0], "size_m": [0.8, 0.06, 0.7]},
        "fluid_footprint_m": [1.0, 1.0],
        "fluid_low_m": [2.2, 0, 0],
        "fluid_point_m": [2.21, 0.01, 0.01],
        "fluid_size_anchor_m": [0.98, 0.98, 0.28],
        "fluid_drawbox_comment": "v1 fallback controlled fluid cell centres",
        "source_geometry_definition": {
            "pointref_m": [0.01, 0.01, 0.01],
            "pointmin_m": [-0.05, -0.05, -0.05],
            "pointmax_m": [4.0, 2.0, 2.0],
            "setdrawmode": "full",
        },
        "source_definition": f"{INTEGRATION_LAB}/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_bounded_fallback_three_dp_gencase_027/selected_definitions/F1_FALLBACK_DUAL_COARSE_Def.xml",
        "source_definition_sha256": "b16c9a83a3d711fcc11939ca5418d62fbc1ae0fa4e6fe13f48613177cbe9914e",
        "source_binding": f"{INTEGRATION_LAB}/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_bounded_fallback_three_dp_gencase_027/dual_coarse/binding.json",
        "source_binding_sha256": "c3f24622865ac17cb10d9196d704060827b6406c01b27b74d004d1debe6ed70a",
        "source_preparation_request": f"{INTEGRATION_LAB}/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_bounded_fallback_three_dp_gencase_027/dual_coarse/request.json",
        "source_preparation_request_sha256": "0af46553f9b3a2feb6f1cb5a1307d441431f4e568b41c364da64863296cfbad3",
        "canonical_owner": f"{INTEGRATION_LAB}/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/dual_coarse/owner.json",
        "canonical_owner_sha256": "c6ef0fa65136464c2f6315022f35792fa50b21d2349b0077b92802ed6f220045",
        "canonical_typed_request": f"{INTEGRATION_LAB}/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/dual_coarse/request.json",
        "canonical_typed_request_sha256": "e286b28168a0b373fa1bbdfa418c5df1bfb1bfc3c2d9d581e8f95f898c6c3e68",
        "canonical_physical_binding": f"{INTEGRATION_LAB}/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/dual-physical-binding.json",
        "canonical_physical_binding_sha256": "fb7f4ca8b704b41bdcb68cf925040c38a4ba7323d8b716e9c4fbcb62d6e771ff",
        "physical_condition_sha256": "feb710be76c89fb67074b1bbbf6c9c22869652ce5760c4d7e4721187b4d580bf",
        "native_weight_float32_kg": 0.00800000037997961,
        "native_weight_reference": "027 binding prediction only; new BI4/native inventory is absent",
        "source_step_time_max_key": "TimeMax",
    },
}

HEIGHTS = {
    "eccentric_obstacle": (0.11, 0.13, 0.15, 0.19),
    "asymmetric_dual_channel": (0.22, 0.26, 0.30, 0.34),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_contracts() -> dict[str, Any]:
    contracts: dict[str, Any] = {}
    for mechanism, template in TEMPLATES.items():
        step_flags = dict(COMMON_STEP_FLAGS)
        step_flags[template["source_step_time_max_key"]] = str(template["time_max_s"])
        contracts[template["contract_id"]] = {
            "schema": "ds02.f1.exact-mother-source-contract.v1",
            "mechanism_id": mechanism,
            "resolution_label": "coarse",
            "single_resolution": True,
            "dp_m": template["dp_m"],
            "anchor_height_m": template["anchor_height_m"],
            "source_definition": {
                "path": template["source_definition"],
                "sha256": template["source_definition_sha256"],
                "status": "immutable_integration_source",
            },
            "known_working_preparation_027": {
                "binding_path": template["source_binding"],
                "binding_sha256": template["source_binding_sha256"],
                "request_path": template["source_preparation_request"],
                "request_sha256": template["source_preparation_request_sha256"],
                "wrapper_path": GENCASE_WRAPPER,
                "wrapper_sha256": HASHES["gencase_wrapper"],
                "wrapper_reuse_policy": "provenance_only_until_a_height_specific_binding_is_materialized",
            },
            "canonical_binding_034": {
                "owner_path": template["canonical_owner"],
                "owner_sha256": template["canonical_owner_sha256"],
                "typed_request_path": template["canonical_typed_request"],
                "typed_request_sha256": template["canonical_typed_request_sha256"],
                "physical_binding_path": template["canonical_physical_binding"],
                "physical_binding_sha256": template["canonical_physical_binding_sha256"],
                "physical_condition_sha256": template["physical_condition_sha256"],
            },
            "physical_geometry_invariants": {
                "tank": template["tank"],
                "obstacle_or_divider": template["obstacle_or_divider"],
                "fluid_low_m": template["fluid_low_m"],
                "fluid_footprint_m": template["fluid_footprint_m"],
                "fluid_mk": 0,
                "fluid_velocity_m_per_s": [0, 0, 0],
            },
            "source_geometry_definition_invariants": template["source_geometry_definition"],
            "fluid_drawbox_source_contract": {
                "comment": template["fluid_drawbox_comment"],
                "point_m": template["fluid_point_m"],
                "anchor_size_m": template["fluid_size_anchor_m"],
                "mutation_selector": f"geometry.commands.mainlist.drawbox[@cmt='{template['fluid_drawbox_comment']}']/size/@z",
                "mutation_rule": "set size.z to target_height_m - dp_m; retain point, x/y size, comment, ordering, and every other source byte",
                "materialized_source_sha256": None,
            },
            "eos_constants": COMMON_EOS,
            "native_execution_step_flags": step_flags,
            "source_literals": {
                "setshapemode": "dp | actual | bound",
                "setshapemode_policy": "retain this existing source literal byte-for-byte; do not classify or rewrite it in this plan",
                "boundary_support_layer_count_claim": None,
                "boundary_policy": "bind exact source bytes; do not translate the support geometry into a layer-count claim",
            },
            "time_window": {
                "time_max_s": template["time_max_s"],
                "time_out_s": template["time_out_s"],
                "expected_frames_if_run": int(round(template["time_max_s"] / template["time_out_s"])) + 1,
            },
            "native_mass_policy": "native_massfluid_no_rescaling",
        }
    return contracts


def make_row(row_index: int, mechanism: str, height_m: float) -> dict[str, Any]:
    template = TEMPLATES[mechanism]
    dp = template["dp_m"]
    height_steps = int(round(height_m / dp))
    if abs(height_steps * dp - height_m) > 1e-12:
        raise ValueError(f"height is not commensurate with dp: {mechanism} {height_m}")

    nx = int(round(template["fluid_footprint_m"][0] / dp))
    ny = int(round(template["fluid_footprint_m"][1] / dp))
    nz = height_steps
    volume = template["fluid_footprint_m"][0] * template["fluid_footprint_m"][1] * height_m
    mass = volume * COMMON_EOS["rhop0"]
    tag = f"{height_m:.2f}".replace(".", "")
    case_id = f"F1_MOTHER_{template['mechanism_label']}_H{tag}_DP{int(round(dp * 1000)):03d}"
    physical_case_id = f"F1_{template['mechanism_label']}_EXACT_MOTHER_H{tag}"
    anchor = abs(height_m - template["anchor_height_m"]) < 1e-12
    target_size_z = round((height_steps - 1) * dp, 12)
    row: dict[str, Any] = {
        "row_index": row_index,
        "case_id": case_id,
        "physical_case_id": physical_case_id,
        "mechanism_id": mechanism,
        "mechanism_label": template["mechanism_label"],
        "source_contract_id": template["contract_id"],
        "resolution": {
            "label": "coarse",
            "dp_m": dp,
            "single_resolution": True,
            "resolution_views_per_recipe": 1,
        },
        "initial_fluid_height_m": height_m,
        "head_step_m": dp,
        "anchor_reference": {
            "is_existing_anchor_height": anchor,
            "anchor_height_m": template["anchor_height_m"],
            "canonical_physical_condition_sha256": template["physical_condition_sha256"],
            "existing_anchor_artifacts_reused_by_this_scope": False,
        },
        "planned_source_mutation": {
            "kind": "single_parameter_source_mutation",
            "target": "fluid_drawbox.size.z",
            "selector": f"geometry.commands.mainlist.drawbox[@cmt='{template['fluid_drawbox_comment']}']/size/@z",
            "source_anchor_value_m": template["fluid_size_anchor_m"][2],
            "target_value_m": target_size_z,
            "target_height_m": height_m,
            "changed_from_anchor": not anchor,
            "materialized_definition_sha256": None,
            "materialization_status": "not_materialized",
            "all_other_source_bytes": "must remain byte-identical outside the selected size.z attribute",
        },
        "predicted_initial_state": {
            "grid_cells_xyz": [nx, ny, nz],
            "predicted_fluid_particles": nx * ny * nz,
            "theoretical_fluid_volume_m3": round(volume, 12),
            "theoretical_fluid_mass_kg": round(mass, 12),
            "native_weight_float32_kg": template["native_weight_float32_kg"],
            "status": "prediction_only_until_new_gencase_and_initial_qa",
        },
        "execution_contract": {
            "launch_allowed": False,
            "launch_owner": "root",
            "dispatch_status": "planned_source_only",
            "production_approval": "none",
            "independent_case_count_increment": 0,
            "visual_review_status": "not_reviewed_by_this_scope",
            "user_visual_approval_recorded": False,
            "numerical_precision_status": "not_accepted",
            "bi4_equality_claim": False,
        },
        "required_gates": {
            "new_gencase_required_before_artifact_claim": True,
            "new_initial_qa_required_before_artifact_claim": True,
            "solver_allowed_by_this_scope": False,
            "conversion_allowed_by_this_scope": False,
            "array_processing_allowed_by_this_scope": False,
            "paraview_render_allowed_by_this_scope": False,
        },
        "request_files": {
            "gencase": f"requests/{case_id}_gencase_request.json",
            "initial_qa": f"requests/{case_id}_initial_qa_request.json",
        },
        "actual_artifacts": None,
    }
    row["recipe_sha256"] = sha256_json(row)
    return row


def make_plan() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    row_index = 1
    for mechanism in ("eccentric_obstacle", "asymmetric_dual_channel"):
        for height_m in HEIGHTS[mechanism]:
            rows.append(make_row(row_index, mechanism, height_m))
            row_index += 1

    return {
        "schema": "ds02.f1.exact-mother-batch8-plan.v1",
        "family_id": "F1",
        "scope_name": SCOPE_NAME,
        "status": "planned_source_only",
        "source_only": True,
        "execution_performed": False,
        "launch_allowed": False,
        "launch_owner": "root",
        "rows": rows,
        "resolution_policy": "one coarse DP per recipe: ECC dp=0.01 m and DUAL dp=0.02 m",
        "height_policy": "initial fluid height is the only intended recipe variable; every height is an integer multiple of its DP",
        "invariant_policy": "current 027 source geometry, EOS constants, source literals, and native execution step flags remain bound by source hash",
        "counting_policy": {
            "planned_rows": 8,
            "physical_case_count_claimed_now": 0,
            "independent_case_count_increment_in_each_request": 0,
            "anchor_rows": "H=.15 ECC and H=.30 DUAL reference existing canonical conditions; this scope does not duplicate their count",
            "future_counting": "Root reconciles one physical case per newly accepted row only after actual GenCase and initial QA",
        },
        "quality_gates": {
            "gencase": "new height-specific generated XML/BI4 is required; 027 output is provenance only",
            "initial_qa": "new height-specific initial QA is required for counts, finite coordinates, partition, and mass bookkeeping",
            "visual_review": "pending Root full-animation inspection; no user approval is recorded here",
            "q_n": "not accepted; historical negative precision evidence remains retained",
            "q_e": "not a Stage 1 prerequisite",
        },
        "historical_negatives": [
            {
                "mechanism_id": "eccentric_obstacle",
                "head_m": 0.30,
                "status": "historical_failed_mother_retained",
                "source_record": "root_followup_049_visual_stage1_batch_v1/SOURCE_AUDIT_027_035_AND_CANONICAL_034.md",
                "revalidated_by_this_scope": False,
            },
            {
                "mechanism_id": "asymmetric_dual_channel",
                "head_m": 0.55,
                "status": "historical_failed_mother_retained",
                "source_record": "root_followup_049_visual_stage1_batch_v1/SOURCE_AUDIT_027_035_AND_CANONICAL_034.md",
                "revalidated_by_this_scope": False,
            },
        ],
        "claim_boundary": {
            "zero_loss_or_eliminated_overtopping_proven": False,
            "geometry_or_solver_numeric_change_claim": False,
            "setshapemode_rewrite_or_invalidity_claim": False,
            "two_dp_to_four_layer_translation_claim": False,
            "new_height_generation_claim": False,
            "bi4_equality_claim": False,
        },
    }


def make_source_contract_document() -> dict[str, Any]:
    return {
        "schema": "ds02.f1.exact-mother-source-contracts.v1",
        "family_id": "F1",
        "scope_name": SCOPE_NAME,
        "contracts": source_contracts(),
        "toolchain_provenance": {
            "official_gencase": {"path": GENCASE_BINARY, "sha256": HASHES["official_gencase"]},
            "integration_python": {"path": INTEGRATION_PYTHON, "sha256": HASHES["integration_python"]},
            "gencase_wrapper_027": {"path": GENCASE_WRAPPER, "sha256": HASHES["gencase_wrapper"]},
            "runtime_v2": {"path": RUNTIME_SCRIPT, "sha256": HASHES["runtime_script"]},
            "strict_dispatch_v1": {"path": STRICT_DISPATCH, "sha256": HASHES["strict_dispatch"]},
        },
        "tool_use_policy": {
            "this_scope_invoked_gencase": False,
            "this_scope_invoked_solver": False,
            "this_scope_invoked_conversion": False,
            "this_scope_read_source_arrays": False,
            "this_scope_rendered_paraview": False,
        },
    }


def make_gencase_request(row: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    case_id = row["case_id"]
    materialized_definition = f"{{attempt_root}}/prepared/{case_id}_Def.xml"
    materialized_prefix = f"{{attempt_root}}/prepared/{case_id}"
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F1",
        "scope_name": SCOPE_NAME,
        "case_id": case_id,
        "attempt_id": f"f1-exact-mother-batch8-{case_id.lower()}-gencase-plan-001",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 2,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 1073741824,
        "launch_allowed": False,
        "launch_owner": "root",
        "dispatch_status": "planned_only_requires_root_authorization",
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "command_template": [
            GENCASE_BINARY,
            materialized_definition.removesuffix(".xml"),
            materialized_prefix,
            "-save:all",
            "-threads:2",
        ],
        "preparation_template": {
            "known_working_stage": "root_actual_bounded_fallback_three_dp_gencase_027",
            "wrapper_path": GENCASE_WRAPPER,
            "wrapper_sha256": HASHES["gencase_wrapper"],
            "binding_template_path": contract["known_working_preparation_027"]["binding_path"],
            "binding_template_sha256": contract["known_working_preparation_027"]["binding_sha256"],
            "binding_status": "provenance_only; height-specific binding must be freshly materialized",
            "materialization_requirement": "Root must materialize the one allowed fluid size.z mutation and hash the resulting definition and binding before launch",
        },
        "source_inputs": {
            "definition_template_path": contract["source_definition"]["path"],
            "definition_template_sha256": contract["source_definition"]["sha256"],
            "canonical_owner_path": contract["canonical_binding_034"]["owner_path"],
            "canonical_owner_sha256": contract["canonical_binding_034"]["owner_sha256"],
            "canonical_physical_binding_path": contract["canonical_binding_034"]["physical_binding_path"],
            "canonical_physical_binding_sha256": contract["canonical_binding_034"]["physical_binding_sha256"],
            "official_gencase_path": GENCASE_BINARY,
            "official_gencase_sha256": HASHES["official_gencase"],
        },
        "planned_source_mutation": row["planned_source_mutation"],
        "post_gencase_initial_qa_request": row["request_files"]["initial_qa"],
        "actual_outputs": None,
        "output_templates": {
            "generated_xml": materialized_definition,
            "generated_bi4": materialized_prefix + ".bi4",
            "gencase_receipt": "{attempt_root}/execution-receipt.json",
            "actual_outputs": None,
        },
        "claim_boundary": {
            "new_generation_completed": False,
            "initial_qa_completed": False,
            "solver_completed": False,
            "bi4_equal_to_anchor": False,
        },
    }


def make_initial_qa_request(row: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    case_id = row["case_id"]
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F1",
        "scope_name": SCOPE_NAME,
        "case_id": case_id,
        "attempt_id": f"f1-exact-mother-batch8-{case_id.lower()}-initial-qa-plan-001",
        "kind": "cpu",
        "cpu_task_kind": "initial_qa",
        "cpu_threads": 2,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": 1073741824,
        "launch_allowed": False,
        "launch_owner": "root",
        "dispatch_status": "blocked_until_new_gencase_receipt",
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "input_contract": {
            "source_definition_template_path": contract["source_definition"]["path"],
            "source_definition_template_sha256": contract["source_definition"]["sha256"],
            "required_height_specific_definition_sha256": None,
            "required_height_specific_gencase_receipt_sha256": None,
            "required_generated_bi4_sha256": None,
            "new_artifact_hashes_are_pending": True,
        },
        "required_checks": [
            "bind the generated XML and GenCase receipt to this exact target height and recipe hash",
            "verify generated fluid count equals the predicted count only after inspecting actual GenCase output",
            "verify all initial coordinates are finite and fluid coordinates lie in the target reservoir bounds",
            "verify native particle IDs are unique/contiguous and the 3-D flag is preserved",
            "verify fluid/boundary/void partition and source mk labels from generated output",
            "record actual native mass inventory separately from theoretical continuum mass",
            "retain any count, mass, or boundary failure as a failure; do not convert a plan into a pass",
        ],
        "predicted_values_for_qa_comparison": row["predicted_initial_state"],
        "forbidden_shortcuts": [
            "do not reuse the anchor BI4 as evidence for a changed height",
            "do not assert BI4 equality across heights",
            "do not process solver arrays or run a solver in this initial-QA request",
            "do not infer overtopping, zero loss, or visual acceptance from initial QA",
        ],
        "actual_outputs": None,
    }


def make_manifest(plan: dict[str, Any], contracts: dict[str, Any]) -> dict[str, Any]:
    artifact_paths = [
        SCOPE / "README.md",
        SCOPE / "batch8_plan.json",
        SCOPE / "source_contract.json",
        SCOPE / "scripts" / "build_exact_mother_batch8.py",
        SCOPE / "tests" / "test_exact_mother_batch8.py",
    ]
    artifact_paths.extend(sorted(REQUESTS.glob("*.json")))
    artifacts: dict[str, Any] = {}
    for path in artifact_paths:
        if path.exists():
            data = path.read_bytes()
            artifacts[str(path.relative_to(SCOPE))] = {
                "bytes": len(data),
                "sha256": sha256_bytes(data),
            }

    return {
        "schema": "ds02.f1.exact-mother-batch8-manifest.v1",
        "family_id": "F1",
        "scope_name": SCOPE_NAME,
        "status": "source_plan_committed; execution_not_performed",
        "source_only": True,
        "launch_allowed": False,
        "planned_recipe_count": len(plan["rows"]),
        "request_count": len(list(REQUESTS.glob("*.json"))),
        "source_template_contracts": sorted(contracts),
        "historical_negative_evidence_retained": True,
        "user_visual_approval_recorded": False,
        "root_visual_review_status": "pending_root_full_animation_review",
        "q_n_status": "not_accepted",
        "execution_calls_made": {
            "gencase": False,
            "solver": False,
            "conversion": False,
            "array_processing": False,
            "paraview": False,
        },
        "artifacts": artifacts,
    }


def build() -> None:
    REQUESTS.mkdir(parents=True, exist_ok=True)
    contracts_doc = make_source_contract_document()
    plan = make_plan()
    contracts = contracts_doc["contracts"]

    write_json(SCOPE / "source_contract.json", contracts_doc)
    write_json(SCOPE / "batch8_plan.json", plan)
    for row in plan["rows"]:
        contract = contracts[row["source_contract_id"]]
        write_json(REQUESTS / f"{row['case_id']}_gencase_request.json", make_gencase_request(row, contract))
        write_json(REQUESTS / f"{row['case_id']}_initial_qa_request.json", make_initial_qa_request(row, contract))

    write_json(SCOPE / "manifest.json", make_manifest(plan, contracts))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="build files; intended for deterministic source-plan checks")
    parser.parse_args()
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
