#!/usr/bin/env python3
"""Materialize the F2 fresh095 first-eight source-only package.

This builder only writes source XML, copied forcing text, metadata, owners,
disabled Root142/Root230 requests, and bounded provenance JSON. It never calls
GenCase, PartVTK, DualSPHysics, a runner, or an array reader.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

INFRA = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics")
HERE = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_095_f2_stage1_first8_offset_lattice_v1"
BASE090 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_090_f2_stage1_production_endpoints_v1"
BASE092 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_092_f2_stage1_native109_nvme_typed_v1"
BASE094 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_094_f2_stage1_typed_xmf_render_bind_v1"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
LAB = INTEGRATION / "lagrangian-fluid-lab"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2")
TEMPLATE_DEF = BASE090 / "source/F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010_Def.xml"
TEMPLATE_MOTION = BASE090 / "source/F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010_motion.dat"
TEMPLATE_METADATA = BASE090 / "source/F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010.metadata.json"
TEMPLATE_QA_WORKER = BASE090 / "workers/f2_stage1_initial_qa_worker.py"
MOTHER_OWNER = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/rv4_matched_three_dp_init_v1/root_fulltyped_macro_review_002/offset-coarse-owner.json"
ROOT142_POLICY = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
ROOT230_DIR = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT230_POLICY = ROOT230_DIR / "root_native_home_floor_inventory_policy.py"
ROOT230_LAUNCH = ROOT230_DIR / "launch.py"
GPU_POLICY = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
GENCASE = INFRA / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
PARTVTK = INFRA / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
SOLVER = INFRA / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
MOTHER_CASE_ID = "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010"
MOTHER_PHYSICAL_HASH = "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
P01_PHYSICAL_HASH = "c994d0a680c84cdedb984d98c7fcb28bc62d2719999889d3164e44820ccb883c"
P03_PHYSICAL_HASH = "402f576739ee7618ff00e5f570ba726d60a7a88017e456f6ad0aa57b46a2cab2"
ROOT142_PROFILE = "root_home_floor_no_legacy_dataset_walk_v1"
ROOT142_POLICY_SHA = "2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5"
ROOT230_PROFILE = "root_home_floor_no_legacy_dataset_walk_native_v1"
ROOT230_POLICY_SHA = "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5"
SCOPE_ID = "F2_STAGE1_FIRST8_OFFSET_LATTICE_V1"
OFFSETS = (0.47, 0.50, 0.55, 0.60, 0.63)
RECIPE = {
    "dp_m": 0.01, "time_max_s": 4.0, "time_out_s": 0.01,
    "expected_saved_frames": 401, "solver_dimension": 3,
    "native_forcing_file_format": "#Time;Degrees",
    "recipe_role": "Stage1 full-window native visual candidate; no precision/Q-N claim",
}

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def bind(path: Path) -> dict[str, Any]:
    path = path.resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "exists": True}

def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def case_spec(x: float) -> dict[str, Any]:
    code = int(round(x * 100))
    return {
        "x": x,
        "case_id": f"F2_STAGE1_FIRST8_OFFSET_RX{code:03d}_DP010_SPATIAL_REFERENCE_SAVE010",
        "physical_case_id": f"F2_STAGE1_FIRST8_OFFSET_OPEN_RIM_RX{code:03d}_RY014_FILL080",
    }

def condition(spec: dict[str, Any]) -> dict[str, Any]:
    x = float(spec["x"])
    return {
        "family_id": "F2", "mechanism_id": "offset_spill",
        "geometry_family_id": "F2_GEOM_CUP_RECEIVER_OFFSET_V1",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
        "cup_low_m": [0.0, -0.15, 0.65], "cup_size_m": [0.425, 0.30, 0.45],
        "receiver_low_m": [x, -0.16, 0.0], "receiver_size_m": [1.10, 0.60, 0.45],
        "tray_low_m": [-1.20, -1.00, -0.20], "tray_size_m": [4.00, 2.00, 0.15],
        "fluid_low_m": [0.05, -0.11, 0.70], "fluid_source_size_m": [0.325, 0.22, 0.264],
        "source_layer_count": 3, "source_mk_values": [0, 1, 2],
        "initial_velocity_m_per_s": [0.0, 0.0, 0.0], "fill_ratio": 0.8,
        "receiver_x_m": x, "receiver_y_m": 0.14, "mouth_geometry": "open_rim",
        "rotation_duration_s": 0.65, "rotation_hold_start_s": 0.5,
        "rotation_final_angle_deg": -105.0,
        "motion_file_sha256": sha256(TEMPLATE_MOTION),
        "native_forcing": "official mvrotfile; static 0.5 s, cosine ramp, final -105 degrees, post-stop hold",
    }

def counts_contract() -> dict[str, Any]:
    return {
        "expected_counts": {"total_particles": None, "fluid_particles": None,
                            "fixed_particles": None, "moving_particles": None},
        "count_source": "actual GenCase receipt plus generated XML/prepared-input-report; no source-side expected count",
        "measurements_required": [
            "actual GenCase status and returncode",
            "generated XML particle summary and 3-D flag",
            "prepared-input-report actual totals",
            "Root frame-zero PartVTK/QA finite, UID/type/Mk/zone and geometry checks",
        ],
        "no_forced_count": True, "no_mother_count_substitution": True,
        "mass_policy": "Root reads actual native mass and reports continuum difference without rescale; source095 asserts no mass",
    }

def materialize_source(spec: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    cid, pid, x = spec["case_id"], spec["physical_case_id"], f'{spec["x"]:.2f}'
    text = TEMPLATE_DEF.read_text(encoding="utf-8")
    old_comment = "<!-- mechanism=offset_spill; physical_case_id=F2_STAGE1_OFFSET_P01_OPEN_RIM_RX045_RY014_FILL080; resolution=coarse_dp010 -->"
    new_comment = f"<!-- mechanism=offset_spill; physical_case_id={pid}; resolution=coarse_dp010; source_template=F2_STAGE1_OFFSET_P01 -->"
    old_motion = "F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010_motion.dat"
    new_motion = f"{cid}_motion.dat"
    old_point = '<point x="0.45" y="-0.16" z="0" />'
    new_point = f'<point x="{x}" y="-0.16" z="0" />'
    for old in (old_comment, old_motion, old_point):
        if text.count(old) != 1:
            raise AssertionError(f"source template mismatch: {old}")
    text = text.replace(old_comment, new_comment, 1).replace(old_motion, new_motion, 1).replace(old_point, new_point, 1)
    ET.fromstring(text)
    definition = HERE / "source" / f"{cid}_Def.xml"
    motion = HERE / "source" / f"{cid}_motion.dat"
    definition.write_text(text, encoding="utf-8")
    shutil.copyfile(TEMPLATE_MOTION, motion)
    before = re.sub(r"<!-- mechanism=.*? -->", "<!-- normalized -->", TEMPLATE_DEF.read_text(), count=1)
    after = re.sub(r"<!-- mechanism=.*? -->", "<!-- normalized -->", text, count=1)
    before = re.sub(r"F2_STAGE1_[A-Z0-9_]+_motion\.dat", "{MOTION}", before)
    after = re.sub(r"F2_STAGE1_[A-Z0-9_]+_motion\.dat", "{MOTION}", after)
    changed = [line.rstrip("\n") for line in difflib.unified_diff(before.splitlines(True), after.splitlines(True))
               if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
    expected = [f'-            <point x="0.45" y="-0.16" z="0" />',
                f'+            <point x="{x}" y="-0.16" z="0" />']
    if changed != expected:
        raise AssertionError(f"unexpected source diff for {cid}: {changed!r}")
    cond = condition(spec)
    meta = {
        "schema": "ds02.f2.stage1.first8.prospective-source.v1",
        "family_id": "F2", "scope_id": SCOPE_ID, "case_id": cid, "physical_case_id": pid,
        "source_batch_template": "F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010",
        "lineage_group_id": "F2_STAGE1_FIRST8_OFFSET_LATTICE_MINIMAL_VARIATION_V1",
        "mechanism_id": "offset_spill", "geometry_family_id": cond["geometry_family_id"],
        "control_family_id": cond["control_family_id"],
        "parameter_values": {"receiver_x_m": spec["x"], "receiver_y_m": 0.14,
                             "fill_ratio": 0.8, "mouth_geometry": "open_rim",
                             "rotation_duration_s": 0.65},
        "geometry": {
            "dimension": 3, "data2d": False, "dp_m": 0.01,
            "receiver_low_m": [spec["x"], -0.16, 0.0], "receiver_size_m": [1.10, 0.60, 0.45],
            "cup_low_m": [0.0, -0.15, 0.65], "cup_size_m": [0.425, 0.30, 0.45],
            "tray_low_m": [-1.20, -1.00, -0.20], "tray_size_m": [4.00, 2.00, 0.15],
            "fluid_low_m": [0.05, -0.11, 0.70], "fluid_source_size_m": [0.325, 0.22, 0.264],
            "source_layer_count": 3, "source_mk_values": [0, 1, 2],
            "receiver_x_grid_index_dp010": int(round(spec["x"] / 0.01)),
            "receiver_x_lattice_contract": {"grid_spacing_m": 0.01, "closed_reviewed_range_m": [0.45, 0.65]},
        },
        "motion": {"file_name": motion.name, "sha256": sha256(motion), "format": "#Time;Degrees",
                   "time_start_s": 0.0, "time_end_s": 4.0, "static_hold_start_s": 0.5,
                   "rotation_duration_s": 0.65, "rotation_stop_s": 1.15,
                   "final_angle_deg": -105.0, "source_bytes_equal_to_reviewed_p01": True},
        "physical_condition": cond, "physical_condition_sha256": canonical_sha(cond),
        "numerical_recipe": RECIPE, "numerical_recipe_sha256": canonical_sha(RECIPE),
        "definition_path": str(definition.resolve()), "definition_sha256": sha256(definition),
        "motion_path": str(motion.resolve()), "count_contract": counts_contract(),
        "initial_native_qa_contract": {"worker": str((HERE / "workers/f2_stage1_initial_qa_worker.py").resolve()),
                                        "status": "prospective_disabled_until_actual_gencase_receipt",
                                        "future_report_sha256": None, "future_csv_sha256": None},
        "stripped_mother_diff": {"baseline": bind(TEMPLATE_DEF), "changed_xml_element": "receiver low-x point",
                                 "changed_lines": changed, "parameter_change_only": True,
                                 "all_other_source_bytes_equal_after_normalization": True},
        "mother_support": {"case_id": MOTHER_CASE_ID, "physical_condition_sha256": MOTHER_PHYSICAL_HASH,
                           "role": "read-only support only; not reused or recounted"},
        "generation_status": "source_fixture_only_not_gencase_run",
        "production_status": "prospective_pending_root_actual_gencase_qa_native_visual",
        "qualification_claim": "none", "production_claim": "none", "source_only": True,
        "actual_counts": None, "actual_mass_kg": None,
        "future_receipt_hashes": {"gencase": None, "initial_qa": None, "native_solver": None},
        "independent_case_count_increment": 1,
        "p07_status": "not_used; pre-registered P07 has no native109 output",
    }
    metadata = HERE / "source" / f"{cid}.metadata.json"
    dump(metadata, meta)
    return definition, motion, meta

def inputs(definition: Path, motion: Path, metadata: Path) -> tuple[list[str], dict[str, str]]:
    paths = [definition, motion, metadata, HERE / "workers/f2_stage1_initial_qa_worker.py",
             HERE / "workers/f2_first8_source_contract_validator.py", TEMPLATE_DEF, TEMPLATE_MOTION,
             TEMPLATE_METADATA, BASE090 / "F2_STAGE1_OFFSET_ENDPOINT_MANIFEST.json",
             BASE092 / "manifest.json", BASE094 / "manifest.json",
             BASE094 / "metadata/endpoint-audit.json", MOTHER_OWNER, ROOT142_POLICY,
             ROOT230_POLICY, ROOT230_LAUNCH, GPU_POLICY]
    paths = [Path(p).resolve() for p in paths]
    return [str(p) for p in paths], {str(p): sha256(p) for p in paths}

def request_common(meta: dict[str, Any], files: list[str], hashes: dict[str, str]) -> dict[str, Any]:
    return {"schema": "ds02.runner-request.v2", "family_id": "F2", "scope_id": SCOPE_ID,
            "case_id": meta["case_id"], "physical_case_id": meta["physical_case_id"],
            "physical_condition_sha256": meta["physical_condition_sha256"],
            "numerical_recipe_sha256": meta["numerical_recipe_sha256"], "worktree_root": str(INFRA),
            "raw_output_root": str((DATA_ROOT / meta["case_id"]).resolve()), "source_only": True,
            "root_review_required": True, "launch_owner": "root", "launch": False,
            "launch_allowed": False, "execution_allowed": False, "disabled": True,
            "production_claim": "none", "qualification_claim": "none",
            "numerical_precision_status": "not_accepted", "input_files": files, "input_sha256": hashes,
            "root142_policy_source": str(ROOT142_POLICY.resolve()),
            "root142_policy_source_sha256": ROOT142_POLICY_SHA}

def write_requests(meta: dict[str, Any], definition: Path, worker: Path) -> dict[str, Path]:
    files, hashes = inputs(definition, HERE / "source" / f"{meta['case_id']}_motion.dat",
                           HERE / "source" / f"{meta['case_id']}.metadata.json")
    cid = meta["case_id"]; base = request_common(meta, files, hashes)
    ga = f"root-stage1-f2-{cid.lower()}-genuine-gencase-095"
    qa = f"root-stage1-f2-{cid.lower()}-actual-initial-qa-095"
    docs = {
        "gencase": {**base, "attempt_id": ga, "kind": "cpu", "cpu_task_kind": "gencase",
            "cpu_threads": 4, "max_wall_seconds": 600, "estimated_storage_bytes": 536870912,
            "command": [str(GENCASE), str(definition.with_suffix("")), f"{{attempt_root}}/{cid}", "-save:all", "-threads:4"],
            "cwd": str(definition.parent), "root_dataset_inventory_profile": ROOT142_PROFILE,
            "root_inventory_policy_source_sha256": ROOT142_POLICY_SHA, "count_contract": meta["count_contract"],
            "expected_checks": {"dimension": 3, "data2d": False, "dp_m": 0.01,
                                "time_max_s": 4.0, "time_out_s": 0.01,
                                "counts": "actual receipt/XML only; no fabricated expected count",
                                "positive_fluid_required": True, "native_geometry_qa_required_before_solver": True},
            "disabled_reason": "Root142 enable only after source review"},
        "actual_qa": {**base, "attempt_id": qa, "kind": "cpu", "cpu_task_kind": "audit",
            "cpu_threads": 2, "max_wall_seconds": 1800, "estimated_storage_bytes": 268435456,
            "command": [str(INFRA / "lagrangian-fluid-lab/.venv/bin/python"), str(worker), "--case-id", cid,
                        "--definition", str(definition), "--gencase-receipt", "{gencase_attempt_root}/execution-receipt.json",
                        "--partvtk", str(PARTVTK), "--partvtk-output-dir", "{attempt_root}/partvtk",
                        "--output", "{attempt_root}/actual-initial-qa.json"],
            "cwd": str(INFRA / "lagrangian-fluid-lab"), "depends_on_attempt": ga,
            "root_dataset_inventory_profile": ROOT142_PROFILE,
            "root_inventory_policy_source_sha256": ROOT142_POLICY_SHA,
            "required_checks": ["actual GenCase success", "actual 3-D XML", "finite frame zero",
                                 "positive Type3 fluid", "unique Idp", "domain/non-overlap/source lattice"],
            "disabled_reason": "Enable only after matching actual GenCase receipt"},
        "solver": {**base, "attempt_id": f"root-stage1-f2-{cid.lower()}-full401-native-095",
            "kind": "qualification", "cpu_task_kind": "solver", "cpu_threads": 2,
            "target_gpu_index": None, "max_wall_seconds": 3600, "estimated_peak_gpu_mib": 8192,
            "estimated_storage_bytes": 8589934592,
            "command": [str(SOLVER), "{gencase_prefix}", "{attempt_root}/solver_output", "-tmax:4.0", "-tout:0.01"],
            "cwd": "{gencase_output_root}", "gencase_receipt": "{gencase_attempt_root}/execution-receipt.json",
            "initial_qa_report": "{qa_attempt_root}/actual-initial-qa.json",
            "depends_on_attempts": [ga, qa],
            "solver_options_policy": "exact native command; no mdbc/noslip; XML mvrotfile authoritative",
            "expected_output": {"full_window_s": 4.0, "save_interval_s": 0.01, "frame_count": 401,
                                "solver_dimension": 3, "native_output_hash": None},
            "native_initial_qa_required": True, "solver_launch_forbidden": True,
            "root_dataset_inventory_profile": ROOT230_PROFILE, "root_inventory_policy_source_sha256": ROOT230_POLICY_SHA,
            "root230_dispatch": {"entry": str(ROOT230_LAUNCH), "entry_sha256": sha256(ROOT230_LAUNCH),
                                 "home_floor_policy": str(ROOT230_POLICY), "home_floor_policy_sha256": ROOT230_POLICY_SHA,
                                 "gpu_policy": str(GPU_POLICY), "gpu_policy_sha256": sha256(GPU_POLICY), "root_owned": True},
            "disabled_reason": "Root230 enable only after actual GenCase and initial QA pass"},
    }
    out = {}
    for kind, doc in docs.items():
        path = HERE / "requests" / f"{cid}-{kind}-disabled.json"; dump(path, doc); out[kind] = path
    return out

def build() -> None:
    for name in ("source", "requests", "owners", "evidence", "workers"):
        (HERE / name).mkdir(parents=True, exist_ok=True)
    worker = HERE / "workers/f2_stage1_initial_qa_worker.py"; shutil.copyfile(TEMPLATE_QA_WORKER, worker)
    rows = []
    for x in OFFSETS:
        spec = case_spec(x); definition, motion, meta = materialize_source(spec)
        reqs = write_requests(meta, definition, worker)
        owner = {"schema": "ds02.f2.stage1.first8.prospective-owner.v1", "family_id": "F2",
                 "scope_id": SCOPE_ID, "case_id": spec["case_id"], "physical_case_id": spec["physical_case_id"],
                 "physical_condition_sha256": meta["physical_condition_sha256"],
                 "numerical_recipe_sha256": meta["numerical_recipe_sha256"],
                 "canonical_identity": {"condition_id": f"{spec['physical_case_id']}::{meta['physical_condition_sha256']}",
                                        "alias_counting": "source zero; count only after actual GenCase+QA+native+Root visual"},
                 "source": {"definition": bind(definition), "motion": bind(motion),
                            "metadata": bind(HERE / "source" / f"{spec['case_id']}.metadata.json"),
                            "source_template": bind(TEMPLATE_DEF), "initial_qa_worker": bind(worker)},
                 "physical_parameter_changed": "receiver_x_m", "execution_allowed": False,
                 "actual_evidence": {"gencase": None, "initial_qa": None, "native_solver": None, "visual_acceptance": None},
                 "production_approval": "none", "qualification": "none",
                 "mass_policy": "No native count or mass asserted; Root actual outputs are authoritative",
                 "disabled_requests": {k: str(v.resolve()) for k, v in reqs.items()}}
        op = HERE / "owners" / f"{spec['case_id']}.owner.json"; dump(op, owner)
        rows.append({"case_id": spec["case_id"], "physical_case_id": spec["physical_case_id"], "receiver_x_m": x,
                     "receiver_x_grid_index_dp010": int(round(x / 0.01)),
                     "physical_condition_sha256": meta["physical_condition_sha256"],
                     "numerical_recipe_sha256": meta["numerical_recipe_sha256"],
                     "definition": bind(definition), "motion": bind(motion),
                     "metadata": bind(HERE / "source" / f"{spec['case_id']}.metadata.json"),
                     "owner": bind(op), "source_fixture_only": True,
                     "requests": {k: str(v.resolve()) for k, v in reqs.items()}})
    dump(HERE / "evidence/existing-endpoint-audit.json", {
        "schema": "ds02.f2.stage1.first8.existing-endpoint-audit.v1", "source_only": True,
        "arrays_opened": False, "mother_support": {"case_id": MOTHER_CASE_ID,
        "physical_condition_sha256": MOTHER_PHYSICAL_HASH, "owner": bind(MOTHER_OWNER),
        "status": "accepted_support_only"}, "source090": {"manifest": bind(BASE090 / "F2_STAGE1_OFFSET_ENDPOINT_MANIFEST.json"),
        "p01_condition_sha256": P01_PHYSICAL_HASH, "p03_condition_sha256": P03_PHYSICAL_HASH},
        "source092": {"manifest": bind(BASE092 / "manifest.json")},
        "source094": {"manifest": bind(BASE094 / "manifest.json"), "endpoint_audit": bind(BASE094 / "metadata/endpoint-audit.json"),
        "p01_status": "actual native+typed completed0; visual accepted",
        "p03_status": "native completed0; original typed OS143/unknown; recovery-bound postprocessing; visual pending",
        "p07_status": "pre_registered_no_native_output; no completion/rejection claim"},
        "distinct_case_accounting": {"existing_distinct_cases": 3, "new_source_conditions": 5,
                                      "prospective_first8_total": 8, "no_resolution_or_time_aliases": True}})
    dump(HERE / "evidence/root-request-contract.json", {
        "schema": "ds02.f2.stage1.first8.root-request-contract.v1",
        "root142": {"policy": str(ROOT142_POLICY), "policy_sha256": ROOT142_POLICY_SHA, "disabled_gencase_and_qa": True},
        "root230": {"policy": str(ROOT230_POLICY), "policy_sha256": ROOT230_POLICY_SHA, "launch": str(ROOT230_LAUNCH),
                    "gpu_policy": str(GPU_POLICY), "disabled_solver_until_actual_gencase_and_qa": True},
        "native_recipe": {"command": [str(SOLVER), "{gencase_prefix}", "{attempt_root}/solver_output", "-tmax:4.0", "-tout:0.01"],
                          "no_extra_mdbc_or_noslip": True, "expected_frames": 401, "future_hash": None},
        "source_only": True, "execution_allowed": False, "no_shared_ledger_write": True})
    dump(HERE / "evidence/stripped-mother-diff.json", {
        "schema": "ds02.f2.stage1.first8.stripped-mother-diff.v1",
        "mother_support": {"case_id": MOTHER_CASE_ID, "physical_condition_sha256": MOTHER_PHYSICAL_HASH,
                           "role": "support only; no mother count/mass reuse"},
        "p01_template_condition_sha256": P01_PHYSICAL_HASH, "p03_condition_sha256": P03_PHYSICAL_HASH,
        "parameter_policy": "Only receiver low-x changes from the reviewed P01 source; all fluid, motion, controls and window stay fixed.",
        "new_cases": [{"case_id": r["case_id"], "receiver_x_m": r["receiver_x_m"],
                       "changed_xml_element": "receiver low-x point", "parameter_change_only": True} for r in rows],
        "p07_reclassification": False})
    dump(HERE / "F2_STAGE1_FIRST8_REMAINING_OFFSET_LATTICE_MANIFEST.json", {
        "schema": "ds02.f2.stage1.first8.source-only-manifest.v1", "family_id": "F2",
        "scope_id": SCOPE_ID, "status": "source_fixture_only_pending_root_review", "source_only": True,
        "execution_allowed": False, "existing_distinct_cases": {"mother": MOTHER_PHYSICAL_HASH,
        "p01": P01_PHYSICAL_HASH, "p03": P03_PHYSICAL_HASH}, "new_case_count": 5,
        "prospective_first8_total": 8, "selection": {"receiver_x_m": list(OFFSETS),
        "grid_spacing_m": 0.01, "receiver_y_m": 0.14, "fill_ratio": 0.8, "mouth_geometry": "open_rim",
        "physical_parameter_varied": "receiver_x_m only", "no_repeated_resolution_or_time_view": True},
        "recipe_contract": RECIPE, "count_contract": counts_contract(), "cases": rows,
        "next_two_genuine_gencase_requests": [
            str((HERE / "requests" / f"{rows[0]['case_id']}-gencase-disabled.json").resolve()),
            str((HERE / "requests" / f"{rows[1]['case_id']}-gencase-disabled.json").resolve()),
        ],
        "future_hashes_null": True, "disabled_requests": True,
        "p07_policy": "P07 remains pre_registered_no_native_output; no completion/rejection claim",
        "no_numeric_execution_in_build": True})

if __name__ == "__main__":
    build()
