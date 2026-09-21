#!/usr/bin/env python3
"""Build a relocatable reader bundle, without claiming a complete Core release."""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from collections.abc import Mapping
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.core_dataset import (COMPACT_SCHEMA, CoreDataset, SCHEMA,
                                  validate_manifest)
from scripts.core_cfd_dataset import open_dataset
from scripts.core_runtime import atomic_json, digest


CHECKPOINT_REGISTRY_SCHEMA = 'core.bundled_checkpoints.v1'
CHECKPOINT_PAYLOAD_SCHEMA = 'core.checkpoint.v1'
READER_MANIFEST_PREFLIGHT_SCHEMA = 'core.reader_manifest_preflight.v1'
READER_MANIFEST_NORMALIZATION_PLAN_SCHEMA = 'core.reader_manifest_normalization_plan.v1'
READER_MANIFEST_SCHEMAS = {SCHEMA, COMPACT_SCHEMA}
READER_MANIFEST_TARGET_SCHEMA = COMPACT_SCHEMA

# The learning-side formal admission gate is intentionally repeated here as a
# data contract.  This module only plans and audits the inputs; it does not
# infer a qualification result from a trajectory or launch a training job.
FORMAL_READER_GATE = {
    'validation_split': 'validation',
    'minimum_validation_cases': 12,
    'minimum_validation_families': 3,
    'minimum_validation_cases_per_family': 4,
}


def _canonical_hash(value):
    payload = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    import hashlib
    return hashlib.sha256(payload.encode()).hexdigest()


def _load_reader_manifest(value, data_root=None):
    """Load a canonical reader manifest without opening any trajectory file."""
    if isinstance(value, (str, Path)):
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = (Path(data_root).expanduser() if data_root is not None else Path.cwd()) / path
        path = path.resolve()
        payload = json.loads(path.read_text())
        return payload, path
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value)), None
    raise ValueError('reader manifest must be a JSON path or mapping')


def _hash_ref_is_portable(reference, *, label):
    if not isinstance(reference, Mapping) or not isinstance(reference.get('path'), str):
        raise ValueError(f'{label} requires a relative path reference')
    path = Path(reference['path'])
    if path.is_absolute() or '..' in path.parts:
        raise ValueError(f'{label} path is not portable')
    sha = reference.get('sha256')
    if not isinstance(sha, str) or len(sha) != 64:
        raise ValueError(f'{label} requires a SHA-256 reference')
    try:
        int(sha, 16)
    except ValueError as error:
        raise ValueError(f'{label} requires a SHA-256 reference') from error


