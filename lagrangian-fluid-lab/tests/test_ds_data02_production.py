import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from ds_data02_production import authorize, revalidate_approval
from test_ds_data02_scope import _write_fixture


def save(path, value):
    path.write_text(json.dumps(value, indent=2))
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def fixture(tmp_path):
    scope_path, evidence_path = _write_fixture(tmp_path)
    scope, evidence = json.loads(scope_path.read_text()), json.loads(evidence_path.read_text())
    scope['initialization_acceptance'] = dict(relative_mass_error_max=.01)
    scope['physical_domain']['cases'][0]['continuous_initial_fluid_mass_kg'] = 10.
    scope_binding = save(scope_path, scope)
    evidence['scope_binding']['sha256'] = scope_binding['sha256']
    evidence_binding = save(evidence_path, evidence)
    frozen = scope['physical_domain']['cases'][0]
    case = copy.deepcopy(frozen)
    case.update(resolution='fine', numeric_settings=frozen['numeric_settings_by_resolution']['fine'],
                numerical_recipe_hash=frozen['numerical_recipe_hash_by_resolution']['fine'])
    prefix = tmp_path/'native'
    generated_xml = tmp_path/'native.xml'
    generated_xml.write_text('<case><execution><constants><massfluid value="0.1"/></constants></execution></case>')
    generated_bi4 = tmp_path/'native.bi4'
    generated_bi4.write_bytes(b'unit fixture, not real CFD evidence')
    gen = dict(status='completed', returncode=0, total_particles=150, fluid_particles=100,
               solver_dimension_from_gencase=3, command=['GenCase', 'Def', str(prefix)])
    gen['input_hashes_at_launch'] = {b['path']: b['sha256'] for b in frozen['input_bindings']}
    gen['input_hashes_after_run'] = copy.deepcopy(gen['input_hashes_at_launch'])
    case['gencase_receipt'] = save(tmp_path/'gen-receipt.json', gen)
    for p in (generated_xml, generated_bi4):
        case['input_bindings'].append(dict(role='generated_native', path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    checks = ('actual_3d', 'positive_fluid', 'effective_transverse_layers', 'finite_boundary_coverage',
              'no_initial_fluid_solid_overlap', 'continuous_initial_mass_within_frozen_budget')
    audit = dict(schema='ds02.production-initialization-audit.v1', case_id=case['case_id'],
                 checks={key: True for key in checks}, gencase_receipt=case['gencase_receipt'],
                 source_bindings=case['input_bindings'], continuous_mass_accounting=dict(
                     continuous_fluid_mass_kg=10., native_fluid_mass_kg=10., mass_rescaling=False))
    case['initialization_audit'] = save(tmp_path/'init-audit.json', audit)
    case['solver_command'] = ['solver', str(prefix), '{attempt_root}/solver', '-tmax:4', '-tout:0.01']
    case['solver_cwd'] = str(tmp_path)
    manifest = dict(schema='ds02.production-manifest.v1', family_id='F2', scope_id=scope['scope_id'], cases=[case])
    manifest_binding = save(tmp_path/'manifest.json', manifest)
    bindings = dict(scope_spec=scope_binding, scope_evidence=evidence_binding, production_manifest=manifest_binding)
    decision = dict(schema='ds02.root-scientific-decision.v1', status='Q-N-approved-by-root',
                    family_id='F2', scope_id=scope['scope_id'], bindings=bindings)
    entry = dict(scope_id=scope['scope_id'], family_id='F2', **bindings,
                 root_decision=save(tmp_path/'decision.json', decision))
    index_path = tmp_path/'index.json'
    save(index_path, dict(schema='ds02.root-approved-scopes.v1', campaign_id='DS-DATA-02', scopes=[entry]))
    request = copy.deepcopy(case)
    request.update(family_id='F2', scope_id=scope['scope_id'], command=case['solver_command'], cwd=str(tmp_path),
                   gencase_receipt=case['gencase_receipt']['path'], gencase_receipt_sha256=case['gencase_receipt']['sha256'],
                   complete_event_window_s=[0., 4.])
    return request, index_path


def test_actual_scope_verifier_and_membership_bind_successful_launch_without_case_trajectory(tmp_path):
    request, index = fixture(tmp_path)
    context = {}
    hashes = authorize(request, index_path=index, approval_context=context)
    assert str(index) not in hashes
    assert context['index_sha256_at_launch'] == hashlib.sha256(index.read_bytes()).hexdigest()
    assert revalidate_approval(context)['status'] == 'selected_approval_unchanged'
    assert request['gencase_receipt'] in hashes


def test_another_family_approval_does_not_invalidate_selected_launch(tmp_path):
    request, index = fixture(tmp_path)
    context = {}
    hashes = authorize(request, index_path=index, approval_context=context)
    document = json.loads(index.read_text())
    document['scopes'].append(dict(family_id='F7', scope_id='other-family-scope'))
    save(index, document)
    result = revalidate_approval(context)
    assert result['status'] == 'selected_approval_unchanged'
    assert result['index_sha256'] != context['index_sha256_at_launch']
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p,h in hashes.items())


@pytest.mark.parametrize('change', ['remove', 'duplicate', 'change'])
def test_selected_approval_revocation_or_change_is_detected(tmp_path, change):
    request, index = fixture(tmp_path)
    context = {}
    authorize(request, index_path=index, approval_context=context)
    document = json.loads(index.read_text())
    if change == 'remove': document['scopes'] = []
    elif change == 'duplicate': document['scopes'].append(copy.deepcopy(document['scopes'][0]))
    else: document['scopes'][0]['root_decision']['sha256'] = 'f'*64
    save(index, document)
    with pytest.raises(ValueError, match='changed or was revoked'):
        revalidate_approval(context)


def test_self_declared_qualification_cannot_rescue_missing_root_approval(tmp_path):
    request, index = fixture(tmp_path)
    save(index, dict(schema='ds02.root-approved-scopes.v1', campaign_id='DS-DATA-02', scopes=[]))
    request['qualified'] = True
    with pytest.raises(ValueError, match='not_approved'):
        authorize(request, index_path=index)


@pytest.mark.parametrize('field,value,message', [('numeric_settings', {'dp_m': .001}, 'numeric settings'),
    ('physical_condition_hash', 'f'*64, 'physical membership'), ('split', 'hidden_test', 'membership'),
    ('complete_event_window_s', [0, 1], 'event window'), ('command', ['solver', 'other_case'], 'actual command')])
def test_changes_to_physics_recipe_split_window_or_solver_prefix_are_rejected(tmp_path, field, value, message):
    request, index = fixture(tmp_path)
    request[field] = value
    with pytest.raises(ValueError, match=message):
        authorize(request, index_path=index)


def test_consumed_native_input_tampering_is_detected_before_gpu_lease(tmp_path):
    request, index = fixture(tmp_path)
    (tmp_path/'native.bi4').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='hash mismatch'):
        authorize(request, index_path=index)


def test_failed_spatial_evidence_cannot_be_overridden_by_root_approval_marker(tmp_path):
    request, index = fixture(tmp_path)
    document = json.loads(index.read_text())
    entry = document['scopes'][0]
    evidence_path = Path(entry['scope_evidence']['path'])
    evidence = json.loads(evidence_path.read_text())
    evidence['spatial_comparisons'] = []
    entry['scope_evidence'] = save(evidence_path, evidence)
    decision_path = Path(entry['root_decision']['path'])
    decision = json.loads(decision_path.read_text())
    decision['bindings']['scope_evidence'] = entry['scope_evidence']
    entry['root_decision'] = save(decision_path, decision)
    save(index, document)
    with pytest.raises(ValueError, match='scientific scope evidence is ineligible'):
        authorize(request, index_path=index)
