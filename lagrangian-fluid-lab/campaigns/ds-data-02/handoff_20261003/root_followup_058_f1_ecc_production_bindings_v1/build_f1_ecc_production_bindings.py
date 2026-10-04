#!/usr/bin/env python3
"""Build the source-only F1 ECC Stage 1 production binding package.

This package freezes the four-case Root062 domain and prepares one prospective
H130 request for the 057 visual adapter.  It deliberately does not launch a
solver, GenCase, converter, ParaView, or subprocess and it never decodes a
BI4/XML value array.  Existing JSON receipts and bounded physical metadata are
read and hashed only.

The H130 mass/evidence gate is intentionally a two-step contract.  This module
writes a fresh strict CPU audit request.  A Root-owned worker must later emit
the mass-discrepancy report and four evidence sidecars.  ``attach_worker_outputs``
only accepts those worker outputs after checking their identity and checks; it
does not calculate native mass or invent a passing JSON document.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping, MutableMapping


HERE = Path(__file__).resolve().parent
INFRA_LAB = HERE.parents[3]
INTEGRATION_LAB = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/"
    "DualSPHysics/lagrangian-fluid-lab"
)
INTEGRATION_CAMPAIGN = INTEGRATION_LAB / "campaigns/ds-data-02"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")

V057_DIR = HERE.parent / "root_followup_057_f1_ecc_stage1_production_authorization_v1"
V057_DISPATCH = V057_DIR / "ds_data02_stage1_dispatch_f1.py"
V057_AUTHORIZER = V057_DIR / "ds_data02_stage1_production_f1.py"
STRICT = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
SOLVER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)

GOAL = INTEGRATION_CAMPAIGN / "GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
ROOT_DOMAIN_DECISION = INTEGRATION_CAMPAIGN / (
    "handoff_20261003/root_stage1_f1_ecc_four_head_observed_domain_062/"
    "root-visual-domain-decision.json"
)
H130_OWNER = ROOT_DOMAIN_DECISION.parent / "ecc-h130-owner.json"
H110_OWNER = INTEGRATION_CAMPAIGN / (
    "handoff_20261003/root_stage1_f1_four_physical_head_endpoints_native_032/"
    "F1_STAGE1_ECC_H110_DP010/owner.json"
)
H190_OWNER = INTEGRATION_CAMPAIGN / (
    "handoff_20261003/root_stage1_f1_four_physical_head_endpoints_native_032/"
    "F1_STAGE1_ECC_H190_DP010/owner.json"
)
H150_OWNER = INTEGRATION_CAMPAIGN / (
    "families/F1/handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/"
    "ecc_coarse/owner.json"
)

H130_RECEIPT = DATA_ROOT / (
    "F1_STAGE1_ECC_H130_DP010/root-stage1-ecc-h130-actual-gencase-027/"
    "execution-receipt.json"
)
H130_PREPARED_REPORT = DATA_ROOT / (
    "F1_STAGE1_ECC_H130_DP010/root-stage1-ecc-h130-actual-gencase-027/"
    "prepared/prepared-input-report.json"
)
H130_XML = DATA_ROOT / (
    "F1_STAGE1_ECC_H130_DP010/root-stage1-ecc-h130-actual-gencase-027/"
    "prepared/F1_STAGE1_ECC_H130_DP010.xml"
)
H130_BI4 = DATA_ROOT / (
    "F1_STAGE1_ECC_H130_DP010/root-stage1-ecc-h130-actual-gencase-027/"
    "prepared/F1_STAGE1_ECC_H130_DP010.bi4"
)
H130_QA = DATA_ROOT / (
    "F1_STAGE1_SIX_NEW_HEAD_ACTUAL_INITIAL_QA/"
    "root-stage1-six-new-head-actual-native-initial-qa-031/native-initial-qa.json"
)

H110_RECEIPT = DATA_ROOT / (
    "F1_STAGE1_ECC_H110_DP010/root-stage1-ecc-h110-physical-endpoint-full-native-032/"
    "execution-receipt.json"
)
H110_STDOUT = H110_RECEIPT.parent / "stdout.log"
H110_VISUAL_DECISION = INTEGRATION_CAMPAIGN / (
    "handoff_20261003/root_stage1_f1_ecc_endpoint_visual_acceptance_047/"
    "ecc-h110-root-visual-decision.json"
)
H150_VISUAL_DECISION = INTEGRATION_CAMPAIGN / (
    "handoff_20261003/root_stage1_f1_ecc_mother_visual_acceptance_033/"
    "root-visual-decision.json"
)
H190_VISUAL_DECISION = INTEGRATION_CAMPAIGN / (
    "handoff_20261003/root_stage1_f1_ecc_endpoint_visual_acceptance_047/"
    "ecc-h190-root-visual-decision.json"
)
H110_INTEGRITY = DATA_ROOT / (
    "F1_STAGE1_ECC_H110_DP010/root-stage1-f1_stage1_ecc_h110_dp010-"
    "full161-native-geometry-animation-043/paraview-full-animation-report.json"
)
H150_INTEGRITY = DATA_ROOT / (
    "F1_FALLBACK_ECC_COARSE/root-stage1-f1-full161-native-geometry-animation-028/"
    "paraview-full-animation-report.json"
)
H190_INTEGRITY = DATA_ROOT / (
    "F1_STAGE1_ECC_H190_DP010/root-stage1-f1_stage1_ecc_h190_dp010-"
    "full161-native-geometry-animation-043/paraview-full-animation-report.json"
)

SCOPE_ID = "F1_ECC_STAGE1_FIRST4_HEAD0110_0190_VISUAL_V1"
CASE_ID = "F1_STAGE1_ECC_H130_DP010"
EXPECTED_GOAL_SHA = "53d422511b5581266410de92c54627ac67e8085eccb75a9ebfe57de10a34316a"
EXPECTED_DOMAIN_SHA = ""
EXPECTED_H130_OWNER_SHA = "e281b1179254ddbb39f0e7667a04fcafa56707e37c4e3129885d2496bf9fed8d"
EXPECTED_H130_RECEIPT_SHA = "293d0e3620538b1fd8a93660aab414d594bf348e43332018c619728704083083"
EXPECTED_H130_XML_SHA = "6ebb95a87d3ffea3970c782883b03d97d46eed47fe464821bb60176e4473b68b"
EXPECTED_H130_BI4_SHA = "21a698ce199d3e707c2c3747f591f38ba8dc36d3ba86d020b189d98ceb225a20"
EXPECTED_H130_QA_SHA = "c23a5a5c670e246dd45b7c12964a7e8cf5924283456a5fd3b66cad8eb1fb4768"
EXPECTED_TOTAL = 136276
EXPECTED_FLUID = 34840
EXPECTED_WINDOW = [0.0, 1.6]
EXPECTED_FRAMES = 161
EXPECTED_DP = 0.01

OBSERVED = (
    "F1_STAGE1_ECC_H110_DP010",
    "F1_FALLBACK_ECC_COARSE",
    "F1_STAGE1_ECC_H190_DP010",
)


class BindingBuildError(ValueError):
    """Raised when the frozen source metadata is incomplete or changed."""


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def binding(path: Path, expected: str | None = None) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise BindingBuildError(f"required source file is missing: {path}")
    actual = sha256(path)
    if expected is not None and actual != expected:
        raise BindingBuildError(f"hash mismatch for {path}: {actual} != {expected}")
    return {"path": str(path), "sha256": actual}


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BindingBuildError(f"cannot read JSON source: {path}") from error


def save(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BindingBuildError(f"{label} must be an object")
    return value


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise BindingBuildError(f"{label} differs from the frozen actual value: {actual!r} != {expected!r}")


def _qa_row(document: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    rows = document.get("cases")
    if not isinstance(rows, list):
        raise BindingBuildError("QA document has no cases list")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("case_id") == case_id]
    if len(matches) != 1:
        raise BindingBuildError(f"QA document does not contain exactly one {case_id} row")
    return matches[0]


def _path_in_hash_map(raw_path: str, expected: str, *, label: str) -> dict[str, str]:
    path = Path(raw_path).resolve()
    return binding(path, expected)


def _check_h130_sources() -> dict[str, Any]:
    domain_decision = _require_mapping(load(ROOT_DOMAIN_DECISION), "Root062 domain decision")
    _require_equal(domain_decision.get("schema"), "ds02.stage1.root-visual-domain-decision.v1", "Root062 schema")
    _require_equal(domain_decision.get("family_id"), "F1", "Root062 family")
    _require_equal(domain_decision.get("scope_id"), SCOPE_ID, "Root062 scope")
    _require_equal(domain_decision.get("selected_case_ids"), [CASE_ID], "Root062 selected case")
    _require_equal(domain_decision.get("prospective_case_ids"), [CASE_ID], "Root062 prospective case")
    _require_equal(domain_decision.get("observed_case_ids"), list(OBSERVED), "Root062 observed cases")
    _require_equal(domain_decision.get("production_scope_approval"), False, "Root062 production approval")
    _require_equal(domain_decision.get("q_n"), "not_granted", "Root062 Q-N")
    _require_equal(domain_decision.get("numerical_precision_status"), "not_accepted", "Root062 precision status")
    goal = _require_mapping(domain_decision.get("goal_authority"), "Root062 goal authority")
    _require_equal(goal.get("sha256"), EXPECTED_GOAL_SHA, "Root062 goal hash")

    owner = _require_mapping(load(H130_OWNER), "H130 owner")
    _require_equal(sha256(H130_OWNER), EXPECTED_H130_OWNER_SHA, "H130 owner hash")
    _require_equal(owner.get("case_id"), CASE_ID, "H130 owner case")
    _require_equal(owner.get("physical_condition_sha256"), "16ba07faf7b61f7d97f4bfc9d88a315293292107f1390ca860c15825a3bdb36e", "H130 physical condition")
    _require_equal(owner.get("claims", {}).get("q_n"), "not_granted", "H130 owner Q-N")
    _require_equal(owner.get("claims", {}).get("independent_case_count_increment"), 0, "H130 owner count")

    receipt = _require_mapping(load(H130_RECEIPT), "H130 GenCase receipt")
    _require_equal(sha256(H130_RECEIPT), EXPECTED_H130_RECEIPT_SHA, "H130 GenCase receipt hash")
    _require_equal(receipt.get("status"), "completed", "H130 GenCase status")
    _require_equal(receipt.get("returncode"), 0, "H130 GenCase returncode")
    _require_equal(receipt.get("solver_dimension_from_gencase"), 3, "H130 GenCase dimension")
    _require_equal(receipt.get("total_particles"), EXPECTED_TOTAL, "H130 GenCase total")
    _require_equal(receipt.get("fluid_particles"), EXPECTED_FLUID, "H130 GenCase fluid")
    if receipt.get("input_hashes_at_launch") != receipt.get("input_hashes_after_run"):
        raise BindingBuildError("H130 GenCase input provenance changed during the run")

    prepared = _require_mapping(load(H130_PREPARED_REPORT), "H130 prepared-input report")
    _require_equal(prepared.get("case_id"), CASE_ID, "H130 prepared case")
    _require_equal(prepared.get("actual_total_particles"), EXPECTED_TOTAL, "H130 prepared total")
    counts = _require_mapping(prepared.get("generated_xml_particle_counts"), "H130 XML particle counts")
    _require_equal(counts.get("fluid"), EXPECTED_FLUID, "H130 prepared fluid")
    _require_equal(sha256(H130_XML), EXPECTED_H130_XML_SHA, "H130 XML hash")
    _require_equal(sha256(H130_BI4), EXPECTED_H130_BI4_SHA, "H130 BI4 hash")
    _require_equal(prepared.get("xml_sha256"), EXPECTED_H130_XML_SHA, "H130 prepared XML hash")
    _require_equal(prepared.get("bi4_sha256"), EXPECTED_H130_BI4_SHA, "H130 prepared BI4 hash")
    # The worker must later use this metadata, but this builder never computes
    # a native mass from it.
    predictions = _require_mapping(prepared.get("predictions"), "H130 prepared predictions")
    if not isinstance(predictions.get("native_weight_float32_kg"), (int, float)):
        raise BindingBuildError("H130 prepared report lacks native weight metadata for the worker request")

    qa_document = _require_mapping(load(H130_QA), "QA031")
    _require_equal(sha256(H130_QA), EXPECTED_H130_QA_SHA, "QA031 hash")
    qa = _require_mapping(_qa_row(qa_document, CASE_ID), "QA031 H130 row")
    _require_equal(qa.get("passed"), True, "QA031 H130 passed")
    _require_equal(qa.get("actual_3d"), True, "QA031 H130 3D")
    _require_equal(qa.get("native_particles"), EXPECTED_TOTAL, "QA031 H130 total")
    _require_equal(qa.get("native_fluid"), EXPECTED_FLUID, "QA031 H130 fluid")
    _require_equal(qa.get("generated_xml_sha256"), EXPECTED_H130_XML_SHA, "QA031 H130 XML")
    _require_equal(qa.get("initial_bi4_sha256"), EXPECTED_H130_BI4_SHA, "QA031 H130 BI4")

    return {
        "domain_decision": domain_decision,
        "domain_decision_binding": binding(ROOT_DOMAIN_DECISION),
        "goal_binding": binding(GOAL, EXPECTED_GOAL_SHA),
        "owner": owner,
        "owner_binding": binding(H130_OWNER, EXPECTED_H130_OWNER_SHA),
        "gencase_receipt": receipt,
        "gencase_binding": binding(H130_RECEIPT, EXPECTED_H130_RECEIPT_SHA),
        "prepared_report": prepared,
        "prepared_report_binding": binding(H130_PREPARED_REPORT),
        "qa_document": qa_document,
        "qa_row": qa,
        "qa_binding": binding(H130_QA, EXPECTED_H130_QA_SHA),
        "xml_binding": binding(H130_XML, EXPECTED_H130_XML_SHA),
        "bi4_binding": binding(H130_BI4, EXPECTED_H130_BI4_SHA),
    }


def _h110_recipe(ctx: Mapping[str, Any]) -> dict[str, Any]:
    receipt = _require_mapping(load(H110_RECEIPT), "H110 native032 receipt")
    request = _require_mapping(receipt.get("request"), "H110 native032 request")
    command = request.get("command")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise BindingBuildError("H110 native032 request command is not a string list")
    _require_equal(command[-2:], ["-tmax:1.6", "-tout:0.01"], "H110 native032 solver options")
    _require_equal(request.get("expected_native_frames"), EXPECTED_FRAMES, "H110 native032 frames")
    _require_equal(request.get("physical_window_s"), [0, 1.6], "H110 native032 physical window")
    _require_equal(request.get("actual_execution_parameters", {}).get("TimeMax"), "1.6", "H110 TimeMax")
    _require_equal(request.get("actual_execution_parameters", {}).get("TimeOut"), "0.01", "H110 TimeOut")
    _require_equal(request.get("actual_execution_parameters", {}).get("Boundary"), "1", "H110 Boundary")
    _require_equal(request.get("actual_generated_constants", {}).get("dp", {}).get("value"), "0.01", "H110 Dp")
    if not H110_STDOUT.is_file() or "mDBC no-slip" not in H110_STDOUT.read_text(encoding="utf-8", errors="replace"):
        raise BindingBuildError("H110 native032 stdout does not preserve the mDBC no-slip feature record")

    h130_prefix = str(Path(ctx["gencase_receipt"]["output_root"]) / "prepared" / CASE_ID)
    transformed = list(command)
    if len(transformed) < 3:
        raise BindingBuildError("H110 native032 command lacks a prefix/output pair")
    transformed[1] = h130_prefix
    transformed[2] = "{attempt_root}/solver_output"
    recipe = {
        "schema": "ds02.f1.ecc.stage1.native032-recipe.v1",
        "source_receipt": binding(H110_RECEIPT),
        "source_runtime_log": binding(H110_STDOUT),
        "command_options_reused_exactly": True,
        "command": transformed,
        "cwd": request.get("cwd"),
        "expected_native_frames": EXPECTED_FRAMES,
        "physical_window_s": EXPECTED_WINDOW,
        "dp_m": EXPECTED_DP,
        "save_interval_s": 0.01,
        "boundary_parameter": "1",
        "boundary_feature_record": "mDBC no-slip",
        "actual_execution_parameters": copy.deepcopy(request.get("actual_execution_parameters")),
        "actual_generated_constants": copy.deepcopy(request.get("actual_generated_constants")),
        "prefix_transform": {
            "source_prefix": command[1],
            "target_prefix": h130_prefix,
            "output_transform": "{attempt_root}/solver_output",
            "physical_definition_unchanged": True,
        },
    }
    return {
        "receipt": receipt,
        "request": request,
        "recipe": recipe,
        "command": transformed,
        "cwd": request.get("cwd"),
        "h110_binding": binding(H110_RECEIPT),
        "h110_stdout_binding": binding(H110_STDOUT),
    }


def _owner_rows(ctx: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    decision = ctx["domain_decision"]
    owners = {
        "F1_STAGE1_ECC_H110_DP010": (H110_OWNER, "observed"),
        "F1_FALLBACK_ECC_COARSE": (H150_OWNER, "observed"),
        "F1_STAGE1_ECC_H190_DP010": (H190_OWNER, "observed"),
        CASE_ID: (H130_OWNER, "prospective"),
    }
    frozen = {row["case_id"]: row for row in decision["frozen_case_membership"]}
    result: dict[str, Mapping[str, Any]] = {}
    for case_id, (owner_path, role) in owners.items():
        owner = _require_mapping(load(owner_path), f"owner {case_id}")
        root_row = _require_mapping(frozen.get(case_id), f"Root062 membership {case_id}")
        _require_equal(owner.get("case_id"), case_id, f"owner {case_id} case")
        _require_equal(owner.get("physical_case_id"), root_row.get("physical_case_id"), f"owner {case_id} physical case")
        _require_equal(owner.get("physical_condition_sha256"), root_row.get("physical_condition_sha256"), f"owner {case_id} condition")
        physical = _require_mapping(owner.get("physical_binding"), f"owner {case_id} physical binding")
        params = _require_mapping(physical.get("parameters"), f"owner {case_id} parameters")
        tuple_value = copy.deepcopy(root_row.get("parameter_tuple"))
        if tuple_value != {
            "mechanism_id": owner.get("mechanism_id"),
            "fluid_depth_m": params.get("fluid_depth_m"),
            "dp_m": EXPECTED_DP,
        }:
            raise BindingBuildError(f"{case_id} Root062 parameter tuple differs from owner/source")
        result[case_id] = {
            "case_id": case_id,
            "physical_case_id": owner["physical_case_id"],
            "physical_condition_sha256": owner["physical_condition_sha256"],
            "parameter_tuple": tuple_value,
            "role": role,
            "owner": owner,
            "owner_path": owner_path,
            "owner_binding": binding(owner_path),
            "physical_binding": copy.deepcopy(physical),
            "root_membership": copy.deepcopy(root_row),
        }
    return result


def _base_case_row(row: Mapping[str, Any]) -> dict[str, Any]:
    owner = row["owner"]
    physical = row["physical_binding"]
    event = _require_mapping(physical.get("event_window"), f"{row['case_id']} event window")
    window = [event.get("time_start_s"), event.get("time_end_s")]
    _require_equal(window, [0, 1.6], f"{row['case_id']} event window")
    return {
        "case_id": row["case_id"],
        "physical_case_id": row["physical_case_id"],
        "physical_condition_sha256": row["physical_condition_sha256"],
        "parameter_tuple": copy.deepcopy(row["parameter_tuple"]),
        "role": row["role"],
        "source_owner": row["owner_binding"],
        "physical_binding": copy.deepcopy(physical),
        "mechanism_id": owner.get("mechanism_id"),
        "geometry_family_id": physical.get("geometry_family_id"),
        "control_family_id": physical.get("control_family_id"),
        "physics": {
            "mechanism_id": owner.get("mechanism_id"),
            "gravity_m_s2": copy.deepcopy(physical.get("gravity_m_s2")),
            "density_kg_m3": physical.get("density_kg_m3"),
            "controls": copy.deepcopy(physical.get("controls")),
            "mass_policy": physical.get("mass_policy"),
        },
        "geometry": copy.deepcopy(physical.get("geometry")),
        "motion": {
            "mode": "gravity_release",
            "initial_velocities_m_per_s": copy.deepcopy(
                physical.get("initial_state", {}).get("velocities_m_per_s")
            ),
            "prescribed_forcing": "none",
            "event_sequence": copy.deepcopy(event.get("sequence")),
        },
        "event_window_s": window,
        "complete_event_window_s": window,
        "expected_saved_frames": EXPECTED_FRAMES,
        "native_frame_interval_s": 0.01,
        "independent_case_count_increment": 0,
        "parent_group_id": physical.get("lineage_group_id"),
        "split": row["role"],
    }


def _observed_source_row(case_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
    result = _base_case_row(row)
    if case_id == "F1_STAGE1_ECC_H110_DP010":
        result.update(
            {
                "native_particles": 130916,
                "native_fluid_particles": 29480,
                "visual_review_status": "visual-approved-by-root",
            }
        )
    elif case_id == "F1_FALLBACK_ECC_COARSE":
        result.update(
            {
                "native_particles": 141636,
                "native_fluid_particles": 40200,
                "visual_review_status": "visual-approved-by-root; historical mother",
            }
        )
    elif case_id == "F1_STAGE1_ECC_H190_DP010":
        result.update(
            {
                "native_particles": 152356,
                "native_fluid_particles": 50920,
                "visual_review_status": "visual-approved-by-root",
            }
        )
    return result


def _h130_input_bindings(ctx: Mapping[str, Any], *, audit_request: Path | None = None) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(value: Mapping[str, Any]) -> None:
        path = str(Path(str(value["path"])).resolve())
        if path not in seen:
            result.append({"path": path, "sha256": value["sha256"]})
            seen.add(path)

    receipt = ctx["gencase_receipt"]
    launch = _require_mapping(receipt.get("input_hashes_at_launch"), "H130 GenCase inputs")
    for raw_path, expected in launch.items():
        add(_path_in_hash_map(str(raw_path), str(expected), label="H130 GenCase input"))
    for value in (
        ctx["gencase_binding"],
        ctx["qa_binding"],
        ctx["prepared_report_binding"],
        ctx["xml_binding"],
        ctx["bi4_binding"],
    ):
        add(value)
    official_csv = ctx["qa_row"].get("official_csv")
    official_sha = ctx["qa_row"].get("official_csv_sha256")
    if not isinstance(official_csv, str) or not isinstance(official_sha, str):
        raise BindingBuildError("QA031 H130 official CSV binding is missing")
    add(binding(Path(official_csv), official_sha))
    add(ctx["owner_binding"])
    add(ctx["domain_decision_binding"])
    add(ctx["goal_binding"])
    if audit_request is not None:
        add(binding(audit_request))
    return result


def build_physical_domain(ctx: Mapping[str, Any]) -> dict[str, Any]:
    rows = _owner_rows(ctx)
    ordered = [rows[case_id] for case_id in (*OBSERVED, CASE_ID)]
    return {
        "schema": "ds02.stage1.frozen-physical-domain.v1",
        "status": "source_fixture_only_pending_h130_audit",
        "source_only": True,
        "execution_allowed": False,
        "family_id": "F1",
        "scope_id": SCOPE_ID,
        "goal_authority": ctx["goal_binding"],
        "root_visual_domain_decision": ctx["domain_decision_binding"],
        "event_window_s": EXPECTED_WINDOW,
        "time_window_s": EXPECTED_WINDOW,
        "save_interval_s": 0.01,
        "expected_saved_frames": EXPECTED_FRAMES,
        "no_interpolation_or_extrapolation": True,
        "unchanged_obstacle_and_boundary_geometry": True,
        "cases": [_base_case_row(row) for row in ordered],
    }


def build_case_manifest(ctx: Mapping[str, Any], *, audit_request: Path, builder_binding: Mapping[str, str]) -> dict[str, Any]:
    rows = _owner_rows(ctx)
    cases = [_observed_source_row(case_id, rows[case_id]) for case_id in OBSERVED]
    h130 = _base_case_row(rows[CASE_ID])
    recipe = ctx["h110_recipe"]
    owner = ctx["owner"]
    source = _require_mapping(owner.get("source"), "H130 owner source")
    h130.update(
        {
            "qa_semantics": "genuine_3d_generation",
            "initial_qa_case_id": CASE_ID,
            "native_particles": EXPECTED_TOTAL,
            "native_fluid_particles": EXPECTED_FLUID,
            "visual_review_pending": True,
            "prospective_domain_launch": True,
            "production_approval": "none",
            "numerical_precision_status": "not_accepted",
            "q_n": "not_granted",
            "q_e": "not_assessed",
            "initial_state_qa": ctx["qa_binding"],
            "gencase_receipt": ctx["gencase_binding"],
            "initial_bytes": [ctx["xml_binding"], ctx["bi4_binding"]],
            "prepared_input": {
                "report": ctx["prepared_report_binding"],
                "generated_xml": ctx["xml_binding"],
                "initial_bi4": ctx["bi4_binding"],
            },
            "input_bindings": _h130_input_bindings(ctx, audit_request=audit_request),
            "source": {
                "exact_definition": binding(Path(ctx["domain_decision"]["bindings"]["exact_definition"]["path"]), ctx["domain_decision"]["bindings"]["exact_definition"]["sha256"]),
                "generated_xml": ctx["xml_binding"],
                "initial_bi4": ctx["bi4_binding"],
                "actual_gencase_receipt": ctx["gencase_binding"],
                "actual_initial_qa": ctx["qa_binding"],
                "owner": ctx["owner_binding"],
            },
            "continuum_reference_mass_kg": owner["physical_binding"]["initial_state"]["continuum_mass_by_source_kg"]["fluid"],
            "mass_policy": "native MassFluid from worker audit; no normalization or rescaling",
            "solver_recipe_source": recipe["h110_binding"],
            "actual_solver_command": recipe["command"],
            "actual_solver_cwd": recipe["cwd"],
            "solver_command": recipe["command"],
            "solver_cwd": recipe["cwd"],
            "numerical_recipe": copy.deepcopy(recipe["recipe"]),
            "strict_cpu_audit_request": binding(audit_request),
            "evidence_builder": builder_binding,
            "evidence_status": "pending_root_strict_cpu_audit_outputs",
            "root062_owner_source": source,
        }
    )
    cases.append(h130)
    return {
        "schema": "ds02.stage1.visual-case-manifest.v1",
        "status": "source_fixture_only_pending_h130_audit",
        "source_only": True,
        "execution_allowed": False,
        "family_id": "F1",
        "scope_id": SCOPE_ID,
        "goal_authority": ctx["goal_binding"],
        "root_visual_domain_decision": ctx["domain_decision_binding"],
        "cases": cases,
        "shared_initial_state": {
            "semantics": "h130_genuine_generation_only",
            "actual_initial_qa": ctx["qa_binding"],
            "generated_xml": ctx["xml_binding"],
            "initial_bi4": ctx["bi4_binding"],
            "native_counts": {"total_particles": EXPECTED_TOTAL, "fluid_particles": EXPECTED_FLUID},
            "native_weight": "must be emitted by Root strict CPU worker; no value is asserted here",
        },
        "source_documents": {
            "root062_domain_decision": ctx["domain_decision_binding"],
            "root062_h130_owner": ctx["owner_binding"],
            "h110_native032_receipt": ctx["h110_recipe"]["h110_binding"],
        },
    }


def build_visual_evidence(ctx: Mapping[str, Any]) -> dict[str, Any]:
    observed = []
    for case_id, decision_path, integrity_path, historical in (
        ("F1_STAGE1_ECC_H110_DP010", H110_VISUAL_DECISION, H110_INTEGRITY, False),
        ("F1_FALLBACK_ECC_COARSE", H150_VISUAL_DECISION, H150_INTEGRITY, True),
        ("F1_STAGE1_ECC_H190_DP010", H190_VISUAL_DECISION, H190_INTEGRITY, False),
    ):
        observed.append(
            {
                "case_id": case_id,
                "status": "visual-approved-by-root; historical mother" if historical else "visual-approved-by-root",
                "decision": binding(decision_path),
                "integrity_report": binding(integrity_path),
                "historical": historical,
            }
        )
    return {
        "observed": observed,
        "prospective": [
            {
                "case_ids": [CASE_ID],
                "status": "pending actual complete solver/state/ParaView/root case decision",
                "decision": None,
                "integrity_report": None,
            }
        ],
    }


def build_scope_entry(ctx: Mapping[str, Any], domain_path: Path, manifest_path: Path) -> dict[str, Any]:
    return {
        "schema": "ds02.stage1.f1.ecc-source-v1-scope-entry.v1",
        "family_id": "F1",
        "scope_id": SCOPE_ID,
        "visual_stage_profile": "stage1_visual",
        "status": "source_fixture_only_pending_h130_audit",
        "execution_allowed": False,
        "production_scope_approval": False,
        "numerical_precision_status": "not_accepted",
        "q_n": "not_granted",
        "q_e": "not_assessed",
        "stage1_label": "视觉检查通过、数值精度未验收",
        "goal_authority": ctx["goal_binding"],
        "root_visual_domain_decision": ctx["domain_decision_binding"],
        "physical_domain": binding(domain_path),
        "case_manifest": binding(manifest_path),
        "selected_case_ids": [CASE_ID],
        "visual_evidence": build_visual_evidence(ctx),
        "review_contract": {
            "future_case_visual_decision_required_after_actual_complete_run": True,
            "future_full_saved_frame_integrity_required_after_actual_complete_run": True,
            "independent_case_count_increment_before_case_decision": 0,
            "no_interpolation_or_extrapolation": True,
            "no_q_n_or_numerical_precision_grant": True,
            "h130_mass_and_four_evidence_sidecars_required": True,
        },
    }


def build_fixture_index(ctx: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ds02.root-approved-visual-scopes.v2",
        "campaign_id": "DS-DATA-02",
        "interpretation": "F1 source fixture only; not the shared approval index",
        "status": "source_fixture_only",
        "execution_allowed": False,
        "production_scope_approval": False,
        "goal_authority": ctx["goal_binding"],
        "scopes": [copy.deepcopy(dict(entry))],
    }


def build_strict_cpu_audit_input_manifest(ctx: Mapping[str, Any], out: Path) -> dict[str, Any]:
    input_values = _h130_input_bindings(ctx)
    physical = _require_mapping(ctx["owner"].get("physical_binding"), "H130 owner physical binding")
    initial_state = _require_mapping(physical.get("initial_state"), "H130 owner initial state")
    continuum_by_source = _require_mapping(
        initial_state.get("continuum_mass_by_source_kg"),
        "H130 continuum mass source map",
    )
    continuum_reference_mass = continuum_by_source.get("fluid")
    if not isinstance(continuum_reference_mass, (int, float)):
        raise BindingBuildError("H130 owner lacks a numeric continuum fluid mass reference")
    return {
        "schema": "ds02.stage1.f1.ecc.h130-strict-cpu-audit-inputs.v1",
        "status": "input_manifest_only_pending_root_worker",
        "source_only": True,
        "execution_allowed": False,
        "family_id": "F1",
        "case_id": CASE_ID,
        "scope_id": SCOPE_ID,
        "inputs": input_values,
        "expected_identity": {
            "genuine_gencase_total_particles": EXPECTED_TOTAL,
            "genuine_gencase_fluid_particles": EXPECTED_FLUID,
            "qa_native_particles": EXPECTED_TOTAL,
            "qa_native_fluid": EXPECTED_FLUID,
            "actual_3d": True,
            "continuum_reference_mass_kg": continuum_reference_mass,
            "mass_rescaling": False,
            "native_particle_weight": "worker must read actual BI4/XML metadata; builder does not calculate it",
        },
        "required_worker_checks": [
            "genuine_gencase_counts_match_qa031_and_prepared_report",
            "native_particle_weight_read_from_actual_input",
            "native_fluid_mass_and_continuum_difference_computed_by_worker",
            "no_mass_rescaling",
            "physics_finite_state",
            "geometry_finite_state",
            "motion_finite_state",
            "no_initial_fluid_solid_overlap",
        ],
        "required_sidecars": {
            "initial_mass_discrepancy_report": "initial_mass_discrepancy_report.json",
            "physics_evidence": "physics_evidence.json",
            "geometry_evidence": "geometry_evidence.json",
            "motion_evidence": "motion_evidence.json",
            "no_overlap_finite_state_evidence": "no_overlap_finite_state_evidence.json",
        },
        "prohibitions": [
            "No solver, GenCase, conversion, ParaView, GPU, or Q-N claim",
            "Do not infer native mass from particle count in this worktree",
            "Do not replace worker-computed mass difference with a predicted value",
            "Do not mark evidence checks true unless emitted by the Root strict CPU worker",
        ],
        "output_root_contract": str(
            DATA_ROOT / "F1_STAGE1_ECC_H130_DP010/root-stage1-ecc-h130-strict-cpu-audit-058"
        ),
    }


def build_strict_cpu_audit_request(ctx: Mapping[str, Any], input_manifest_path: Path) -> dict[str, Any]:
    # This command is an explicit Root-only contract placeholder.  The shared
    # runner must substitute the reviewed strict CPU worker before any launch.
    return {
        "schema": "ds02.runner.request.v2",
        "family_id": "F1",
        "case_id": CASE_ID,
        "attempt_id": "root-stage1-ecc-h130-strict-cpu-audit-058-pending",
        "kind": "cpu",
        "cpu_task_kind": "strict_initial_state_audit",
        "model_profile": "gpt-5.6-luna/max",
        "cpu_threads": 2,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 1073741824,
        "cwd": str(INFRA_LAB),
        "worktree_root": str(INFRA_LAB.parent),
        "command": [
            "ROOT_MUST_SUPPLY_REVIEWED_STRICT_CPU_WORKER",
            "--input-manifest",
            str(input_manifest_path.resolve()),
            "--output",
            "{attempt_root}/strict-cpu-audit.json",
        ],
        "input_files": [str(input_manifest_path.resolve()), str(V057_AUTHORIZER.resolve())],
        "input_sha256": {
            str(input_manifest_path.resolve()): sha256(input_manifest_path),
            str(V057_AUTHORIZER.resolve()): sha256(V057_AUTHORIZER),
        },
        "source_immutability": True,
        "launch_allowed": False,
        "launch_authority": "Root only after reviewing and substituting a strict CPU worker",
        "scope": "Read-only H130 genuine GenCase/QA/XML/BI4 metadata audit and derived evidence sidecars; no solver or raw-array analysis from this source-only package.",
        "source_input_manifest": str(input_manifest_path.resolve()),
        "required_output_contract": {
            "schema": "ds02.stage1.f1.ecc.h130-strict-cpu-audit-result.v1",
            "status": "completed",
            "returncode": 0,
            "sidecars": "five actual worker-produced JSON bindings",
        },
        "q_n_status": "not_assessed",
    }


def _load_v057_authorizer() -> Any:
    scripts = str(INTEGRATION_LAB / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("ds_data02_stage1_production_f1_v057", V057_AUTHORIZER)
    if spec is None or spec.loader is None:
        raise BindingBuildError(f"cannot import 057 authorizer: {V057_AUTHORIZER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_h130_request(case: Mapping[str, Any], ctx: Mapping[str, Any], audit_request: Path) -> dict[str, Any]:
    authorizer = _load_v057_authorizer()
    input_files = [str(SOLVER.resolve()), str(audit_request.resolve())]
    request = authorizer.build_request(
        case,
        family_id="F1",
        scope_id=SCOPE_ID,
        attempt_id="root-stage1-ecc-h130-production-bindings-058-pending-root-audit",
        adapter_path=V057_DISPATCH,
        strict_path=STRICT,
        runtime_path=RUNTIME,
        command=copy.deepcopy(ctx["h110_recipe"]["command"]),
        cwd=ctx["h110_recipe"]["cwd"],
        complete_event_window_s=EXPECTED_WINDOW,
        input_files=input_files,
        prospective_domain_launch=True,
        cpu_threads=4,
        max_wall_seconds=900,
        estimated_peak_gpu_mib=8000,
        estimated_storage_bytes=4294967296,
        worktree_root=str(INFRA_LAB.parent),
    )
    request.update(
        {
            "source_only": True,
            "execution_allowed": False,
            "launch_allowed": False,
            "launch_owner": "Root after explicit adapter/index review and strict CPU sidecars",
            "production_approval": "none",
            "q_n": "not_granted",
            "q_e": "not_assessed",
            "numerical_precision_status": "not_accepted",
            "request_status": "pending_root_strict_cpu_audit_outputs",
            "strict_cpu_audit_request": binding(audit_request),
            "future_case_visual_review": "required_after_actual_complete_run",
        }
    )
    return request


def build_sidecar_contract() -> dict[str, Any]:
    return {
        "schema": "ds02.stage1.f1.ecc.h130-derived-sidecar-builder.v1",
        "source_only": True,
        "case_id": CASE_ID,
        "status": "builder_only_pending_worker_output",
        "builder": str((HERE / "derive_f1_ecc_sidecars.py").resolve()),
        "derivation_policy": "Copy only scalar checks and path/hash provenance emitted by the Root strict CPU worker; do not claim an independent experiment.",
        "required_worker_sidecars": [
            "initial_mass_discrepancy_report",
            "physics_evidence",
            "geometry_evidence",
            "motion_evidence",
            "no_overlap_finite_state_evidence",
        ],
        "required_checks": {
            "physics_evidence": ["finite_state"],
            "geometry_evidence": ["finite_state"],
            "motion_evidence": ["finite_state"],
            "no_overlap_finite_state_evidence": ["finite_state", "no_initial_fluid_solid_overlap"],
        },
        "mass_policy": {
            "native_weight_source": "actual BI4/XML worker output",
            "continuum_reference_source": "Root062 H130 owner physical_binding.initial_state.continuum_mass_by_source_kg.fluid",
            "rescaling": False,
            "builder_calculates_mass": False,
        },
    }


def _worker_binding(value: Any, label: str) -> tuple[Path, dict[str, str], Mapping[str, Any]]:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        raise BindingBuildError(f"worker output lacks {label} path binding")
    path = Path(value["path"]).resolve()
    normalized = binding(path, value.get("sha256"))
    document = _require_mapping(load(path), label)
    return path, normalized, document


def _nested_bindings(value: Any) -> list[Mapping[str, Any]]:
    """Collect only path/hash objects; never interpret file contents."""

    result: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            result.append(value)
        for child in value.values():
            result.extend(_nested_bindings(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_nested_bindings(child))
    return result


def refresh_request_bindings(
    request: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy the worker-bound H130 row and refresh immutable request hashes.

    Root may use this after the strict CPU worker has produced actual sidecars.
    The resulting request still preserves the source package's launch flags;
    Root must separately review and authorize any production launch.
    """

    result = copy.deepcopy(dict(request))
    rows = manifest.get("cases")
    if not isinstance(rows, list):
        raise BindingBuildError("manifest has no cases")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("case_id") == CASE_ID]
    if len(matches) != 1:
        raise BindingBuildError("manifest does not contain one H130 row")
    result.update(copy.deepcopy(dict(matches[0])))

    paths: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path, expected: str | None = None) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            binding(resolved, expected)
            paths.append(resolved)
            seen.add(resolved)

    for raw_path in result.get("input_files", []):
        if isinstance(raw_path, str):
            add(Path(raw_path))
    for nested in _nested_bindings(matches[0]):
        add(Path(str(nested["path"])), str(nested["sha256"]))
    result["input_files"] = [str(path) for path in paths]
    result["input_sha256"] = {str(path): sha256(path) for path in paths}
    result["input_hashes"] = dict(result["input_sha256"])
    return result