def inspect_reader_manifests(manifests, *, data_root=None, expected_families=None,
                             expected_cases_per_family=None, expected_split_counts=None,
                             require_formal=False):
    """Perform a read-only composition/portability check for reader manifests.

    The check validates only JSON contracts and relative content-addressed
    references.  It deliberately does not open or hash HDF5 trajectories, so
    it is safe to run before an expensive full source verification.  Mixed v1
    (inline inputs) and v2 (hashed input assets) manifests are reported as
    non-composable; callers must normalize them explicitly before publishing a
    single training manifest.
    """
    if not isinstance(manifests, (list, tuple)) or not manifests:
        raise ValueError('at least one reader manifest is required')
    expected_families = (tuple(str(item) for item in expected_families)
                         if expected_families is not None else None)
    expected_split_counts = dict(expected_split_counts or {})
    rows_by_case, physical_owner, lineage_owner = {}, {}, {}
    sources, errors, schema_values = [], [], set()
    family_counts, split_counts = Counter(), Counter()
    portable = True
    for source in manifests:
        try:
            payload, path = _load_reader_manifest(source, data_root)
            schema = payload.get('schema') if isinstance(payload, Mapping) else None
            schema_values.add(schema)
            if schema not in READER_MANIFEST_SCHEMAS:
                raise ValueError(f'unsupported reader manifest schema: {schema}')
            validate_manifest(payload)
            formal = payload.get('formal_release', False)
            if not isinstance(formal, bool):
                raise ValueError('formal_release must be boolean')
            cases = payload.get('cases', [])
            for row in cases:
                case_id = row['case_id']
                if case_id in rows_by_case:
                    raise ValueError(f'duplicate case_id across reader manifests: {case_id}')
                rows_by_case[case_id] = row
                family = str(row['family'])
                split = str(row['split'])
                family_counts[family] += 1
                split_counts[(family, split)] += 1
                for key, owners in (('physical_case_id', physical_owner),
                                    ('lineage_group_id', lineage_owner)):
                    identity = row[key]
                    prior = owners.get(identity)
                    if prior is not None and prior != (family, split):
                        raise ValueError(
                            f'{key} crosses family/split boundaries: {identity}')
                    owners[identity] = (family, split)
                if schema == COMPACT_SCHEMA:
                    refs = row['known_inputs_ref']
                    for key in ('geometry', 'control'):
                        _hash_ref_is_portable(refs[key], label=f'{case_id}/{key}')
                else:
                    # Inline v1 inputs are portable by construction after
                    # validate_manifest has checked their finite arrays.
                    if 'known_inputs_ref' in row:
                        raise ValueError(f'{case_id} mixes inline and compact inputs')
            source_record = {
                'path': str(path) if path is not None else '<in-memory>',
                'sha256': digest(path) if path is not None else _canonical_hash(payload),
                'schema': schema, 'dataset_id': payload.get('dataset_id'),
                'formal_release': formal, 'case_count': len(cases),
                'family_counts': dict(sorted(Counter(row['family'] for row in cases).items())),
                'read_only': True,
            }
            sources.append(source_record)
        except (AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            portable = False
            errors.append(str(error))
            sources.append({'path': str(source), 'read_only': True, 'error': str(error)})

    if len(schema_values) > 1:
        errors.append('reader manifests use mixed core.dataset.v1/core.dataset.v2 schemas')
    if expected_families is not None:
        observed_families = set(family_counts)
        missing = sorted(set(expected_families) - observed_families)
        extra = sorted(observed_families - set(expected_families))
        if missing:
            errors.append('missing reader families: ' + ', '.join(missing))
        if extra:
            errors.append('unexpected reader families: ' + ', '.join(extra))
    if expected_cases_per_family is not None:
        if isinstance(expected_cases_per_family, Mapping):
            expected_cases = {str(k): int(v) for k, v in expected_cases_per_family.items()}
        else:
            expected_cases = {family: int(expected_cases_per_family)
                              for family in (expected_families or family_counts)}
        for family, expected in sorted(expected_cases.items()):
            observed = int(family_counts.get(family, 0))
            if observed != expected:
                errors.append(f'family {family} has {observed} reader cases; requires {expected}')
    for family, split in sorted(split_counts):
        expected = expected_split_counts.get(split)
        if expected is not None and split_counts[(family, split)] != int(expected):
            errors.append(
                f'family {family} split {split} has {split_counts[(family, split)]} cases; '
                f'requires {int(expected)}')
    if expected_split_counts:
        for family in sorted(family_counts):
            for split, expected in expected_split_counts.items():
                observed = int(split_counts.get((family, split), 0))
                if observed != int(expected):
                    errors.append(
                        f'family {family} split {split} has {observed} cases; '
                        f'requires {int(expected)}')
    all_formal = bool(sources) and all(item.get('formal_release') is True for item in sources)
    composable = bool(portable and len(schema_values) == 1 and not errors)
    formal_eligible = bool(composable and (all_formal if require_formal else True))
    if require_formal and not all_formal:
        errors.append('all reader manifests must declare formal_release=true')
        formal_eligible = False
    return {
        'schema': READER_MANIFEST_PREFLIGHT_SCHEMA,
        'manifest_count': len(sources),
        'sources': sources,
        'schema_versions': sorted(str(value) for value in schema_values),
        'family_case_counts': dict(sorted(family_counts.items())),
        'split_case_counts': {
            family: dict(sorted({split: count for (owner, split), count in split_counts.items()
                                 if owner == family}.items()))
            for family in sorted(family_counts)
        },
        'case_count': len(rows_by_case),
        'portable': bool(portable),
        'composable': composable,
        'formal_release': all_formal,
        'formal_eligible': formal_eligible,
        'hold_reasons': sorted(set(errors)),
        'read_only': True,
        'trajectory_files_opened': False,
        'future_state_inputs': False,
    }


def plan_reader_manifest_normalization(
        manifests, *, data_root=None, expected_families=None,
        required_validation_families=None,
        required_validation_cases_per_family=None, require_formal=True):
    """Create a read-only plan for normalizing reader manifests to v2.

    ``core.dataset.v2`` is the common target because its geometry and control
    inputs are content-addressed, relative references.  A v1 source is not
    converted here: the plan records the exact assets and hash checks a later
    materialization step must provide.  No HDF5 file is opened, no future
    state is read, and no manifest or registry is written.

    The formal gate mirrors :mod:`scripts.core_learning`: validation only,
    twelve cases total, at least three families, and at least four validation
    cases per family.  Keeping that gate in the plan makes the missing third
    family/T1 evidence explicit without treating this metadata audit as
    qualification.
    """
    if required_validation_families is None:
        required_validation_families = FORMAL_READER_GATE['minimum_validation_families']
    if required_validation_cases_per_family is None:
        required_validation_cases_per_family = FORMAL_READER_GATE[
            'minimum_validation_cases_per_family']
    try:
        required_validation_families = int(required_validation_families)
        required_validation_cases_per_family = int(required_validation_cases_per_family)
    except (TypeError, ValueError) as error:
        raise ValueError('formal validation family requirements must be integers') from error
    if required_validation_families < 1 or required_validation_cases_per_family < 1:
        raise ValueError('formal validation family requirements must be positive')

    inspection = inspect_reader_manifests(
        manifests, data_root=data_root, expected_families=expected_families,
        require_formal=False)
    blockers = []
    source_plans = []
    observed_schemas = set(inspection.get('schema_versions', []))
    valid_payloads = []

    def add_blocker(code, message, *, scope='normalization', source=None,
                    required_input=None):
        row = {'code': str(code), 'scope': str(scope), 'message': str(message)}
        if source is not None:
            row['source'] = str(source)
        if required_input is not None:
            row['required_input'] = str(required_input)
        blockers.append(row)

    for source in manifests:
        try:
            payload, path = _load_reader_manifest(source, data_root)
            schema = payload.get('schema') if isinstance(payload, Mapping) else None
            validate_manifest(payload)
            formal = payload.get('formal_release', False)
            if not isinstance(formal, bool):
                raise ValueError('formal_release must be boolean')
            valid_payloads.append((payload, path))
            cases = payload.get('cases', [])
            family_counts = Counter(str(row['family']) for row in cases)
            split_counts = Counter((str(row['family']), str(row['split'])) for row in cases)
            source_label = str(path) if path is not None else '<in-memory>'
            common = {
                'path': source_label,
                'sha256': digest(path) if path is not None else _canonical_hash(payload),
                'dataset_id': payload.get('dataset_id'),
                'source_schema': schema,
                'target_schema': READER_MANIFEST_TARGET_SCHEMA,
                'formal_release': formal,
                'case_count': len(cases),
                'family_counts': dict(sorted(family_counts.items())),
                'split_counts': {
                    family: dict(sorted({split: count for (owner, split), count
                                         in split_counts.items() if owner == family}.items()))
                    for family in sorted(family_counts)
                },
                'read_only': True,
                'trajectory_files_opened': False,
            }
            if schema == READER_MANIFEST_TARGET_SCHEMA:
                common.update({
                    'normalization_status': 'already_target_schema',
                    'normalization_action': 'retain_compact_input_references',
                    'required_inputs': [
                        'verify every known_inputs_ref geometry/control path is relative',
                        'verify every known_inputs_ref geometry/control SHA-256 against its asset',
                        'preserve each known_inputs_sha256 and all native trajectory bindings',
                    ],
                })
                for row in cases:
                    refs = row.get('known_inputs_ref', {})
                    for key in ('geometry', 'control'):
                        try:
                            _hash_ref_is_portable(
                                refs.get(key), label=f"{row['case_id']}/{key}")
                        except ValueError as error:
                            add_blocker(
                                'compact_input_reference_invalid', str(error), source=source_label,
                                required_input=(
                                    'portable content-addressed geometry/control references'))
            elif schema == SCHEMA:
                common.update({
                    'normalization_status': 'pending_asset_materialization',
                    'normalization_action': 'materialize_inline_inputs_as_compact_assets',
                    'required_inputs': [
                        'materialize one content-addressed geometry asset per distinct inline geometry',
                        'materialize one content-addressed control asset per distinct inline control',
                        'record relative path and SHA-256 for each geometry/control asset',
                        'copy physics, numerics, coordinate_frame, and contract_version metadata',
                        'recompute contract hash and require equality with known_inputs_sha256',
                        'preserve hdf5 path, byte count, trajectory SHA-256, and case identity fields',
                    ],
                })
                add_blocker(
                    'inline_inputs_require_compact_assets',
                    'v1 inline known_inputs must be materialized as hash-bound geometry/control assets',
                    source=source_label,
                    required_input=(
                        'content-addressed geometry/control assets plus post-materialization '
                        'known_inputs_sha256 equality'))
            else:
                add_blocker(
                    'unsupported_reader_schema',
                    f'unsupported reader manifest schema: {schema}', source=source_label)
        except (AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            source_label = str(source)
            add_blocker('manifest_contract_invalid', str(error), source=source_label)
            source_plans.append({
                'path': source_label,
                'target_schema': READER_MANIFEST_TARGET_SCHEMA,
                'normalization_status': 'blocked_invalid_source',
                'read_only': True,
                'trajectory_files_opened': False,
            })
            continue
        source_plans.append(common)

    if len(observed_schemas) > 1:
        add_blocker(
            'mixed_source_schema',
            'v1 inline and v2 compact reader manifests cannot be published as one '
            'common-schema manifest until v1 inputs are normalized',
            required_input='normalize every v1 source to core.dataset.v2')
    if not inspection.get('portable', False):
        add_blocker(
            'reader_manifest_portability',
            'one or more source manifests failed the relative-path/hash portability contract',
            required_input='repair the source manifest contract before normalization')

    # The source manifest can declare formal_release, but this plan never
    # upgrades that claim.  A false claim remains a formal blocker until an
    # independently produced release artifact is supplied.
    if require_formal:
        for payload, path in valid_payloads:
            if payload.get('formal_release') is not True:
                add_blocker(
                    'source_not_formal',
                    'source manifest does not declare formal_release=true',
                    scope='formal', source=str(path) if path is not None else '<in-memory>',
                    required_input='a separately qualified formal reader manifest')

    family_counts = inspection.get('family_case_counts', {})
    validation_counts = {
        family: int(inspection.get('split_case_counts', {}).get(family, {}).get('validation', 0))
        for family in sorted(family_counts)
    }
    validation_case_count = sum(validation_counts.values())
    validation_families = len([family for family, count in validation_counts.items() if count > 0])
    formal_gate = {
        'validation_split': FORMAL_READER_GATE['validation_split'],
        'minimum_validation_cases': FORMAL_READER_GATE['minimum_validation_cases'],
        'minimum_validation_families': required_validation_families,
        'minimum_validation_cases_per_family': required_validation_cases_per_family,
        'observed_validation_cases': validation_case_count,
        'observed_validation_families': validation_families,
        'observed_validation_case_counts': validation_counts,
        'third_family_required': validation_families < required_validation_families,
    }
    if validation_case_count < int(FORMAL_READER_GATE['minimum_validation_cases']):
        add_blocker(
            'formal_validation_case_gate',
            f'formal validation requires at least {FORMAL_READER_GATE["minimum_validation_cases"]} '
            f'cases; observed {validation_case_count}',
            scope='formal', required_input='at least twelve validation cases')
    if validation_families < required_validation_families:
        add_blocker(
            'formal_validation_family_gate',
            f'formal validation requires at least {required_validation_families} families with '
            f'validation cases; observed {validation_families}',
            scope='formal', required_input=(
                'a third independently qualified family/T1 validation block before formal planning'))
    undersized = {
        family: count for family, count in validation_counts.items()
        if count < required_validation_cases_per_family
    }
    if undersized:
        add_blocker(
            'formal_validation_cases_per_family_gate',
            f'each validation family requires at least {required_validation_cases_per_family} '
            f'cases; undersized families: {undersized}',
            scope='formal', required_input='four validation cases for every formal family')

    split_policy = {
        'formal_split': FORMAL_READER_GATE['validation_split'],
        'observed_splits_by_family': inspection.get('split_case_counts', {}),
        'test_roles_must_remain_explicit': True,
        'resolution': (
            'retain native test/id_test/ood_test names, or provide an explicit role map before '
            'any combined test evaluation; this plan does not silently relabel cases'),
    }
    normalization_contract = {
        'target_schema': READER_MANIFEST_TARGET_SCHEMA,
        'case_field_mapping': {
            'known_inputs.geometry': 'known_inputs_ref.geometry',
            'known_inputs.control': 'known_inputs_ref.control',
            'known_inputs.physics': 'known_inputs_ref.physics',
            'known_inputs.numerics': 'known_inputs_ref.numerics',
            'known_inputs.coordinate_frame': 'known_inputs_ref.coordinate_frame',
            'known_inputs.contract_version': 'known_inputs_ref.contract_version',
        },
        'preserve_case_fields': [
            'case_id', 'physical_case_id', 'lineage_group_id', 'family', 'split',
            'evaluation_role', 'scope_id', 'hdf5', 'bytes', 'sha256',
            'known_inputs_sha256', 'qualification_case', 'provenance', 'semantics',
        ],
        'geometry_asset_payload': [
            'triangles', 'component_id', 'body_id', 'wall_velocity',
            'coordinate_frame', 'version',
        ],
        'control_asset_payload': ['samples', 'centre', 'semantics'],
        'post_materialization_checks': [
            'all input asset paths are relative to the explicit data root',
            'all input asset hashes match their bytes',
            'known_inputs_from_record contract hash equals known_inputs_sha256 for every case',
            'native trajectory bindings remain byte/hash identical',
        ],
    }
    normalization_blocked = any(item['scope'] == 'normalization' for item in blockers)
    formal_blocked = any(item['scope'] == 'formal' for item in blockers)
    formal_ready = bool(source_plans and not normalization_blocked and not formal_blocked)
    return {
        'schema': READER_MANIFEST_NORMALIZATION_PLAN_SCHEMA,
        'target_schema': READER_MANIFEST_TARGET_SCHEMA,
        'manifest_count': len(source_plans),
        'sources': source_plans,
        'source_schema_versions': sorted(observed_schemas),
        'family_case_counts': family_counts,
        'formal_gate': formal_gate,
        'split_policy': split_policy,
        'normalization_contract': normalization_contract,
        'normalization_ready': bool(source_plans and not normalization_blocked),
        'formal_ready': formal_ready,
        'formal_preflight_passed': formal_ready,
        # Eligibility here means that the metadata gate is ready for a later
        # planner.  It never claims that a model was trained or scientifically
        # qualified; those claims require separate evidence and publication.
        'formal_eligible': bool(formal_ready and require_formal),
        'qualification_claimed': False,
        'hold_reasons': sorted({item['message'] for item in blockers}),
        'blockers': sorted(blockers, key=lambda item: (
            item['scope'], item['code'], item.get('source', ''))),
        'read_only': True,
        'trajectory_files_opened': False,
        'future_state_inputs': False,
        'training_started': False,
        'manifest_written': False,
        'registry_written': False,
    }


def _sha256_hex(value, *, label):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f'{label} must be a 64-character SHA-256 hex digest')
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(f'{label} must be a 64-character SHA-256 hex digest') from error
    return value.lower()


def _strict_bytes(value, *, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f'{label} must be a non-negative integer')
    return value


def _bundle_relative_path(value, *, label):
    """Return one canonical, POSIX-relative path usable after relocation."""
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError(f'{label} must be a portable relative path')
    path = Path(value)
    normalized = path.as_posix()
    if (path.is_absolute() or '..' in path.parts or normalized != value
            or normalized in ('', '.')):
        raise ValueError(f'{label} must be a portable relative path')
    return normalized


def _checkpoint_payload_identity(path):
    """Read only the CPU checkpoint metadata needed for package identity.

    This is content validation, not a training or scientific qualification
    step.  Core checkpoints are serialized mappings, so their identity fields
    can be compared with the registry without constructing a model or using a
    GPU.
    """
    try:
        import torch
        try:
            payload = torch.load(Path(path), map_location='cpu', weights_only=False)
        except TypeError:  # torch versions predating the weights_only keyword
            payload = torch.load(Path(path), map_location='cpu')
    except Exception as error:
        raise ValueError('checkpoint content is not a readable Core checkpoint') from error
    if not isinstance(payload, Mapping) or payload.get('schema') != CHECKPOINT_PAYLOAD_SCHEMA:
        raise ValueError('checkpoint content has an unsupported Core checkpoint schema')
    model_kind = payload.get('model_kind')
    if not isinstance(model_kind, str) or not model_kind:
        raise ValueError('checkpoint content model_kind is missing')
    identity = {'model_kind': model_kind}
    for key in ('seed', 'hidden', 'update'):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f'checkpoint content {key} is malformed')
        if key == 'update' and value < 0:
            raise ValueError('checkpoint content update is malformed')
        identity[key] = value
    return identity


