#!/usr/bin/env python3
"""Build and validate fresh102 explicit physical bindings.

This script reads only JSON/XML/Python metadata and static source XML/JSON.
It refuses science payload suffixes and never opens DAT/BI4/CSV/H5/VTK/XMF.
It uses the real integration converter's physical-binding validator and hash.
"""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
F5 = PKG.parents[2]
INTEGRATION = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
LAB = INTEGRATION/'lagrangian-fluid-lab'
F5_ROOT = Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics')
F5_FAMILY = F5_ROOT/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F5'
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5')
CASE_DIR = DATA/'F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1'
CASE = 'F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1'
BASELINE_PHYSICAL_CASE = 'F5_COMPACT_STILL_WATER_RUNUP_RECOVERY_C082S1'
BASE_MOTION_SHA = '51e197f0831915a73534c619704658b06812c9d52c38c470ab4cbb8d59f5614a'
LEGACY_SCOPE_SHA = '3cd1ceab16be11428bbc1011a1b4e297c384d8c7926432c222c254064744ccd0'
SOURCE_PLAN_SHA = '5bad3ec9f9a71aa87da8272003c357f4523d4ffa164d3f06e5d25fee1a4fbfa6'
GENCASE_ATTEMPT = 'root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293'
GENCASE_RECEIPT = CASE_DIR/GENCASE_ATTEMPT/'execution-receipt.json'
GENCASE_REPORT = CASE_DIR/GENCASE_ATTEMPT/'prepared/prepared-input-report.json'
GENCASE_XML = CASE_DIR/GENCASE_ATTEMPT/'prepared/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1.xml'
ROOT363_REPORT = CASE_DIR/'root-stage1-f5-c082s1-actual-full801-bed-audit-root363/audit-output/c082s1-full-event-bed-footprint-audit.json'
ROOT370_REPORT = CASE_DIR/'root-stage1-f5-c082s1-full801-actual-motion-trajectory-audit-370/audit-output/actual-motion-trajectory-audit.json'
ROOT370_RECEIPT = CASE_DIR/'root-stage1-f5-c082s1-full801-actual-motion-trajectory-audit-370/execution-receipt.json'
RECIPE = F5_FAMILY/'handoff_20261003/root_followup_093_stage1_f5_c082s1_short51_pipeline_v1/canonical-physical-recipe.json'
OWNER094 = F5_FAMILY/'handoff_20261003/root_followup_094_stage1_f5_c082s1_conversion_owner_v1/conversion-owner-metadata.json'
OWNER099 = F5_FAMILY/'handoff_20261003/root_followup_099_stage1_f5_c082s1_bounded_excitation_recovery_v1/candidates'
EVIDENCE099 = F5_FAMILY/'handoff_20261003/root_followup_099_stage1_f5_c082s1_bounded_excitation_recovery_v1/metadata/mechanism-recovery-evidence.json'
CONVERTER = LAB/'scripts/ds_data02_direct_convert.py'
ROOT230_LAUNCH = LAB/'campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py'
ROOT230_POLICY = LAB/'campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230/root_native_home_floor_inventory_policy.py'
ROOT142_POLICY = LAB/'campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py'
RESOURCE_APPROVAL = LAB/'handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json'
RUNTIME = LAB/'scripts/ds_data02_runtime_v2.py'
STRICT = LAB/'scripts/ds_data02_strict_dispatch_v1.py'
GENCASE_WORKER = LAB/'campaigns/ds-data-02/handoff_20261003/root_native_source_preflight_tools_003/gencase.py'
GENCASE_BINARY = Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64')
SOLVER_BINARY = Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64')
MOTION_WORKER = F5_FAMILY/'handoff_20261003/root_followup_099_stage1_f5_c082s1_bounded_excitation_recovery_v1/workers/scale_compact_motion.py'
BASE_MOTION = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050/root-compact-equilibrium-runup_coarse-clip-direction-fix-gencase-050/prepared/assets/f5_compact_packet_motion.dat')
RESOURCE_SHA = '2a35e26e36920d8ca40001fd7f28416f27bcf371b8b882eca37868f4a15152b8'
ROOT230_LAUNCH_SHA = '7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e'
ROOT230_POLICY_SHA = 'c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5'
ROOT142_POLICY_SHA = '2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5'
CONVERTER_SHA = '8ec204edb5ac20f2d83e2b9a3b5e70eb45cf1104fe0ee4bd8c3413a241c10ccd'
GENCASE_SHA = 'a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226'
ROOT230_PROFILE = 'root_home_floor_no_legacy_dataset_walk_native_v1'
ROOT142_PROFILE = 'root_home_floor_no_legacy_dataset_walk_v1'

