#!/usr/bin/env python3
"""Build and validate the F1 Stage 1 native-to-NVMe typed conversion handoff.

This source-only builder reads bounded JSON metadata and hashes ordinary
provenance files.  It never opens BI4 particle arrays, runs GenCase,
DualSPHysics, PartVTK, or the converter.  The generated CPU conversion
requests are deliberately disabled; Root may review and enable them later.

The physical binding is copied from Root094's prospective case row and checked
against the corresponding canonical Root058/059 domain row.  The native solver
output is the completed Root094 output tree named in each request.  The
typed conversion command is the unchanged typed040 NVMe wrapper command.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
INTEGRATION_LAB = INTEGRATION_ROOT / "lagrangian-fluid-lab"
INTEGRATION_CAMPAIGN = INTEGRATION_LAB / "campaigns/ds-data-02"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")

ROOT094 = INTEGRATION_CAMPAIGN / (
    "handoff_20261003/root_stage1_f1_two_interior_actual_visual_production_094"
)
ROOT058 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_followup_058_f1_ecc_production_bindings_v1"
)
ROOT059 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_followup_059_f1_dual_production_bindings_v1"
)
SCOPE_ECC = INTEGRATION_CAMPAIGN / (
    "handoff_20261003/root_stage1_f1_ecc_four_head_observed_domain_062"
)
SCOPE_DUAL = INTEGRATION_CAMPAIGN / (
    "handoff_20261003/root_stage1_f1_dual_four_head_observed_domain_072"
)

PYTHON = INTEGRATION_LAB / ".venv/bin/python"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/"
    "official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
)
NVME_WRAPPER = INTEGRATION_LAB / "scripts/ds_data02_nvme_convert_v1.py"
DIRECT_CONVERTER = INTEGRATION_LAB / "scripts/ds_data02_direct_convert.py"
NVME_AUDIT = INTEGRATION_LAB / "scripts/ds_data02_f3_nvme_input_audit_v1.py"
CONVERTER_COMPAT = INTEGRATION_LAB / "scripts/ds_data02_convert.py"
STRICT_DISPATCH = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
GOAL = INTEGRATION_CAMPAIGN / "GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"

COMMON_INPUTS = [
    PYTHON,
    DECODER,
    PARTVTK,
    NVME_WRAPPER,
    DIRECT_CONVERTER,
    NVME_AUDIT,
    CONVERTER_COMPAT,
    STRICT_DISPATCH,
    RUNTIME,
    GOAL,
]


class BuildError(ValueError):
    """Raised when the frozen Root metadata is incomplete or drifted."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read JSON metadata: {path}") from exc


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def binding(path: Path, expected: str | None = None) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise BuildError(f"required provenance file is missing: {path}")
    actual = sha256(path)
    if expected is not None and actual != expected:
        raise BuildError(f"hash drift for {path}: {actual} != {expected}")
    return {"path": str(path), "sha256": actual}


def require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise BuildError(f"{label}: {actual!r} != {expected!r}")


def require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BuildError(f"{label} must be an object")
    return value


