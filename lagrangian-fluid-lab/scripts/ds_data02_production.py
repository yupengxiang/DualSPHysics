#!/usr/bin/env python3
"""Bind production launches to root decisions, scientific evidence and GenCase.

This module grants no scientific approval. The root-owned index is the only
approval source; prospective cases need successful input QA, not a trajectory
from the production solver they have yet to run. Final case Q-I stays separate.
"""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


INDEX = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/APPROVED_SCOPES.json')
LAB = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def _json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON field')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def _binding(binding, hashes):
    if not isinstance(binding, dict) or not isinstance(binding.get('sha256'), str):
        raise ValueError('production evidence requires a file SHA-256 binding')
    path = Path(binding['path']).resolve()
    value = digest(path)
    if binding['sha256'] != value:
        raise ValueError('production evidence hash mismatch: '+str(path))
    hashes[str(path)] = value
    return path


def _scope_verdict(scope, evidence):
    # Runtime uses system Python; scientific HDF5 dependencies belong to the
    # existing dataset venv. The validator executable cannot be request-owned.
    result = subprocess.run([str(LAB/'.venv/bin/python'), str(LAB/'scripts/ds_data02_scope.py'),
                             '--scope', str(scope), '--evidence', str(evidence)],
                            capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise ValueError('scientific scope evidence is ineligible: '+result.stdout[-1600:]+result.stderr[-400:])
    return json.loads(result.stdout)


def authorize(request, *, index_path=INDEX):
    """Return all immutable launch bindings; reject before any GPU lease."""
    index_path = Path(index_path).resolve()
    index = _json(index_path)
    if index.get('schema') != 'ds02.root-approved-scopes.v1' or index.get('campaign_id') != 'DS-DATA-02':
        raise ValueError('invalid root approval index')
    entries = index.get('scopes', [])
    matching = [entry for entry in entries if entry.get('scope_id') == request.get('scope_id') and entry.get('family_id') == request['family_id']]
    if len(matching) != 1:
        raise ValueError('production_scope_not_approved')
    entry = matching[0]
    hashes = {str(index_path): digest(index_path), str(Path(__file__).resolve()): digest(__file__)}
    paths = {key: _binding(entry[key], hashes) for key in ('scope_spec', 'scope_evidence', 'root_decision', 'production_manifest')}
    scope, decision, manifest = (_json(paths[key]) for key in ('scope_spec', 'root_decision', 'production_manifest'))
    identity = (request['family_id'], request['scope_id'])
    for value in (scope, decision, manifest):
        if (value.get('family_id'), value.get('scope_id')) != identity:
            raise ValueError('production scope identity mismatch')
    if decision.get('schema') != 'ds02.root-scientific-decision.v1' or decision.get('status') != 'Q-N-approved-by-root':
        raise ValueError('root scientific decision is not an approval')
    for key in ('scope_spec', 'scope_evidence', 'production_manifest'):
        if decision.get('bindings', {}).get(key) != entry[key]:
            raise ValueError('root decision differs from approved evidence/manifest')
    if manifest.get('schema') != 'ds02.production-manifest.v1':
        raise ValueError('invalid production manifest')
    cases = manifest.get('cases', [])
    for field in ('case_id', 'physical_case_id'):
        if len({case.get(field) for case in cases}) != len(cases) or any(not case.get(field) for case in cases):
            raise ValueError('production manifest duplicates physical cases or views')
    parents = {}
    for case in cases:
        if not case.get('parent_group_id') or not case.get('split'):
            raise ValueError('production case lacks a parent split')
        if parents.setdefault(case['parent_group_id'], case['split']) != case['split']:
            raise ValueError('production parent group leaks across splits')
    candidates = [case for case in cases if case['case_id'] == request['case_id']]
    if len(candidates) != 1:
        raise ValueError('production case not in approved manifest')
    case = candidates[0]
    frozen = [row for row in scope['physical_domain']['cases'] if row['case_id'] == case['case_id']]
    if len(frozen) != 1:
        raise ValueError('production case not in frozen physical domain')
    frozen = frozen[0]
    for key in ('physical_case_id', 'physical_condition_hash', 'parent_group_id', 'split', 'background',
                'mechanism_id', 'geometry_family_id', 'control_family_id', 'parameter_values', 'geometry', 'control'):
        if case.get(key) != frozen.get(key) or request.get(key) != case.get(key):
            raise ValueError('production physical membership differs: '+key)
    resolution = case['resolution']
    settings = frozen['numeric_settings_by_resolution'].get(resolution)
    recipe_hash = frozen['numerical_recipe_hash_by_resolution'].get(resolution)
    if settings is None or request.get('numeric_settings') != settings or case.get('numeric_settings') != settings:
        raise ValueError('production numeric settings differ')
    if request.get('numerical_recipe_hash') != recipe_hash or case.get('numerical_recipe_hash') != recipe_hash:
        raise ValueError('production numerical recipe differs')
    if request.get('resolution') != resolution or request.get('command') != case.get('solver_command') or request.get('cwd') != case.get('solver_cwd'):
        raise ValueError('production actual command/frame differs from approved manifest')
    if request.get('complete_event_window_s') != [scope['time_domain']['start_s'], scope['time_domain']['end_s']]:
        raise ValueError('production complete event window differs')
    gen_path = _binding(case['gencase_receipt'], hashes)
    if Path(request['gencase_receipt']).resolve() != gen_path or request.get('gencase_receipt_sha256') != hashes[str(gen_path)]:
        raise ValueError('production GenCase receipt differs')
    gen = _json(gen_path)
    if gen.get('status') != 'completed' or gen.get('returncode') != 0 or gen.get('solver_dimension_from_gencase') != 3 or gen.get('fluid_particles', 0) <= 0:
        raise ValueError('production GenCase is not an actual successful 3D preflight')
    if gen.get('input_hashes_after_run') != gen.get('input_hashes_at_launch'):
        raise ValueError('production GenCase inputs mutated during execution')
    generated_prefix = Path(gen['command'][2]).resolve()
    if str(generated_prefix) not in request['command']:
        raise ValueError('production solver input is not the audited GenCase prefix')
    inputs = {_binding(binding, hashes) for binding in case.get('input_bindings', [])}
    for suffix in ('.xml', '.bi4'):
        if Path(str(generated_prefix)+suffix).resolve() not in inputs:
            raise ValueError('production generated XML/BI4 binding missing')
    for binding in frozen['input_bindings']:
        path = _binding(binding, hashes)
        if path not in inputs or gen['input_hashes_at_launch'].get(str(path)) != hashes[str(path)]:
            raise ValueError('production physical source differs from actual GenCase launch')
    audit_path = _binding(case['initialization_audit'], hashes)
    audit = _json(audit_path)
    required = ('actual_3d', 'positive_fluid', 'effective_transverse_layers', 'finite_boundary_coverage',
                'no_initial_fluid_solid_overlap', 'continuous_initial_mass_within_frozen_budget')
    if audit.get('schema') != 'ds02.production-initialization-audit.v1' or audit.get('case_id') != case['case_id'] or any(audit.get('checks', {}).get(key) is not True for key in required):
        raise ValueError('production initialization QA is incomplete or failed')
    if audit.get('gencase_receipt') != case['gencase_receipt']:
        raise ValueError('initialization QA does not bind actual GenCase')
    for binding in audit.get('source_bindings', []):
        _binding(binding, hashes)
    if not audit.get('source_bindings') or not audit.get('continuous_mass_accounting'):
        raise ValueError('initialization QA lacks source and continuous mass evidence')
    account = audit['continuous_mass_accounting']
    target = account.get('continuous_fluid_mass_kg')
    represented = account.get('native_fluid_mass_kg')
    tolerance = scope.get('initialization_acceptance', {}).get('relative_mass_error_max')
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v <= 0 for v in (target, represented, tolerance)):
        raise ValueError('initialization QA lacks finite physical mass/budget')
    frozen_target = frozen.get('continuous_initial_fluid_mass_kg')
    if not isinstance(frozen_target, (int, float)) or not math.isfinite(frozen_target) or frozen_target <= 0 or not math.isclose(target, frozen_target, rel_tol=1e-10):
        raise ValueError('initialization denominator differs from frozen continuous physical mass')
    node = ET.parse(str(generated_prefix)+'.xml').find('./execution/constants/massfluid')
    if node is None:
        raise ValueError('generated native massfluid is missing')
    actual_mass = float(node.attrib['value']) * gen['fluid_particles']
    if not math.isclose(represented, actual_mass, rel_tol=1e-6) or abs(actual_mass-target)/target > tolerance:
        raise ValueError('native initial mass exceeds the frozen continuous-volume budget')
    if account.get('mass_rescaling') is not False:
        raise ValueError('production initial mass rescaling is forbidden')
    # Re-evaluate current scientific reference/domain evidence. Approval is
    # still separate from this verifier's eligibility conclusion.
    verdict = _scope_verdict(paths['scope_spec'], paths['scope_evidence'])
    if verdict.get('status') != 'evidence-bound-eligible' or verdict.get('errors') or not verdict.get('evidence_bound_eligible'):
        raise ValueError('scientific scope evidence is not eligible')
    for binding in verdict['bound_artifacts']:
        hashes[binding['path']] = binding['actual_sha256']
    _binding(verdict['validator_binding'], hashes)
    return hashes