SCIENCE_SUFFIXES = {'.dat', '.bi4', '.h5', '.hdf5', '.csv', '.vtk', '.vtu', '.xmf', '.xdmf'}

def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))

def sha(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise RuntimeError(f'refusing science payload hash: {path}')
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')

def import_converter():
    spec = importlib.util.spec_from_file_location('ds_data02_direct_convert_fresh102', CONVERTER)
    if spec is None or spec.loader is None:
        raise RuntimeError('cannot import real converter')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

def xml_data2d_and_pointref(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    data2d = root.find('./execution/constants/data2d')
    point = root.find('./geometry/pointref')
    return {
        'root_tag': root.tag,
        'data2d': None if data2d is None else data2d.get('value'),
        'pointref_xml': None if point is None else dict(point.attrib),
    }

def binding_for(cid: str, owner: dict[str, Any], recipe: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    scale = float(owner['motion_transform']['scale'])
    geometry = copy.deepcopy(baseline['geometry'])
    initial_state = copy.deepcopy(baseline['initial_state'])
    controls = copy.deepcopy(baseline['controls'])
    event_window = copy.deepcopy(baseline['event_window'])
    params = {
        'bed_closed': True,
        'bed_representation': 'closed analytic xz profile extruded along y',
        'bed_extrusion_y_bounds_m': copy.deepcopy(recipe['bed']['extrusion_y_bounds_m']),
        'bed_profile_upper_xz_m': copy.deepcopy(recipe['bed']['profile_nodes_xz_m']),
        'bed_profile_lower_xz_m': copy.deepcopy(baseline['parameters']['bed_profile_lower_xz_m']),
        'boundary_method': 'finite floor and sidewalls with prescribed moving piston',
        'fluid_box_m': copy.deepcopy(baseline['parameters']['fluid_box_m']),
        'pointref_m': copy.deepcopy(recipe['pointref_m']),
        'piston_motion': {
            'kind': 'prescribed_table_motion',
            'asset_relative_name': 'assets/f5_c082s1_motion_s%s.dat' % ('080' if scale == 0.8 else '120'),
            'base_asset_relative_name': recipe['controls_unchanged']['motion_asset_relative_name'],
            'base_asset_sha256': BASE_MOTION_SHA,
            'base_asset_sha256_provenance': 'copied from registered C082S1 producer metadata; this source package did not read or hash DAT',
            'duration_s': float(recipe['controls_unchanged']['motion_duration_s']),
            'fieldtime': 0,
            'fieldx': 1,
            'amplitude_scale': scale,
        },
        'source_draw_order': 'closed analytic bed/tank/piston followed by clipplane separator, solid fluid drawbox, and clipreset',
    }
    return {
        'schema': 'ds-data-02.physical-binding.v1',
        'family_id': 'F5',
        'physical_case_id': owner['physical_case_id'],
        'mechanism_id': baseline['mechanism_id'],
        'geometry_family_id': baseline['geometry_family_id'],
        'control_family_id': owner['control_recipe_id'],
        'lineage_group_id': baseline['lineage_group_id'],
        'paired_background_id': baseline['paired_background_id'],
        'open_inlet': False,
        'periodic_boundary': False,
        'geometry': geometry,
        'initial_state': initial_state,
        'controls': controls,
        'gravity_m_s2': copy.deepcopy(baseline['gravity_m_s2']),
        'density_kg_m3': float(baseline['density_kg_m3']),
        'parameters': params,
        'event_window': event_window,
        'mass_policy': 'native particle weights are authoritative; continuum mass is a reporting baseline and is never rescaled',
    }

def static_inputs(paths: list[Path | str], base_motion_hash: str = BASE_MOTION_SHA) -> tuple[list[str], dict[str, str | None]]:
    files: list[str] = []
    hashes: dict[str, str | None] = {}
    for item in paths:
        s = str(item)
        files.append(s)
        p = Path(s)
        if s.startswith('<root-bind:') or s.startswith('{') or not p.exists():
            hashes[s] = None
        elif p == BASE_MOTION or p.suffix.lower() == '.dat':
            # Producer-declared hash is copied; this script never opens DAT.
            hashes[s] = base_motion_hash if p == BASE_MOTION else None
        elif p.suffix.lower() in SCIENCE_SUFFIXES:
            hashes[s] = None
        elif p.is_file():
            hashes[s] = sha(p)
        else:
            hashes[s] = None
    return files, hashes

def root230_meta() -> dict[str, Any]:
    return {
        'entrypoint': str(ROOT230_LAUNCH),
        'entrypoint_sha256': ROOT230_LAUNCH_SHA,
        'policy_source': str(ROOT230_POLICY),
        'policy_source_sha256': ROOT230_POLICY_SHA,
        'profile': ROOT230_PROFILE,
        'solver_kinds_only': ['qualification', 'production'],
        'launch_owner': 'root',
        'gpu_protection': 'Root230 launch is the reviewed Home-floor/native GPU wrapper; CPU metadata stages remain disabled and use Root142 CPU dispatch until Root binds them.',
    }

def root142_meta() -> dict[str, Any]:
    return {
        'policy_source': str(ROOT142_POLICY),
        'policy_source_sha256': ROOT142_POLICY_SHA,
        'profile': ROOT142_PROFILE,
        'launch_owner': 'root',
        'cpu_stage_only': True,
    }

def resource_window() -> dict[str, Any]:
    return {
        'approval_sha256': RESOURCE_SHA,
        'cpu_core_hours': 3840,
        'gpu_hours': 512,
        'qualification_attempts': 1024,
        'production_attempts': 720,
        'home_min_free_bytes': 536870912000,
        'deadline_utc': '2026-10-14T07:23:48+00:00',
        'launch_owner': 'root',
        'profile': ROOT142_PROFILE,
    }

def common_request(cid: str, owner: dict[str, Any], bind_hash: str, attempt: str, kind: str, task: str, *, max_wall: int, storage: int, depends: str | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {
        'schema': 'ds02.runner-request.v2',
        'status': 'disabled_until_root_review_and_actual_upstream_receipts',
        'kind': kind,
        'cpu_task_kind': task,
        'disabled': True,
        'launch': False,
        'launch_allowed': False,
        'execution_allowed': False,
        'solver_allowed': False,
        'conversion_allowed': False,
        'arrays_allowed': False,
        'array_edit_allowed': False,
        'shared_registry_write_allowed': False,
        'source_only': True,
        'root_review_required': True,
        'launch_owner': 'root',
        'family_id': 'F5',
        'candidate_id': owner['candidate_id'],
        'case_id': CASE,
        'physical_case_id': owner['physical_case_id'],
        'condition_id': owner['condition_id'],
        'physical_condition_sha256': bind_hash,
        'canonical_physical_binding_sha256': bind_hash,
        'source_plan_physical_condition_sha256': owner['source_plan_physical_condition_sha256'],
        'attempt_id': attempt,
        'depends_on_attempt': depends,
        'cwd': str(LAB),
        'cpu_threads': 2,
        'max_wall_seconds': max_wall,
        'estimated_storage_bytes': storage,
        'independent_case_count_increment': 0,
        'full16_authorized': False,
        'full801_authorized': False,
        'q_n_granted': False,
        'production_approval': 'none',
        'future_output_hashes': {
            'receipt_sha256': None,
            'prepared_input_report_sha256': None,
            'generated_xml_sha256': None,
            'generated_bi4_sha256': None,
            'scaled_motion_sha256': None,
            'native_typed_h5_sha256': None,
            'xmf_manifest_sha256': None,
            'bed_audit_report_sha256': None,
        },
        'resource_window': resource_window(),
        'root_dataset_inventory_profile': ROOT142_PROFILE,
        'root_inventory_policy_source_sha256': ROOT142_POLICY_SHA,
        'root230_dispatch_provenance': root230_meta(),
        'root230_gpu_selection_required_for_native_solver': True,
        'input_sha256_provenance': 'static source/metadata hashes only; producer-declared base DAT hash is copied without source-agent DAT read; future outputs remain null',
        'old_attempt_modification_forbidden': True,
        'worktree_root': str(F5_ROOT),
    }
    if depends is None:
        d.pop('depends_on_attempt')
    return d

def future_contract(cid: str, owner: dict[str, Any], bind_hash: str, baseline_counts: dict[str, Any]) -> dict[str, Any]:
    scale = owner['motion_transform']['scale']
    short = '080' if scale == 0.8 else '120'
    motion_attempt = f'root-stage1-f5-c082s1-A{short}-motion-transform-102'
    gen_attempt = f'root-stage1-f5-c082s1-A{short}-genuine-gencase-102'
    qa_attempt = f'root-stage1-f5-c082s1-A{short}-initial-qa-mk50-102'
    short_attempt = f'root-stage1-f5-c082s1-A{short}-short-native-qualification-102'
    bed_attempt = f'root-stage1-f5-c082s1-A{short}-short-bed-audit-102'
    return {
        'candidate_id': owner['candidate_id'],
        'scale': scale,
        'attempts': {'motion_transform': motion_attempt, 'gencase': gen_attempt, 'initial_qa_mk50': qa_attempt, 'short_native': short_attempt, 'short_bed_audit': bed_attempt},
        'candidate_counts': {'total_particles': None, 'fixed_particles': None, 'moving_particles': None, 'floating_particles': None, 'fluid_particles': None},
        'baseline_reference_counts_only': baseline_counts,
        'expected_dimension_from_producer': None,
        'future_artifacts': {'motion_transform_receipt': None, 'scaled_motion_sha256': None, 'gencase_receipt_sha256': None, 'prepared_input_report_sha256': None, 'generated_xml_sha256': None, 'generated_bi4_sha256': None, 'initial_qa_report_sha256': None, 'short_native_receipt_sha256': None, 'typed_h5_sha256': None, 'xmf_manifest_sha256': None, 'bed_audit_report_sha256': None},
        'stage_order': ['motion_transform', 'genuine_gencase', 'initial_qa_and_mk50_coverage', 'short_native_1s_51frames', 'short_dynamic_bed_audit'],
        'full801_enabled': False,
    }

def main() -> int:
    recipe = load(RECIPE)
    baseline = load(OWNER094)
    evidence = load(EVIDENCE099)
    gencase_receipt = load(GENCASE_RECEIPT)
    gencase_report = load(GENCASE_REPORT)
    bed_report = load(ROOT363_REPORT)
    motion_report = load(ROOT370_REPORT)
    motion_receipt = load(ROOT370_RECEIPT)
    xml_meta = xml_data2d_and_pointref(GENCASE_XML)
    if xml_meta['data2d'] != 'false':
        raise RuntimeError('actual Gen293 XML is not 3-D')
    counts = {
        'total_particles': int(gencase_receipt['total_particles']),
        'fixed_particles': int(gencase_report['generated_xml_particle_counts']['fixed']),
        'moving_particles': int(gencase_report['generated_xml_particle_counts']['moving']),
        'floating_particles': int(gencase_report['generated_xml_particle_counts']['floating']),
        'fluid_particles': int(gencase_receipt['fluid_particles']),
        'solver_dimension': int(gencase_receipt['solver_dimension_from_gencase']),
    }
    if counts != {'total_particles': 194427, 'fixed_particles': 158559, 'moving_particles': 4210, 'floating_particles': 0, 'fluid_particles': 31658, 'solver_dimension': 3}:
        raise RuntimeError(f'unexpected actual baseline producer counts: {counts}')
    mod = import_converter()
    reports: dict[str, Any] = {}
    scope_hashes: dict[str, str] = {}
    for cid in ('A080', 'A120'):
        owner = load(OWNER099/cid/'canonical-physical-owner.json')
        binding = binding_for(cid, owner, recipe, baseline)
        validated = mod._validate_physical_binding(binding)
        scoped = mod._physical_condition_scope({'physical_binding': binding})
        if scoped != validated:
            raise RuntimeError(f'{cid}: converter scope differs from validated binding')
        canonical = mod.canonical_hash(scoped)
        scope_hashes[cid] = canonical
        if canonical in {owner['canonical_physical_condition_sha256'], owner['source_plan_physical_condition_sha256'], LEGACY_SCOPE_SHA, recipe['physical_condition_sha256']}:
            raise RuntimeError(f'{cid}: canonical scope hash collided with an older identity')
        dump(PKG/'bindings'/f'{cid}-physical-binding.json', binding)
        report = {
            'schema': 'ds02.f5.c082s1.explicit-physical-binding-report.fresh102.v1',
            'candidate_id': owner['candidate_id'],
            'case_id': CASE,
            'physical_case_id': owner['physical_case_id'],
            'condition_id': owner['condition_id'],
            'binding_path': str(PKG/'bindings'/f'{cid}-physical-binding.json'),
            'physical_binding_schema': binding['schema'],
            'converter_scope_schema': scoped['schema'],
            'canonical_physical_binding_sha256': canonical,
            'converter_source': str(CONVERTER),
            'converter_source_sha256': CONVERTER_SHA,
            'converter_validation': 'actual ds_data02_direct_convert._validate_physical_binding and _physical_condition_scope passed metadata-only',
            'identity_separation': {
                'fresh099_owner_identity_sha256': owner['canonical_physical_condition_sha256'],
                'fresh099_owner_file_sha256': sha(OWNER099/cid/f'canonical-physical-owner.json'),
                'candidate_definition_sha256': sha(PKG/'inputs'/f'{cid}-Definition.xml'),
                'candidate_source_plan_sha256': owner['source_plan_physical_condition_sha256'],
                'baseline_recipe_physical_condition_sha256': recipe['physical_condition_sha256'],
                'baseline_gen293_legacy_producer_scope_sha256': LEGACY_SCOPE_SHA,
                'new_explicit_converter_scope_sha256': canonical,
                'definition_sha256_equals_source_plan_sha256_as_declared': sha(PKG/'inputs'/f'{cid}-Definition.xml') == owner['source_plan_physical_condition_sha256'],
                'scope_identities_distinct': len({owner['canonical_physical_condition_sha256'], sha(OWNER099/cid/f'canonical-physical-owner.json'), owner['source_plan_physical_condition_sha256'], recipe['physical_condition_sha256'], LEGACY_SCOPE_SHA, canonical}) == 6,
            },
            'motion_control': {
                'scale': owner['motion_transform']['scale'],
                'base_asset_relative_name': recipe['controls_unchanged']['motion_asset_relative_name'],
                'base_asset_sha256': BASE_MOTION_SHA,
                'base_asset_sha256_provenance': 'registered producer metadata only; source agent did not read or hash DAT',
                    'scaled_receipt_sha256': None,
                'control_rows': int(motion_report['control_rows']),
                'control_time_range_s': motion_report['control_time_range_s'],
                'motion_audit_source': str(ROOT370_REPORT),
                'motion_audit_sha256': 'f0f9dfabc0929919f630848b76f7adfe89081a05bebb69c9e0658d6cdbf8996c',
                'weak_excitation_hold': True,
            },
            'baseline_gen293_producer_provenance_only': {
                'attempt_id': GENCASE_ATTEMPT,
                'receipt_path': str(GENCASE_RECEIPT),
                'receipt_sha256': '651f3dd714ded9a9d8e4cc158702925f0cb06d0b778dcc66827de4b085e058b7',
                'prepared_input_report_path': str(GENCASE_REPORT),
                'prepared_input_report_sha256': 'c0572867ac670c4d4676f40463ebc903ace06ddf9bf5a47f533a2cfd5c83585a',
                'generated_xml_path': str(GENCASE_XML),
                'generated_xml_sha256': '19102e12efb4ba6d36f12bc020135fbcd7013949b9089fe1b6197b8e23c51e8e',
                'generated_bi4_sha256_from_producer_report': gencase_report.get('bi4_sha256'),
                'generated_xml_data2d': xml_meta['data2d'],
                'actual_counts': counts,
                'candidate_counts_are_not_inferred': True,
            },
            'root363_exact_bed_provenance': {
                'path': str(ROOT363_REPORT),
                'schema': bed_report.get('schema'),
                'status': bed_report.get('status'),
                'native_bed_marker_mk': bed_report['native_identity_contract']['native_bed_marker_mk'],
                'source_bed_marker_mkbound': bed_report['native_identity_contract']['source_bed_marker_mkbound'],
                'bed_x_domain_m': bed_report['scan']['bed_x_domain_m'],
                'bed_y_domain_m': bed_report['scan']['bed_y_domain_m'],
                'depth_tolerances_m': bed_report['scan']['depth_tolerances_m'],
                'frames_scanned': bed_report['scan']['frames_scanned'],
                'dynamic_acceptance': bed_report['dynamic_bed_diagnostic']['dynamic_acceptance'],
            },
            'root370_motion_provenance': {
                'path': str(ROOT370_REPORT),
                'receipt_path': str(ROOT370_RECEIPT),
                'status': motion_report['status'],
                'control_rows': motion_report['control_rows'],
                'moving_saved_displacement_max_m': motion_report['moving_saved_displacement_max_m'],
                'fluid_saved_displacement_max_m': motion_report['fluid_saved_displacement_max_m'],
                'full_visual_runup_event_not_granted': motion_report['full_visual_runup_event_not_granted'],
                'actual_receipt_counts': motion_receipt['request']['actual_counts'],
            },
            'candidate_future': future_contract(cid, owner, canonical, counts),
        }
        dump(PKG/'metadata'/f'{cid}-explicit-physical-binding-report.json', report)
        reports[cid] = report
    baseline_provenance = {
        'schema': 'ds02.f5.c082s1.baseline-and-scope-separation.fresh102.v1',
        'baseline_case': BASELINE_PHYSICAL_CASE,
        'baseline_recipe_physical_condition_sha256': recipe['physical_condition_sha256'],
        'baseline_gen293_legacy_producer_scope_sha256': LEGACY_SCOPE_SHA,
        'baseline_counts_producer_bound_only': counts,
        'baseline_continuum_mass_kg': baseline['initial_state']['continuum_mass_by_source_kg']['fluid'],
        'baseline_native_mass_policy': baseline['initial_state']['mass_policy'],
        'candidate_scope_hashes': scope_hashes,
        'candidate_counts': {'A080': None, 'A120': None},
        'source_plan_hash': SOURCE_PLAN_SHA,
        'candidate_source_definition_hashes': {cid: sha(PKG/'inputs'/f'{cid}-Definition.xml') for cid in ('A080','A120')},
        'fresh099_owner_identity_hashes': {cid: load(OWNER099/cid/'canonical-physical-owner.json')['canonical_physical_condition_sha256'] for cid in ('A080','A120')},
        'no_candidate_conversion_or_solver_started_by_builder': True,
    }
    dump(PKG/'metadata/baseline-provenance.json', baseline_provenance)
    dump(PKG/'metadata/root230-provenance.json', {'schema':'ds02.f5.root230-gpu-protection.fresh102.v1','root230':root230_meta(),'root142_cpu':root142_meta(),'resource_window':resource_window()})
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