def _require_registered_asset(file_rows, seen, *, path, sha256, bytes_value=None, label):
    relative = _bundle_relative_path(path, label=f'{label} path')
    item = file_rows.get(relative)
    if relative not in seen or item is None:
        raise ValueError(f'{label} is not registered in bundle.json')
    expected_hash = _sha256_hex(sha256, label=f'{label} hash')
    if item['sha256'].lower() != expected_hash:
        raise ValueError(f'{label} hash disagrees with bundle artifact')
    if bytes_value is not None:
        expected_bytes = _strict_bytes(bytes_value, label=f'{label} bytes')
        if item['bytes'] != expected_bytes:
            raise ValueError(f'{label} bytes disagrees with bundle artifact')
    return relative


def _validate_dataset_assets(root, report, seen):
    """Bind every dataset-declared asset to a measured bundle artifact."""
    dataset_path = root / 'dataset.json'
    try:
        payload = json.loads(dataset_path.read_text())
        validate_manifest(payload)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError('invalid bundled dataset manifest') from error
    file_rows = {item['path']: item for item in report['files']}
    for row in payload['cases']:
        _require_registered_asset(
            file_rows, seen, path=row['hdf5'], sha256=row['sha256'],
            bytes_value=row.get('bytes'), label=f"case {row['case_id']} HDF5")
        if payload['schema'] == COMPACT_SCHEMA:
            references = row['known_inputs_ref']
            for key in ('geometry', 'control'):
                reference = references[key]
                _require_registered_asset(
                    file_rows, seen, path=reference['path'], sha256=reference['sha256'],
                    bytes_value=reference.get('bytes'),
                    label=f"case {row['case_id']} {key} input")
        provenance = row.get('provenance', {})
        if not isinstance(provenance, Mapping):
            raise ValueError(f"case {row['case_id']} provenance is malformed")
        for key, reference in provenance.items():
            if isinstance(reference, Mapping) and 'path' in reference:
                _require_registered_asset(
                    file_rows, seen, path=reference['path'], sha256=reference.get('sha256'),
                    bytes_value=reference.get('bytes'),
                    label=f"case {row['case_id']} provenance {key}")
            elif key == 'prepared' and isinstance(reference, str):
                prepared_hash = provenance.get('prepared_sha256')
                if prepared_hash is None:
                    raise ValueError(
                        f"case {row['case_id']} prepared asset is missing its hash")
                _require_registered_asset(
                    file_rows, seen, path=reference, sha256=prepared_hash,
                    label=f"case {row['case_id']} prepared asset")
    declared_cases = report.get('case_count')
    if (isinstance(declared_cases, bool) or not isinstance(declared_cases, int)
            or declared_cases != len(payload['cases'])):
        raise ValueError('bundle case count disagrees with dataset manifest')