def prospective_row(manifest: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    rows = manifest.get("cases")
    if not isinstance(rows, list):
        raise BuildError("Root094 case manifest has no cases list")
    matches = [
        row for row in rows
        if isinstance(row, Mapping) and row.get("case_id") == case_id
    ]
    if len(matches) != 1:
        raise BuildError(f"Root094 manifest must have exactly one {case_id} row")
    row = matches[0]
    require_equal(row.get("role"), "prospective", f"{case_id} role")
    return row


def qa_row(document: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    rows = document.get("cases")
    if not isinstance(rows, list):
        raise BuildError("QA031 has no cases list")
    matches = [
        row for row in rows
        if isinstance(row, Mapping) and row.get("case_id") == case_id
    ]
    if len(matches) != 1:
        raise BuildError(f"QA031 must have exactly one {case_id} row")
    return matches[0]


def sidecar(path: Path, expected: str | None = None) -> dict[str, str]:
    return binding(path, expected)


def case_config(family: str) -> dict[str, Any]:
    if family == "ecc":
        case_id = "F1_STAGE1_ECC_H130_DP010"
        head = "130"
        scope_id = "F1_ECC_STAGE1_FIRST4_HEAD0110_0190_VISUAL_V1"
        root_scope = SCOPE_ECC
        domain_dir = ROOT058
        domain_file = domain_dir / "F1_ECC_STAGE1_PHYSICAL_DOMAIN.json"
        manifest = ROOT094 / "ecc/case-manifest.json"
        request = ROOT094 / "ecc/request.json"
        worker_bindings = ROOT094 / "ecc/F1_ECC_H130_WORKER_OUTPUT_BINDINGS.json"
        semantics = DATA_ROOT / case_id / (
            "root-stage1-f1-ecc-h130-full161-native-visual-production-094/"
            "execution-receipt.visual-stage1-semantics.json"
        )
        solver_receipt = DATA_ROOT / case_id / (
            "root-stage1-f1-ecc-h130-full161-native-visual-production-094/"
            "execution-receipt.json"
        )
        solver_log = solver_receipt.parent / "solver_output/Run.out"
        data_root = solver_receipt.parent / "solver_output/data"
        gencase_receipt = DATA_ROOT / case_id / (
            "root-stage1-ecc-h130-actual-gencase-027/execution-receipt.json"
        )
        prepared_report = gencase_receipt.parent / "prepared/prepared-input-report.json"
        generated_xml = gencase_receipt.parent / "prepared/F1_STAGE1_ECC_H130_DP010.xml"
        audit_dir = DATA_ROOT / case_id / "root-stage1-f1-ecc-h130-actual-initial-audit-092"
        audit_receipt = audit_dir / "execution-receipt.json"
        qa = DATA_ROOT / "F1_STAGE1_SIX_NEW_HEAD_ACTUAL_INITIAL_QA" / (
            "root-stage1-six-new-head-actual-native-initial-qa-031/native-initial-qa.json"
        )
        old_receipt = DATA_ROOT / "F1_STAGE1_ECC_H110_DP010" / (
            "root-stage1-ecc-h110-physical-endpoint-full-native-032/"
            "execution-receipt.json"
        )
        old_log = old_receipt.parent / "stdout.log"
        physical_scope = "F1_ECC_STAGE1_PHYSICAL_DOMAIN.json"
        resolution = "dp010_stage1_ecc_native_nvme"
        conversion_attempt = "root-stage1-f1-ecc-h130-full161-native-typed-nvme-063"
        selected_domain_hash = "0ba2790d9050752999ce88de2d78e0b7ab4c7656349ea1b4266db2e01791c987"
        expected = {
            "total": 136276,
            "fluid": 34840,
            "frames": 161,
            "window": [0.0, 1.6],
            "dp": 0.01,
            "physical_hash": "16ba07faf7b61f7d97f4bfc9d88a315293292107f1390ca860c15825a3bdb36e",
            "mass": 34.84,
            "scope_hash": selected_domain_hash,
        }
        native_solver_source = DATA_ROOT / "F1_STAGE1_ECC_H110_DP010" / (
            "root-stage1-ecc-h110-physical-endpoint-full-native-032/"
            "execution-receipt.json"
        )
    elif family == "dual":
        case_id = "F1_STAGE1_DUAL_H260_DP020"
        head = "260"
        scope_id = "F1_DUAL_STAGE1_FIRST4_HEAD0220_0340_VISUAL_V1"
        root_scope = SCOPE_DUAL
        domain_dir = ROOT059
        domain_file = domain_dir / "F1_DUAL_STAGE1_PHYSICAL_DOMAIN.json"
        manifest = ROOT094 / "dual/case-manifest.json"
        request = ROOT094 / "dual/request.json"
        worker_bindings = ROOT094 / "dual/F1_DUAL_H260_WORKER_OUTPUT_BINDINGS.json"
        semantics = DATA_ROOT / case_id / (
            "root-stage1-f1-dual-h260-full401-native-visual-production-094/"
            "execution-receipt.visual-stage1-semantics.json"
        )
        solver_receipt = DATA_ROOT / case_id / (
            "root-stage1-f1-dual-h260-full401-native-visual-production-094/"
            "execution-receipt.json"
        )
        solver_log = solver_receipt.parent / "solver_output/Run.out"
        data_root = solver_receipt.parent / "solver_output/data"
        gencase_receipt = DATA_ROOT / case_id / (
            "root-stage1-dual-h260-actual-gencase-027/execution-receipt.json"
        )
        prepared_report = gencase_receipt.parent / "prepared/prepared-input-report.json"
        generated_xml = gencase_receipt.parent / "prepared/F1_STAGE1_DUAL_H260_DP020.xml"
        audit_dir = DATA_ROOT / case_id / "root-stage1-f1-dual-h260-actual-initial-audit-092"
        audit_receipt = audit_dir / "execution-receipt.json"
        qa = DATA_ROOT / "F1_STAGE1_SIX_NEW_HEAD_ACTUAL_INITIAL_QA" / (
            "root-stage1-six-new-head-actual-native-initial-qa-031/native-initial-qa.json"
        )
        old_receipt = DATA_ROOT / "F1_STAGE1_DUAL_H220_DP020" / (
            "root-stage1-dual-h220-physical-endpoint-full-native-032/"
            "execution-receipt.json"
        )
        old_log = old_receipt.parent / "stdout.log"
        physical_scope = "F1_DUAL_STAGE1_PHYSICAL_DOMAIN.json"
        resolution = "dp020_stage1_dual_native_nvme"
        conversion_attempt = "root-stage1-f1-dual-h260-full401-native-typed-nvme-063"
        selected_domain_hash = "11a7372afa6b25376669bccc013e0b456de33a010055b9d428cfeb800ddd88f9"
        expected = {
            "total": 120316,
            "fluid": 32500,
            "frames": 401,
            "window": [0.0, 4.0],
            "dp": 0.02,
            "physical_hash": "238906071b2bc9742a66966ea707ae2d0de0fd0029c204c29636f415bc4a551c",
            "mass": 260.0,
            "scope_hash": selected_domain_hash,
        }
        native_solver_source = DATA_ROOT / "F1_STAGE1_DUAL_H220_DP020" / (
            "root-stage1-dual-h220-physical-endpoint-full-native-032/"
            "execution-receipt.json"
        )
    else:
        raise BuildError(f"unsupported family: {family}")
    return locals()


def read_case(family: str) -> dict[str, Any]:
    cfg = case_config(family)
    manifest_doc = require_mapping(load(cfg["manifest"]), "Root094 case manifest")
    request_doc = require_mapping(load(cfg["request"]), "Root094 actual request")
    row = prospective_row(manifest_doc, cfg["case_id"])
    binding = require_mapping(row.get("physical_binding"), "Root094 physical_binding")
    domain_doc = require_mapping(load(cfg["domain_file"]), "canonical physical domain")
    domain_row = prospective_row(domain_doc, cfg["case_id"])
    require_equal(
        binding,
        domain_row.get("physical_binding"),
        f"{family} Root094 vs canonical physical binding",
    )
    require_equal(
        row.get("physical_condition_sha256"),
        domain_row.get("physical_condition_sha256"),
        f"{family} physical condition hash",
    )
    require_equal(
        canonical_hash(binding),
        row.get("physical_condition_sha256"),
        f"{family} canonical physical condition hash",
    )

    require_equal(request_doc.get("case_id"), cfg["case_id"], f"{family} actual request case")
    require_equal(request_doc.get("physical_condition_sha256"), cfg["expected"]["physical_hash"], f"{family} request physical hash")
    require_equal(request_doc.get("native_particles"), cfg["expected"]["total"], f"{family} request total")
    require_equal(request_doc.get("native_fluid_particles"), cfg["expected"]["fluid"], f"{family} request fluid")
    require_equal(request_doc.get("expected_saved_frames"), cfg["expected"]["frames"], f"{family} request frames")
    require_equal(request_doc.get("event_window_s"), cfg["expected"]["window"], f"{family} request window")
    require_equal(request_doc.get("native_frame_interval_s"), 0.01, f"{family} request output interval")
    require_equal(request_doc.get("parameter_tuple", {}).get("dp_m"), cfg["expected"]["dp"], f"{family} request dp")
    require_equal(request_doc.get("source_only"), True, f"{family} Root094 source-only marker")

    # Freeze the actual mother endpoint recipe that governs this prospective
    # production prefix.  This is provenance only: the package never launches
    # the transformed solver command.
    source_receipt = require_mapping(load(cfg["old_receipt"]), f"{family} native032 source receipt")
    source_request = require_mapping(source_receipt.get("request"), f"{family} native032 source request")
    source_command = source_request.get("command")
    if not isinstance(source_command, list) or not all(isinstance(arg, str) for arg in source_command):
        raise BuildError(f"{family} native032 source command is not an argv list")
    require_equal(source_command[-2:], [
        f"-tmax:{str(cfg['expected']['window'][1]).rstrip('0').rstrip('.')}",
        "-tout:0.01",
    ], f"{family} native032 exact solver options")
    require_equal(source_request.get("expected_native_frames"), cfg["expected"]["frames"], f"{family} native032 frame count")
    require_equal(source_request.get("physical_window_s"), [int(cfg["expected"]["window"][0]), cfg["expected"]["window"][1]], f"{family} native032 physical window")
    require_equal(source_request.get("actual_execution_parameters", {}).get("Boundary"), "1", f"{family} native032 Boundary")
    require_equal(source_request.get("actual_execution_parameters", {}).get("TimeOut"), "0.01", f"{family} native032 TimeOut")
    if any("mdbc" in str(arg).lower() for arg in source_command):
        raise BuildError(f"{family} native032 source command unexpectedly contains an mdbc option")
    if family == "ecc" and "mDBC no-slip" not in cfg["old_log"].read_text(encoding="utf-8", errors="replace"):
        raise BuildError("ECC H110 native032 stdout does not preserve the mDBC no-slip feature record")
    target_prefix = str(cfg["gencase_receipt"].parent / "prepared" / cfg["case_id"])
    transformed_command = list(source_command)
    transformed_command[1] = target_prefix
    transformed_command[2] = "{attempt_root}/solver_output"
    native_recipe = {
        "schema": f"ds02.f1.{family}.stage1.native032-recipe.v1",
        "source_receipt": sidecar(cfg["old_receipt"]),
        "source_runtime_log": sidecar(cfg["old_log"]),
        "source_request_command": source_command,
        "source_runtime_receipt_command": source_receipt.get("command"),
        "cwd": source_request.get("cwd"),
        "expected_native_frames": source_request.get("expected_native_frames"),
        "physical_window_s": source_request.get("physical_window_s"),
        "dp_m": cfg["expected"]["dp"],
        "save_interval_s": 0.01,
        "boundary_parameter": source_request.get("actual_execution_parameters", {}).get("Boundary"),
        "boundary_feature_record": "mDBC no-slip" if family == "ecc" else None,
        "actual_execution_parameters": copy.deepcopy(source_request.get("actual_execution_parameters")),
        "actual_generated_constants": copy.deepcopy(source_request.get("actual_generated_constants")),
        "command_options_reused_exactly": True,
        "command_has_no_extra_mdbc_option": True,
        "transformed_request_command": transformed_command,
        "prefix_transform": {
            "source_prefix": source_command[1],
            "target_prefix": target_prefix,
            "output_transform": "{attempt_root}/solver_output",
            "physical_definition_unchanged": True,
        },
    }

    solver = require_mapping(load(cfg["solver_receipt"]), f"{family} Root094 solver receipt")
    require_equal(solver.get("status"), "completed", f"{family} solver status")
    require_equal(solver.get("returncode"), 0, f"{family} solver returncode")
    require_equal(solver.get("output_root"), str(cfg["solver_receipt"].parent), f"{family} solver output root")
    command = solver.get("command")
    if not isinstance(command, list) or any("mdbc" in str(arg).lower() for arg in command):
        raise BuildError(f"{family} actual solver command unexpectedly contains an mdbc option")
    require_equal(command[-2:], [
        f"-tmax:{str(cfg['expected']['window'][1]).rstrip('0').rstrip('.')}",
        "-tout:0.01",
    ], f"{family} actual solver time options")
    # The actual output tree is only named and counted through filesystem
    # metadata here.  No Part_*.bi4 bytes are opened or hashed.
    if not cfg["data_root"].is_dir() or not cfg["solver_log"].is_file():
        raise BuildError(f"{family} Root094 solver output metadata is incomplete")
    frame_paths = sorted(cfg["data_root"].glob("Part_*.bi4"))
    require_equal(len(frame_paths), cfg["expected"]["frames"], f"{family} native frame count")
    if not (cfg["data_root"] / "PartInfo.ibi4").is_file():
        raise BuildError(f"{family} Root094 PartInfo metadata is missing")

    gencase = require_mapping(load(cfg["gencase_receipt"]), f"{family} GenCase receipt")
    require_equal(gencase.get("status"), "completed", f"{family} GenCase status")
    require_equal(gencase.get("returncode"), 0, f"{family} GenCase returncode")
    require_equal(gencase.get("solver_dimension_from_gencase"), 3, f"{family} GenCase dimension")
    require_equal(gencase.get("total_particles"), cfg["expected"]["total"], f"{family} GenCase total")
    require_equal(gencase.get("fluid_particles"), cfg["expected"]["fluid"], f"{family} GenCase fluid")

    prepared = require_mapping(load(cfg["prepared_report"]), f"{family} prepared report")
    require_equal(prepared.get("case_id"), cfg["case_id"], f"{family} prepared case")
    require_equal(prepared.get("actual_total_particles"), cfg["expected"]["total"], f"{family} prepared total")
    counts = require_mapping(prepared.get("generated_xml_particle_counts"), f"{family} XML counts")
    require_equal(counts.get("fluid"), cfg["expected"]["fluid"], f"{family} XML fluid count")
    require_equal(counts.get("fixed"), cfg["expected"]["total"] - cfg["expected"]["fluid"], f"{family} XML fixed count")
    require_equal(sha256(cfg["generated_xml"]), prepared.get("xml_sha256"), f"{family} generated XML hash")
    require_equal(prepared.get("native_initial_typed_QA"), "pending actual arrays", f"{family} preflight pending marker")
    require_equal(prepared.get("mass_evidence"), "Generated XML text only; actual binary native weights pending typed QA", f"{family} preflight mass marker")

    qa_doc = require_mapping(load(cfg["qa"]), "QA031")
    qa = qa_row(qa_doc, cfg["case_id"])
    require_equal(qa.get("passed"), True, f"{family} QA031 passed")
    require_equal(qa.get("actual_3d"), True, f"{family} QA031 3D")
    require_equal(qa.get("native_particles"), cfg["expected"]["total"], f"{family} QA031 total")
    require_equal(qa.get("native_fluid"), cfg["expected"]["fluid"], f"{family} QA031 fluid")
    require_equal(qa.get("expected_types"), [0, 3], f"{family} QA031 type set")
    require_equal(qa.get("generated_xml_sha256"), prepared.get("xml_sha256"), f"{family} QA031 XML binding")

    audit = require_mapping(load(cfg["audit_receipt"]), f"{family} 092 audit receipt")
    require_equal(audit.get("status"), "completed", f"{family} 092 status")
    require_equal(audit.get("returncode"), 0, f"{family} 092 returncode")
    mass_path = cfg["audit_dir"] / "initial_mass_discrepancy_report.json"
    mass = require_mapping(load(mass_path), f"{family} actual mass audit")
    require_equal(mass.get("status"), "actual_worker_computed", f"{family} mass worker status")
    require_equal(mass.get("mass_rescaling"), False, f"{family} mass rescaling")
    require_equal(mass.get("native_fluid_particle_count"), cfg["expected"]["fluid"], f"{family} mass fluid count")
    require_equal(mass.get("continuum_reference_mass_kg"), cfg["expected"]["mass"], f"{family} mass continuum reference")
    worker_audit = load(cfg["audit_dir"] / "strict-cpu-audit.json")
    worker_audit = require_mapping(worker_audit, f"{family} strict CPU audit")
    require_equal(worker_audit.get("status"), "completed", f"{family} strict audit status")
    require_equal(worker_audit.get("returncode"), 0, f"{family} strict audit returncode")
    require_equal(worker_audit.get("solver_launched"), False, f"{family} strict audit solver marker")
    require_equal(worker_audit.get("raw_arrays_written"), False, f"{family} strict audit array marker")

    # The actual worker's computed values are copied as observations.  The
    # builder does not derive mass, weight, or discrepancy from any array.
    mass_observation = {
        key: mass.get(key)
        for key in (
            "continuum_reference_mass_kg",
            "native_fluid_mass_kg",
            "native_fluid_particle_count",
            "native_particle_weight_kg",
            "native_particle_weight_uniform",
            "mass_difference_kg",
            "relative_mass_difference",
            "mass_rescaling",
            "xml_massfluid_kg",
            "xml_massfluid_float32_kg",
            "status",
        )
    }
    return {
        "cfg": cfg,
        "manifest": manifest_doc,
        "row": row,
        "domain": domain_doc,
        "domain_row": domain_row,
        "request": request_doc,
        "solver": solver,
        "gencase": gencase,
        "prepared": prepared,
        "qa": qa,
        "audit": audit,
        "mass": mass,
        "mass_observation": mass_observation,
        "worker_audit": worker_audit,
        "native_recipe": native_recipe,
        "physical_hash_differences": [],
    }


def make_owner(ctx: Mapping[str, Any]) -> dict[str, Any]:
    cfg = ctx["cfg"]
    row = ctx["row"]
    request = ctx["request"]
    prepared = ctx["prepared"]
    qa = ctx["qa"]
    mass = ctx["mass_observation"]
    source_files = {
        "root094_case_manifest": sidecar(cfg["manifest"]),
        "root094_actual_request": sidecar(cfg["request"]),
        "root094_worker_output_bindings": sidecar(cfg["worker_bindings"]),
        "root094_semantics_receipt": sidecar(cfg["semantics"]),
        "root094_solver_receipt": sidecar(cfg["solver_receipt"]),
        "root094_solver_log": sidecar(cfg["solver_log"]),
        "genuine_gencase027_receipt": sidecar(cfg["gencase_receipt"]),
        "genuine_gencase027_prepared_report": sidecar(cfg["prepared_report"]),
        "generated_xml": sidecar(cfg["generated_xml"], prepared["xml_sha256"]),
        "qa031_metadata": sidecar(cfg["qa"]),
        "actual_initial_audit092_receipt": sidecar(cfg["audit_receipt"]),
        "actual_initial_audit092_mass": sidecar(cfg["audit_dir"] / "initial_mass_discrepancy_report.json"),
        "actual_initial_audit092_geometry": sidecar(cfg["audit_dir"] / "geometry_evidence.json"),
        "actual_initial_audit092_motion": sidecar(cfg["audit_dir"] / "motion_evidence.json"),
        "actual_initial_audit092_no_overlap": sidecar(cfg["audit_dir"] / "no_overlap_finite_state_evidence.json"),
        "actual_initial_audit092_physics": sidecar(cfg["audit_dir"] / "physics_evidence.json"),
        "actual_initial_audit092_strict": sidecar(cfg["audit_dir"] / "strict-cpu-audit.json"),
        "root_domain_source": sidecar(cfg["domain_file"], cfg["expected"]["scope_hash"]),
        "root_visual_scope_decision": sidecar(cfg["root_scope"] / "root-visual-domain-decision.json"),
        "native_recipe_source_receipt": sidecar(cfg["old_receipt"]),
        "native_recipe_source_log": sidecar(cfg["old_log"]),
        "goal_authority": sidecar(GOAL),
    }
    native_type_binding = {
        "axis_source": "GenCase generated typed ranges plus decoder Idp; full converter retains generated initial axis",
        "actual_3d": qa["actual_3d"],
        "actual_total_particles": qa["native_particles"],
        "actual_fluid_particles": qa["native_fluid"],
        "expected_types": qa["expected_types"],
        "native_type_counts": qa["native_type_counts"],
        "fluid_type": 3,
        "fluid_mk": 1,
        "fluid_cohort_semantics": "physical binding source label: Initial Type3/Mk1 cohort",
        "uid_policy": "original native Idp identity; no interpolation, reindexing, or cohort resampling",
    }
    return {
        "schema": "ds02.f1.stage1.native-nvme-typed-owner.v1",
        "family_id": "F1",
        "case_id": cfg["case_id"],
        "physical_case_id": row["physical_case_id"],
        "mechanism_id": row["mechanism_id"],
        "physical_condition_sha256": row["physical_condition_sha256"],
        "physical_hash_differences": ctx["physical_hash_differences"],
        "physical_binding": copy.deepcopy(row["physical_binding"]),
        "resolution": cfg["resolution"],
        "native_frame_contract": {
            "event_window_s": cfg["expected"]["window"],
            "save_interval_s": 0.01,
            "expected_saved_frames": cfg["expected"]["frames"],
            "dp_m": cfg["expected"]["dp"],
            "source_solver_completed": True,
        },
        "eos": copy.deepcopy(prepared["actual_generated_constants"]),
        "native_typed_identity": native_type_binding,
        "mass_audit_observation": mass,
        "mass_policy": {
            "name": "native_massfluid_no_rescaling",
            "rescale": False,
            "source": "Root092 actual worker mass discrepancy report",
            "continuum_reference_is_physical_geometry": True,
            "native_weight_is_worker_observation": True,
        },
        "solver_provenance": {
            "actual_completed_root094_receipt": source_files["root094_solver_receipt"],
            "actual_command_has_no_mdbc_option": True,
            "source_native_recipe_receipt": source_files["native_recipe_source_receipt"],
            "source_native_recipe_log": source_files["native_recipe_source_log"],
            "native_solver_recipe": copy.deepcopy(ctx["native_recipe"]),
            "solver_recipe_reused_for_production": True,
            "solver_recipe_note": "Conversion consumes the completed Root094 native output; no solver is launched by this package.",
        },
        "converter_contract": {
            "schema": "ds-data-02.bi4-direct-conversion.v1",
            "wrapper": sidecar(NVME_WRAPPER),
            "direct_converter": sidecar(DIRECT_CONVERTER),
            "stage_root": "/tmp/ds02-nvme-conversion",
            "publish_policy": "checksum-verified NVMe staging then final publication",
            "typed_fields": ["Idp", "Zone", "Type", "Mk", "position", "velocity", "density", "mass", "pressure"],
            "partvtk_validation": True,
            "raw_tree_mutation": False,
            "mass_rescaling": False,
        },
        "source": source_files,
        "claims": {
            "independent_case_count_increment": 0,
            "numerical_precision_status": "not_accepted",
            "q_n": "not_granted",
            "visual_review": "pending post-conversion full saved-frame integrity and Root case decision",
            "conversion_status": "source_only_disabled_pending_root_actual_conversion",
        },
    }


def conversion_command(ctx: Mapping[str, Any], owner_path: Path) -> list[str]:
    cfg = ctx["cfg"]
    return [
        str(PYTHON),
        str(NVME_WRAPPER),
        "--staging-root",
        "/tmp/ds02-nvme-conversion",
        "--staging-limit-bytes",
        "51539607552",
        "--",
        "--data-root",
        str(cfg["data_root"]),
        "--generated-xml",
        str(cfg["generated_xml"]),
        "--output",
        "{attempt_root}/trajectory.h5",
        "--report",
        "{attempt_root}/conversion-report.json",
        "--solver-log",
        str(cfg["solver_log"]),
        "--solver-receipt",
        str(cfg["solver_receipt"]),
        "--gencase-receipt",
        str(cfg["gencase_receipt"]),
        "--decoder",
        str(DECODER),
        "--partvtk",
        str(PARTVTK),
        "--validation-dir",
        "{attempt_root}/partvtk-validation",
        "--keep-validation-csv",
        "--owner-metadata",
        str(owner_path),
        "--particle-chunk",
        "65536",
    ]


def conversion_inputs(ctx: Mapping[str, Any], owner_path: Path) -> list[Path]:
    cfg = ctx["cfg"]
    paths = list(COMMON_INPUTS)
    paths.extend(
        [
            HERE / "build_f1_stage1_nvme_typed_requests.py",
            owner_path,
            cfg["manifest"],
            cfg["request"],
            cfg["worker_bindings"],
            cfg["semantics"],
            cfg["solver_receipt"],
            cfg["solver_log"],
            cfg["gencase_receipt"],
            cfg["prepared_report"],
            cfg["generated_xml"],
            cfg["qa"],
            cfg["audit_receipt"],
            cfg["audit_dir"] / "initial_mass_discrepancy_report.json",
            cfg["audit_dir"] / "geometry_evidence.json",
            cfg["audit_dir"] / "motion_evidence.json",
            cfg["audit_dir"] / "no_overlap_finite_state_evidence.json",
            cfg["audit_dir"] / "physics_evidence.json",
            cfg["audit_dir"] / "strict-cpu-audit.json",
            cfg["domain_file"],
            cfg["root_scope"] / "root-visual-domain-decision.json",
            cfg["old_receipt"],
            cfg["old_log"],
        ]
    )
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.resolve()
        if str(resolved) not in seen:
            result.append(resolved)
            seen.add(str(resolved))
    return result


def make_request(ctx: Mapping[str, Any], owner_path: Path) -> dict[str, Any]:
    cfg = ctx["cfg"]
    owner = load(owner_path)
    input_paths = conversion_inputs(ctx, owner_path)
    input_bindings = [binding(path) for path in input_paths]
    input_hashes = {item["path"]: item["sha256"] for item in input_bindings}
    command = conversion_command(ctx, owner_path)
    if any("mdbc" in arg.lower() for arg in command):
        raise BuildError(f"{cfg['case_id']} conversion command contains an mdbc option")
    expected = cfg["expected"]
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F1",
        "case_id": cfg["case_id"],
        "attempt_id": cfg["conversion_attempt"],
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 2,
        "max_wall_seconds": 10800,
        "estimated_storage_bytes": 51539607552,
        "cwd": str(INTEGRATION_LAB),
        "worktree_root": str(INTEGRATION_ROOT),
        "command": command,
        "input_files": [item["path"] for item in input_bindings],
        "input_sha256": input_hashes,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "request_status": "disabled_pending_root_actual_conversion",
        "launch_owner": "root",
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "claim": "Full completed native output to typed NVME conversion evidence; original Idp/Type/Mk/mass/velocity/rho/pressure retained by the converter; no Q-N, precision, production, or new solver claim.",
        "scope_id": cfg["scope_id"],
        "root094_case_manifest": sidecar(cfg["manifest"]),
        "root094_actual_request": sidecar(cfg["request"]),
        "root094_solver_receipt": sidecar(cfg["solver_receipt"]),
        "root094_solver_status": {
            "status": ctx["solver"]["status"],
            "returncode": ctx["solver"]["returncode"],
            "output_root": ctx["solver"]["output_root"],
        },
        "native_source": {
            "data_root": str(cfg["data_root"]),
            "data_root_frames": expected["frames"],
            "raw_part_arrays_read_by_builder": False,
            "raw_part_arrays_hashed_by_builder": False,
            "completed_root094_output_is_input": True,
        },
        "genuine_generation": {
            "gencase_receipt": sidecar(cfg["gencase_receipt"]),
            "prepared_report": sidecar(cfg["prepared_report"]),
            "generated_xml": sidecar(cfg["generated_xml"]),
            "actual_3d": True,
            "total_particles": expected["total"],
            "fluid_particles": expected["fluid"],
        },
        "initial_qa031": sidecar(cfg["qa"]),
        "initial_audit092": {
            "receipt": sidecar(cfg["audit_receipt"]),
            "mass": sidecar(cfg["audit_dir"] / "initial_mass_discrepancy_report.json"),
            "geometry": sidecar(cfg["audit_dir"] / "geometry_evidence.json"),
            "motion": sidecar(cfg["audit_dir"] / "motion_evidence.json"),
            "no_overlap": sidecar(cfg["audit_dir"] / "no_overlap_finite_state_evidence.json"),
            "physics": sidecar(cfg["audit_dir"] / "physics_evidence.json"),
            "strict": sidecar(cfg["audit_dir"] / "strict-cpu-audit.json"),
            "mass_rescaling": False,
        },
        "physical_case_id": ctx["row"]["physical_case_id"],
        "physical_condition_sha256": ctx["row"]["physical_condition_sha256"],
        "physical_hash_differences": [],
        "physical_binding": copy.deepcopy(ctx["row"]["physical_binding"]),
        "geometry": copy.deepcopy(ctx["row"]["geometry"]),
        "mechanism_id": ctx["row"]["mechanism_id"],
        "geometry_family_id": ctx["row"]["geometry_family_id"],
        "control_family_id": ctx["row"]["control_family_id"],
        "parameter_tuple": copy.deepcopy(ctx["row"]["parameter_tuple"]),
        "event_window_s": expected["window"],
        "native_frame_interval_s": 0.01,
        "expected_native_frames": expected["frames"],
        "continuum_reference_mass_kg": expected["mass"],
        "native_particles": expected["total"],
        "native_fluid_particles": expected["fluid"],
        "native_mass_policy": "native_massfluid_no_rescaling",
        "numerical_precision_status": "not_accepted",
        "q_e": "not_assessed",
        "q_n": "not_granted",
        "no_mass_rescaling": True,
        "no_extra_mdbc_option": True,
        "solver_recipe_provenance": {
            "actual_completed_native_output": sidecar(cfg["solver_receipt"]),
            "source_native_recipe_receipt": sidecar(cfg["old_receipt"]),
            "source_native_recipe_log": sidecar(cfg["old_log"]),
            "exact_source_request_recipe": copy.deepcopy(ctx["native_recipe"]),
            "solver_command_options_are_not_part_of_conversion_argv": True,
        },
        "owner_metadata": sidecar(owner_path),
        "converter": {
            "schema": "ds-data-02.bi4-direct-conversion.v1",
            "wrapper": sidecar(NVME_WRAPPER),
            "direct_converter": sidecar(DIRECT_CONVERTER),
            "partvtk": sidecar(PARTVTK),
            "decoder": sidecar(DECODER),
            "typed_fields": ["Idp", "Zone", "Type", "Mk", "position", "velocity", "density", "mass", "pressure"],
            "expected_output": "{attempt_root}/trajectory.h5",
            "expected_report": "{attempt_root}/conversion-report.json",
            "full_native_timeline": True,
            "partvtk_validation": True,
            "nvme_staging_root": "/tmp/ds02-nvme-conversion",
            "staging_limit_bytes": 51539607552,
        },
        "conversion_command_contract": {
            "command_reused_from_typed040": True,
            "command_has_no_mdbc_argument": True,
            "solver_not_launched": True,
            "raw_arrays_not_read_by_builder": True,
        },
    }


def build() -> dict[str, Any]:
    contexts = {family: read_case(family) for family in ("ecc", "dual")}
    owners: dict[str, Path] = {}
    requests: dict[str, Path] = {}
    for family, ctx in contexts.items():
        owner_path = HERE / "owners" / f"{ctx['cfg']['case_id']}.owner.json"
        save(owner_path, make_owner(ctx))
        owner = load(owner_path)
        require_equal(
            canonical_hash(owner["physical_binding"]),
            owner["physical_condition_sha256"],
            f"{family} owner physical binding hash",
        )
        request_path = HERE / "requests" / f"{ctx['cfg']['case_id']}.request.json"
        request = make_request(ctx, owner_path)
        save(request_path, request)
        owners[family] = owner_path
        requests[family] = request_path
    manifest = {
        "schema": "ds02.f1.stage1.native-nvme-typed-handoff.v1",
        "package_status": "source_only_disabled_pending_root_actual_conversion",
        "family_id": "F1",
        "handoff_id": "root_followup_063_f1_native_nvme_typed_conversion_v1",
        "source_only": True,
        "execution_allowed": False,
        "solver_launched": False,
        "converter_launched": False,
        "raw_arrays_read": False,
        "raw_arrays_hashed": False,
        "shared_index_or_ledger_modified": False,
        "physical_hash_differences": [],
        "cases": [],
        "builder": sidecar(HERE / "build_f1_stage1_nvme_typed_requests.py"),
    }
    for family, ctx in contexts.items():
        owner = load(owners[family])
        request = load(requests[family])
        manifest["cases"].append(
            {
                "family_variant": family,
                "case_id": ctx["cfg"]["case_id"],
                "owner": sidecar(owners[family]),
                "request": sidecar(requests[family]),
                "scope_id": ctx["cfg"]["scope_id"],
                "physical_condition_sha256": ctx["row"]["physical_condition_sha256"],
                "physical_hash_differences": [],
                "dp_m": ctx["cfg"]["expected"]["dp"],
                "event_window_s": ctx["cfg"]["expected"]["window"],
                "save_interval_s": 0.01,
                "expected_native_frames": ctx["cfg"]["expected"]["frames"],
                "actual_gencase": {
                    "status": ctx["gencase"]["status"],
                    "returncode": ctx["gencase"]["returncode"],
                    "total_particles": ctx["gencase"]["total_particles"],
                    "fluid_particles": ctx["gencase"]["fluid_particles"],
                    "dimension": ctx["gencase"]["solver_dimension_from_gencase"],
                },
                "actual_initial_audit": {
                    "status": ctx["audit"]["status"],
                    "returncode": ctx["audit"]["returncode"],
                    "mass_rescaling": ctx["mass_observation"]["mass_rescaling"],
                    "native_fluid_mass_kg": ctx["mass_observation"]["native_fluid_mass_kg"],
                    "native_particle_weight_kg": ctx["mass_observation"]["native_particle_weight_kg"],
                    "mass_difference_kg": ctx["mass_observation"]["mass_difference_kg"],
                },
                "request_disabled": {
                    "launch_allowed": request["launch_allowed"],
                    "execution_allowed": request["execution_allowed"],
                },
                "owner_physical_binding_keys": sorted(owner["physical_binding"]),
            }
        )
    save(HERE / "manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    result = build()
    print(json.dumps(result, ensure_ascii=False, indent=2))
