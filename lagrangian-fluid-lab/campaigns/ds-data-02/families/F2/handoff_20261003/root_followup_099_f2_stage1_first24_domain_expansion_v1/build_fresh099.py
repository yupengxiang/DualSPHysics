#!/usr/bin/env python3
"""Build the F2 fresh099 first24 source-only expansion package.

The builder materializes only small text/XML/JSON fixtures and disabled
requests. It never calls GenCase, PartVTK, DualSPHysics, the shared runner,
an array reader, or a converter. Future native counts and all future output
digests remain null until Root performs the independent GenCase/QA/native
sequence.
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
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
LAB = INTEGRATION / "lagrangian-fluid-lab"
HERE = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_099_f2_stage1_first24_domain_expansion_v1"
BASE095 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_095_f2_stage1_first8_offset_lattice_v1"
BASE090 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_090_f2_stage1_production_endpoints_v1"
BASE098 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_098_f2_actual_typed401_xmf_render_v1"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2")

TEMPLATE_DEF = BASE090 / "source/F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010_Def.xml"
TEMPLATE_MOTION_FAST = BASE090 / "source/F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010_motion.dat"
TEMPLATE_METADATA = BASE090 / "source/F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010.metadata.json"
TEMPLATE_QA_WORKER = BASE095 / "workers/f2_stage1_initial_qa_worker.py"
TEMPLATE_VALIDATOR = BASE095 / "workers/f2_first8_source_contract_validator.py"
MOTION_MEDIUM = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/definitions/F2_REF_OFFSET_NOMINAL_MEDIUM_motion.dat"
FRESH095_MANIFEST = BASE095 / "F2_STAGE1_FIRST8_REMAINING_OFFSET_LATTICE_MANIFEST.json"
FRESH095_ENDPOINT_AUDIT = BASE095 / "evidence/existing-endpoint-audit.json"
FRESH098_REGISTRY = BASE098 / "metadata/case-registry.json"
ROOT326_DECISION = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f2_rx047_full401_visual_acceptance_326/rx047-root-visual-decision.json"
MOTHER_DECISION = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f2_full401_visual_acceptance_061/root-visual-decision.json"
P01_DECISION = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f2_p01_full401_visual_acceptance_177/p01-root-visual-decision.json"
P03_DECISION = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f2_p03_recovered_full401_visual_acceptance_275/p03-root-visual-decision.json"

ROOT142_POLICY = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
ROOT230_DIR = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT230_POLICY = ROOT230_DIR / "root_native_home_floor_inventory_policy.py"
ROOT230_LAUNCH = ROOT230_DIR / "launch.py"
ROOT230_CONTRACT = ROOT230_DIR / "source-policy-contract.json"
GPU_POLICY = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
STRICT_DISPATCH = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
NVME_CONVERTER = LAB / "scripts/ds_data02_nvme_convert_v1.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")

GENCASE = INFRA / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
PARTVTK = INFRA / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
SOLVER = INFRA / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
PYTHON = INFRA / "lagrangian-fluid-lab/.venv/bin/python"
INTEGRATION_PYTHON = INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"

SCOPE_ID = "F2_STAGE1_FIRST24_DOMAIN_EXPANSION_V1"
ROOT142_PROFILE = "root_home_floor_no_legacy_dataset_walk_v1"
ROOT230_PROFILE = "root_home_floor_no_legacy_dataset_walk_native_v1"
ROOT142_POLICY_SHA = "2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5"
ROOT230_POLICY_SHA = "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5"
MOTHER_PHYSICAL_HASH = "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
P01_PHYSICAL_HASH = "c994d0a680c84cdedb984d98c7fcb28bc62d2719999889d3164e44820ccb883c"
P03_PHYSICAL_HASH = "402f576739ee7618ff00e5f570ba726d60a7a88017e456f6ad0aa57b46a2cab2"

X_VALUES = (0.46, 0.48, 0.52, 0.54, 0.57, 0.59, 0.62, 0.64)
ROTATIONS = ((0.65, "065", TEMPLATE_MOTION_FAST, "P01 reviewed fast rotation"),
             (1.20, "120", MOTION_MEDIUM, "reviewed nominal-medium rotation"))
FIRST8_X = {0.45, 0.47, 0.50, 0.55, 0.60, 0.63, 0.65}
RECIPE = {
    "dp_m": 0.01,
    "time_max_s": 4.0,
    "time_out_s": 0.01,
    "expected_saved_frames": 401,
    "solver_dimension": 3,
    "native_forcing_file_format": "#Time;Degrees",
    "solver_options": ["-tmax:4.0", "-tout:0.01"],
    "recipe_role": "Stage1 source candidate; native visual/precision/Q-N/production status pending Root evidence",
}


def sha256(path: Path) -> str:
    """Hash only source/contract text; this builder never accepts science arrays."""
    path = Path(path).resolve()
    if path.suffix.lower() not in {".json", ".xml", ".dat", ".py", ".md", ".txt"} and path.name not in {"bi4_dump", "PartVTK_linux64", "GenCase_linux64", "DualSPHysics5.4_linux64"}:
        raise ValueError(f"refusing non-source hash: {path}")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def bind(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "exists": True}


def dump(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_motion(path: Path) -> dict[float, float]:
    values: dict[float, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip():
            continue
        time_s, angle_s = line.split(";", 1)
        values[float(time_s)] = float(angle_s)
    return values


def case_spec(x: float, rotation_s: float, rotation_code: str, motion_template: Path, motion_label: str) -> dict[str, Any]:
    x_code = int(round(x * 100))
    cid = f"F2_STAGE1_FIRST24_EXPANSION_RX{x_code:03d}_RY014_FILL080_ROT{rotation_code}_DP010_SPATIAL_REFERENCE_SAVE010"
    pid = f"F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX{x_code:03d}_RY014_FILL080_ROT{rotation_code}"
    return {"x": x, "x_code": x_code, "rotation_s": rotation_s, "rotation_code": rotation_code,
            "motion_template": motion_template, "motion_label": motion_label, "case_id": cid,
            "physical_case_id": pid}


def source_condition(spec: dict[str, Any], motion_path: Path) -> dict[str, Any]:
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
        "rotation_duration_s": float(spec["rotation_s"]), "rotation_hold_start_s": 0.5,
        "rotation_final_angle_deg": -105.0, "motion_file_sha256": sha256(motion_path),
        "native_forcing": "official mvrotfile; static 0.5 s, reviewed smooth rotation, final -105 degrees, post-stop hold",
    }


def count_contract() -> dict[str, Any]:
    return {
        "expected_counts": {"total_particles": None, "fluid_particles": None, "fixed_particles": None, "moving_particles": None},
        "count_source": "Root actual GenCase receipt plus generated XML/prepared-input-report; no source-side expected count",
        "measurements_required": [
            "actual GenCase terminal status and returncode",
            "generated XML particle summary and 3-D flag",
            "prepared-input-report actual totals",
            "Root frame-zero native QA finite/UID/Type/Mk/Zone/domain/non-overlap/source-lattice checks",
        ],
        "no_forced_count": True, "no_mother_count_substitution": True,
        "mass_policy": "Root reads actual native mass and reports continuum difference without rescale; source package asserts no mass",
    }


def materialize_source(spec: dict[str, Any]) -> tuple[Path, Path, Path, dict[str, Any]]:
    cid = spec["case_id"]
    pid = spec["physical_case_id"]
    x = f"{spec['x']:.2f}"
    text = TEMPLATE_DEF.read_text(encoding="utf-8")
    old_comment = "<!-- mechanism=offset_spill; physical_case_id=F2_STAGE1_OFFSET_P01_OPEN_RIM_RX045_RY014_FILL080; resolution=coarse_dp010 -->"
    new_comment = f"<!-- mechanism=offset_spill; physical_case_id={pid}; resolution=coarse_dp010; source_template=P01; fresh=fresh099 -->"
    old_motion = "F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010_motion.dat"
    new_motion = f"{cid}_motion.dat"
    old_point = '<point x="0.45" y="-0.16" z="0" />'
    new_point = f'<point x="{x}" y="-0.16" z="0" />'
    for old in (old_comment, old_motion, old_point):
        if text.count(old) != 1:
            raise AssertionError(f"P01 template mismatch for {cid}: {old}")
    text = text.replace(old_comment, new_comment, 1).replace(old_motion, new_motion, 1).replace(old_point, new_point, 1)
    ET.fromstring(text)
    definition = HERE / "source" / f"{cid}_Def.xml"
    motion = HERE / "source" / f"{cid}_motion.dat"
    metadata_path = HERE / "source" / f"{cid}.metadata.json"
    definition.write_text(text, encoding="utf-8")
    shutil.copyfile(spec["motion_template"], motion)

    before = re.sub(r"<!-- mechanism=.*? -->", "<!-- normalized -->", TEMPLATE_DEF.read_text(encoding="utf-8"), count=1)
    after = re.sub(r"<!-- mechanism=.*? -->", "<!-- normalized -->", text, count=1)
    before = re.sub(r"F2_STAGE1_[A-Z0-9_]+_motion\.dat", "{MOTION}", before)
    after = re.sub(r"F2_STAGE1_[A-Z0-9_]+_motion\.dat", "{MOTION}", after)
    changed = [line.rstrip("\n") for line in difflib.unified_diff(before.splitlines(True), after.splitlines(True))
               if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
    expected = [f'-            <point x="0.45" y="-0.16" z="0" />',
                f'+            <point x="{x}" y="-0.16" z="0" />']
    if changed != expected:
        raise AssertionError(f"unexpected source diff for {cid}: {changed!r}")

    condition = source_condition(spec, motion)
    rotation_stop = 0.5 + float(spec["rotation_s"])
    motion_values = read_motion(motion)
    if motion_values.get(0.0) != 0.0 or motion_values.get(4.0) != -105.0 or motion_values.get(rotation_stop) != -105.0:
        raise AssertionError(f"motion contract mismatch for {cid}")
    recipe = dict(RECIPE)
    meta = {
        "schema": "ds02.f2.stage1.first24.prospective-source.v1", "family_id": "F2", "scope_id": SCOPE_ID,
        "case_id": cid, "physical_case_id": pid, "source_batch_template": "F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010",
        "lineage_group_id": "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_DOMAIN_EXPANSION_V1",
        "mechanism_id": "offset_spill", "geometry_family_id": condition["geometry_family_id"], "control_family_id": condition["control_family_id"],
        "parameter_values": {"receiver_x_m": spec["x"], "receiver_y_m": 0.14, "fill_ratio": 0.8,
                             "mouth_geometry": "open_rim", "rotation_duration_s": spec["rotation_s"],
                             "rotation_final_angle_deg": -105.0, "initial_tilt_deg": 0.0},
        "geometry": {"dimension": 3, "data2d": False, "dp_m": 0.01,
                     "receiver_low_m": [spec["x"], -0.16, 0.0], "receiver_size_m": [1.10, 0.60, 0.45],
                     "cup_low_m": [0.0, -0.15, 0.65], "cup_size_m": [0.425, 0.30, 0.45],
                     "tray_low_m": [-1.20, -1.00, -0.20], "tray_size_m": [4.00, 2.00, 0.15],
                     "fluid_low_m": [0.05, -0.11, 0.70], "fluid_source_size_m": [0.325, 0.22, 0.264],
                     "source_layer_count": 3, "source_mk_values": [0, 1, 2],
                     "receiver_x_grid_index_dp010": int(round(spec["x"] / 0.01)),
                     "receiver_x_lattice_contract": {"grid_spacing_m": 0.01, "reviewed_visual_range_m": [0.45, 0.65]}},
        "initial_state": {"velocity_m_per_s": [0.0, 0.0, 0.0], "source_layers": [0, 1, 2],
                          "official_xml_fluid_boxes": True, "actual_counts": None, "actual_mass_kg": None,
                          "source_side_count_assertion": False},
        "motion": {"file_name": motion.name, "sha256": sha256(motion), "format": "#Time;Degrees",
                   "time_start_s": 0.0, "time_end_s": 4.0, "static_hold_start_s": 0.5,
                   "rotation_duration_s": spec["rotation_s"], "rotation_stop_s": rotation_stop,
                   "final_angle_deg": -105.0, "template": spec["motion_label"], "source_bytes_equal_to_reviewed_template": True},
        "physical_condition": condition, "physical_condition_sha256": canonical_sha(condition),
        "source_plan_physical_condition_sha256": canonical_sha(condition), "actual_converter_physical_condition_scope": None,
        "source_canonical_physical_binding_sha256": None, "numerical_recipe": recipe, "numerical_recipe_sha256": canonical_sha(recipe),
        "definition_path": str(definition.resolve()), "definition_sha256": sha256(definition), "motion_path": str(motion.resolve()),
        "count_contract": count_contract(),
        "initial_native_qa_contract": {"worker": str((HERE / "workers/f2_stage1_initial_qa_worker.py").resolve()),
                                        "status": "prospective_disabled_until_actual_gencase_receipt", "future_report_sha256": None, "future_csv_sha256": None},
        "stripped_mother_diff": {"baseline": bind(TEMPLATE_DEF), "changed_xml_element": "receiver low-x point",
                                 "changed_lines": changed, "parameter_change_only": True, "all_other_source_bytes_equal_after_normalization": True},
        "domain_basis": {"root_visual_anchor": str(ROOT326_DECISION.resolve()), "root_visual_anchor_sha256": sha256(ROOT326_DECISION),
                          "accepted_controls": ["open_rim", "receiver_y=0.14", "dp=0.01", "3D", "full4s/401", "final angle=-105deg"],
                          "new_axes": ["receiver_x_m", "rotation_duration_s"], "source_geometry_unchanged": True},
        "generation_status": "source_fixture_only_not_gencase_run", "production_status": "prospective_pending_root_actual_gencase_qa_native_visual",
        "qualification_claim": "none", "production_claim": "none", "source_only": True, "actual_counts": None, "actual_mass_kg": None,
        "future_receipt_hashes": {"gencase": None, "initial_qa": None, "native_solver": None, "typed": None},
        "independent_case_count_increment": 0,
        "independent_case_count_policy": "source condition only; Root increments after genuine GenCase, QA, native and visual evidence",
    }
    dump(metadata_path, meta)
    return definition, motion, metadata_path, meta


def source_inputs(definition: Path, motion: Path, metadata: Path, validator: Path, builder: Path, owner: Path) -> tuple[list[str], dict[str, str]]:
    paths = [definition, motion, metadata, HERE / "workers/f2_stage1_initial_qa_worker.py", validator, builder, owner,
             TEMPLATE_DEF, TEMPLATE_MOTION_FAST, TEMPLATE_METADATA, MOTION_MEDIUM, FRESH095_MANIFEST, FRESH095_ENDPOINT_AUDIT,
             FRESH098_REGISTRY, ROOT326_DECISION, MOTHER_DECISION, P01_DECISION, P03_DECISION,
             ROOT142_POLICY, ROOT230_POLICY, ROOT230_LAUNCH, ROOT230_CONTRACT, GPU_POLICY,
             STRICT_DISPATCH, RUNTIME, NVME_CONVERTER, DECODER, PARTVTK]
    paths = [Path(p).resolve() for p in paths]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    return [str(p) for p in paths], {str(p): sha256(p) for p in paths}


def request_common(meta: dict[str, Any], files: list[str], hashes: dict[str, str]) -> dict[str, Any]:
    return {"schema": "ds02.runner-request.v2", "family_id": "F2", "scope_id": SCOPE_ID,
            "case_id": meta["case_id"], "physical_case_id": meta["physical_case_id"],
            "physical_condition_sha256": meta["physical_condition_sha256"],
            "source_plan_physical_condition_sha256": meta["source_plan_physical_condition_sha256"],
            "canonical_physical_binding_sha256": None, "numerical_recipe_sha256": meta["numerical_recipe_sha256"],
            "worktree_root": str(INFRA), "raw_output_root": str((DATA_ROOT / meta["case_id"]).resolve()), "source_only": True,
            "root_review_required": True, "launch_owner": "root", "launch": False, "launch_allowed": False,
            "execution_allowed": False, "disabled": True, "production_claim": "none", "qualification_claim": "none",
            "numerical_precision_status": "not_accepted", "input_files": files, "input_sha256": hashes,
            "root_dataset_inventory_profile": ROOT142_PROFILE, "root_inventory_policy_source": str(ROOT142_POLICY.resolve()),
            "root_inventory_policy_source_sha256": ROOT142_POLICY_SHA, "no_arrays_read": True, "no_shared_registry_write": True}


def write_requests(meta: dict[str, Any], definition: Path, metadata: Path, validator: Path, builder: Path, owner: Path) -> dict[str, Path]:
    motion = HERE / "source" / f"{meta['case_id']}_motion.dat"
    files, hashes = source_inputs(definition, motion, metadata, validator, builder, owner)
    base = request_common(meta, files, hashes)
    cid = meta["case_id"]; slug = cid.lower()
    ga = f"root-stage1-f2-{slug}-genuine-gencase-099"; qa = f"root-stage1-f2-{slug}-actual-initial-qa-099"
    native = f"root-stage1-f2-{slug}-full401-native-099"; typed = f"root-stage1-f2-{slug}-full401-typed-nvme-099"
    count = count_contract()
    docs: dict[str, dict[str, Any]] = {
        "gencase": {**base, "attempt_id": ga, "kind": "cpu", "cpu_task_kind": "gencase", "cpu_threads": 4,
                    "max_wall_seconds": 600, "estimated_storage_bytes": 536870912,
                    "command": [str(GENCASE), str(definition.with_suffix("")), f"{{attempt_root}}/{cid}", "-save:all", "-threads:4"],
                    "cwd": str(definition.parent), "root_dataset_inventory_profile": ROOT142_PROFILE, "count_contract": count,
                    "expected_checks": {"dimension": 3, "data2d": False, "dp_m": 0.01, "time_max_s": 4.0, "time_out_s": 0.01,
                                        "counts": "actual receipt/XML only; no fabricated expected count", "positive_fluid_required": True,
                                        "native_geometry_qa_required_before_solver": True},
                    "output_contract": {"generated_xml_sha256": None, "generated_bi4_sha256": None, "prepared_input_report_sha256": None, "actual_counts": None},
                    "disabled_reason": "Source-only fresh099; Root may enable only after review and strict dispatch approval"},
        "initial-qa": {**base, "attempt_id": qa, "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2,
                       "max_wall_seconds": 1800, "estimated_storage_bytes": 268435456,
                       "command": [str(PYTHON), str(HERE / "workers/f2_stage1_initial_qa_worker.py"), "--case-id", cid,
                                   "--definition", str(definition), "--gencase-receipt", "{gencase_attempt_root}/execution-receipt.json",
                                   "--partvtk", str(PARTVTK), "--partvtk-output-dir", "{attempt_root}/partvtk", "--output", "{attempt_root}/actual-initial-qa.json"],
                       "cwd": str(INFRA / "lagrangian-fluid-lab"), "depends_on_attempt": ga, "root_dataset_inventory_profile": ROOT142_PROFILE,
                       "root_inventory_policy_source_sha256": ROOT142_POLICY_SHA,
                       "required_checks": ["actual GenCase success", "actual 3-D XML", "finite frame zero", "positive fluid", "unique Idp",
                                            "Type/Mk/Zone partition", "domain/non-overlap/source lattice"],
                       "output_contract": {"actual_qa_report_sha256": None, "actual_counts": None, "mass_kg": None},
                       "disabled_reason": "Enable only after matching actual GenCase receipt exists; no QA output is prefilled"},
        "native": {**base, "attempt_id": native, "kind": "qualification", "cpu_task_kind": "solver", "cpu_threads": 2,
                   "target_gpu_index": None, "max_wall_seconds": 3600, "estimated_peak_gpu_mib": 8192, "estimated_storage_bytes": 8589934592,
                   "command": [str(SOLVER), "{gencase_prefix}", "{attempt_root}/solver_output", "-tmax:4.0", "-tout:0.01"],
                   "cwd": "{gencase_output_root}", "gencase_receipt": "{gencase_attempt_root}/execution-receipt.json", "gencase_receipt_sha256": None,
                   "initial_qa_report": "{qa_attempt_root}/actual-initial-qa.json", "initial_qa_report_sha256": None,
                   "depends_on_attempts": [ga, qa],
                   "solver_options_policy": "exact native command only; no added forcing and no mdbc/noslip option; XML mvrotfile is authoritative",
                   "expected_output": {"full_window_s": 4.0, "save_interval_s": 0.01, "frame_count": 401, "solver_dimension": 3,
                                       "particle_counts": None, "native_output_hash": None}, "native_initial_qa_required": True, "solver_launch_forbidden": True,
                   "root_dataset_inventory_profile": ROOT230_PROFILE, "root_inventory_policy_source_sha256": ROOT230_POLICY_SHA,
                   "root230_dispatch": {"entry": str(ROOT230_LAUNCH), "entry_sha256": sha256(ROOT230_LAUNCH), "home_floor_policy": str(ROOT230_POLICY),
                                        "home_floor_policy_sha256": ROOT230_POLICY_SHA, "gpu_policy": str(GPU_POLICY), "gpu_policy_sha256": sha256(GPU_POLICY), "root_owned": True},
                   "output_contract": {"execution_receipt_sha256": None, "run_out_sha256": None, "actual_frame_count": None, "actual_particle_counts": None},
                   "disabled_reason": "Enable only after actual GenCase and independent initial QA pass; no native output exists here"},
        "typed": {**base, "attempt_id": typed, "kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 2, "max_wall_seconds": 5400,
                  "estimated_storage_bytes": 34359738368,
                  "command": [str(INTEGRATION_PYTHON), str(NVME_CONVERTER), "--staging-root", "/tmp/ds02-nvme-conversion", "--staging-limit-bytes", "25769803776", "--",
                              "--data-root", "{native_attempt_root}/solver_output/data", "--generated-xml", "{gencase_attempt_root}/prepared/{case_id}.xml",
                              "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json", "--solver-log", "{native_attempt_root}/solver_output/Run.out",
                              "--solver-receipt", "{native_attempt_root}/execution-receipt.json", "--gencase-receipt", "{gencase_attempt_root}/execution-receipt.json",
                              "--decoder", str(DECODER), "--partvtk", str(PARTVTK), "--validation-dir", "{attempt_root}/partvtk-validation",
                              "--owner-metadata", str(HERE / "owners" / f"{cid}.owner.json"), "--particle-chunk", "65536"],
                  "cwd": str(LAB), "depends_on_attempts": [ga, qa, native], "expected_dimension": 3, "expected_native_frames": 401,
                  "expected_particles": None, "native_receipt": "{native_attempt_root}/execution-receipt.json", "native_receipt_sha256": None,
                  "gencase_receipt": "{gencase_attempt_root}/execution-receipt.json", "gencase_receipt_sha256": None,
                  "initial_qa_report": "{qa_attempt_root}/actual-initial-qa.json", "initial_qa_report_sha256": None,
                  "producer_scope_schema": "future actual converter scope; source plan binding remains separate", "future_hashes_null": True,
                  "future_input_files": ["{native_attempt_root}/solver_output/data", "{native_attempt_root}/solver_output/Run.out", "{native_attempt_root}/execution-receipt.json",
                                         "{gencase_attempt_root}/prepared/{case_id}.xml", "{gencase_attempt_root}/execution-receipt.json", "{qa_attempt_root}/actual-initial-qa.json"],
                  "future_input_sha256": {"{native_attempt_root}/solver_output/data": None, "{native_attempt_root}/solver_output/Run.out": None,
                                          "{native_attempt_root}/execution-receipt.json": None, "{gencase_attempt_root}/prepared/{case_id}.xml": None,
                                          "{gencase_attempt_root}/execution-receipt.json": None, "{qa_attempt_root}/actual-initial-qa.json": None},
                  "future_outputs": {"conversion_report": "{attempt_root}/conversion-report.json", "conversion_report_sha256": None,
                                     "execution_receipt": "{attempt_root}/execution-receipt.json", "execution_receipt_sha256": None,
                                     "trajectory_h5": "{attempt_root}/trajectory.h5", "trajectory_h5_sha256": None},
                  "resource_contract": {"conversion_concurrency": 2, "cpu_threads": 2, "home_min_free_bytes": 536870912000,
                                        "nvme_free_space_floor_bytes": 107374182400, "nvme_staging_peak_limit_bytes": 25769803776},
                  "owner_metadata": str((HERE / "owners" / f"{cid}.owner.json").resolve()),
                  "decoder_sha256": "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e",
                  "output_contract": {"conversion_report_sha256": None, "trajectory_h5_sha256": None, "actual_frame_count": None, "actual_particle_counts": None},
                  "disabled_reason": "Future typed conversion only after independent native completed/0 and initial QA; no science outputs are bound"},
    }
    out: dict[str, Path] = {}
    for kind, doc in docs.items():
        path = HERE / "requests" / f"{cid}-{kind}-disabled.json"
        dump(path, doc)
        out[kind] = path
    return out


def make_owner(meta: dict[str, Any], definition: Path, motion: Path, metadata: Path, requests: dict[str, Path], worker: Path) -> dict[str, Any]:
    cid = meta["case_id"]
    return {"schema": "ds02.f2.stage1.first24.prospective-owner.v1", "family_id": "F2", "scope_id": SCOPE_ID,
            "case_id": cid, "physical_case_id": meta["physical_case_id"], "physical_condition_sha256": meta["physical_condition_sha256"],
            "source_plan_physical_condition_sha256": meta["source_plan_physical_condition_sha256"], "canonical_physical_binding_sha256": None,
            "canonical_identity": {"condition_id": f"{meta['physical_case_id']}::{meta['physical_condition_sha256']}",
                                   "alias_counting": "source fixture only; Root increments after actual GenCase+QA+native+visual"},
            "source": {"definition": bind(definition), "motion": bind(motion), "metadata": bind(metadata),
                       "source_template": bind(TEMPLATE_DEF), "initial_qa_worker": bind(worker)},
            "physical_parameter_changes": {"receiver_x_m": meta["physical_condition"]["receiver_x_m"], "rotation_duration_s": meta["physical_condition"]["rotation_duration_s"]},
            "geometry_control": {"mouth_geometry": "open_rim", "receiver_y_m": 0.14, "initial_tilt_deg": 0.0,
                                  "fluid_initial_velocity_m_per_s": [0.0, 0.0, 0.0]}, "execution_allowed": False, "source_only": True,
            "actual_evidence": {"gencase": None, "initial_qa": None, "native_solver": None, "typed": None, "visual_acceptance": None},
            "future_hashes_null": True, "production_approval": "none", "qualification": "none",
            "mass_policy": "No native count or mass asserted; Root actual outputs are authoritative",
            "disabled_requests": {key: str(path.resolve()) for key, path in requests.items()}}


def build() -> None:
    for name in ("source", "requests", "owners", "evidence", "workers"):
        (HERE / name).mkdir(parents=True, exist_ok=True)
    worker = HERE / "workers/f2_stage1_initial_qa_worker.py"
    validator = HERE / "workers/fresh099_source_contract_validator.py"
    builder = HERE / "build_fresh099.py"
    shutil.copyfile(TEMPLATE_QA_WORKER, worker)
    if not validator.exists():
        raise FileNotFoundError("fresh099 validator must be present before build")
    rows: list[dict[str, Any]] = []
    for x in X_VALUES:
        for rotation_s, rotation_code, motion_template, motion_label in ROTATIONS:
            spec = case_spec(x, rotation_s, rotation_code, motion_template, motion_label)
            definition, motion, metadata, meta = materialize_source(spec)
            owner_path = HERE / "owners" / f"{spec['case_id']}.owner.json"
            request_paths = {
                "gencase": HERE / "requests" / f"{spec['case_id']}-gencase-disabled.json",
                "initial-qa": HERE / "requests" / f"{spec['case_id']}-initial-qa-disabled.json",
                "native": HERE / "requests" / f"{spec['case_id']}-native-disabled.json",
                "typed": HERE / "requests" / f"{spec['case_id']}-typed-disabled.json",
            }
            # Owner metadata exists before request hashing so every future
            # request binds the exact owner bytes without a hash cycle.
            dump(owner_path, make_owner(meta, definition, motion, metadata, request_paths, worker))
            requests = write_requests(meta, definition, metadata, validator, builder, owner_path)
            rows.append({"case_id": spec["case_id"], "physical_case_id": spec["physical_case_id"], "receiver_x_m": x,
                         "rotation_duration_s": rotation_s, "receiver_y_m": 0.14, "physical_condition_sha256": meta["physical_condition_sha256"],
                         "source_plan_physical_condition_sha256": meta["source_plan_physical_condition_sha256"], "definition": bind(definition),
                         "motion": bind(motion), "metadata": bind(metadata), "owner": bind(owner_path),
                         "requests": {key: str(path.resolve()) for key, path in requests.items()}, "source_fixture_only": True, "actual_evidence": None})

    dump(HERE / "evidence/existing-first8-audit.json", {
        "schema": "ds02.f2.stage1.first24.existing-first8-audit.v1", "source_only": True, "arrays_opened": False,
        "first8_provenance": {"fresh095_manifest": bind(FRESH095_MANIFEST), "fresh095_endpoint_audit": bind(FRESH095_ENDPOINT_AUDIT),
                               "fresh098_registry": bind(FRESH098_REGISTRY), "root326_visual_decision": bind(ROOT326_DECISION),
                               "mother_visual_decision": bind(MOTHER_DECISION), "p01_visual_decision": bind(P01_DECISION), "p03_visual_decision": bind(P03_DECISION)},
        "observed_first8_source_offsets_m": [0.45, 0.47, 0.50, 0.55, 0.60, 0.63, 0.65],
        "existing_first8_count_policy": "mother/P01/P03 and fresh095 five offset fixtures are provenance only; no source row here is counted as accepted",
        "root326_visual_anchor": {"status": "visual-approved-by-root", "frames": 401, "window_s": 4.0, "precision": "not_accepted", "q_n": "not_granted", "production": False, "legacy_scope_retained_separately": True},
        "source_selection": {"new_receiver_x_m": list(X_VALUES), "new_rotation_duration_s": [0.65, 1.2], "tuple_count": 16, "all_new_tuples_unique": True, "excluded_first8_x": sorted(FIRST8_X)},
    })
    dump(HERE / "evidence/domain-decision.json", {
        "schema": "ds02.f2.stage1.first24.domain-decision.v1", "family_id": "F2", "scope_id": SCOPE_ID,
        "status": "source_only_pending_root_review", "source_only": True, "arrays_opened": False,
        "basis": "Bounded extension of the already visual-reviewed open-rim offset domain in Root326/P01/P03; source geometry remains the official P01 construction.",
        "new_parameters": ["receiver_x_m", "rotation_duration_s"], "new_receiver_x_m": list(X_VALUES), "new_rotation_duration_s": [0.65, 1.2], "new_tuple_count": 16,
        "first8_receiver_x_m": sorted(FIRST8_X), "fill_ratio": 0.8, "receiver_y_m": 0.14, "mouth_geometry": "open_rim", "initial_tilt_deg": 0.0,
        "numerical_recipe": RECIPE, "true_3d": True, "actual_count": None,
        "visual_basis": {"root326": bind(ROOT326_DECISION), "p01": bind(P01_DECISION), "p03": bind(P03_DECISION), "mother": bind(MOTHER_DECISION)},
        "legacy_actual_scope_warning": "Root326 actual converter legacy-owner-scope.v0 is retained as evidence; these source tuples do not inherit a canonical/production/precision approval.",
        "excluded_holdouts": {"initial_tilt": "not materialized because the reviewed official XML has no tilt implementation in this source package",
                              "short_spout": "not materialized because no reviewed official source definition implements it", "other_openings": "not materialized; open_rim is the only reviewed opening used here"},
        "approval": {"qualification": "none", "production": "none", "precision": "not_accepted", "q_n": "not_granted"},
    })
    dump(HERE / "evidence/root-request-contract.json", {
        "schema": "ds02.f2.stage1.first24.root-request-contract.v1", "source_only": True, "execution_allowed": False,
        "root142": {"policy": str(ROOT142_POLICY), "policy_sha256": ROOT142_POLICY_SHA, "disabled_gencase_and_qa": True},
        "root230": {"policy": str(ROOT230_POLICY), "policy_sha256": ROOT230_POLICY_SHA, "launch": str(ROOT230_LAUNCH), "gpu_policy": str(GPU_POLICY), "disabled_native_until_actual_gencase_and_qa": True},
        "native_recipe": {"command": [str(SOLVER), "{gencase_prefix}", "{attempt_root}/solver_output", "-tmax:4.0", "-tout:0.01"], "no_extra_mdbc_or_noslip": True, "frames": 401, "window_s": 4.0, "future_hash": None},
        "typed_recipe": {"converter": str(NVME_CONVERTER), "decoder": str(DECODER), "decoder_sha256": "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e", "staging_root": "/tmp/ds02-nvme-conversion", "staging_limit_bytes": 25769803776, "future_native_scope": None, "future_typed_hash": None},
        "all_requests_disabled": True, "no_shared_ledger_write": True, "no_science_input_bound": True,
    })
    dump(HERE / "evidence/stripped-mother-diff.json", {
        "schema": "ds02.f2.stage1.first24.stripped-mother-diff.v1", "source_only": True, "mother_role": "read-only support only; no mother count/mass reuse", "mother_visual_decision": bind(MOTHER_DECISION), "template": bind(TEMPLATE_DEF),
        "parameter_policy": "Each source XML changes only the reviewed P01 receiver low-x point and the forcing-file identity; forcing bytes are copied from a reviewed .65 or .1.2 template. Fluid geometry, opening, source layers, domain, solver parameters and full window remain fixed.",
        "new_cases": [{"case_id": row["case_id"], "receiver_x_m": row["receiver_x_m"], "rotation_duration_s": row["rotation_duration_s"], "changed_xml_element": "receiver low-x point + motion file reference", "parameter_change_only": True} for row in rows],
        "unsupported_axes_not_claimed": ["initial_tilt", "short_spout", "non-open-rim opening"],
    })
    dump(HERE / "F2_STAGE1_FIRST24_DOMAIN_EXPANSION_MANIFEST.json", {
        "schema": "ds02.f2.stage1.first24.source-only-manifest.v1", "family_id": "F2", "scope_id": SCOPE_ID, "status": "source_fixture_only_pending_root_review", "source_only": True, "execution_allowed": False,
        "existing_first8_count": 8, "new_case_count": 16, "prospective_first24_total": 24,
        "selection": {"receiver_x_m": list(X_VALUES), "rotation_duration_s": [0.65, 1.2], "grid_spacing_m": 0.01, "receiver_y_m": 0.14, "fill_ratio": 0.8, "mouth_geometry": "open_rim", "physical_parameters_varied": ["receiver_x_m", "rotation_duration_s"], "no_repeated_physical_tuples": True, "first8_subsumed": True},
        "recipe_contract": RECIPE, "count_contract": count_contract(), "cases": rows,
        "next_two_genuine_gencase_requests": [rows[0]["requests"]["gencase"], rows[1]["requests"]["gencase"]], "future_hashes_null": True, "all_requests_disabled": True, "no_numeric_execution_in_build": True,
        "approval": {"visual": "none for new cases", "precision": "not_accepted", "q_n": "not_granted", "production": "none"},
    })


if __name__ == "__main__":
    build()