def attach_worker_outputs(
    manifest: Mapping[str, Any],
    audit_result_path: Path,
    *,
    output_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Attach actual Root worker sidecars to a copied manifest.

    The function reads only JSON metadata and path/hash bindings.  It refuses
    missing or pending worker output and never computes native mass itself.
    """

    audit = _require_mapping(load(audit_result_path), "strict CPU audit result")
    _require_equal(audit.get("schema"), "ds02.stage1.f1.ecc.h130-strict-cpu-audit-result.v1", "audit schema")
    _require_equal(audit.get("status"), "completed", "audit status")
    _require_equal(audit.get("returncode"), 0, "audit returncode")
    identity = _require_mapping(audit.get("identity"), "audit identity")
    _require_equal(identity.get("case_id"), CASE_ID, "audit case")
    _require_equal(identity.get("total_particles"), EXPECTED_TOTAL, "audit total")
    _require_equal(identity.get("fluid_particles"), EXPECTED_FLUID, "audit fluid")
    checks = _require_mapping(audit.get("checks"), "audit checks")
    for name in (
        "genuine_gencase_counts_match_qa031_and_prepared_report",
        "native_particle_weight_read_from_actual_input",
        "mass_difference_computed_by_worker",
        "no_mass_rescaling",
    ):
        _require_equal(checks.get(name), True, f"audit check {name}")

    sidecars = _require_mapping(audit.get("sidecars"), "audit sidecars")
    required = {
        "initial_mass_discrepancy_report": (),
        "physics_evidence": ("finite_state",),
        "geometry_evidence": ("finite_state",),
        "motion_evidence": ("finite_state",),
        "no_overlap_finite_state_evidence": ("finite_state", "no_initial_fluid_solid_overlap"),
    }
    normalized: dict[str, dict[str, str]] = {}
    for label, required_checks in required.items():
        _, normalized_binding, document = _worker_binding(sidecars.get(label), label)
        for check in required_checks:
            checks_map = document.get("checks") if isinstance(document.get("checks"), Mapping) else document
            _require_equal(checks_map.get(check), True, f"{label}.{check}")
        normalized[label] = normalized_binding

    result = copy.deepcopy(dict(manifest))
    rows = result.get("cases")
    if not isinstance(rows, list):
        raise BindingBuildError("manifest has no cases")
    matches = [row for row in rows if isinstance(row, MutableMapping) and row.get("case_id") == CASE_ID]
    if len(matches) != 1:
        raise BindingBuildError("manifest does not contain one H130 row")
    h130 = matches[0]
    for label, normalized_binding in normalized.items():
        h130[label] = normalized_binding
    h130["evidence_status"] = "actual_root_worker_sidecars_attached"
    audit_binding = binding(audit_result_path)
    h130["strict_cpu_audit_result"] = audit_binding
    input_bindings = h130.get("input_bindings")
    if not isinstance(input_bindings, list):
        raise BindingBuildError("H130 manifest row has no input_bindings list")
    known = {
        str(Path(item["path"]).resolve())
        for item in input_bindings
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    }
    for item in [*normalized.values(), audit_binding]:
        resolved = str(Path(item["path"]).resolve())
        if resolved not in known:
            input_bindings.append(item)
            known.add(resolved)
    result["status"] = "source_fixture_with_actual_worker_sidecars_pending_root_review"
    output_dir.mkdir(parents=True, exist_ok=True)
    save(output_dir / "F1_ECC_H130_WORKER_OUTPUT_BINDINGS.json", normalized)
    return result, normalized


def build_source_package(out: Path = HERE) -> dict[str, Any]:
    out = out.resolve()
    ctx = _check_h130_sources()
    ctx["h110_recipe"] = _h110_recipe(ctx)
    owners = _owner_rows(ctx)
    ctx["owners"] = owners

    # The input manifest is written first because the request records its hash.
    input_manifest_path = out / "F1_ECC_H130_STRICT_CPU_AUDIT_INPUTS.json"
    input_manifest = build_strict_cpu_audit_input_manifest(ctx, input_manifest_path)
    save(input_manifest_path, input_manifest)
    input_manifest["manifest_binding_after_write"] = binding(input_manifest_path)
    save(input_manifest_path, input_manifest)

    audit_request_path = out / "F1_ECC_H130_STRICT_CPU_AUDIT_REQUEST.json"
    audit_request = build_strict_cpu_audit_request(ctx, input_manifest_path)
    save(audit_request_path, audit_request)

    domain = build_physical_domain(ctx)
    domain_path = out / "F1_ECC_STAGE1_PHYSICAL_DOMAIN.json"
    save(domain_path, domain)

    builder_binding = binding(HERE / "derive_f1_ecc_sidecars.py")
    manifest = build_case_manifest(ctx, audit_request=audit_request_path, builder_binding=builder_binding)
    manifest_path = out / "F1_ECC_STAGE1_CASE_MANIFEST.json"
    save(manifest_path, manifest)

    request = build_h130_request(manifest["cases"][-1], ctx, audit_request_path)
    request_path = out / "requests" / f"{CASE_ID}.json"
    save(request_path, request)

    entry = build_scope_entry(ctx, domain_path, manifest_path)
    save(out / "F1_ECC_STAGE1_SCOPE_ENTRY.template.json", entry)
    fixture = build_fixture_index(ctx, entry)
    save(out / "F1_ECC_AUTHORIZE_PREFLIGHT_INDEX.fixture.json", fixture)
    save(out / "F1_ECC_H130_EVIDENCE_BUILD_SPEC.json", build_sidecar_contract())
    save(
        out / "F1_ECC_STAGE1_REQUEST_SET.template.json",
        {
            "schema": "ds02.stage1.f1.ecc.request-set.v1",
            "source_only": True,
            "execution_allowed": False,
            "production_scope_approval": False,
            "q_n": "not_granted",
            "scope_id": SCOPE_ID,
            "case_ids": [CASE_ID],
            "request_paths": [str(request_path.resolve())],
            "manifest": binding(manifest_path),
            "strict_cpu_audit_request": binding(audit_request_path),
        },
    )
    return {
        "output": str(out),
        "domain": str(domain_path),
        "manifest": str(manifest_path),
        "request": str(request_path),
        "strict_cpu_audit_request": str(audit_request_path),
        "fixture_index": str(out / "F1_ECC_AUTHORIZE_PREFLIGHT_INDEX.fixture.json"),
    }


def main(argv: list[str] | None = None) -> int:
    del argv
    result = build_source_package()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BindingBuildError",
    "CASE_ID",
    "EXPECTED_FLUID",
    "EXPECTED_FRAMES",
    "EXPECTED_TOTAL",
    "SCOPE_ID",
    "attach_worker_outputs",
    "build_source_package",
    "build_strict_cpu_audit_request",
    "build_strict_cpu_audit_input_manifest",
    "refresh_request_bindings",
]
