from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

F7 = Path('/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics')
I = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
L = I / 'lagrangian-fluid-lab'
HANDOFF = F7 / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003'
NEW = HANDOFF / 'root_followup_078_stage48_gap_a052p5_v1'
FRESH064 = HANDOFF / 'root_followup_064_stage1_target_angle_full601_native099_nvme_typed_v1'
FRESH065 = HANDOFF / 'root_followup_065_stage1_first8_target_angles_v1'
FRESH070 = HANDOFF / 'root_followup_070_stage1_first24_target_angles_v1'
FRESH074 = HANDOFF / 'root_followup_074_stage1_next24_target_angles_v1'
FRESH077 = HANDOFF / 'root_followup_077_actual_converter_scope_root142_adapter_v1'
CONVERTER = L / 'scripts/ds_data02_direct_convert.py'
VENV = L / '.venv/bin/python'
RUNTIME = L / 'scripts/ds_data02_runtime_v2.py'
STRICT = L / 'scripts/ds_data02_strict_dispatch_v1.py'
GENCASE = I / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_native_source_preflight_tools_003/gencase.py'
MOTION_WORKER = FRESH074 / 'workers/prepare_f7_next24_motion.py'
QA_WORKER = FRESH074 / 'workers/run_f7_next24_native_initial_qa.py'
MOTION_MODULE = I / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_actual_quintic_target_verified_recipe_preparation_020/selected_owner_motion.py'
ROOT230 = I / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230'
ROOT230_LAUNCH = ROOT230 / 'launch.py'
ROOT230_POLICY = ROOT230 / 'root_native_home_floor_inventory_policy.py'
RESOURCE = I / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json'
GPU_POLICY = I / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py'
OFFICIAL = F7 / 'lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux'
GENCASE_BIN = OFFICIAL / 'GenCase_linux64'
SOLVER_BIN = OFFICIAL / 'DualSPHysics5.4_linux64'
PARTVTK_BIN = OFFICIAL / 'PartVTK_linux64'
DECODER = Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump')
NVME = L / 'scripts/ds_data02_nvme_convert_v1.py'
XMF_WORKER = I / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_repair_a_short51_actual_typed_bed_pipeline_105/workers/export_xmf.py'
RENDERER = I / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py'
TEMPLATE076 = HANDOFF / 'root_followup_076_actual_full601_typed_xmf_render_templates_v1'
CASE_MAP = I / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f7_actual_first2_typed077_metadata_XMF_adapter_383/case-map.json'
CASE = 'F7_OBSTACLE_QUINTIC_B08_A052P5'
AMPLITUDE = 52.5
ENCODING = 'A052P5'
RAW_SUFFIXES = {'.bi4', '.csv', '.h5', '.hdf5', '.dat', '.ibi4', '.vtk', '.npy', '.npz'}
HEX64 = re.compile(r'^[0-9a-f]{64}$')

if NEW.exists():
    raise SystemExit(f'refusing to overwrite existing package: {NEW}')
for p in (FRESH064, FRESH065, FRESH070, FRESH074, FRESH077, CONVERTER, VENV, GENCASE, MOTION_WORKER, QA_WORKER, MOTION_MODULE, ROOT230_LAUNCH, ROOT230_POLICY, RESOURCE, GPU_POLICY, GENCASE_BIN, SOLVER_BIN, PARTVTK_BIN, NVME, RUNTIME, STRICT, XMF_WORKER, RENDERER, TEMPLATE076 / 'manifest.json', CASE_MAP):
    if not p.exists():
        raise SystemExit(f'missing required metadata/source input: {p}')


def load(path: Path):
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) and path.name != 'case-map.json':
        raise ValueError(f'JSON object required: {path}')
    return value


def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')