def _validate_checkpoint_registry(root, report, seen):
    """Validate optional model assets without turning packaging into training."""
    if 'checkpoints.json' not in seen:
        return 0
    registry_path = root / 'checkpoints.json'
    try:
        registry = json.loads(registry_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError('invalid checkpoint registry') from error
    if registry.get('schema') != CHECKPOINT_REGISTRY_SCHEMA:
        raise ValueError('unsupported checkpoint registry version')
    rows = registry.get('checkpoints')
    if not isinstance(rows, list) or not rows:
        raise ValueError('checkpoint registry must contain at least one checkpoint')
    file_rows = {item['path']: item for item in report['files']}
    paths = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('malformed checkpoint registry entry')
        path = _bundle_relative_path(row.get('path'), label='checkpoint registry path')
        if path in paths or path not in seen or path not in file_rows:
            raise ValueError('checkpoint registry path is missing or duplicated')
        paths.add(path)
        sha = _sha256_hex(row.get('sha256'), label='checkpoint registry hash')
        registered_bytes = _strict_bytes(
            row.get('bytes'), label='checkpoint registry bytes')
        file_row = file_rows[path]
        target = (root / path).resolve()
        target.relative_to(root)
        if not target.is_file() or target.stat().st_size != registered_bytes:
            raise ValueError('checkpoint registry bytes disagree with checkpoint artifact')
        if digest(target).lower() != sha:
            raise ValueError('checkpoint registry hash disagrees with checkpoint artifact')
        if file_row['sha256'].lower() != sha:
            raise ValueError('checkpoint registry hash disagrees with bundle artifact')
        if file_row['bytes'] != registered_bytes:
            raise ValueError('checkpoint registry bytes disagree with bundle artifact')
        for key in ('model_kind', 'seed', 'hidden', 'update'):
            if key not in row:
                raise ValueError(f'checkpoint registry entry missing {key}')
        if not isinstance(row['model_kind'], str) or not row['model_kind']:
            raise ValueError('checkpoint registry model_kind is missing')
        for key in ('seed', 'hidden'):
            if isinstance(row[key], bool) or not isinstance(row[key], int):
                raise ValueError(f'checkpoint registry {key} is malformed')
        if (isinstance(row['update'], bool) or not isinstance(row['update'], int)
                or row['update'] < 0):
            raise ValueError('checkpoint registry update is malformed')
        identity = _checkpoint_payload_identity(target)
        for key, value in identity.items():
            if row[key] != value:
                raise ValueError(
                    f'checkpoint registry {key} disagrees with checkpoint content')
    return len(rows)


def verify_bundle(directory):
    """Verify measured bundle contents before any reproduction entrypoint."""
    root = Path(directory).expanduser().resolve()
    try:
        report = json.loads((root / 'bundle.json').read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError('invalid bundle index') from error
    if not isinstance(report, Mapping) or report.get('schema') != 'core.reader_bundle.v1':
        raise ValueError('unsupported bundle version')
    entries = report.get('files')
    if not isinstance(entries, list):
        raise ValueError('bundle index files must be a list')
    seen = set()
    normalized_entries = []
    for item in entries:
        if not isinstance(item, Mapping):
            raise ValueError('malformed bundle artifact registration')
        relative = _bundle_relative_path(item.get('path'), label='bundle artifact path')
        if relative in seen:
            raise ValueError('invalid or duplicate bundle artifact path')
        seen.add(relative)
        sha = _sha256_hex(item.get('sha256'), label=f'bundle artifact {relative} hash')
        bytes_value = _strict_bytes(item.get('bytes'), label=f'bundle artifact {relative} bytes')
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError as error:
            raise ValueError(f'bundle artifact path escapes bundle: {relative}') from error
        if (not target.is_file() or target.stat().st_size != bytes_value
                or digest(target).lower() != sha):
            raise ValueError(f'bundle artifact integrity failure: {relative}')
        normalized_entries.append({'path': relative, 'sha256': sha, 'bytes': bytes_value})
    report = dict(report)
    report['files'] = normalized_entries
    required = {'dataset.json', 'environment.json', 'code/scripts/core_benchmark.py',
                'code/scripts/core_cfd_dataset.py', 'code/scripts/core_learning.py',
                'code/scripts/core_models.py', 'code/scripts/core_evaluation.py',
                'code/scripts/core_contract.py', 'code/scripts/core_physics.py',
                'code/scripts/core_reproduction_check.py', 'code/scripts/core_package.py'}
    if not required <= seen:
        raise ValueError('bundle is missing required artifact registrations')
    _validate_dataset_assets(root, report, seen)
    checkpoint_count = _validate_checkpoint_registry(root, report, seen)
    declared_count = report.get('checkpoint_count', 0)
    if (isinstance(declared_count, bool) or not isinstance(declared_count, int)
            or declared_count != checkpoint_count):
        raise ValueError('bundle checkpoint count disagrees with registry')
    declared_supported = report.get('model_reproduction_supported')
    if declared_supported is not None and not isinstance(declared_supported, bool):
        raise ValueError('bundle model reproduction declaration is malformed')
    if declared_supported is not None and declared_supported != bool(checkpoint_count):
        raise ValueError('bundle model reproduction declaration disagrees with registry')
    return {'passed': True, 'verified_files': len(seen), 'full_core_release': False,
            'checkpoint_count': checkpoint_count,
            'model_reproduction_supported': bool(checkpoint_count)}


def require_verified_bundle(directory, *, manifest=None):
    """The package boundary used by bundled reader/model reproduction code."""
    verification = verify_bundle(directory)
    if manifest is not None:
        root = Path(directory).expanduser().resolve()
        candidate = Path(manifest).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            candidate = candidate.resolve()
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError('reproduction manifest must be inside the bundle') from error
        if candidate != (root / 'dataset.json').resolve():
            raise ValueError('reproduction must use the bundle registered dataset.json')
    return verification


def _patch_bundle_reproduction_entrypoint(source):
    """Add the package gate to the copied benchmark module only.

    The repository-wide benchmark module is intentionally outside this
    package task's edit boundary.  A published bundle gets a small, measured
    entrypoint guard so both its imported ``reproduce`` API and its CLI call
    verify the immutable bundle before opening reader/model state.
    """
    text = Path(source).read_text()
    if 'require_verified_bundle(data_root, manifest=manifest)' in text:
        return
    lines = text.splitlines(keepends=True)
    start = next((index for index, line in enumerate(lines)
                  if line.startswith('def reproduce(')), None)
    if start is None:
        raise ValueError('benchmark module has no reproduce entrypoint')
    end = next((index for index in range(start, len(lines))
                if lines[index].rstrip().endswith('):')), None)
    if end is None:
        raise ValueError('benchmark reproduce signature is malformed')
    lines[end + 1:end + 1] = [
        '    from scripts.core_package import require_verified_bundle\n',
        '    require_verified_bundle(data_root, manifest=manifest)\n',
    ]
    Path(source).write_text(''.join(lines))


def _install_source_reader_gate():
    """Protect the repository API without changing ``core_benchmark.py``."""
    try:
        import scripts.core_benchmark as benchmark
    except ImportError:
        return
    original = getattr(benchmark, 'verify_dataset', None)
    if original is None or getattr(original, '_core_package_gate', False):
        return

    def guarded_verify_dataset(manifest, data_root, *, case_ids=None, full_scan=False):
        root = Path(data_root).expanduser().resolve()
        if (root / 'bundle.json').is_file():
            require_verified_bundle(root, manifest=manifest)
        return original(manifest, data_root, case_ids=case_ids, full_scan=full_scan)

    guarded_verify_dataset._core_package_gate = True
    guarded_verify_dataset.__name__ = getattr(original, '__name__', 'verify_dataset')
    guarded_verify_dataset.__doc__ = getattr(original, '__doc__', None)
    benchmark.verify_dataset = guarded_verify_dataset


def build_bundle(manifest, data_root, destination, *, hardlink=False, checkpoint_manifest=None):
    # Keep the package builder aligned with inspect/open_dataset: a relative
    # manifest name is rooted at the explicit data_root, rather than at the
    # caller's current working directory.  This matters when the unified
    # verify -> inspect -> package entrypoint is invoked from a relocated
    # worker directory.
    root = Path(data_root).expanduser().resolve()
    manifest = Path(manifest).expanduser()
    if not manifest.is_absolute():
        manifest = root / manifest
    manifest = manifest.resolve()
    destination = Path(destination).absolute()
    if destination.exists():
        raise FileExistsError("bundle destination already exists; immutable publication required")
    assets = {}
    checkpoints = []
    if checkpoint_manifest is not None:
        try:
            checkpoint_source = json.loads(Path(checkpoint_manifest).read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError('invalid checkpoint manifest') from error
        rows = checkpoint_source.get('checkpoints') if isinstance(checkpoint_source, Mapping) else None
        if not isinstance(rows, list):
            raise ValueError('checkpoint manifest must contain a checkpoints list')
        for index, item in enumerate(rows):
            if not isinstance(item, Mapping):
                raise ValueError('malformed checkpoint manifest entry')
            source_value = item.get('path')
            if not isinstance(source_value, str) or not source_value:
                raise ValueError('checkpoint manifest entry requires a path')
            source = Path(source_value)
            source = (source if source.is_absolute() else root / source).resolve()
            try:
                source.relative_to(root)
            except ValueError as error:
                raise ValueError('checkpoint source must be inside data_root') from error
            expected_hash = _sha256_hex(item.get('sha256'), label='checkpoint manifest hash')
            observed_hash = digest(source)
            if observed_hash.lower() != expected_hash:
                raise ValueError(f'source checkpoint integrity failure: {source}')
            observed_bytes = source.stat().st_size
            if item.get('bytes') is not None and _strict_bytes(
                    item.get('bytes'), label='checkpoint manifest bytes') != observed_bytes:
                raise ValueError(f'source checkpoint bytes mismatch: {source}')
            identity = _checkpoint_payload_identity(source)
            for key in ('model_kind', 'seed', 'update'):
                if key not in item:
                    raise ValueError(f'checkpoint manifest entry missing {key}')
                if item[key] != identity[key]:
                    raise ValueError(f'checkpoint manifest {key} disagrees with checkpoint content')
            if item.get('hidden') is not None and item['hidden'] != identity['hidden']:
                raise ValueError('checkpoint manifest hidden disagrees with checkpoint content')
            relative = f'models/checkpoint-{index:03d}.pt'
            assets[relative] = {'sha256':observed_hash, 'source':source}
            checkpoints.append({'path':relative,'sha256':observed_hash,
                                'bytes':observed_bytes, 'model_kind':identity['model_kind'],
                                'seed':identity['seed'], 'hidden':identity['hidden'],
                                'update':identity['update']})
        if not checkpoints:
            raise ValueError('checkpoint manifest must register at least one checkpoint')
    with open_dataset(manifest, root) as data:
        # Publish the normalized public contract so a CFD source manifest does
        # not retain a runtime dependency on its original preparation directory.
        payload = copy.deepcopy(data.manifest)
        for case_id in data.case_ids():
            row = data.record(case_id)
            data.known_inputs(case_id)
            references = [{"path":row["hdf5"], "sha256":row["sha256"]}]
            references += [v for k,v in row.get("known_inputs_ref",{}).items() if k in ("geometry","control")]
            for ref in references:
                relative = Path(ref["path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("bundle assets must use portable relative paths")
                source = (root / relative).resolve()
                source.relative_to(root)
                if relative.as_posix() in assets and assets[relative.as_posix()]["sha256"] != ref["sha256"]:
                    raise ValueError("conflicting content hashes for a shared asset")
                assets[relative.as_posix()] = {"sha256":ref["sha256"], "source":source}
        for row in payload['cases']:
            provenance = row.get('provenance', {})
            if not isinstance(provenance, Mapping):
                raise ValueError(f"case {row['case_id']} provenance is malformed")
            prepared = provenance.get('prepared')
            if isinstance(prepared, str):
                source = Path(prepared)
                source = (source if source.is_absolute() else root/source).resolve()
                relative = source.relative_to(root).as_posix()
                observed_hash = digest(source)
                prior = assets.get(relative)
                if prior is not None and prior['sha256'] != observed_hash:
                    raise ValueError('conflicting content hashes for a shared asset')
                assets[relative] = {'sha256':observed_hash,'source':source}
                provenance['prepared'] = relative
                provenance['prepared_sha256'] = observed_hash
            for key, reference in list(provenance.items()):
                if not isinstance(reference, Mapping) or 'path' not in reference:
                    continue
                source = Path(reference['path'])
                source = (source if source.is_absolute() else root/source).resolve()
                relative = source.relative_to(root).as_posix()
                expected_hash = _sha256_hex(
                    reference.get('sha256'),
                    label=f"case {row['case_id']} provenance {key} hash")
                observed_hash = digest(source)
                if observed_hash.lower() != expected_hash:
                    raise ValueError(
                        f"source provenance integrity failure: {row['case_id']}/{key}")
                observed_bytes = source.stat().st_size
                if reference.get('bytes') is not None and _strict_bytes(
                        reference.get('bytes'),
                        label=f"case {row['case_id']} provenance {key} bytes") != observed_bytes:
                    raise ValueError(
                        f"source provenance bytes mismatch: {row['case_id']}/{key}")
                prior = assets.get(relative)
                if prior is not None and prior['sha256'] != observed_hash:
                    raise ValueError('conflicting content hashes for a shared asset')
                assets[relative] = {'sha256':observed_hash,'source':source}
                normalized = dict(reference)
                normalized.update({'path': relative, 'sha256': observed_hash,
                                   'bytes': observed_bytes})
                provenance[key] = normalized
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging = destination.with_name(destination.name + ".staging-" + uuid.uuid4().hex)
    staging.mkdir()
    try:
        files = []
        for relative, ref in sorted(assets.items()):
            source, target = ref["source"], staging / relative
            if digest(source) != ref["sha256"]:
                raise ValueError(f"source integrity failure: {relative}")
            target.parent.mkdir(parents=True,exist_ok=True)
            if hardlink:
                os.link(source,target)
            else:
                shutil.copyfile(source,target)
            if digest(target) != ref["sha256"]:
                raise ValueError(f"transfer integrity failure: {relative}")
            files.append({"path":relative,"sha256":ref["sha256"],"bytes":target.stat().st_size})
        atomic_json(staging/'dataset.json',payload)
        files.append({"path":"dataset.json","sha256":digest(staging/'dataset.json'),
                      "bytes":(staging/'dataset.json').stat().st_size})
        if checkpoints:
            atomic_json(staging/'checkpoints.json',{'schema':'core.bundled_checkpoints.v1',
                'checkpoints':checkpoints,'formal_training_qualification':'not_inferred_from_packaging'})
            files.append({'path':'checkpoints.json','sha256':digest(staging/'checkpoints.json'),
                          'bytes':(staging/'checkpoints.json').stat().st_size})
        code_root = staging/'code/scripts'
        code_root.mkdir(parents=True)
        (code_root/'__init__.py').write_text('')
        for name in ('core_benchmark.py','core_runtime.py','core_contract.py','core_dataset.py',
                     'core_models.py','core_learning.py','core_cfd_dataset.py','core_package.py',
                     'core_evaluation.py','core_physics.py','core_reproduction_check.py',
                     'passive_tracers.py','f3_control.py'):
            source = Path(__file__).resolve().parent/name
            target = code_root/name
            shutil.copyfile(source,target)
            if name == 'core_benchmark.py':
                _patch_bundle_reproduction_entrypoint(target)
            compile(target.read_text(),str(target),'exec')
            files.append({'path':str(target.relative_to(staging)),'sha256':digest(target),'bytes':target.stat().st_size})
        versions = {name:importlib.metadata.version(name) for name in ('numpy','scipy','h5py','torch')}
        atomic_json(staging/'environment.json',{'python':sys.version,'observed_packages':versions,
                    'note':'Recorded build environment; choose the torch CUDA wheel for the target host. No environment is modified.'})
        (staging/'README.md').write_text(
            '# Core development reader bundle\n\n'
            'From this directory, run:\n\n'
            '```sh\n'
            'python code/scripts/core_package.py --verify-bundle .\n'
            'python code/scripts/core_benchmark.py verify --manifest dataset.json --data-root .\n'
            '# With a registered checkpoint and explicitly selected cases:\n'
            'python code/scripts/core_benchmark.py reproduce --manifest dataset.json --data-root . '
            '--checkpoint models/checkpoint-000.pt --case-id CASE_ID --output-dir ../reproduction\n'
            '```\n\n'
            'The reader path needs NumPy, SciPy and h5py. Checkpoint-backed model reproduction additionally needs PyTorch.\n'
            'Build versions are recorded in environment.json. Full product reproduction requires a paired report from a distinct host.\n'
            'This bundle is not a completed or scientifically qualified Core release.\n')
        for relative in ('code/scripts/__init__.py','environment.json','README.md'):
            target=staging/relative
            files.append({'path':relative,'sha256':digest(target),'bytes':target.stat().st_size})
        report = {"schema":"core.reader_bundle.v1", "full_core_release":False,
                  "scope":"registered dataset, public inputs, code and optionally hash-bound model checkpoints; scientific qualification remains separate",
                  "checkpoint_count":len(checkpoints),
                  "case_count":len(payload['cases']),"files":files,
                  "physical_storage":"shared hardlinks; do not mutate source or bundle" if hardlink else "independent copies",
                  "entrypoint":"python code/scripts/core_benchmark.py reproduce --manifest dataset.json --data-root .",
                  "model_reproduction_supported":bool(checkpoints),
                  "model_entrypoint":"python code/scripts/core_benchmark.py reproduce --manifest dataset.json --data-root . --checkpoint models/checkpoint-000.pt --case-id CASE_ID --output-dir ../reproduction"}
        atomic_json(staging/'bundle.json',report)
        verify_bundle(staging)
        # Rename publishes only a fully copied and verified directory.
        os.rename(staging,destination)
        return report
    except BaseException:
        shutil.rmtree(staging,ignore_errors=True)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-bundle',type=Path,help='verify an existing immutable bundle without rebuilding')
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--data-root',type=Path)
    parser.add_argument('--destination',type=Path)
    parser.add_argument('--checkpoint-manifest',type=Path,help='optional registered checkpoint paths, hashes and model identities')
    parser.add_argument('--hardlink',action='store_true')
    parser.add_argument('--verify-reader',action='store_true')
    parser.add_argument('--source-host')
    args=parser.parse_args()
    if args.verify_bundle is not None:
        if any((args.manifest,args.data_root,args.destination,args.checkpoint_manifest,args.hardlink,args.verify_reader,args.source_host)):
            parser.error('--verify-bundle cannot be combined with build options')
        print(json.dumps(verify_bundle(args.verify_bundle),indent=2))
        return 0
    if not all((args.manifest,args.data_root,args.destination)):
        parser.error('building requires --manifest, --data-root and --destination')
    report=build_bundle(args.manifest,args.data_root,args.destination,hardlink=args.hardlink,
                        checkpoint_manifest=args.checkpoint_manifest)
    if args.verify_reader:
        destination=args.destination.resolve()
        verify_bundle(destination)
        command=[sys.executable,str(destination/'code/scripts/core_benchmark.py'),'reproduce',
                 '--manifest',str(destination/'dataset.json'),'--data-root',str(destination),
                 '--output',str(destination/'reader-reproduction.json')]
        if args.source_host:
            command.extend(['--source-host',args.source_host])
        env=dict(os.environ)
        env.pop('PYTHONPATH',None)
        subprocess.run(command,cwd=destination,env=env,check=True)
        verification=json.loads((destination/'reader-reproduction.json').read_text())
        if not verification['passed']:
            return 1
    print(json.dumps({k:v for k,v in report.items() if k!='files'},indent=2))
    return 0


_install_source_reader_gate()


if __name__=='__main__':
    raise SystemExit(main())
