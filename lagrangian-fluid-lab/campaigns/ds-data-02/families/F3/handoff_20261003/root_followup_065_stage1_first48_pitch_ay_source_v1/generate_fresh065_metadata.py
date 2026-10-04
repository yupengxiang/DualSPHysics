#!/usr/bin/env python3
"""Build the fresh065 source-only metadata package.

This generator reads JSON source metadata and small source files only.  It
never opens the nominal forcing CSV or the baseline BI4.  The known baseline
digests are carried from fresh064; future forcing and physical-condition
digests are deliberately null.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "root_followup_064_stage1_first24_source_variants_v1"
OLD_ROOT = str(OLD)
NEW_ROOT = str(HERE)
SCOPE = "F3_STAGE1_FIRST48_PITCH0800_1200_AY0250_AY0750_SOURCE_V1"
PITCHES = (0.8, 1.2)
AYS = (0.25, 0.29, 0.32, 0.36, 0.39, 0.43, 0.46, 0.50, 0.54, 0.57, 0.64, 0.75)
ARRAY_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz"}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    if path.suffix.lower() in ARRAY_SUFFIXES:
        raise RuntimeError(f"refusing to hash array-bearing file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def replace(value: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [replace(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: replace(item, replacements) for key, item in value.items()}
    return value


def pitch_token(pitch: float) -> str:
    return f"P{int(round(pitch * 1000)):04d}"


def ay_token(ay: float) -> str:
    return f"AY{int(round(ay * 1000)):04d}"


def case_row(pitch: float, ay: float, index: int) -> dict[str, Any]:
    pt, at = pitch_token(pitch), ay_token(ay)
    case_id = f"F3_STAGE1_DP006_{pt}_{at}"
    physical_id = f"F3_TWOAXIS_{pt}_{at}_STAGE1_FIRST48_PITCH_VARIANT"
    return {
        "role": f"pitch{int(round(pitch * 100)):03d}_ay{int(round(ay * 1000)):04d}",
        "case_id": case_id,
        "physical_case_id": physical_id,
        "nominal_pitch_multiplier": pitch,
        "transverse_amplitude_m_s2": ay,
        "role_in_domain": "new first48 pitch/AY candidate; disabled until actual CPU preparation, typed/native state, full836 product, and Root visual authorization",
        "expected_new_case": True,
        "candidate_order": index,
        "future_actual_forcing_sha256": None,
        "future_physical_condition_sha256": None,
    }


def old_input_hashes() -> dict[str, str]:
    return load(OLD / "requests/batch-source-preparation-request.json")["input_sha256"]


def source_input_hashes(request: dict[str, Any], old_hashes: dict[str, str]) -> None:
    updated: dict[str, str] = {}
    for raw in request["input_files"]:
        path = Path(raw)
        if raw in old_hashes and path.suffix.lower() in ARRAY_SUFFIXES:
            updated[raw] = old_hashes[raw]
        elif path.suffix.lower() in ARRAY_SUFFIXES:
            raise RuntimeError(f"new array input would need hashing: {path}")
        elif path.is_file():
            updated[raw] = sha(path)
        else:
            # Unchanged external source paths retain the reviewed fresh064 hash.
            old_key = next((key for key in old_hashes if key == raw), None)
            if old_key is None and path.name == "helper-binding.json":
                # The helper is written after requests are templated.  Use its
                # old reviewed digest for this first pass; the final closure
                # pass below replaces it with the fresh065 digest.
                old_key = next((key for key in old_hashes if key.endswith("/helper-binding.json")), None)
            if old_key is None:
                raise RuntimeError(f"missing request source input: {path}")
            updated[raw] = old_hashes[old_key]
    request["input_sha256"] = updated
    if set(request["input_files"]) != set(updated):
        raise RuntimeError("input hash closure did not close")


def main() -> None:
    old_binding = load(OLD / "source-binding.json")
    old_first24 = load(OLD / "first24-manifest.json")
    old_template = load(OLD / "canonical-physical-binding-template.json")
    old_hashes = old_input_hashes()
    old_first24_ids = list(old_first24["first24_case_ids_in_order"])
    old_first24_sha = sha(OLD / "first24-manifest.json")

    candidates = [case_row(pitch, ay, i) for i, (pitch, ay) in enumerate(
        (pair for pitch in PITCHES for pair in ((pitch, ay) for ay in AYS)), start=1
    )]
    # The generator itself uses only the small JSON source references.
    if len(candidates) != 24:
        raise RuntimeError("expected 24 pitch/AY candidates")

    binding = copy.deepcopy(old_binding)
    binding = replace(binding, [(OLD_ROOT, NEW_ROOT), ("fresh064", "fresh065"), ("064", "065")])
    binding.update({
        "schema": "ds02.stage1.f3.first48-pitch-ay-source-binding.v1",
        "fresh_id": "fresh065",
        "scope_id": SCOPE,
        "candidates": candidates,
        "stage1_authority_file": old_binding["stage1_authority_file"],
        "physical_domain_design": (
            "Existing first24 nominal-pitch source remains an exact subset. New pitch multipliers .8 and 1.2 "
            "are outside the registered nominal-pitch visual domain. AY values are .25,.29,.32,.36,.39,.43,.46,.50,.54,.57,.64,.75. "
            "The four corners P0800/P1200 x AY.25/.75 require independent complete qualification, native-to-typed evidence, "
            "and Root full-frame visual decisions before any two-dimensional pitch/AY domain registration."
        ),
        "preparation_script": str(HERE / "prepare_pitch_axis.py"),
        "preparation_script_sha256": sha(HERE / "prepare_pitch_axis.py"),
        "source_provenance": {
            **binding.get("source_provenance", {}),
            "fresh065_pitch_axis_preparation": {
                "path": str(HERE / "prepare_pitch_axis.py"),
                "sha256": sha(HERE / "prepare_pitch_axis.py"),
                "transformer_pitch_argument": "amplitude_x",
                "transformer_transverse_argument": "amplitude_y",
            },
        },
        "source_builder_policy": {
            "uses_existing_preparation_code": True,
            "uses_reviewed_transformer": True,
            "transformer_pitch_argument": "amplitude_x",
            "transformer_transverse_argument": "amplitude_y",
            "solver_invocation": False,
            "gencase_invocation": False,
            "array_reading": False,
            "future_forcing_and_condition_hashes": "computed only by Root CPU preparation then bound from prepared-input-report.json",
        },
        "first24_exact_subset_source": {
            "manifest": {
                "path": str(HERE / "first24-subset-reference.json"),
                "sha256": sha(HERE / "first24-subset-reference.json"),
            },
            "original_manifest": {"path": str(OLD / "first24-manifest.json"), "sha256": old_first24_sha},
            "case_ids": old_first24_ids,
            "case_count": 24,
            "rows_unchanged": True,
            "production_selected_by_this_package": False,
        },
        "new_pitch_values": list(PITCHES),
        "new_ay_values_m_s2": list(AYS),
        "first48_case_count": 48,
        "output_contract": {
            "root_attempt_id": "root-stage1-f3-first48-pitch-ay-source-preparation-065",
            "output_root_template": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/root-stage1-f3-first48-pitch-ay-source-preparation-065",
            "prepared_case_layout": "prepared/{role}/{case_id}/{case_id}.xml plus .bi4, CaseSloshingAccData.csv, prepared-input-report.json",
            "post_prepare_index": "fresh065-prepared-index.json",
            "future_hashes": "all null before actual Root CPU execution",
        },
        "candidates": candidates,
    })
    write(HERE / "source-binding.json", binding)

    # Conditions and owners are source-only templates.  They retain the actual
    # 3D parent counts and known XML/BI4 digests but never claim new forcing.
    baseline = old_binding["baseline_physical_binding"]
    baseline_xml_sha = old_binding["baseline_xml_sha256"]
    baseline_bi4_sha = old_binding["baseline_bi4_sha256"]
    baseline_gencase = {"path": old_binding["baseline_gencase_receipt"], "sha256": sha(Path(old_binding["baseline_gencase_receipt"]))}
    baseline_qa = {"path": old_binding["baseline_initial_reference"]["initial_typed_qa"], "sha256": sha(Path(old_binding["baseline_initial_reference"]["initial_typed_qa"]))}
    template_sha = sha(HERE / "canonical-physical-binding-template.json")
    for candidate in candidates:
        case_id = candidate["case_id"]
        condition = {
            "schema": "ds02.stage1.f3.first48-pitch-ay-condition-template.v1",
            "status": "pending_actual_cpu_preparation",
            "case_id": case_id,
            "physical_case_id": candidate["physical_case_id"],
            "parameter_tuple": {
                "mechanism_id": "F3_TWOAXIS_TRANSVERSE_LINACC_V1",
                "nominal_pitch_multiplier": candidate["nominal_pitch_multiplier"],
                "transverse_amplitude_m_s2": candidate["transverse_amplitude_m_s2"],
                "transverse_omega_rad_s": baseline["parameters"]["transverse_omega_rad_s"],
                "transverse_phase_rad": baseline["parameters"]["transverse_phase_rad"],
                "transverse_ramp_duration_s": baseline["parameters"]["transverse_ramp_duration_s"],
                "active_window_s": [0.0, 8.35],
                "definition_dp_m": 0.006,
                "save_interval_s": 0.01,
                "time_max_s": 8.35,
                "solver_mode": "-mdbc_noslip:1",
            },
            "source_forcing_sha256": old_binding["nominal_source_forcing_sha256"],
            "actual_forcing_sha256": None,
            "physical_condition_sha256": None,
            "hash_policy": "Root CPU preparation materializes physical_binding and transformed forcing, then records both hashes; this package does not fabricate them.",
            "xml_sha256_expected": baseline_xml_sha,
            "bi4_sha256_expected": baseline_bi4_sha,
            "geometry_and_initial_state": "byte-identical clone of genuine 3D DP006 parent; no new GenCase receipt is created here",
        }
        write(HERE / "conditions" / f"{case_id}.json", condition)
        owner = copy.deepcopy(load(OLD / "owners/F3_STAGE1_DP006_P1000_AY0270.json"))
        owner = replace(owner, [(OLD_ROOT, NEW_ROOT), ("fresh064", "fresh065"), ("064", "065"), ("F3_STAGE1_DP006_P1000_AY0270", case_id), ("F3_TWOAXIS_PITCH1000_AY0270_STAGE1_FIRST24_NEW", candidate["physical_case_id"]), ("new_interior01", candidate["role"])])
        owner.update({
            "schema": "ds02.stage1.f3.first48-pitch-ay-owner-template.v1",
            "status": "pending_actual_cpu_preparation",
            "case_id": case_id,
            "physical_case_id": candidate["physical_case_id"],
            "role": candidate["role"],
            "split": "first48_new_pitch_variant",
            "transverse_amplitude_m_s2": candidate["transverse_amplitude_m_s2"],
            "nominal_pitch_multiplier": candidate["nominal_pitch_multiplier"],
            "canonical_physical_binding_template": {"path": str(HERE / "canonical-physical-binding-template.json"), "sha256": template_sha},
            "condition_template": {"path": str(HERE / "conditions" / f"{case_id}.json"), "sha256": sha(HERE / "conditions" / f"{case_id}.json")},
        })
        owner["source_preparation"].update({
            "builder": str(HERE / "source_builder.py"),
            "binding": {"path": str(HERE / "source-binding.json"), "sha256": sha(HERE / "source-binding.json")},
            "preparation_script": {"path": str(HERE / "prepare_pitch_axis.py"), "sha256": sha(HERE / "prepare_pitch_axis.py")},
            "frozen_transformer": {"path": binding["forcing_transformer"], "sha256": binding.get("source_provenance", {}).get("frozen_transformer", {}).get("sha256", "5ac8112a907c527aaf31791419e7830fe85fe8e53b92ff9d7f1544326f883c99")},
            "actual_forcing_sha256": None,
            "physical_condition_sha256": None,
        })
        owner["source_preparation"]["output_report_template"] = binding["output_contract"]["output_root_template"] + f"/prepared/{candidate['role']}/{case_id}/prepared-input-report.json"
        owner["source_preparation"]["output_forcing_template"] = binding["output_contract"]["output_root_template"] + f"/prepared/{candidate['role']}/{case_id}/CaseSloshingAccData.csv"
        owner["source_preparation"]["output_pitch_multiplier_argument"] = "amplitude_x"
        owner["shared_initial_state"].update({
            "genuine_parent_gencase_receipt": baseline_gencase,
            "parent_initial_qa": baseline_qa,
            "native_particles": 179208,
            "native_fluid": 67500,
            "native_fixed": 111708,
            "actual_3d": True,
            "initial_xml_sha256": baseline_xml_sha,
            "initial_bi4_sha256": baseline_bi4_sha,
            "continuum_reference_mass_kg": 14.58,
            "native_initial_mass_kg": 14.580000000000002,
            "mass_normalization": "none",
        })
        owner["production_gate"].update({"launch_allowed": False, "production_approval": "none", "independent_case_count_increment": 0, "q_n": "not_granted", "numerical_precision_status": "not_accepted"})
        owner["pitch_domain_gate"] = {
            "registered_nominal_pitch_domain": [1.0],
            "candidate_pitch_domain": [0.8, 1.2],
            "corner_cases_required_first": [
                "F3_STAGE1_DP006_P0800_AY0250", "F3_STAGE1_DP006_P0800_AY0750",
                "F3_STAGE1_DP006_P1200_AY0250", "F3_STAGE1_DP006_P1200_AY0750",
            ],
            "registration_status": "not_registered",
        }
        write(HERE / "owners" / f"{case_id}.json", owner)

    # Rebind the old per-case production request without changing its frozen
    # solver recipe.  Existing baseline array digests remain copied metadata;
    # new forcing/output digests remain null.
    old_req = load(OLD / "requests/F3_STAGE1_DP006_P1000_AY0270.json")
    old_hash_map = old_req["input_sha256"]
    for candidate in candidates:
        case_id = candidate["case_id"]
        old_case = "F3_STAGE1_DP006_P1000_AY0270"
        old_attempt = "root-stage1-f3-first24-ay0270-full836-visual-production-064"
        attempt = f"root-stage1-f3-first48-{candidate['role']}-full836-visual-production-065"
        req = copy.deepcopy(old_req)
        req = replace(req, [(OLD_ROOT, NEW_ROOT), (old_attempt, attempt), (old_case, case_id), ("F3_TWOAXIS_PITCH1000_AY0270_STAGE1_FIRST24_NEW", candidate["physical_case_id"]), ("fresh064", "fresh065"), ("F3_STAGE1_FIRST24_AY0250_AY0750_SOURCE_VARIANTS_V1", SCOPE), ("root-stage1-f3-first24-source-preparation-064", "root-stage1-f3-first48-pitch-ay-source-preparation-065")])
        req.update({
            "schema": "ds02.runner-request.v2",
            "fresh_id": "fresh065",
            "scope_id": SCOPE,
            "case_id": case_id,
            "attempt_id": attempt,
            "role": candidate["role"],
            "split": "first48_new_pitch_variant",
            "physical_case_id": candidate["physical_case_id"],
            "transverse_amplitude_m_s2": candidate["transverse_amplitude_m_s2"],
            "nominal_pitch_multiplier": candidate["nominal_pitch_multiplier"],
            "physical_condition_sha256": None,
            "source_owner": {"path": str(HERE / "owners" / f"{case_id}.json"), "sha256": sha(HERE / "owners" / f"{case_id}.json")},
        })
        req["parameter_tuple"] = {
            "mechanism_id": "F3_TWOAXIS_TRANSVERSE_LINACC_V1",
            "nominal_pitch_multiplier": candidate["nominal_pitch_multiplier"],
            "transverse_amplitude_m_s2": candidate["transverse_amplitude_m_s2"],
        }
        req["physics"].update({"nominal_pitch_multiplier": candidate["nominal_pitch_multiplier"], "transverse_amplitude_m_s2": candidate["transverse_amplitude_m_s2"]})
        req["actual_solver_command"][2] = binding["output_contract"]["output_root_template"] + f"/prepared/{candidate['role']}/{case_id}/{case_id}"
        req["prepared_input_gate"].update({
            "status": "pending_actual_cpu_preparation",
            "prepared_input_report": binding["output_contract"]["output_root_template"] + f"/prepared/{candidate['role']}/{case_id}/prepared-input-report.json",
            "forcing_path": binding["output_contract"]["output_root_template"] + f"/prepared/{candidate['role']}/{case_id}/CaseSloshingAccData.csv",
            "generated_xml": binding["output_contract"]["output_root_template"] + f"/prepared/{candidate['role']}/{case_id}/{case_id}.xml",
            "initial_bi4": binding["output_contract"]["output_root_template"] + f"/prepared/{candidate['role']}/{case_id}/{case_id}.bi4",
            "forcing_sha256": None,
            "physical_condition_sha256": None,
            "generated_xml_sha256_expected": baseline_xml_sha,
            "initial_bi4_sha256_expected": baseline_bi4_sha,
        })
        req["input_files"] = [
            str(Path(path).as_posix()).replace(str(OLD / "source_builder.py"), str(HERE / "source_builder.py"))
            .replace(str(OLD / "source-binding.json"), str(HERE / "source-binding.json"))
            .replace(str(OLD / "helper-binding.json"), str(HERE / "helper-binding.json"))
            .replace("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_visual_domain_endpoint_inputs_006/prepare.py", str(HERE / "prepare_pitch_axis.py"))
            for path in req["input_files"]
        ]
        source_input_hashes(req, old_hashes)
        write(HERE / "requests" / f"{case_id}.json", req)

    batch = load(OLD / "requests/batch-source-preparation-request.json")
    batch = replace(batch, [(OLD_ROOT, NEW_ROOT), ("fresh064", "fresh065"), ("F3_STAGE1_FIRST24_AY0250_AY0750_SOURCE_VARIANTS_V1", SCOPE), ("F3_STAGE1_FIRST24_SOURCE_PREPARATION", "F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION"), ("root-stage1-f3-first24-source-preparation-064", "root-stage1-f3-first48-pitch-ay-source-preparation-065")])
    batch.update({
        "schema": "ds02.runner-request.v2",
        "fresh_id": "fresh065",
        "case_id": "F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION",
        "attempt_id": "root-stage1-f3-first48-pitch-ay-source-preparation-065",
        "claim": "One disabled CPU source preparation for 24 new pitch/AY candidates; reuses exact 3D initial XML/BI4 and the reviewed amplitude_x/amplitude_y transformer. No GenCase, solver, conversion, ParaView, GPU, or array reader.",
        "output_contract": {
            "output_root_template": binding["output_contract"]["output_root_template"],
            "prepared_index": binding["output_contract"]["output_root_template"] + "/prepared/fresh065-prepared-index.json",
            "future_forcing_hashes": None,
            "future_condition_hashes": None,
        },
    })
    batch["command"] = [
        batch["command"][0], str(HERE / "source_builder.py"), "--binding", str(HERE / "source-binding.json"), "--output-dir", "{attempt_root}/prepared"
    ]
    batch["input_files"] = [
        str(Path(path).as_posix()).replace(str(OLD / "source_builder.py"), str(HERE / "source_builder.py"))
        .replace(str(OLD / "source-binding.json"), str(HERE / "source-binding.json"))
        .replace(str(OLD / "helper-binding.json"), str(HERE / "helper-binding.json"))
        .replace("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_visual_domain_endpoint_inputs_006/prepare.py", str(HERE / "prepare_pitch_axis.py"))
        for path in batch["input_files"]
    ]
    source_input_hashes(batch, old_hashes)
    write(HERE / "requests/batch-source-preparation-request.json", batch)

    helper = load(OLD / "helper-binding.json")
    helper = replace(helper, [(OLD_ROOT, NEW_ROOT), ("fresh064", "fresh065"), ("064", "065"), ("F3_STAGE1_FIRST24_AY0250_AY0750_SOURCE_VARIANTS_V1", SCOPE), ("F3_STAGE1_FIRST24_SOURCE_PREPARATION", "F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION"), ("root-stage1-f3-first24-source-preparation-064", "root-stage1-f3-first48-pitch-ay-source-preparation-065")])
    helper.update({
        "schema": "ds02.stage1.f3.fresh065-source-helper.v1",
        "fresh_id": "fresh065",
        "package_root": NEW_ROOT,
        "scope_id": SCOPE,
        "new_case_gate": {
            "case_ids": [c["case_id"] for c in candidates],
            "production_selected": False,
            "launch_allowed": False,
            "production_approval": "none",
            "condition_hashes": "null until Root CPU preparation",
            "forcing_hashes": "null until Root CPU preparation",
            "pitch_domain_status": "outside registered nominal pitch domain; not registered",
            "requires_first": ["four corners P0800/P1200 x AY0250/AY0750 complete qualification", "native-to-typed evidence", "full836 and Root visual decision"],
        },
        "fresh065_pitch_axis_preparation": {
            "path": str(HERE / "prepare_pitch_axis.py"),
            "sha256": sha(HERE / "prepare_pitch_axis.py"),
            "transformer_pitch_argument": "amplitude_x",
            "transformer_transverse_argument": "amplitude_y",
            "initial_xml_bi4_policy": "byte-identical genuine 3D parent clone",
        },
        "request_paths": [str(HERE / "requests" / f"{c['case_id']}.json") for c in candidates],
    })
    # The helper contains no request digests, so it can be written before request closure.
    write(HERE / "helper-binding.json", helper)

    # Recompute request closures now that helper and owner files exist.
    for candidate in candidates:
        path = HERE / "requests" / f"{candidate['case_id']}.json"
        req = load(path)
        source_input_hashes(req, old_hashes)
        write(path, req)
    batch = load(HERE / "requests/batch-source-preparation-request.json")
    source_input_hashes(batch, old_hashes)
    write(HERE / "requests/batch-source-preparation-request.json", batch)

    visual = load(OLD / "requests/stage1-visual-authorizer-batch-request.json")
    visual = replace(visual, [(OLD_ROOT, NEW_ROOT), ("fresh064", "fresh065"), ("064", "065"), ("F3_STAGE1_FIRST24_AY0250_AY0750_SOURCE_VARIANTS_V1", SCOPE), ("F3_STAGE1_FIRST24_SOURCE_PREPARATION", "F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION"), ("root-stage1-f3-first24-source-preparation-064", "root-stage1-f3-first48-pitch-ay-source-preparation-065")])
    visual.update({
        "schema": "ds02.stage1.f3.first48-pitch-ay-visual-authorizer-batch-request.v1",
        "fresh_id": "fresh065",
        "scope_id": SCOPE,
        "status": "source_only_disabled_pending_actual_cpu_and_root_authorizer",
        "source_only": True,
        "execution_allowed": False,
        "production_scope_approval": False,
        "q_n": "not_granted",
        "q_e": "not_assessed",
        "numerical_precision_status": "not_accepted",
        "new_case_ids": [c["case_id"] for c in candidates],
        "production_selected_case_ids": [],
        "source_preparation_request": {"path": str(HERE / "requests/batch-source-preparation-request.json"), "sha256": sha(HERE / "requests/batch-source-preparation-request.json")},
        "no_future_hashes_claimed": True,
        "enablement_gate": "Every new case remains disabled until Root binds actual fresh065-prepared-index/report hashes, completes normal typed/native/full836 evidence, and records Root visual decisions. Pitch-domain registration additionally requires the four .8/.1.2 x .25/.75 corners.",
    })
    visual["request_paths"] = [
        {"path": str(HERE / "requests" / f"{c['case_id']}.json"), "sha256": sha(HERE / "requests" / f"{c['case_id']}.json"), "case_id": c["case_id"]}
        for c in candidates
    ]
    write(HERE / "requests/stage1-visual-authorizer-batch-request.json", visual)

    first48 = {
        "schema": "ds02.stage1.f3.first48-pitch-ay-source-manifest.v1",
        "fresh_id": "fresh065",
        "family_id": "F3",
        "scope_id": SCOPE,
        "status": "source_only_disabled_pending_root_actual_cpu_typed_native_full836_and_visual",
        "source_only": True,
        "execution_allowed": False,
        "production_scope_approval": False,
        "q_n": "not_granted",
        "numerical_precision_status": "not_accepted",
        "independent_case_count_increment": 0,
        "first24_exact_subset": {
            "path": str(HERE / "first24-subset-reference.json"),
            "sha256": sha(HERE / "first24-subset-reference.json"),
            "original_path": str(OLD / "first24-manifest.json"),
            "original_sha256": old_first24_sha,
            "case_ids": old_first24_ids,
            "case_count": 24,
            "rows_unchanged": True,
        },
        "new_pitch_ay_case_rows": [
            {**c, "physical_condition_sha256": None, "forcing_sha256": None, "actual_forcing_sha256": None, "launch_allowed": False}
            for c in candidates
        ],
        "first48_case_ids": old_first24_ids + [c["case_id"] for c in candidates],
        "case_count": 48,
        "new_case_count": 24,
        "parameter_axis": {
            "mechanism_id": "F3_TWOAXIS_TRANSVERSE_LINACC_V1",
            "pitch_multiplier_values": list(PITCHES),
            "transverse_amplitude_values_m_s2": list(AYS),
            "transformer_pitch_argument": "amplitude_x",
            "transformer_transverse_argument": "amplitude_y",
            "geometry_initial_xml_bi4": "exact byte-identical 3D parent clone",
            "solver_recipe": {"mode": "-mdbc_noslip:1", "time_max_s": 8.35, "save_interval_s": 0.01, "expected_frames": 836},
        },
        "pitch_domain_gate": {
            "registered_pitch_values": [1.0],
            "candidate_pitch_values": list(PITCHES),
            "corner_case_ids": [
                "F3_STAGE1_DP006_P0800_AY0250", "F3_STAGE1_DP006_P0800_AY0750",
                "F3_STAGE1_DP006_P1200_AY0250", "F3_STAGE1_DP006_P1200_AY0750",
            ],
            "registration_status": "not_registered",
            "required_evidence": ["genuine CPU preparation", "normal native initial QA", "typed conversion", "full836 native solver", "Root full-frame visual decisions"],
        },
        "request_set": {
            "source_preparation": {"path": str(HERE / "requests/batch-source-preparation-request.json"), "sha256": sha(HERE / "requests/batch-source-preparation-request.json")},
            "visual_authorizer": {"path": str(HERE / "requests/stage1-visual-authorizer-batch-request.json"), "sha256": sha(HERE / "requests/stage1-visual-authorizer-batch-request.json")},
        },
        "future_hash_policy": "New forcing, physical-condition, preparation receipt, solver receipt, typed conversion, and visual evidence SHA256 values remain null until Root executes and audits them.",
        "no_claims": ["no production authorization", "no precision certificate", "no pitch-domain registration", "no case-count increment"],
    }
    write(HERE / "first48-manifest.json", first48)

    print(json.dumps({"new_cases": len(candidates), "first24_subset": len(old_first24_ids), "first48": 48, "launch_allowed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