def sha(path: Path) -> str:
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f'raw/scientific payload hashing is forbidden: {path}')
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def canonical(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()


def ensure_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise ValueError(f'{label} missing: {path}')


def metadata_closure(paths):
    files = []
    hashes = {}
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        ensure_file(path, 'metadata closure input')
        if path.suffix.lower() in RAW_SUFFIXES:
            raise ValueError(f'raw payload in metadata closure: {path}')
        key = str(path)
        if key not in hashes:
            files.append(key)
            hashes[key] = sha(path)
    if set(files) != set(hashes):
        raise AssertionError('input_files/input_sha256 closure mismatch')
    return files, hashes


def replace_case(value, old='A050P5', new='A052P5'):
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [replace_case(x, old, new) for x in value]
    if isinstance(value, dict):
        return {k: replace_case(v, old, new) for k, v in value.items()}
    return value


def load_converter():
    spec = importlib.util.spec_from_file_location('ds02_direct_convert_fresh078', CONVERTER)
    if spec is None or spec.loader is None:
        raise RuntimeError('cannot load converter')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# 1. Audit source physical IDs only. Fresh071 duplicates fresh070 and is intentionally not counted.
coverage_sources = [FRESH064, FRESH065, FRESH070, FRESH074]
coverage_rows = []
for package in coverage_sources:
    owners = sorted((package / 'owners').glob('*.json'))
    if not owners:
        raise ValueError(f'no owners in {package}')
    for owner_path in owners:
        owner = load(owner_path)
        physical_case_id = owner.get('physical_case_id') or owner.get('case_id')
        if not isinstance(physical_case_id, str):
            raise ValueError(f'owner has no physical_case_id: {owner_path}')
        pb = owner.get('physical_binding') or {}
        params = pb.get('parameters') or {}
        coverage_rows.append({
            'physical_case_id': physical_case_id,
            'source_owner': str(owner_path.resolve()),
            'source_owner_sha256': sha(owner_path),
            'amplitude_deg': params.get('amplitude_deg'),
            'amplitude_encoding': params.get('amplitude_encoding'),
            'dp_m': params.get('dp_m', 0.02),
            'geometry_family_id': pb.get('geometry_family_id'),
            'lineage_group_id': pb.get('lineage_group_id'),
        })
ids = [row['physical_case_id'] for row in coverage_rows]
unique_ids = sorted(set(ids))
duplicates = sorted({x for x in ids if ids.count(x) > 1})
if len(coverage_rows) != 47 or len(unique_ids) != 47 or duplicates:
    raise ValueError(f'unexpected source physical registry: rows={len(coverage_rows)} unique={len(unique_ids)} duplicates={duplicates}')
if CASE in unique_ids:
    raise ValueError(f'prospective gap is already registered: {CASE}')
coverage = {
    'schema': 'ds02.f7.fresh078.stage48-physical-coverage-audit.v1',
    'scope_id': 'root_followup_078_stage48_gap_a052p5_v1',
    'family_id': 'F7',
    'target_unique_physical_case_count': 48,
    'existing_unique_source_case_count': len(unique_ids),
    'existing_source_owner_row_count': len(coverage_rows),
    'gap_count': 48 - len(unique_ids),
    'source_package_counts': {str(p.resolve()): len(list((p / 'owners').glob('*.json'))) for p in coverage_sources},
    'duplicate_ids': duplicates,
    'existing_unique_physical_case_ids': unique_ids,
    'selected_new_case': CASE,
    'selected_new_amplitude_deg': AMPLITUDE,
    'selected_new_amplitude_encoding': ENCODING,
    'neighboring_registered_amplitudes_deg': [50.5, 54.5],
    'selection_reason': 'Only one source-ID gap remains. A052P5 is a new continuous amplitude between registered A050P5 and A054P5 under the same reviewed geometry/control envelope.',
    'source_rows': coverage_rows,
    'arrays_read': False,
    'payloads_read_or_hashed': False,
    'jobs_started': False,
    'shared_state_written': False,
    'acceptance_claim': 'none; this is a source registry audit and prospective queue entry only',
}

# 2. Create package directories and the one genuinely new source condition.
for rel in ('metadata', 'source', 'owners', 'bindings', 'requests/motion', 'requests/gencase', 'requests/native-qa', 'requests/native', 'requests/typed', 'scripts', 'builders'):
    (NEW / rel).mkdir(parents=True, exist_ok=True)
dump(NEW / 'metadata/physical-coverage-audit.json', coverage)

source_xml_template = FRESH074 / 'source/F7_OBSTACLE_QUINTIC_B08_A050P5_Def.xml'
xml_text = '\n'.join(line.rstrip() for line in source_xml_template.read_text(encoding='utf-8').splitlines()) + '\n'
marker = ('  <!-- fresh078 prospective physical case A052P5: target amplitude 52.5 degrees. '
          'The motion asset is generated only by Root\'s registered motion worker; no .dat payload is included. -->\n')
if '<case>\n' not in xml_text:
    raise ValueError('unexpected source XML root')
new_xml_text = xml_text.replace('<case>\n', '<case>\n' + marker, 1)
xml_path = NEW / f'source/{CASE}_Def.xml'
xml_path.write_text(new_xml_text, encoding='utf-8')

# Construct the corrected converter owner from the immutable fresh077 A050P5 owner.
template_owner_path = FRESH077 / 'owners/F7_OBSTACLE_QUINTIC_B08_A050P5.converter-owner.json'
template_owner = load(template_owner_path)
owner = copy.deepcopy(template_owner)
pb = owner['physical_binding']
pb['physical_case_id'] = CASE
pb['parameters']['amplitude_deg'] = AMPLITUDE
pb['parameters']['amplitude_encoding'] = ENCODING
owner['case_id'] = CASE
owner['physical_case_id'] = CASE
owner['condition_id'] = CASE
owner['scope_id'] = 'root_followup_078_stage48_gap_a052p5_v1'
owner['schema'] = 'ds02.f7.fresh078.converter-owner.v1'
owner['status'] = 'source_only_disabled_pending_stage48_root_review'
owner['launch_allowed'] = False
owner['source'] = {
    'selected_motion_module': str(MOTION_MODULE.resolve()),
    'selected_motion_module_sha256': sha(MOTION_MODULE),
    'source_definition': str(xml_path.resolve()),
    'source_definition_sha256': sha(xml_path),
    'source_plan': str((NEW / 'metadata/stage48-gap-plan.json').resolve()),
    'source_plan_sha256': None,
}
owner['planned_execution'] = {
    'root_owner': 'root',
    'motion_worker': str(MOTION_WORKER.resolve()),
    'motion_asset_name': 'motion_obstacle_quintic.dat',
    'motion_asset_generation': 'future registered worker only; no source payload present',
    'gencase_attempt_id': 'root-stage1-f7-a052p5-genuine-gencase-078',
    'native_attempt_id': 'root-stage1-f7-a052p5-full601-native-qualification-078',
    'typed_attempt_id': 'root-stage1-f7-a052p5-full601-typed-nvme-078',
    'time_max_s': 12.0,
    'time_out_s': 0.02,
    'frames': 601,
}
owner['native_recipe_expected'] = {
    'dp_m': 0.02,
    'time_max_s': 12.0,
    'time_out_s': 0.02,
    'frames': 601,
    'dimension': 3,
    'counts': {'total': 70179, 'fixed': 27495, 'moving': 1984, 'floating': 0, 'fluid': 40700},
    'motion_rows': 12001,
    'native_fluid_support_mass_kg': 325.60001628,
    'continuum_physical_mass_kg': 320.1984,
    'mass_policy': 'keep native support mass and continuum physical mass separate; no rescale',
    'type_mk_blocks': [
        {'name': 'fixed', 'begin': 0, 'count': 27495, 'type': 0, 'mk': 10},
        {'name': 'moving', 'begin': 27495, 'count': 1984, 'type': 1, 'mk': 12},
        {'name': 'fluid', 'begin': 29479, 'count': 40700, 'type': 3, 'mk': 2},
    ],
}
owner['claims'] = {
    'genuine_gencase_completed': False,
    'initial_native_qa_completed': False,
    'full_native_completed': False,
    'typed_conversion_completed': False,
    'visual_acceptance': False,
    'q_n': 'not_assessed',
    'production_approval': 'none',
    'precision_status': 'not_accepted',
}

source_plan_payload = {
    'family_id': 'F7',
    'physical_case_id': CASE,
    'lineage_group_id': pb['lineage_group_id'],
    'geometry_family_id': pb['geometry_family_id'],
    'control_family_id': pb['control_family_id'],
    'paired_background_id': pb['paired_background_id'],
    'dp_m': 0.02,
    'gravity_m_s2': pb['gravity_m_s2'],
    'density_kg_m3': pb['density_kg_m3'],
    'mechanism_id': pb['mechanism_id'],
    'controls': pb['controls'],
    'event_window': pb['event_window'],
    'parameters': pb['parameters'],
    'native_recipe_expected': owner['native_recipe_expected'],
    'mass_policy': 'continuum 320.1984 kg and native support 325.60001628 kg remain separately declared; no normalization',
}
source_plan_condition_sha = canonical(source_plan_payload)
source_plan = {
    'schema': 'ds02.f7.fresh078.stage48-gap-source-plan.v1',
    'scope_id': 'root_followup_078_stage48_gap_a052p5_v1',
    'family_id': 'F7',
    'case_id': CASE,
    'physical_case_id': CASE,
    'source_status': 'prospective_source_only_disabled',
    'physical_condition_payload': source_plan_payload,
    'declared_source_condition_sha256': source_plan_condition_sha,
    'source_definition': str(xml_path.resolve()),
    'source_definition_sha256': sha(xml_path),
    'motion_asset': {
        'name': 'motion_obstacle_quintic.dat',
        'generated_by': str(MOTION_WORKER.resolve()),
        'generated_by_sha256': sha(MOTION_WORKER),
        'future_data_root': f'/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/{CASE}/root-stage1-f7-a052p5-motion-preparation-078/prepared/{CASE}/motion_obstacle_quintic.dat',
        'sha256': None,
        'read_or_hashed_by_source_agent': False,
    },
    'full_window': {'time_max_s': 12.0, 'time_out_s': 0.02, 'frames': 601, 'motion_rows': 12001},
    'native_counts_expected_only': {'total': 70179, 'fixed': 27495, 'moving': 1984, 'floating': 0, 'fluid': 40700, 'dimension': 3},
    'source_plan_hash_semantics': 'This digest covers the bounded physical_condition_payload; it is deliberately distinct from the converter physical_binding.v1 scope digest and from any future producer digest.',
    'arrays_read': False,
    'payloads_read_or_hashed': False,
    'jobs_started': False,
}
dump(NEW / 'metadata/stage48-gap-plan.json', source_plan)
source_plan_file_sha = sha(NEW / 'metadata/stage48-gap-plan.json')
owner['source']['source_plan_sha256'] = source_plan_file_sha
owner['condition_hash_semantics'] = {
    'converter_hash_scope': 'actual ds_data02_direct_convert._physical_condition_scope(owner) over ds-data-02.physical-binding.v1',
    'declared_source_hash': source_plan_condition_sha,
    'declared_source_hash_scope': 'fresh078 stage48-gap source-plan physical_condition_payload',
    'source_plan_file_sha256': source_plan_file_sha,
    'source_and_converter_hashes_are_distinct': True,
    'equality_claim': 'none',
}
owner['scope_repair'] = {
    'schema': 'ds02.f7.fresh078.converter-scope-preflight.v1',
    'template_owner_path': str(template_owner_path.resolve()),
    'template_owner_sha256': sha(template_owner_path),
    'explicit_required_fields': ['density_kg_m3', 'gravity_m_s2', 'mechanism_id'],
    'repair_status': 'inherited fresh077 corrected explicit fields; rechecked by actual converter callable',
    'arrays_read': False,
    'payloads_read_or_hashed': False,
}

# Run the actual converter scope function against the new owner metadata.
conv = load_converter()
scope = conv._physical_condition_scope(owner)
if scope.get('schema') != 'ds-data-02.physical-binding.v1':
    raise ValueError('converter returned unexpected scope schema')
converter_scope_sha = conv.canonical_hash(scope)
if converter_scope_sha == source_plan_condition_sha:
    raise ValueError('source-plan and converter scope digests unexpectedly conflated')
owner['canonical_physical_binding_sha256'] = converter_scope_sha
owner['physical_condition_sha256'] = converter_scope_sha
owner_path = NEW / f'owners/{CASE}.converter-owner.json'
dump(owner_path, owner)
owner_file_sha = sha(owner_path)

# Keep the prospective typed request self-contained for the two bounded
# contract audits it names. These files describe metadata/runtime fields;
# they do not stand in for any future GenCase/native receipt.
scope_preflight = {
    'schema': 'ds02.f7.fresh078.converter-scope-preflight.v1',
    'scope_id': 'root_followup_078_stage48_gap_a052p5_v1',
    'family_id': 'F7', 'case_id': CASE,
    'converter_callable': 'ds_data02_direct_convert._physical_condition_scope(owner)',
    'converter_scope_schema': 'ds-data-02.physical-binding.v1',
    'converter_scope_sha256': converter_scope_sha,
    'corrected_owner_path': str(owner_path.resolve()),
    'corrected_owner_sha256': owner_file_sha,
    'required_explicit_fields': ['density_kg_m3', 'gravity_m_s2', 'mechanism_id'],
    'status': 'passed_metadata_only_actual_callable',
    'actual_callable_executed': True,
    'arrays_read': False, 'payloads_read_or_hashed': False,
    'jobs_started': False, 'shared_state_written': False,
    'source_plan_sha256': source_plan_file_sha,
}
scope_preflight_path = NEW / 'metadata/converter-scope-preflight.json'
dump(scope_preflight_path, scope_preflight)
scope_preflight_sha = sha(scope_preflight_path)
root142_contract = {
    'schema': 'ds02.f7.fresh078.root142-contract-audit.v1',
    'scope_id': 'root_followup_078_stage48_gap_a052p5_v1',
    'family_id': 'F7', 'case_id': CASE,
    'status': 'source_contract_preflight_pass_future_receipts_required',
    'launch_owner': 'root', 'kind': 'conversion', 'cpu_threads': 2,
    'estimated_storage_bytes': 34359738368,
    'producer_scope_schema': 'ds-data-02.physical-binding.v1',
    'required_runtime_fields': ['family_id', 'case_id', 'attempt_id', 'kind', 'command', 'cwd', 'max_wall_seconds', 'cpu_threads', 'estimated_storage_bytes', 'input_files', 'worktree_root'],
    'input_files_sha_exact_set': True,
    'typed_frames': 601, 'typed_particles': 70179, 'solver_dimension': 3,
    'xmf_scalar_shape': 'N', 'xmf_vector_shape': 'N 3',
    'isolated_output_dirs': ['{attempt_root}/xdmf', '{attempt_root}/render'],
    'future_receipts_required': ['gencase completed/0', 'native initial QA completed/0', 'full601 native completed/0'],
    'conversion_scope_sha256': converter_scope_sha, 'owner_sha256': owner_file_sha,
    'arrays_read': False, 'payloads_read_or_hashed': False,
    'jobs_started': False, 'shared_state_written': False,
}
root142_contract_path = NEW / 'metadata/root142-contract-audit.json'
dump(root142_contract_path, root142_contract)
root142_contract_sha = sha(root142_contract_path)

# Bind metadata-only GenCase source input. The motion asset remains future/null.
gencase_binding = {
    'schema': 'ds02.f7.fresh078.gencase-binding.v1',
    'scope_id': 'root_followup_078_stage48_gap_a052p5_v1',
    'family_id': 'F7',
    'case_id': CASE,
    'physical_case_id': CASE,
    'amplitude_deg': AMPLITUDE,
    'amplitude_encoding': ENCODING,
    'definition': str(xml_path.resolve()),
    'definition_sha256': sha(xml_path),
    'source_plan': str((NEW / 'metadata/stage48-gap-plan.json').resolve()),
    'source_plan_sha256': source_plan_file_sha,
    'source_plan_condition_sha256': source_plan_condition_sha,
    'canonical_physical_binding_sha256': converter_scope_sha,
    'physical_condition_sha256': converter_scope_sha,
    'dp_m': 0.02,
    'threads': 2,
    'gencase': str(GENCASE_BIN.resolve()),
    'gencase_sha256': sha(GENCASE_BIN),
    'assets': [{
        'relative_name': 'motion_obstacle_quintic.dat',
        'source': source_plan['motion_asset']['future_data_root'],
        'sha256': None,
        'producer': 'Root registered motion-preparation worker',
    }],
    'motion_receipt': None,
    'motion_report': None,
    'expected_fluid': 40700,
    'predictions': {
        'forecast_only': True,
        'actual_counts_must_be_read_from_generated_xml': True,
        'total': 70179,
        'fixed': 27495,
        'moving': 1984,
        'floating': 0,
        'fluid': 40700,
        'dimension': 3,
    },
    'launch_allowed': False,
    'execution_allowed': False,
    'disabled': True,
    'source_only': True,
    'future_hashes_null': True,
    'arrays_read_by_binder': False,
    'payloads_read_or_hashed': False,
    'status': 'source_only_disabled_pending_registered_motion_worker',
}
binding_path = NEW / f'bindings/{CASE}.gencase-binding.json'
dump(binding_path, gencase_binding)
binding_sha = sha(binding_path)

# Shared metadata and runtime closure.
base_metadata = [
    NEW / 'metadata/stage48-gap-plan.json', NEW / 'metadata/physical-coverage-audit.json',
    owner_path, binding_path, xml_path, MOTION_WORKER, MOTION_MODULE, GENCASE,
    VENV, GENCASE_BIN, RUNTIME, STRICT, ROOT230_LAUNCH, ROOT230_POLICY,
    RESOURCE, GPU_POLICY,
]
base_files, base_hashes = metadata_closure(base_metadata)

# Disabled motion-preparation request (Root must explicitly enable a registered worker).
motion_attempt = 'root-stage1-f7-a052p5-motion-preparation-078'
motion_request = {
    'schema': 'ds02.runner-request.v2',
    'scope_id': 'root_followup_078_stage48_gap_a052p5_v1',
    'family_id': 'F7',
    'case_id': CASE,
    'physical_case_id': CASE,
    'attempt_id': motion_attempt,
    'kind': 'cpu',
    'cpu_task_kind': 'audit',
    'cpu_threads': 2,
    'threads': 2,
    'cwd': str(L.resolve()),
    'command': [str(VENV.resolve()), str(MOTION_WORKER.resolve()), '--plan', str((NEW / 'metadata/stage48-gap-plan.json').resolve()), '--output-root', '{attempt_root}/prepared', '--execute'],
    'max_wall_seconds': 1800,
    'estimated_storage_bytes': 268435456,
    'worktree_root': str(I.resolve()),
    'input_files': base_files,
    'input_sha256': base_hashes,
    'future_input_files': [],
    'future_input_sha256': {},
    'output_contract': {
        'prepared_root': '{attempt_root}/prepared',
        'motion_file': '{attempt_root}/prepared/' + CASE + '/motion_obstacle_quintic.dat',
        'prepared_definition': '{attempt_root}/prepared/' + CASE + '/' + CASE + '_Def.xml',
        'report': '{attempt_root}/prepared/motion-source-preparation.json',
        'execution_receipt': '{attempt_root}/execution-receipt.json',
        'motion_rows': 12001,
    },
    'resource_window': {'gpu_hours_total': 512, 'cpu_core_hours_total': 3840, 'qualification_hours': 1024, 'production_hours': 720, 'home_floor_gib': 500, 'nvme_floor_gib': 100},
    'resource_approval': str(RESOURCE.resolve()),
    'resource_approval_sha256': sha(RESOURCE),
    'root230_entrypoint': str(ROOT230_LAUNCH.resolve()),
    'root230_entrypoint_sha256': sha(ROOT230_LAUNCH),
    'root_inventory_policy': str(ROOT230_POLICY.resolve()),
    'root_inventory_policy_sha256': sha(ROOT230_POLICY),
    'gpu_policy': str(GPU_POLICY.resolve()),
    'gpu_policy_sha256': sha(GPU_POLICY),
    'runtime_entrypoint': str(RUNTIME.resolve()),
    'runtime_sha256': sha(RUNTIME),
    'strict_dispatch_entrypoint': str(STRICT.resolve()),
    'strict_dispatch_sha256': sha(STRICT),
    'launch_owner': 'root',
    'launch': False,
    'launch_allowed': False,
    'execution_allowed': False,
    'disabled': True,
    'source_only': True,
    'root_review_required': True,
    'future_hashes_null': True,
    'status': 'source_only_disabled_pending_root_registered_motion_worker',
    'independent_case_count_increment': 0,
    'no_arrays_read': True,
    'no_jobs_started': True,
    'no_shared_registry_write': True,
    'precision_status': 'not_accepted',
    'q_n_status': 'not_assessed',
    'production_approval': 'none',
}
dump(NEW / f'requests/motion/{CASE}.motion-preparation-078.disabled-request.json', motion_request)

# Disabled GenCase request; future motion data and generated outputs stay null.
gencase_attempt = 'root-stage1-f7-a052p5-genuine-gencase-078'
gencase_inputs, gencase_hashes = metadata_closure(base_metadata + [NEW / f'requests/motion/{CASE}.motion-preparation-078.disabled-request.json'])
gencase_request = {
    'schema': 'ds02.runner-request.v2',
    'scope_id': 'root_followup_078_stage48_gap_a052p5_v1',
    'family_id': 'F7',
    'case_id': CASE,
    'physical_case_id': CASE,
    'attempt_id': gencase_attempt,
    'kind': 'cpu',
    'cpu_task_kind': 'audit',
    'cpu_threads': 2,
    'threads': 2,
    'cwd': str(L.resolve()),
    'command': [str(VENV.resolve()), str(GENCASE.resolve()), '--binding', str(binding_path.resolve()), '--output-dir', '{attempt_root}/prepared'],
    'max_wall_seconds': 1800,
    'estimated_storage_bytes': 1073741824,
    'worktree_root': str(I.resolve()),
    'input_files': gencase_inputs,
    'input_sha256': gencase_hashes,
    'future_input_files': [
        source_plan['motion_asset']['future_data_root'],
        f'/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/{CASE}/{gencase_attempt}/execution-receipt.json',
        f'/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/{CASE}/{gencase_attempt}/prepared/{CASE}.xml',
        f'/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/{CASE}/{gencase_attempt}/prepared/{CASE}.bi4',
        f'/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/{CASE}/{gencase_attempt}/prepared/{CASE}_Def.xml',
        f'/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/{CASE}/{gencase_attempt}/prepared/prepared-input-report.json',
    ],
    'future_input_sha256': {str(Path(x).resolve()): None for x in [source_plan['motion_asset']['future_data_root'], f'/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/{CASE}/{gencase_attempt}/execution-receipt.json', f'/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/{CASE}/{gencase_attempt}/prepared/{CASE}.xml', f'/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/{CASE}/{gencase_attempt}/prepared/{CASE}.bi4', f'/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/{CASE}/{gencase_attempt}/prepared/{CASE}_Def.xml', f'/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/{CASE}/{gencase_attempt}/prepared/prepared-input-report.json']},
    'actual_binding': str(binding_path.resolve()),
    'actual_binding_sha256': binding_sha,
    'canonical_physical_binding_sha256': converter_scope_sha,
    'physical_condition_sha256': converter_scope_sha,
    'source_plan_sha256': source_plan_file_sha,
    'source_plan_condition_sha256': source_plan_condition_sha,
    'expected_counts': {'total': 70179, 'fixed': 27495, 'moving': 1984, 'floating': 0, 'fluid': 40700, 'dimension': 3},
    'output_contract': {'prepared_root': '{attempt_root}/prepared', 'generated_xml': '{attempt_root}/prepared/' + CASE + '.xml', 'generated_bi4': '{attempt_root}/prepared/' + CASE + '.bi4', 'prepared_input_report': '{attempt_root}/prepared/prepared-input-report.json'},
    'depends_on_attempt': motion_attempt,
    'resource_window': motion_request['resource_window'],
    'resource_approval': motion_request['resource_approval'],
    'resource_approval_sha256': motion_request['resource_approval_sha256'],
    'root230_entrypoint': motion_request['root230_entrypoint'],
    'root230_entrypoint_sha256': motion_request['root230_entrypoint_sha256'],
    'root_inventory_policy': motion_request['root_inventory_policy'],
    'root_inventory_policy_source_sha256': motion_request['root_inventory_policy_sha256'],
    'gpu_policy': motion_request['gpu_policy'],
    'gpu_policy_sha256': motion_request['gpu_policy_sha256'],
    'runtime_entrypoint': motion_request['runtime_entrypoint'],
    'runtime_sha256': motion_request['runtime_sha256'],
    'strict_dispatch_entrypoint': motion_request['strict_dispatch_entrypoint'],
    'strict_dispatch_sha256': motion_request['strict_dispatch_sha256'],
    'launch_owner': 'root',
    'launch': False,
    'launch_allowed': False,
    'execution_allowed': False,
    'disabled': True,
    'source_only': True,
    'root_review_required': True,
    'future_hashes_null': True,
    'status': 'source_only_disabled_pending_registered_motion_and_root_review',
    'independent_case_count_increment': 0,
    'no_arrays_read': True,
    'no_jobs_started': True,
    'no_shared_registry_write': True,
    'precision_status': 'not_accepted',
    'q_n_status': 'not_assessed',
    'production_approval': 'none',
}
dump(NEW / f'requests/gencase/{CASE}.genuine-gencase-078.disabled-request.json', gencase_request)

# Disabled native QA binding and request. These fields are only future paths; the worker reads arrays only in Root's later job.
qa_type_mk_blocks = [
    {'name': 'fixed', 'begin': 0, 'count': 27495, 'type': 0, 'mk': 10},
    {'name': 'moving', 'begin': 27495, 'count': 1984, 'type': 1, 'mk': 12},
    {'name': 'fluid', 'begin': 29479, 'count': 40700, 'type': 3, 'mk': 2},
]
qa_expected = {
    'total_particles': 70179, 'fixed_particles': 27495, 'moving_particles': 1984, 'floating_particles': 0, 'fluid_particles': 40700,
    'solver_dimension': 3, 'dp_m': 0.02, 'time_max_s': 12.0, 'time_out_s': 0.02, 'motion_rows': 12001,
    'native_fluid_mass_kg': 325.60001628, 'continuum_envelope_mass_kg': 320.1984, 'mass_tolerance_kg': 1e-8,
    'velocity_zero_tolerance_m_per_s': 1e-12, 'type_mk_blocks': qa_type_mk_blocks,
}
qa_attempt = 'root-stage1-f7-a052p5-native-initial-qa-078'
data_case_root = Path(f'/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/{CASE}')
gencase_root = data_case_root / gencase_attempt
qa_binding = {
    'schema': 'ds02.f7.fresh078.actual-gencase-native-qa-binding.v1',
    'scope_id': 'root_followup_078_stage48_gap_a052p5_v1',
    'family_id': 'F7',
    'case_id': CASE,
    'physical_case_id': CASE,
    'amplitude_deg': AMPLITUDE,
    'canonical_physical_binding_sha256': converter_scope_sha,
    'physical_condition_sha256': converter_scope_sha,
    'gencase_binding': str(binding_path.resolve()),
    'gencase_binding_sha256': binding_sha,
    'partvtk': str(PARTVTK_BIN.resolve()),
    'partvtk_sha256': sha(PARTVTK_BIN),
    'expected': qa_expected,
    'cases': [{
        'case_id': CASE,
        'physical_case_id': CASE,
        'amplitude_deg': AMPLITUDE,
        'physical_condition_sha256': converter_scope_sha,
        'canonical_physical_binding_sha256': converter_scope_sha,
        'gencase_receipt': str(gencase_root / 'execution-receipt.json'),
        'prepared_input_report': str(gencase_root / 'prepared/prepared-input-report.json'),
        'generated_xml': str(gencase_root / f'prepared/{CASE}.xml'),
        'generated_definition': str(gencase_root / f'prepared/{CASE}_Def.xml'),
        'generated_bi4': str(gencase_root / f'prepared/{CASE}.bi4'),
        'generated_motion': str(gencase_root / 'prepared/motion_obstacle_quintic.dat'),
        'gencase_receipt_sha256': None, 'prepared_input_report_sha256': None, 'generated_xml_sha256': None,
        'generated_definition_sha256': None, 'generated_bi4_sha256': None, 'generated_motion_sha256': None,
        'expected': qa_expected,
    }],
    'launch_allowed': False, 'execution_allowed': False, 'disabled': True, 'source_only': True,
    'future_hashes_null': True, 'arrays_read_by_binder': False, 'payloads_read_or_hashed': False,
    'status': 'source_only_disabled_pending_actual_gencase',
}
qa_binding_path = NEW / f'bindings/{CASE}.native-initial-qa-binding.json'
dump(qa_binding_path, qa_binding)
qa_binding_sha = sha(qa_binding_path)
qa_inputs, qa_hashes = metadata_closure(base_metadata + [qa_binding_path])
qa_request = {
    'schema': 'ds02.runner-request.v2', 'scope_id': 'root_followup_078_stage48_gap_a052p5_v1', 'family_id': 'F7', 'case_id': CASE, 'physical_case_id': CASE, 'attempt_id': qa_attempt,
    'kind': 'cpu', 'cpu_task_kind': 'audit', 'cpu_threads': 2, 'threads': 2, 'cwd': str(L.resolve()),
    'command': [str(VENV.resolve()), str(QA_WORKER.resolve()), '--binding', str(qa_binding_path.resolve()), '--output-dir', '{attempt_root}/initial-qa'],
    'max_wall_seconds': 7200, 'estimated_storage_bytes': 4294967296, 'worktree_root': str(I.resolve()),
    'input_files': qa_inputs, 'input_sha256': qa_hashes, 'future_input_files': [str(gencase_root / x) for x in ('execution-receipt.json','prepared/prepared-input-report.json',f'prepared/{CASE}.xml',f'prepared/{CASE}.bi4',f'prepared/{CASE}_Def.xml','prepared/motion_obstacle_quintic.dat')], 'future_input_sha256': {},
    'depends_on_attempts': [gencase_attempt], 'initial_qa_binding': str(qa_binding_path.resolve()), 'initial_qa_binding_sha256': qa_binding_sha,
    'canonical_physical_binding_sha256': converter_scope_sha, 'physical_condition_sha256': converter_scope_sha, 'source_plan_sha256': source_plan_file_sha, 'source_plan_condition_sha256': source_plan_condition_sha,
    'expected_counts': {'total': 70179, 'fixed': 27495, 'moving': 1984, 'floating': 0, 'fluid': 40700, 'dimension': 3}, 'output_contract': {'qa_report': '{attempt_root}/initial-qa/native-initial-qa.json', 'official_csv': '{attempt_root}/initial-qa/' + CASE + '-initial-all.csv'},
    'resource_window': motion_request['resource_window'], 'resource_approval': motion_request['resource_approval'], 'resource_approval_sha256': motion_request['resource_approval_sha256'], 'root230_entrypoint': motion_request['root230_entrypoint'], 'root230_entrypoint_sha256': motion_request['root230_entrypoint_sha256'], 'root_inventory_policy': motion_request['root_inventory_policy'], 'root_inventory_policy_sha256': motion_request['root_inventory_policy_sha256'], 'gpu_policy': motion_request['gpu_policy'], 'gpu_policy_sha256': motion_request['gpu_policy_sha256'], 'runtime_entrypoint': motion_request['runtime_entrypoint'], 'runtime_sha256': motion_request['runtime_sha256'], 'strict_dispatch_entrypoint': motion_request['strict_dispatch_entrypoint'], 'strict_dispatch_sha256': motion_request['strict_dispatch_sha256'],
    'launch_owner': 'root', 'launch': False, 'launch_allowed': False, 'execution_allowed': False, 'disabled': True, 'source_only': True, 'root_review_required': True, 'future_hashes_null': True, 'status': 'source_only_disabled_pending_actual_gencase', 'independent_case_count_increment': 0, 'no_arrays_read': True, 'no_jobs_started': True, 'no_shared_registry_write': True,
    'precision_status': 'not_accepted', 'q_n_status': 'not_assessed', 'production_approval': 'none',
}
dump(NEW / f'requests/native-qa/{CASE}.native-initial-qa-078.disabled-request.json', qa_request)

# Disabled native full601 request (Root's shared qualification entry will own any later enablement).
native_attempt = 'root-stage1-f7-a052p5-full601-native-qualification-078'
native_root = data_case_root / native_attempt
native_inputs, native_hashes = metadata_closure(base_metadata + [qa_binding_path, NEW / f'requests/native-qa/{CASE}.native-initial-qa-078.disabled-request.json'])
native_request = {
    'schema': 'ds02.runner-request.v2', 'scope_id': 'root_followup_078_stage48_gap_a052p5_v1', 'family_id': 'F7', 'case_id': CASE, 'physical_case_id': CASE, 'attempt_id': native_attempt,
    'kind': 'qualification', 'cpu_task_kind': 'solver', 'cpu_threads': 4, 'threads': 4, 'cwd': str(data_case_root / gencase_attempt / 'prepared'),
    'command': [str(SOLVER_BIN.resolve()), str(gencase_root / f'prepared/{CASE}'), '{attempt_root}/solver_output', '-tmax:12', '-tout:0.02'],
    'max_wall_seconds': 14400, 'estimated_peak_gpu_mib': 8192, 'estimated_storage_bytes': 17179869184, 'worktree_root': str(I.resolve()),
    'input_files': native_inputs, 'input_sha256': native_hashes,
    'future_input_files': [str(gencase_root / x) for x in ('execution-receipt.json','prepared/prepared-input-report.json',f'prepared/{CASE}.xml',f'prepared/{CASE}.bi4',f'prepared/{CASE}_Def.xml','prepared/motion_obstacle_quintic.dat')] + [str(qa_binding_path.resolve()), str(data_case_root / qa_attempt / 'execution-receipt.json'), str(data_case_root / qa_attempt / 'initial-qa/native-initial-qa.json')],
    'future_input_sha256': {}, 'depends_on_attempts': [gencase_attempt, qa_attempt],
    'gencase_execution_receipt': str(gencase_root / 'execution-receipt.json'), 'gencase_execution_receipt_sha256': None, 'gencase_receipt': str(gencase_root / 'execution-receipt.json'), 'gencase_receipt_sha256': None, 'gencase_report': str(gencase_root / 'prepared/prepared-input-report.json'), 'gencase_report_sha256': None,
    'generated_xml': str(gencase_root / f'prepared/{CASE}.xml'), 'generated_xml_sha256': None, 'generated_definition': str(gencase_root / f'prepared/{CASE}_Def.xml'), 'generated_definition_sha256': None, 'generated_bi4': str(gencase_root / f'prepared/{CASE}.bi4'), 'generated_bi4_sha256': None, 'generated_motion': str(gencase_root / 'prepared/motion_obstacle_quintic.dat'), 'generated_motion_sha256': None,
    'initial_qa_binding': str(qa_binding_path.resolve()), 'initial_qa_binding_sha256': qa_binding_sha, 'initial_typed_qa': str(data_case_root / qa_attempt / 'initial-qa/native-initial-qa.json'), 'initial_typed_qa_receipt': str(data_case_root / qa_attempt / 'execution-receipt.json'), 'initial_typed_qa_receipt_sha256': None, 'initial_typed_qa_sha256': None,
    'canonical_physical_binding_sha256': converter_scope_sha, 'physical_condition_sha256': converter_scope_sha, 'source_plan_sha256': source_plan_file_sha, 'source_plan_condition_sha256': source_plan_condition_sha,
    'expected_counts': {'total': 70179, 'fixed': 27495, 'moving': 1984, 'floating': 0, 'fluid': 40700, 'dimension': 3}, 'output_contract': {'frames': 601, 'save_interval_s': 0.02, 'time_window_s': [0.0, 12.0], 'solver_output': '{attempt_root}/solver_output'},
    'mass_policy': 'continuum physical mass 320.1984 kg and native support 325.60001628 kg remain separate; no rescale', 'native_support_mass_kg': 325.60001628, 'physical_mass_kg': 320.1984,
    'resource_window': motion_request['resource_window'], 'resource_approval': motion_request['resource_approval'], 'resource_approval_sha256': motion_request['resource_approval_sha256'], 'root230_entrypoint': motion_request['root230_entrypoint'], 'root230_entrypoint_sha256': motion_request['root230_entrypoint_sha256'], 'root_inventory_policy': motion_request['root_inventory_policy'], 'root_inventory_policy_sha256': motion_request['root_inventory_policy_sha256'], 'gpu_policy': motion_request['gpu_policy'], 'gpu_policy_sha256': motion_request['gpu_policy_sha256'], 'runtime_entrypoint': motion_request['runtime_entrypoint'], 'runtime_sha256': motion_request['runtime_sha256'], 'strict_dispatch_entrypoint': motion_request['strict_dispatch_entrypoint'], 'strict_dispatch_sha256': motion_request['strict_dispatch_sha256'],
    'launch_owner': 'root', 'launch': False, 'launch_allowed': False, 'execution_allowed': False, 'disabled': True, 'source_only': True, 'root_review_required': True, 'future_hashes_null': True, 'status': 'source_only_disabled_pending_actual_initial_native_qa', 'independent_case_count_increment': 0, 'no_arrays_read': True, 'no_jobs_started': True, 'no_shared_registry_write': True,
    'precision_status': 'not_accepted', 'q_n_status': 'not_assessed', 'production_approval': 'none',
}
dump(NEW / f'requests/native/{CASE}.full601-native-qualification-078.disabled-request.json', native_request)

# Disabled typed conversion request. It is a template only; Root must bind actual native output and QA receipts.
typed_template_path = FRESH077 / 'requests/typed/F7_OBSTACLE_QUINTIC_B08_A050P5.full601-typed-nvme-077.disabled-request.json'
typed_template = load(typed_template_path)
typed_attempt = 'root-stage1-f7-a052p5-full601-typed-nvme-078'
typed_native_data = native_root / 'solver_output/data'
typed_generated_xml = gencase_root / f'prepared/{CASE}.xml'
typed_solver_log = native_root / 'solver_output/Run.out'
typed_solver_receipt = native_root / 'execution-receipt.json'
typed_root = data_case_root / typed_attempt
# Preserve the tested converter command shape while binding only future A052P5 paths.
typed_command = [str(x) for x in typed_template['command']]
replacements = {
    'F7_OBSTACLE_QUINTIC_B08_A050P5': CASE,
    'root-stage1-f7-a050p5-full601-native-qualification-075': native_attempt,
    'root-stage1-f7-a050p5-full601-typed-nvme-077': typed_attempt,
    str(FRESH077 / 'owners/F7_OBSTACLE_QUINTIC_B08_A050P5.converter-owner.json'): str(owner_path.resolve()),
}
typed_command = [next((value for old, value in replacements.items() if old in item), item.replace(next(iter(replacements)), next(iter(replacements.values()))) if False else item) for item in typed_command]
# Apply all replacements safely in sequence.
for old, new in replacements.items():
    typed_command = [item.replace(old, new) for item in typed_command]
# Force approved executable/owner path and future output paths.
for i, item in enumerate(typed_command):
    if item == '/usr/bin/python3.10': typed_command[i] = str(VENV.resolve())
    if item == '--owner-metadata': typed_command[i + 1] = str(owner_path.resolve())
    if item == '--data-root': typed_command[i + 1] = str(typed_native_data)
    if item == '--generated-xml': typed_command[i + 1] = str(typed_generated_xml)
    if item == '--output': typed_command[i + 1] = '{attempt_root}/trajectory.h5'
    if item == '--report': typed_command[i + 1] = '{attempt_root}/conversion-report.json'
    if item == '--solver-log': typed_command[i + 1] = str(typed_solver_log)
    if item == '--solver-receipt': typed_command[i + 1] = str(typed_solver_receipt)
    if item == '--gencase-receipt': typed_command[i + 1] = str(gencase_root / 'execution-receipt.json')
    if item == '--validation-dir': typed_command[i + 1] = '{attempt_root}/partvtk-validation'
# The fresh077 template can have the old attempt in string fragments; verify none remain.
if any('A050P5' in item or '-077' in item for item in typed_command):
    raise ValueError(f'stale A050P5/-077 in typed command: {typed_command}')
typed_meta = [
    TEMPLATE076 / 'README.md', TEMPLATE076 / 'manifest.json', TEMPLATE076 / 'metadata/case-registry.json', TEMPLATE076 / 'metadata/typed-xmf-render-contract.json', TEMPLATE076 / 'metadata/resource-policy.json', TEMPLATE076 / 'metadata/producer-binding-semantics.json',
    TEMPLATE076 / 'scripts/bind_fresh076_actual_typed.py', TEMPLATE076 / 'scripts/preflight_fresh076.py', NVME, CONVERTER, RUNTIME, STRICT, XMF_WORKER, RENDERER, PARTVTK_BIN, DECODER, VENV, ROOT230_LAUNCH, ROOT230_POLICY, RESOURCE,
    NEW / 'metadata/stage48-gap-plan.json', NEW / 'metadata/physical-coverage-audit.json', scope_preflight_path, root142_contract_path, owner_path, binding_path, qa_binding_path, xml_path,
]
typed_inputs, typed_hashes = metadata_closure(typed_meta)
typed_request = copy.deepcopy(typed_template)
typed_request.update({
    'schema': 'ds02.runner-request.v2', 'scope_id': 'root_followup_078_stage48_gap_a052p5_v1', 'family_id': 'F7', 'case_id': CASE, 'physical_case_id': CASE, 'attempt_id': typed_attempt,
    'command': typed_command, 'cwd': str(L.resolve()), 'worktree_root': str(I.resolve()), 'input_files': typed_inputs, 'input_sha256': typed_hashes, 'future_input_files': [str(gencase_root / f'prepared/{CASE}.bi4'), str(gencase_root / 'prepared/motion_obstacle_quintic.dat'), str(typed_solver_data) if False else str(typed_native_data), str(typed_solver_log), str(typed_solver_receipt), str(typed_root / 'execution-receipt.json'), str(typed_root / 'conversion-report.json'), str(typed_root / 'trajectory.h5'), str(typed_root / 'partvtk-validation')], 'future_input_sha256': {},
    'canonical_physical_binding_sha256': converter_scope_sha, 'physical_condition_sha256': converter_scope_sha, 'source_plan_sha256': source_plan_file_sha, 'source_plan_condition_sha256': source_plan_condition_sha,
    'owner_metadata': {'path': str(owner_path.resolve()), 'sha256': owner_file_sha, 'scope_schema': 'ds-data-02.physical-binding.v1', 'scope_sha256': converter_scope_sha, 'source_plan_condition_sha256': source_plan_condition_sha},
    'conversion_owner_contract': {'converter': str(CONVERTER.resolve()), 'converter_sha256': sha(CONVERTER), 'callable': 'ds_data02_direct_convert._physical_condition_scope(owner)', 'corrected_owner': str(owner_path.resolve()), 'corrected_owner_sha256': owner_file_sha, 'scope_schema': 'ds-data-02.physical-binding.v1', 'scope_sha256': converter_scope_sha, 'source_plan_sha256': source_plan_file_sha, 'source_plan_condition_sha256': source_plan_condition_sha},
    'expected_counts': {'total': 70179, 'fixed': 27495, 'moving': 1984, 'floating': 0, 'fluid': 40700, 'dimension': 3}, 'estimated_storage_bytes': 34359738368, 'estimated_peak_gpu_mib': 8192,
    'depends_on_attempts': [native_attempt, qa_attempt], 'gencase_receipt': str(gencase_root / 'execution-receipt.json'), 'gencase_receipt_sha256': None, 'gencase_report': str(gencase_root / 'prepared/prepared-input-report.json'), 'gencase_report_sha256': None, 'generated_xml': str(typed_generated_xml), 'generated_xml_sha256': None,
    'status': 'source_only_disabled_pending_actual_native_and_root142_typed', 'disabled': True, 'source_only': True, 'launch': False, 'launch_allowed': False, 'execution_allowed': False, 'root_review_required': True, 'future_hashes_null': True, 'independent_case_count_increment': 0,
    'no_arrays_read': True, 'no_jobs_started': True, 'no_shared_registry_write': True, 'precision_status': 'not_accepted', 'q_n_status': 'not_assessed', 'production_approval': 'none',
})
# The copied fresh077 request contains producer-specific A050P5 completion
# metadata.  A052P5 is prospective, so keep the same consumer schema while
# replacing every actual-producer section with an explicit future closure.
typed_request['canonical_owner'] = {
    'canonical_physical_binding_sha256': converter_scope_sha,
    'owner_path': str(owner_path.resolve()),
    'owner_sha256': owner_file_sha,
    'source_plan_condition_sha256': source_plan_condition_sha,
}
typed_request['producer_scope'] = {
    'actual_hashes': None,
    'canonical_physical_binding_sha256': converter_scope_sha,
    'source_plan_condition_sha256': source_plan_condition_sha,
    'expected_counts': {'total': 70179, 'fixed': 27495, 'moving': 1984, 'floating': 0, 'fluid': 40700, 'dimension': 3},
    'expected_frames': 601,
    'schema': 'ds-data-02.physical-binding.v1',
}
typed_request['actual_input_closure'] = {
    'status': 'prospective_future_inputs_only',
    'raw_payload_hashes_remain_null': True,
    'corrected_converter_owner': str(owner_path.resolve()),
    'corrected_converter_owner_sha256': owner_file_sha,
    'corrected_converter_scope_sha256': converter_scope_sha,
    'source_plan_condition_sha256': source_plan_condition_sha,
    'gencase_receipt': str(gencase_root / 'execution-receipt.json'),
    'gencase_receipt_sha256': None,
    'gencase_runtime_evidence': str(data_case_root / gencase_attempt / 'binding' / f'{CASE}.gencase-runtime-evidence.json'),
    'gencase_runtime_evidence_sha256': None,
    'generated_definition': str(gencase_root / f'prepared/{CASE}_Def.xml'),
    'generated_definition_sha256': None,
    'generated_xml': str(gencase_root / f'prepared/{CASE}.xml'),
    'generated_xml_sha256': None,
    'initial_qa_receipt': str(data_case_root / qa_attempt / 'execution-receipt.json'),
    'initial_qa_receipt_sha256': None,
    'initial_qa_report': str(data_case_root / qa_attempt / 'initial-qa/native-initial-qa.json'),
    'initial_qa_report_sha256': None,
    'native_receipt': str(native_root / 'execution-receipt.json'),
    'native_receipt_sha256': None,
    'prospective_owner': str(owner_path.resolve()),
    'prospective_owner_sha256': owner_file_sha,
    'scope_preflight': str(scope_preflight_path.resolve()),
    'scope_preflight_sha256': scope_preflight_sha,
    'root142_contract_audit': str(root142_contract_path.resolve()),
    'root142_contract_audit_sha256': root142_contract_sha,
}
typed_request['gencase_actual'] = {
    'attempt_id': gencase_attempt,
    'generated_bi4': str(gencase_root / f'prepared/{CASE}.bi4'),
    'generated_bi4_sha256': None,
    'generated_definition': str(gencase_root / f'prepared/{CASE}_Def.xml'),
    'generated_definition_sha256': None,
    'generated_motion': str(gencase_root / 'prepared/motion_obstacle_quintic.dat'),
    'generated_motion_sha256': None,
    'generated_xml': str(gencase_root / f'prepared/{CASE}.xml'),
    'generated_xml_sha256': None,
    'layout': 'flat prepared/{case}.*',
    'prepared_input_report': str(gencase_root / 'prepared/prepared-input-report.json'),
    'prepared_input_report_sha256': None,
    'receipt': str(gencase_root / 'execution-receipt.json'),
    'receipt_sha256': None,
    'returncode': None,
    'status': 'pending_actual_gencase',
}
typed_request['initial_qa_dependency'] = {
    'receipt': str(data_case_root / qa_attempt / 'execution-receipt.json'),
    'receipt_sha256': None,
    'report': str(data_case_root / qa_attempt / 'initial-qa/native-initial-qa.json'),
    'report_sha256': None,
    'status': 'pending_actual_initial_qa',
}
typed_request['native_dependency'] = {
    'attempt_id': native_attempt,
    'data_root': str(native_root / 'solver_output/data'),
    'receipt': str(native_root / 'execution-receipt.json'),
    'receipt_sha256': None,
    'request': str(NEW / f'requests/native/{CASE}.full601-native-qualification-078.disabled-request.json'),
    'returncode': None,
    'status': 'pending_actual_native',
}
typed_request['future_outputs'] = {
    'conversion_report': str(typed_root / 'conversion-report.json'),
    'conversion_report_sha256': None,
    'partvtk_validation_dir': str(typed_root / 'partvtk-validation'),
    'trajectory_h5': str(typed_root / 'trajectory.h5'),
    'trajectory_h5_sha256': None,
    'typed_receipt': str(typed_root / 'execution-receipt.json'),
    'typed_receipt_sha256': None,
}
typed_request['disabled_reason'] = 'Disabled source request for prospective A052P5. Root must first register completed/0 GenCase, native initial QA, and full601 native receipts before Root142 conversion review.'
# Drop copied actual A050P5 artifacts from provenance maps.  The immutable
# fresh077 owner/template remains represented by the package builder itself;
# this request must never imply that A050P5 is an input for A052P5.
for key in list(typed_request.get('input_hash_provenance', {})):
    if 'A050P5' in key or 'a050p5' in key:
        typed_request['input_hash_provenance'].pop(key, None)
typed_request.setdefault('input_hash_provenance', {})[str(scope_preflight_path.resolve())] = 'fresh078 actual converter callable scope preflight; JSON metadata only'
typed_request.setdefault('input_hash_provenance', {})[str(root142_contract_path.resolve())] = 'fresh078 Root142 contract audit; JSON metadata only'
# Remove stale actual producer hashes from the copied request and preserve future/null status.
for key in ('typed_receipt_sha256', 'conversion_report_sha256', 'trajectory_h5_sha256', 'native_receipt_sha256'):
    if key in typed_request: typed_request[key] = None
# Correct the source-only future closure to exactly match null values.
typed_request['future_input_sha256'] = {str(Path(x).resolve()): None for x in typed_request['future_input_files']}
dump(NEW / f'requests/typed/{CASE}.full601-typed-nvme-078.disabled-request.json', typed_request)

# Corrected metadata adapter: copy the consumed source and make the two observed fixes in this new package only.
old_adapter = FRESH077 / 'scripts/bind_fresh077_actual_typed.py'
adapter_text = old_adapter.read_text(encoding='utf-8')
adapter_text = adapter_text.replace('Bind completed fresh077 typed metadata', 'Bind completed fresh077 typed metadata with fresh078 schema compatibility')
adapter_text = adapter_text.replace('fresh077', 'fresh078')
adapter_text = adapter_text.replace('def future077(', 'def future078(')
adapter_text = adapter_text.replace('future077(', 'future078(')
adapter_text = adapter_text.replace('root_followup_077_actual_converter_scope_root142_adapter_v1', 'root_followup_078_stage48_gap_a052p5_v1')
adapter_text = adapter_text.replace('actual-typed-bound-manifest.v1', 'actual-typed-bound-manifest.v2')
adapter_text = adapter_text.replace('actual-typed.full601.xmf-binding.v1', 'actual-typed.full601.xmf-binding.v2')
adapter_text = adapter_text.replace('actual-typed.full601.render-binding.v1', 'actual-typed.full601.render-binding.v2')
adapter_text = adapter_text.replace('actual-typed.full601.xmf-request.v1', 'actual-typed.full601.xmf-request.v2')
adapter_text = adapter_text.replace('actual-typed.full601.render-request.v1', 'actual-typed.full601.render-request.v2')
# Keep consumed input owner schema/check and producer scope names unchanged.
adapter_text = adapter_text.replace('owner.get("schema") != "ds02.fresh078.converter-owner.v1"', 'owner.get("schema") != "ds02.f7.fresh077.converter-owner.v1"')
adapter_text = adapter_text.replace('if case_id not in CASES:', 'if case_id not in CASES:')
# New downstream attempts are 078; producer typed receipts remain 077.
adapter_text = adapter_text.replace('def future078(value: Any)', 'def future078(value: Any)')
adapter_text = adapter_text.replace('future077(dict(template_xmf_request))', 'future078(dict(template_xmf_request))')
adapter_text = adapter_text.replace('future077(dict(template_render_request))', 'future078(dict(template_render_request))')
adapter_text = adapter_text.replace('xmf_attempt_id = f"root-stage1-f7-{suffix}-full601-normal-xmf-077"', 'xmf_attempt_id = f"root-stage1-f7-{suffix}-full601-normal-xmf-078"')
adapter_text = adapter_text.replace('render_attempt_id = f"root-stage1-f7-{suffix}-full601-native023-render-077"', 'render_attempt_id = f"root-stage1-f7-{suffix}-full601-native023-render-078"')
adapter_text = adapter_text.replace('future078(item)', 'future078(item)')
adapter_text = adapter_text.replace('return value.replace("-076", "-077")', 'return value.replace("-076", "-078")')
adapter_text = adapter_text.replace('full601-normal-xmf-077.actual-bound', 'full601-normal-xmf-078.actual-bound')
adapter_text = adapter_text.replace('full601-native023-render-077.actual-bound', 'full601-native023-render-078.actual-bound')
adapter_text = adapter_text.replace('actual_typed_bound_manifest.v1', 'actual_typed_bound_manifest.v2')
# Ensure template path patterns are strings and always expanded before use.
adapter_text = adapter_text.replace('return (\n        bindings / "{case}.full601-typed-binding.json",\n        bindings / "{case}.full601-xmf-binding.json",\n        bindings / "{case}.full601-render-binding.json",\n        requests / "xmf" / "{case}.full601-normal-xmf-076.disabled-request.json",\n        requests / "render" / "{case}.full601-native023-render-076.disabled-request.json",\n        source_package / "metadata" / "source-validation-report.json",\n    )', 'return (\n        str(bindings / "{case}.full601-typed-binding.json"),\n        str(bindings / "{case}.full601-xmf-binding.json"),\n        str(bindings / "{case}.full601-render-binding.json"),\n        str(requests / "xmf" / "{case}.full601-normal-xmf-076.disabled-request.json"),\n        str(requests / "render" / "{case}.full601-native023-render-076.disabled-request.json"),\n        source_package / "metadata" / "source-validation-report.json",\n    )')
# Path.format() is the first Root383 failure. Replace every templated use with a helper.
needle = '\n\ndef load_json(path: Path) -> dict[str, Any]:\n'
helper = '\n\ndef expand_template(pattern: str, case_id: str) -> Path:\n    return Path(pattern.format(case=case_id))\n\n\ndef load_json(path: Path) -> dict[str, Any]:\n'
if needle not in adapter_text:
    raise ValueError('adapter insertion point missing')
adapter_text = adapter_text.replace(needle, helper, 1)
for var in ('typed_binding_template_path', 'xmf_binding_template_path', 'render_binding_template_path', 'xmf_request_template_path', 'render_request_template_path'):
    adapter_text = adapter_text.replace(f'{var}.format(case=case_id)', f'expand_template({var}, case_id)')
# Actual Root383 reports carry solver_dimension as a metadata object.
old_dimension = '    if report.get("solver_dimension") not in (None, 3):\n        raise AdapterError(f"conversion report is not 3-D: {report_path}")\n'
new_dimension = '''    dimension_meta = report.get("solver_dimension")\n    if isinstance(dimension_meta, dict):\n        solver_dimension = dimension_meta.get("solver_dimension")\n        run_out_dimensions = dimension_meta.get("run_out_dimensions")\n        if run_out_dimensions not in (None, [3]):\n            raise AdapterError(f"conversion report run.out dimension is not 3-D: {report_path}")\n        if dimension_meta.get("xml_data2d") not in (None, "false", False):\n            raise AdapterError(f"conversion report XML is marked 2-D: {report_path}")\n    else:\n        solver_dimension = dimension_meta\n    if solver_dimension not in (None, 3):\n        raise AdapterError(f"conversion report is not 3-D: {report_path}")\n'''
if old_dimension not in adapter_text:
    raise ValueError('solver_dimension fix insertion point missing')
adapter_text = adapter_text.replace(old_dimension, new_dimension, 1)
# Input owner schema must remain fresh077 because this adapter consumes fresh077 corrected owners.
adapter_text = adapter_text.replace('owner.get("schema") != "ds02.f7.fresh078.converter-owner.v1"', 'owner.get("schema") != "ds02.f7.fresh077.converter-owner.v1"')
# The producer typed receipt's attempt remains 077; the global replacement changed this literal, restore it.
adapter_text = adapter_text.replace('f"root-stage1-f7-{case_id.rsplit(\'_\', 1)[1].lower()}-full601-typed-nvme-078"', 'f"root-stage1-f7-{case_id.rsplit(\'_\', 1)[1].lower()}-full601-typed-nvme-077"')
# The adapter's suffix output names and scope remain 078, while producer receipt checks stay 077.
adapter_path = NEW / 'scripts/bind_fresh078_actual_typed.py'
adapter_path.write_text(adapter_text, encoding='utf-8')

# Package-local bounded preflight. It never opens raw scientific payloads and catches request closure errors.
preflight = r'''#!/usr/bin/env python3
"""Metadata-only preflight for fresh078.

The script validates source JSON/XML/Python contracts and converter scope. It
rejects raw payloads in current input closures and never opens, hashes, or
copies BI4/H5/CSV/DAT/scientific arrays.
"""
from __future__ import annotations
import hashlib, importlib.util, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
CONVERTER = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py')
VENV = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python')
RAW = {'.bi4','.csv','.h5','.hdf5','.dat','.ibi4','.vtk','.npy','.npz'}
HEX64 = re.compile(r'^[0-9a-f]{64}$')
def sha(p):
    if Path(p).suffix.lower() in RAW: raise RuntimeError(f'raw hash forbidden: {p}')
    h=hashlib.sha256();
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b): h.update(b)
    return h.hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def main():
    owner_path=next((HERE/'owners').glob('*.json')); owner=load(owner_path)
    assert owner['case_id']=='F7_OBSTACLE_QUINTIC_B08_A052P5'
    assert owner['status'].startswith('source_only_disabled') and owner['launch_allowed'] is False
    spec=importlib.util.spec_from_file_location('fresh078_converter',CONVERTER); m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)
    scope=m._physical_condition_scope(owner); scope_sha=m.canonical_hash(scope)
    assert scope_sha==owner['canonical_physical_binding_sha256']==owner['physical_condition_sha256']
    assert owner['condition_hash_semantics']['declared_source_hash'] != scope_sha
    expected={'total':70179,'fixed':27495,'moving':1984,'floating':0,'fluid':40700,'dimension':3}
    requests=[]; raw_current=[]
    for p in sorted((HERE/'requests').rglob('*.json')):
        d=load(p); requests.append(str(p))
        assert d.get('disabled') is True and d.get('launch_allowed') is False and d.get('execution_allowed') is False
        assert d.get('future_hashes_null') is True
        if d.get('expected_counts') and isinstance(d['expected_counts'],dict):
            for k,v in expected.items():
                if k in d['expected_counts'] and d['expected_counts'][k] != v: raise AssertionError(f'{p}: expected {k}')
        files=d.get('input_files',[]); hashes=d.get('input_sha256',{})
        assert set(files)==set(hashes), f'{p}: input closure mismatch'
        for raw in files:
            if Path(raw).suffix.lower() in RAW: raw_current.append(raw)
    assert not raw_current, raw_current
    cov=load(HERE/'metadata/physical-coverage-audit.json'); assert cov['existing_unique_source_case_count']==47 and cov['gap_count']==1
    out={'schema':'ds02.f7.fresh078.source-validation-report.v1','scope_sha256':scope_sha,'request_count':len(requests),'requests':requests,'coverage_count':47,'gap_count':1,'raw_current_inputs':raw_current,'arrays_read':False,'payloads_read_or_hashed':False,'jobs_started':False,'shared_state_written':False,'adapter_fixes':['Path template expansion via expand_template(pattern, case_id)','solver_dimension metadata object accepted only when nested solver_dimension=3, run_out_dimensions=[3], xml_data2d=false'],'claim_boundary':'Source metadata and disabled requests only; no GenCase, QA, solver, typed, visual, Q-N, precision, or production claim.'}
    (HERE/'metadata/source-validation-report.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps(out,indent=2,sort_keys=True))
if __name__=='__main__': main()
'''
preflight_path = NEW / 'scripts/preflight_fresh078.py'
preflight_path.write_text(preflight, encoding='utf-8')
preflight_path.chmod(0o755)

# Record the actual adapter failure evidence and the fresh078 corrections.
adapter_evidence = {
    'schema': 'ds02.f7.fresh078.actual-adapter-compatibility-evidence.v1',
    'scope_id': 'root_followup_078_stage48_gap_a052p5_v1',
    'consumed_source': str(FRESH077.resolve()),
    'consumed_source_immutable': True,
    'root_reported_observations': [
        {'attempt': 'Root383', 'case_map': str(CASE_MAP.resolve()), 'status': 'actual first two typed receipts completed/0; adapter invoked metadata-only'},
        {'attempt': 'Root384', 'failure': 'fresh077 copy failed at template_typed = load_json(typed_binding_template_path.format(case=case_id)) because template_paths returned pathlib.Path'},
        {'attempt': 'Root384', 'failure': 'after isolated Path expansion fix, conversion report rejected actual solver_dimension metadata object'},
    ],
    'actual_report_schema_observation': {'solver_dimension_type': 'object', 'nested_solver_dimension': 3, 'run_out_dimensions': [3], 'xml_data2d': 'false'},
    'fresh078_fixes': [
        {'bug': 'Path.format on pathlib.Path', 'fix': 'template_paths returns string patterns and expand_template(pattern, case_id) constructs Path before load/stat'},
        {'bug': 'solver_dimension object treated as integer', 'fix': 'accept nested solver_dimension only with run_out_dimensions=[3] and xml_data2d=false'},
    ],
    'source_only_execution': {'arrays_read': False, 'payloads_read_or_hashed': False, 'jobs_started': False, 'shared_state_written': False},
    'claim_boundary': 'Observed metadata contract and source fix only; no scientific output or downstream acceptance claim.',
}
dump(NEW / 'metadata/adapter-compatibility-evidence.json', adapter_evidence)
# Preserve the exact Root383 case map as bounded JSON metadata only.
case_map_value = json.loads(CASE_MAP.read_text(encoding='utf-8'))
dump(NEW / 'metadata/root383-case-map.json', case_map_value)

# Manifest excludes generated actual-bound output until the adapter is run, but records source closure and claims.
manifest = {
    'schema': 'ds02.f7.fresh078.manifest.v1',
    'scope_id': 'root_followup_078_stage48_gap_a052p5_v1',
    'family_id': 'F7',
    'target_unique_physical_case_count': 48,
    'existing_unique_source_case_count': 47,
    'gap_count': 1,
    'selected_case': CASE,
    'selected_amplitude_deg': AMPLITUDE,
    'selected_amplitude_encoding': ENCODING,
    'source_template_lineage': str(template_owner_path.resolve()),
    'converter_scope_sha256': converter_scope_sha,
    'source_plan_condition_sha256': source_plan_condition_sha,
    'source_plan_file_sha256': source_plan_file_sha,
    'owner_sha256': owner_file_sha,
    'gencase_binding_sha256': binding_sha,
    'adapter_script': str(adapter_path.resolve()),
    'adapter_script_sha256': sha(adapter_path),
    'actual_root383_case_map': str((NEW / 'metadata/root383-case-map.json').resolve()),
    'motion_asset_included': False,
    'raw_payloads_included': False,
    'all_requests_disabled': True,
    'future_hashes_null': True,
    'arrays_read': False,
    'bi4_read': False,
    'h5_read': False,
    'csv_read': False,
    'motion_read': False,
    'jobs_started': False,
    'shared_state_written': False,
    'claim_boundary': 'One new prospective physical source condition and a corrected metadata adapter only. No actual GenCase/QA/native/typed/visual/Q-N/precision/production claim.',
}
dump(NEW / 'manifest.json', manifest)
# Store a copy of this bounded builder for reproducibility; it reads only metadata/XML and never payloads.
shutil.copyfile(Path(__file__), NEW / 'builders/build_fresh078_stage48_gap.py')
print(json.dumps({'package': str(NEW), 'existing_unique_source_case_count': len(unique_ids), 'gap_count': 1, 'selected_case': CASE, 'converter_scope_sha256': converter_scope_sha, 'source_plan_condition_sha256': source_plan_condition_sha, 'owner_sha256': owner_file_sha}, indent=2, sort_keys=True))
