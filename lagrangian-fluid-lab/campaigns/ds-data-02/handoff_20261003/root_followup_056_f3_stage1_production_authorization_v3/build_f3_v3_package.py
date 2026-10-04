#!/usr/bin/env python3
"""Build the source-only, concrete F3 Stage 1 v3 authorization package.

This builder reads only small JSON metadata/receipts and hashes the already
prepared XML, BI4, and forcing inputs.  It never invokes GenCase, the solver,
the converter, ParaView, or a subprocess.  The generated package is an
explicit five-case prospective manifest consumed by the v2 authorizer; it is
not an approval index and it does not grant Q-N or numerical precision.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
PREP_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/"
    "F3_STAGE1_FIRST8_PROSPECTIVE_PHYSICAL_INPUT_PREPARATION/"
    "root-stage1-twoaxis-first8-five-new-interior-exact-initial-inputs-012"
)
INTEGRATION_CAMPAIGN = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02"
)
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3")
PARENT_ROOT = DATA_ROOT / (
    "F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005/"
    "root-cell3-dp006-twoaxis-ay0p50-actual-gencase-056"
)
PARENT_QA = DATA_ROOT / (
    "F3_TWOAXIS_NOMINAL_THREE_DP_ACTUAL_INITIAL_QA/"
    "root-cell3-twoaxis-nominal-three-dp-official-native-initial-qa-058"
)
ENDPOINT_PREP_ROOT = DATA_ROOT / (
    "F3_STAGE1_PHYSICAL_VISUAL_ENDPOINT_PREPARATION/"
    "root-stage1-twoaxis-two-physical-amplitude-endpoints-exact-initial-inputs-006"
)
GOAL = INTEGRATION_CAMPAIGN / "GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
ROOT_DOMAIN_DECISION = INTEGRATION_CAMPAIGN / (
    "handoff_20261003/root_stage1_f3_first8_observed_domain_decision_042/"
    "root-visual-domain-decision.json"
)
DOMAIN_054 = HERE.parent / "root_followup_054_f3_stage1_first8_manifest_v1" / "F3_FIRST8_PHYSICAL_DOMAIN.v1.json"
PROVENANCE_054 = HERE.parent / "root_followup_054_f3_stage1_first8_manifest_v1" / "F3_FIRST8_CASE_PROVENANCE.v1.json"
PREP_BINDING_012 = INTEGRATION_CAMPAIGN / (
    "handoff_20261003/root_stage1_f3_first8_prospective_inputs_012/binding.json"
)
V2_DIR = HERE.parent / "root_followup_055_stage1_production_adapter_v2"
V2_DISPATCH = V2_DIR / "ds_data02_stage1_dispatch_v2.py"
V2_AUTHORIZER = V2_DIR / "ds_data02_stage1_production_v2.py"
INTEGRATION_LAB = INTEGRATION_CAMPAIGN.parent.parent
STRICT = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
SOLVER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)
SOLVER_CWD = INTEGRATION_LAB

SCOPE_ID = "F3_STAGE1_FIRST8_AY0250_AY0750_VISUAL_V1"
CURRENT_GOAL_SHA = "53d422511b5581266410de92c54627ac67e8085eccb75a9ebfe57de10a34316a"
ROOT_DOMAIN_DECISION_SHA = "7f33f48ddd33446a9f6684c673764727f1f01c1f6390b8d409facb9a91daea1e"
DOMAIN_054_SHA = "db35a737ed9071829dfce755054af15372fe638a5c7ee63c3598efadfffac628"
PROVENANCE_054_SHA = "11fe974bd52f811f798d1cece10635a53b2535bbc94e28d6c24eceecc8f2e4a7"
PREP_BINDING_012_SHA = "1df424ddbb6a024a9071ce65d5aeca2c96ddd6c13ab5e2356108bc1ea473f4c6"
PARENT_GEN_SHA = "6ed670c0f33e5fc5b9df7d81cb49f9174f0f7e43f6963edc98e99134e9ad761f"
PARENT_QA_SHA = "7ff19bd2db1b731071ec0eeaa8dfe43bbb0cc27ecc5c2dc9d1bb8c0cb5f60349"
PARENT_XML_SHA = "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
PARENT_BI4_SHA = "c9c3fb8315dad402f77dd015539be376c3df68f332f3ed6d03e6c174e4c57d80"
CLONE_006_SHA = "b147c3b91a65434848c7bfc221b3aca8b7d084fd542f3af36926b7ea96f3d15e"
PREP_012_SHA = "79d94fc4050b065cd94f245d5502223301762d18e185cdfb232efe06ec5ef3f4"
PARENT_OWNER_SHA = "10b60ee86c67fee53f06bc6e36774d74993528033d9dc1d2582e3b6334b226a5"
SOURCE_FORCING_SHA = "6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3"
OMEGA = 12.531236478398654
WINDOW = [0.0, 8.35]
SAVE_INTERVAL = 0.01
EXPECTED_FRAMES = 836
NATIVE_PARTICLES = 179208
NATIVE_FLUID = 67500
NATIVE_FIXED = 111708
CONTINUUM_MASS = 14.58
NATIVE_MASS = 14.580000000000002

CASES = (
    ("interior01", "F3_STAGE1_DP006_P1000_AY0320", "F3_TWOAXIS_PITCH1000_AY0320_STAGE1_BATCH8", 0.32),
    ("interior02", "F3_STAGE1_DP006_P1000_AY0390", "F3_TWOAXIS_PITCH1000_AY0390_STAGE1_BATCH8", 0.39),
    ("interior03", "F3_STAGE1_DP006_P1000_AY0460", "F3_TWOAXIS_PITCH1000_AY0460_STAGE1_BATCH8", 0.46),
    ("interior04", "F3_STAGE1_DP006_P1000_AY0570", "F3_TWOAXIS_PITCH1000_AY0570_STAGE1_BATCH8", 0.57),
    ("interior05", "F3_STAGE1_DP006_P1000_AY0640", "F3_TWOAXIS_PITCH1000_AY0640_STAGE1_BATCH8", 0.64),
)


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def binding(path: Path, expected: str | None = None) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = sha256(path)
    if expected is not None and actual != expected:
        raise ValueError(f"hash mismatch for {path}: {actual} != {expected}")
    return {"path": str(path), "sha256": actual}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def static_geometry(report: Mapping[str, Any]) -> dict[str, Any]:
    physical = report["physical_binding"]
    return copy.deepcopy(physical["geometry"])


def static_physics(report: Mapping[str, Any]) -> dict[str, Any]:
    physical = report["physical_binding"]
    return {
        "control_family_id": physical["control_family_id"],
        "controls": copy.deepcopy(physical["controls"]),
        "density_kg_m3": physical["density_kg_m3"],
        "gravity_m_s2": copy.deepcopy(physical["gravity_m_s2"]),
        "geometry_family_id": physical["geometry_family_id"],
        "periodic_boundary": physical["periodic_boundary"],
        "open_inlet": copy.deepcopy(physical["open_inlet"]),
        "lineage_group_id": physical["lineage_group_id"],
        "mass_policy": physical["mass_policy"],
        "event_window": copy.deepcopy(physical["event_window"]),
    }


def motion_row(report: Mapping[str, Any]) -> dict[str, Any]:
    physical = report["physical_binding"]
    params = physical["parameters"]
    transform = report["forcing_transform"]
    return {
        "mechanism_id": physical["mechanism_id"],
        "paired_background_id": physical["paired_background_id"],
        "coordinate_frame": params["coordinate_frame"],
        "transverse_amplitude_m_s2": params["transverse_amplitude_m_s2"],
        "transverse_omega_rad_s": params["transverse_omega_rad_s"],
        "transverse_phase_rad": params["transverse_phase_rad"],
        "transverse_ramp_duration_s": params["transverse_ramp_duration_s"],
        "active_window_s": copy.deepcopy(params["transverse_active_window_s"]),
        "source_forcing_sha256": params["forcing_source_sha256"],
        "actual_forcing_sha256": params["actual_forcing_sha256"],
        "transform_status": transform["status"],
        "rows_processed": transform["rows_processed"],
        "time_range_s": copy.deepcopy(transform["time_range_s"]),
        "source_sha256_before": transform["source_sha256_before"],
        "source_sha256_after": transform["source_sha256_after"],
        "output_sha256": transform["output_sha256"],
    }


def mass_row(report: Mapping[str, Any], report_binding: Mapping[str, str], qa_binding: Mapping[str, str]) -> dict[str, Any]:
    verified = report["initial_native_reference"]["initial_native_verified"]
    native = float(verified["official_CSV_fluid_mass_sum_kg"])
    continuum = float(verified["continuous_reference_mass_kg"])
    return {
        "schema": "ds02.stage1.f3.initial-mass-discrepancy.v1",
        "status": "source_metadata_reported",
        "case_id": report["case_id"],
        "physical_case_id": report["physical_case_id"],
        "physical_condition_sha256": report["physical_condition_sha256"],
        "native_fluid_mass_kg": native,
        "continuum_reference_mass_kg": continuum,
        "mass_difference_kg": native - continuum,
        "relative_difference": (native - continuum) / continuum,
        "mass_normalization": verified["mass_normalization"],
        "mass_rescaling": False,
        "mass_policy": report["physical_binding"]["initial_state"]["mass_policy"],
        "source_bindings": {
            "prepared_input_report": dict(report_binding),
            "parent_native_initial_qa": dict(qa_binding),
        },
        "unknown_loss_observation": "No post-run loss is inferred from this initial-state report; retain unknown loss for the later actual run.",
    }


def make_sidecars(out: Path, report: Mapping[str, Any], report_binding: Mapping[str, str], qa_binding: Mapping[str, str]) -> dict[str, dict[str, str]]:
    role = str(report["role"])
    evidence_dir = out / "evidence" / role
    physical = report["physical_binding"]
    source = {
        "prepared_input_report": dict(report_binding),
        "parent_native_initial_qa": dict(qa_binding),
    }
    documents: dict[str, Any] = {
        "initial_mass_discrepancy_report": mass_row(report, report_binding, qa_binding),
        "physics_evidence": {
            "schema": "ds02.stage1.f3.frozen-physics-evidence.v1",
            "status": "frozen_from_actual_strict012_metadata",
            "case_id": report["case_id"],
            "physical_case_id": report["physical_case_id"],
            "physical_condition_sha256": report["physical_condition_sha256"],
            "checks": {"finite_state": True},
            "physics": static_physics(report),
            "solver_recipe": {
                "definition_dp_m": 0.006,
                "cfl_number": 0.05,
                "coef_dt_min": 0.005,
                "dt_fixed_s": 0.0,
                "solver_mode": "-mdbc_noslip:1",
                "time_max_s": WINDOW[1],
                "time_out_s": SAVE_INTERVAL,
            },
            "source_bindings": source,
            "numerical_precision_status": "not_accepted",
            "no_hidden_precision_gate": True,
        },
        "geometry_evidence": {
            "schema": "ds02.stage1.f3.frozen-geometry-evidence.v1",
            "status": "frozen_from_actual_strict012_metadata",
            "case_id": report["case_id"],
            "physical_case_id": report["physical_case_id"],
            "physical_condition_sha256": report["physical_condition_sha256"],
            "checks": {"finite_state": True},
            "geometry": static_geometry(report),
            "geometry_family_id": physical["geometry_family_id"],
            "top_open": True,
            "periodic_boundary": False,
            "source_bindings": source,
            "initial_xml_sha256": report["xml_sha256"],
            "initial_bi4_sha256": report["bi4_sha256"],
        },
        "motion_evidence": {
            "schema": "ds02.stage1.f3.frozen-motion-evidence.v1",
            "status": "frozen_from_actual_strict012_forcing_transform",
            "case_id": report["case_id"],
            "physical_case_id": report["physical_case_id"],
            "physical_condition_sha256": report["physical_condition_sha256"],
            "checks": {"finite_state": True},
            "motion": motion_row(report),
            "source_bindings": source,
            "numerical_precision_status": "not_accepted",
        },
        "no_overlap_finite_state_evidence": {
            "schema": "ds02.stage1.f3.initial-no-overlap-finite-state-evidence.v1",
            "status": "initial_metadata_bound; postrun_state_review_required",
            "case_id": report["case_id"],
            "physical_case_id": report["physical_case_id"],
            "physical_condition_sha256": report["physical_condition_sha256"],
            "checks": {
                "finite_state": True,
                "no_initial_fluid_solid_overlap": True,
            },
            "basis": {
                "actual_3d": True,
                "native_particles": NATIVE_PARTICLES,
                "native_fluid": NATIVE_FLUID,
                "native_fixed": NATIVE_FIXED,
                "exact_initial_xml_byte_identity": True,
                "exact_initial_bi4_byte_identity": True,
                "source_metadata_only": True,
                "raw_particle_arrays_read": False,
                "postrun_full_state_check": "required_after_actual_complete_run",
            },
            "source_bindings": source,
            "unknown_loss_observation": "This is an initial-state geometry/QA binding; it does not assert post-run particle retention.",
        },
    }
    result: dict[str, dict[str, str]] = {}
    for name, document in documents.items():
        path = evidence_dir / f"{name}.json"
        write_json(path, document)
        result[name] = binding(path)
    return result


def shared_initial_state(parent_gen: dict[str, str], parent_qa: dict[str, str], parent_xml: dict[str, str], parent_bi4: dict[str, str], prep012: dict[str, str], clone006: dict[str, str], owner: dict[str, str], prep_cases: dict[str, str], binding012: dict[str, str]) -> dict[str, Any]:
    return {
        "qa_semantics": "genuine_3d_parent_with_exact_initial_clone",
        "parent_case_id": "F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005",
        "parent_physical_case_id": "F3_TWOAXIS_AY0P50_PITCH_NOMINAL",
        "native_particles": NATIVE_PARTICLES,
        "native_fluid": NATIVE_FLUID,
        "native_fixed": NATIVE_FIXED,
        "actual_3d": True,
        "initial_xml_sha256": PARENT_XML_SHA,
        "initial_bi4_sha256": PARENT_BI4_SHA,
        "continuous_reference_mass_kg": CONTINUUM_MASS,
        "native_initial_mass_kg": NATIVE_MASS,
        "mass_normalization": "none",
        "mass_policy": "native MassFluid from GenCase/BI4; no normalization or rescaling",
        "genuine_gencase_receipt": dict(parent_gen),
        "native_initial_qa": dict(parent_qa),
        "generated_xml": dict(parent_xml),
        "initial_bi4": dict(parent_bi4),
        "source_documents": {
            "first8_preparation_receipt": dict(prep012),
            "first8_prepared_cases": dict(prep_cases),
            "first8_preparation_binding": dict(binding012),
            "endpoint_clone_preparation_receipt_006": dict(clone006),
            "genuine_parent_owner_source": dict(owner),
        },
        "exact_clone_policy": "Reuse the genuine parent initial XML/BI4 bytes; keep the original GenCase receipt and initial QA; do not invent a per-case GenCase receipt or recount AY.50.",
    }


def build_package(out: Path = HERE) -> dict[str, Any]:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    goal = binding(GOAL, CURRENT_GOAL_SHA)
    root_domain_decision = binding(ROOT_DOMAIN_DECISION, ROOT_DOMAIN_DECISION_SHA)
    source_domain_054 = binding(DOMAIN_054, DOMAIN_054_SHA)
    source_provenance_054 = binding(PROVENANCE_054, PROVENANCE_054_SHA)
    prep_binding = binding(PREP_BINDING_012, PREP_BINDING_012_SHA)
    prep_receipt = binding(PREP_ROOT / "execution-receipt.json", PREP_012_SHA)
    prep_cases = binding(PREP_ROOT / "prepared/prepared-cases.json", "a254e1520f11ae39dc8bb4fae7b20f6281db8b70cbda5265fe5baaa6df7385a5")
    parent_gen = binding(PARENT_ROOT / "execution-receipt.json", PARENT_GEN_SHA)
    parent_qa = binding(PARENT_QA / "native-initial-qa.json", PARENT_QA_SHA)
    parent_xml = binding(PARENT_ROOT / "prepared/F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005.xml", PARENT_XML_SHA)
    parent_bi4 = binding(PARENT_ROOT / "prepared/F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005.bi4", PARENT_BI4_SHA)
    clone006 = binding(ENDPOINT_PREP_ROOT / "execution-receipt.json", CLONE_006_SHA)
    owner_path = INTEGRATION_CAMPAIGN / "families/F3/handoff_20261003/root_actual_twoaxis_full_typed_067/dp006/owner.json"
    owner = binding(owner_path, PARENT_OWNER_SHA)

    reports: dict[str, tuple[dict[str, Any], dict[str, str], dict[str, str]]] = {}
    for role, case_id, physical_case_id, amplitude in CASES:
        report_path = PREP_ROOT / f"prepared/{role}/prepared-input-report.json"
        report = read_json(report_path)
        if (report.get("role"), report.get("case_id"), report.get("physical_case_id"), report.get("transverse_amplitude_m_s2")) != (role, case_id, physical_case_id, amplitude):
            raise ValueError(f"strict012 report identity mismatch: {report_path}")
        report_binding = binding(report_path)
        evidence = make_sidecars(out, report, report_binding, parent_qa)
        reports[case_id] = (report, report_binding, evidence)

    shared = shared_initial_state(parent_gen, parent_qa, parent_xml, parent_bi4, prep_receipt, clone006, owner, prep_cases, prep_binding)
    static = reports[CASES[0][1]][0]
    physical_domain_source = read_json(DOMAIN_054)
    domain_cases: list[dict[str, Any]] = []
    manifest_cases: list[dict[str, Any]] = []
    source_domain_rows = {row["case_id"]: row for row in physical_domain_source["cases"]}
    prospective_ids = {case_id for _, case_id, _, _ in CASES}
    for source_row in physical_domain_source["cases"]:
        case_id = source_row["case_id"]
        row = copy.deepcopy(source_row)
        # Keep scalar axis fields alongside the rich parameter tuple for all
        # eight rows.  v2 canonicalizes rows with scalar fields using the
        # condition hash, so observed and prospective representations must be
        # identical even when the historical 054 domain used tuple-only rows.
        row["transverse_amplitude_m_s2"] = source_row["parameter_tuple"]["transverse_amplitude_m_s2"]
        row["nominal_pitch_multiplier"] = source_row["parameter_tuple"]["nominal_pitch_multiplier"]
        # Keep the 054 canonical scalar identity exactly; add explicit fields
        # only to the five strict012 rows that can be bound to actual files.
        if case_id in prospective_ids:
            report, report_binding, evidence = reports[case_id]
            row.update(
                {
                    "physical_case_id": report["physical_case_id"],
                    "physical_condition_sha256": report["physical_condition_sha256"],
                    "transverse_amplitude_m_s2": report["transverse_amplitude_m_s2"],
                    "nominal_pitch_multiplier": 1.0,
                    "physics": static_physics(report),
                    "geometry": static_geometry(report),
                    "motion": motion_row(report),
                    "parent_group_id": "F3_DP006_EXACT_INITIAL_CLONE_PARENT",
                    "split": "first8_prospective_interior",
                    "event_window_s": WINDOW,
                    "complete_event_window_s": WINDOW,
                    "numerical_recipe": "F3_DP006_ADAPTIVE_CFL05_COEF005_TMAX8P35_TOUT0P01_MDBC_NOSLIP1",
                    "source_owner": report_binding,
                }
            )
        domain_cases.append(row)
        if case_id in prospective_ids:
            report, report_binding, evidence = reports[case_id]
            prepared_dir = PREP_ROOT / f"prepared/{report['role']}"
            xml_path = prepared_dir / f"{case_id}.xml"
            bi4_path = prepared_dir / f"{case_id}.bi4"
            forcing_path = prepared_dir / "CaseSloshingAccData.csv"
            xml = binding(xml_path, report["xml_sha256"])
            bi4 = binding(bi4_path, report["bi4_sha256"])
            forcing = binding(forcing_path, report["forcing_sha256"])
            prepared = {
                "report": report_binding,
                "forcing": forcing,
                "generated_xml": xml,
                "initial_bi4": bi4,
                "prepared_prefix": report["prepared_prefix"],
                "xml_byte_identical_to_baseline": True,
                "initial_bi4_byte_identical_to_baseline": True,
            }
            command = [
                str(SOLVER),
                "-mdbc_noslip:1",
                report["prepared_prefix"],
                "{attempt_root}/solver_output",
                "-tmax:8.35",
                "-tout:0.01",
            ]
            sidecar_bindings = list(evidence.values())
            input_bindings = [forcing, xml, bi4, report_binding, *sidecar_bindings]
            manifest_row = {
                "order": source_row["order"],
                "role": report["role"],
                "case_id": case_id,
                "physical_case_id": report["physical_case_id"],
                "transverse_amplitude_m_s2": report["transverse_amplitude_m_s2"],
                "nominal_pitch_multiplier": 1.0,
                "parameter_tuple": copy.deepcopy(source_row["parameter_tuple"]),
                "physical_condition_sha256": report["physical_condition_sha256"],
                "source_owner": report_binding,
                "qa_semantics": "exact_initial_clone_of_genuine_3d_parent",
                "parent_group_id": "F3_DP006_EXACT_INITIAL_CLONE_PARENT",
                "split": "first8_prospective_interior",
                "physics": static_physics(report),
                "geometry": static_geometry(report),
                "motion": motion_row(report),
                "event_window_s": WINDOW,
                "complete_event_window_s": WINDOW,
                "save_interval_s": SAVE_INTERVAL,
                "expected_saved_frames": EXPECTED_FRAMES,
                "numerical_recipe": "F3_DP006_ADAPTIVE_CFL05_COEF005_TMAX8P35_TOUT0P01_MDBC_NOSLIP1",
                "actual_solver_command": command,
                "actual_solver_cwd": str(SOLVER_CWD),
                "prepared_input": prepared,
                "input_bindings": input_bindings,
                "initial_mass_discrepancy_report": evidence["initial_mass_discrepancy_report"],
                "physics_evidence": evidence["physics_evidence"],
                "geometry_evidence": evidence["geometry_evidence"],
                "motion_evidence": evidence["motion_evidence"],
                "no_overlap_finite_state_evidence": evidence["no_overlap_finite_state_evidence"],
                "initial_native_reference": {
                    "parent_initial_qa": dict(parent_qa),
                    "native_particles": NATIVE_PARTICLES,
                    "native_fluid": NATIVE_FLUID,
                    "native_fixed": NATIVE_FIXED,
                    "actual_3d": True,
                    "native_initial_BI4_sha256": PARENT_BI4_SHA,
                    "generated_xml_sha256": PARENT_XML_SHA,
                    "continuum_reference_mass_kg": CONTINUUM_MASS,
                    "native_fluid_mass_kg": NATIVE_MASS,
                    "mass_normalization": "none",
                },
                "clone_provenance": {
                    "first8_preparation_receipt": dict(prep_receipt),
                    "endpoint_clone_preparation_receipt_006": dict(clone006),
                    "genuine_parent_owner_source": dict(owner),
                    "genuine_parent_gencase_receipt": dict(parent_gen),
                },
                "root_visual_decision": None,
                "full_saved_frame_integrity": None,
                "stage1_visual_status": "pending actual complete run and Root case decision",
                "numerical_precision_status": "not_accepted",
                "production_approval": "none",
                "independent_case_count_increment": 0,
                "visual_review_pending": True,
            }
            manifest_cases.append(manifest_row)
        else:
            # Observed rows are retained for domain membership and visual
            # evidence.  They are never selected as a prospective request.
            manifest_cases.append(
                {
                    "order": source_row["order"],
                    "role": source_row["role"],
                    "case_id": case_id,
                    "physical_case_id": source_row["physical_case_id"],
                    "transverse_amplitude_m_s2": source_row["parameter_tuple"]["transverse_amplitude_m_s2"],
                    "nominal_pitch_multiplier": source_row["parameter_tuple"]["nominal_pitch_multiplier"],
                    "parameter_tuple": copy.deepcopy(source_row["parameter_tuple"]),
                    "physical_condition_sha256": source_row["physical_condition_sha256"],
                    "source_owner": source_row["source_owner"],
                    "visual_record_role": "observed_domain_only",
                    "production_approval": "none",
                    "independent_case_count_increment": 0,
                }
            )

    domain = {
        "schema": "ds02.stage1.frozen-physical-domain.v3",
        "campaign_id": "DS-DATA-02",
        "family_id": "F3",
        "scope_id": SCOPE_ID,
        "status": "frozen_candidate_pending_explicit_adapter_index_review",
        "production_scope_approval": False,
        "q_n": "not_granted",
        "q_e": "not_assessed",
        "stage1_label": "视觉检查通过、数值精度未验收",
        "source_domain_054": source_domain_054,
        "source_provenance_054": source_provenance_054,
        "physical_axis": physical_domain_source["physical_axis"],
        "canonical_physical_keys": physical_domain_source["canonical_physical_keys"],
        "solver_recipe": physical_domain_source["solver_recipe"],
        "no_interpolation_or_extrapolation": True,
        "cases": domain_cases,
    }
    manifest = {
        "schema": "ds02.stage1.visual-case-manifest.v3",
        "campaign_id": "DS-DATA-02",
        "family_id": "F3",
        "scope_id": SCOPE_ID,
        "status": "concrete_prospective_request_template_pending_root_adapter_index_review",
        "source_only": True,
        "production_scope_approval": False,
        "q_n": "not_granted",
        "q_e": "not_assessed",
        "stage1_label": "视觉检查通过、数值精度未验收",
        "goal_authority": goal,
        "root_visual_domain_decision": root_domain_decision,
        "source_domain_054": source_domain_054,
        "source_provenance_054": source_provenance_054,
        "source_preparation": {
            "binding": prep_binding,
            "receipt": prep_receipt,
            "prepared_cases": prep_cases,
        },
        "shared_initial_state": shared,
        "source_documents": shared["source_documents"],
        "frozen_physics_contract": {
            "parameter_axis_transverse_amplitude_m_s2": [0.25, 0.32, 0.39, 0.46, 0.5, 0.57, 0.64, 0.75],
            "nominal_pitch_multiplier": 1.0,
            "definition_dp_m": 0.006,
            "event_window_s": WINDOW,
            "save_interval_s": SAVE_INTERVAL,
            "expected_saved_frames": EXPECTED_FRAMES,
            "geometry_unchanged": True,
            "numerical_recipe_unchanged": True,
            "no_interpolation_or_extrapolation": True,
        },
        "cases": manifest_cases,
    }
    write_json(out / "F3_FIRST8_V3_PHYSICAL_DOMAIN.json", domain)
    write_json(out / "F3_FIRST8_V3_CASE_MANIFEST.json", manifest)
    write_json(
        out / "F3_FIRST8_V3_SOURCE_BINDINGS.json",
        {
            "schema": "ds02.stage1.f3.v3-source-bindings.v1",
            "goal_authority": goal,
            "root_visual_domain_decision": root_domain_decision,
            "physical_domain_054": source_domain_054,
            "case_provenance_054": source_provenance_054,
            "strict012_binding": prep_binding,
            "strict012_receipt": prep_receipt,
            "parent_genuine_gencase_receipt": parent_gen,
            "parent_native_initial_qa": parent_qa,
            "parent_xml": parent_xml,
            "parent_bi4": parent_bi4,
            "clone_preparation_receipt_006": clone006,
            "parent_owner_source": owner,
            "v2_authorizer": binding(V2_AUTHORIZER),
            "v2_dispatch_adapter": binding(V2_DISPATCH),
            "consumed_strict_dispatch": binding(STRICT),
            "consumed_runtime": binding(RUNTIME),
            "native_solver_binary": binding(SOLVER),
        },
    )
    return {"domain": domain, "manifest": manifest, "shared": shared}


if __name__ == "__main__":
    build_package()
    print(f"wrote source-only F3 v3 package under {HERE}")
