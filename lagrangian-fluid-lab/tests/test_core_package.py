import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import scripts.core_package as core_package
import pytest
from test_core_contract import tiny_manifest
from scripts.core_package import (build_bundle, inspect_reader_manifests,
                                  plan_reader_manifest_normalization, verify_bundle)
from scripts.core_benchmark import verify_dataset


def test_moved_bundle_reads_and_corruption_is_rejected(tmp_path):
    source=tmp_path/'source';source.mkdir()
    manifest=source/'manifest.json';manifest.write_text(json.dumps(tiny_manifest(source)))
    bundle=tmp_path/'bundle'
    build_bundle(manifest,source,bundle)
    relocated=tmp_path/'different-root';bundle.rename(relocated)
    assert verify_bundle(relocated)['passed']
    assert verify_dataset(relocated/'dataset.json',relocated)['passed']
    with (relocated/'data.h5').open('ab') as stream:stream.write(b'corruption')
    with pytest.raises(ValueError,match='artifact integrity'):
        verify_dataset(relocated/'dataset.json',relocated)


def test_bundle_builder_resolves_relative_manifest_against_data_root(tmp_path, monkeypatch):
    """The package entrypoint must be independent of the caller cwd."""
    source = tmp_path / 'source'
    source.mkdir()
    manifest = source / 'manifest.json'
    manifest.write_text(json.dumps(tiny_manifest(source)))
    caller = tmp_path / 'caller'
    caller.mkdir()
    destination = tmp_path / 'bundle'
    monkeypatch.chdir(caller)

    build_bundle('manifest.json', source, destination)

    assert verify_bundle(destination)['passed']
    assert verify_dataset(destination / 'dataset.json', destination)['passed']


def test_failed_export_does_not_publish_partial_bundle(tmp_path):
    source=tmp_path/'source';source.mkdir()
    value=tiny_manifest(source);value['cases'][0]['sha256']='0'*64
    manifest=source/'manifest.json';manifest.write_text(json.dumps(value))
    destination=tmp_path/'bundle'
    with pytest.raises(ValueError,match='integrity'):
        build_bundle(manifest,source,destination)
    assert not destination.exists()
    assert not list(tmp_path.glob('bundle.staging-*'))


def test_bundle_reader_runs_without_repository_python_path(tmp_path):
    import os
    import subprocess
    import sys
    source=tmp_path/'source';source.mkdir()
    manifest=source/'manifest.json';manifest.write_text(json.dumps(tiny_manifest(source)))
    bundle=tmp_path/'standalone';build_bundle(manifest,source,bundle)
    env=dict(os.environ);env.pop('PYTHONPATH',None)
    result=subprocess.run([sys.executable,str(bundle/'code/scripts/core_benchmark.py'),'verify',
                           '--manifest',str(bundle/'dataset.json'),'--data-root',str(bundle)],
                          cwd=tmp_path,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['passed']
    # The multi-family learning reader is a lazy dependency, so a successful
    # F3 verify alone cannot establish that the learning entrypoint is portable.
    imported=subprocess.run([sys.executable,'-I','-B','-c',
        'import sys; sys.path.insert(0, sys.argv[1]); '
        'from scripts.core_cfd_dataset import open_dataset; '
        'from scripts.core_learning import _dataset',str(bundle/'code')],
        cwd=tmp_path,env=env,capture_output=True,text=True)
    assert imported.returncode==0,imported.stderr
    checked=subprocess.run([sys.executable,str(bundle/'code/scripts/core_package.py'),
                            '--verify-bundle',str(bundle)],cwd=tmp_path,env=env,
                           capture_output=True,text=True)
    assert checked.returncode==0,checked.stderr
    assert json.loads(checked.stdout)['passed']


def test_bundle_rejects_corrupt_code_and_unknown_version(tmp_path):
    source=tmp_path/'source';source.mkdir()
    manifest=source/'manifest.json';manifest.write_text(json.dumps(tiny_manifest(source)))
    bundle=tmp_path/'bundle';build_bundle(manifest,source,bundle)
    assert verify_bundle(bundle)['passed']
    code=bundle/'code/scripts/core_cfd_dataset.py'
    original=code.read_bytes();code.write_bytes(original+b'\n# altered\n')
    with pytest.raises(ValueError,match='artifact integrity'):
        verify_bundle(bundle)
    code.write_bytes(original)
    index=json.loads((bundle/'bundle.json').read_text());index['schema']='future.unknown'
    (bundle/'bundle.json').write_text(json.dumps(index))
    with pytest.raises(ValueError,match='unsupported bundle version'):
        verify_bundle(bundle)


def test_bundle_v2_requires_and_indexes_transitive_reader_dependencies(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    manifest = source / 'manifest.json'
    manifest.write_text(json.dumps(tiny_manifest(source)))
    bundle = tmp_path / 'bundle'

    build_bundle(manifest, source, bundle)

    index = json.loads((bundle / 'bundle.json').read_text())
    paths = {item['path'] for item in index['files']}
    assert index['schema'] == 'core.reader_bundle.v2'
    assert 'code/scripts/core_fsverity.py' in paths
    assert 'code/scripts/core_strict_json.py' in paths
    assert 'code/scripts/core_package.py' in paths
    assert 'code/scripts/core_code_manifest.py' in paths
    assert verify_bundle(bundle)['passed']


def _bundle_snapshot(root):
    snapshot = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot[relative + '/'] = None
        else:
            snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def test_verify_reader_smoke_does_not_mutate_published_bundle(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    manifest = source / 'manifest.json'
    manifest.write_text(json.dumps(tiny_manifest(source)))
    bundle = tmp_path / 'bundle'
    observed = {}
    run = core_package.subprocess.run

    def checked_run(command, **kwargs):
        output = Path(command[command.index('--output') + 1]).resolve()
        try:
            output.relative_to(bundle.resolve())
        except ValueError:
            pass
        else:
            raise AssertionError('reader smoke output was placed inside bundle')
        before = _bundle_snapshot(bundle)
        result = run(command, **kwargs)
        observed['tree_unchanged'] = before == _bundle_snapshot(bundle)
        observed['smoke_report_exists_during_check'] = output.is_file()
        return result

    monkeypatch.setattr(core_package.subprocess, 'run', checked_run)
    monkeypatch.setattr(sys, 'argv', [
        'core_package.py', '--manifest', str(manifest), '--data-root', str(source),
        '--destination', str(bundle), '--verify-reader',
    ])

    assert core_package.main() == 0

    assert observed == {
        'tree_unchanged': True,
        'smoke_report_exists_during_check': True,
    }
    assert not (bundle / 'reader-reproduction.json').exists()
    assert verify_bundle(bundle)['passed']


def test_bundle_verifier_rejects_unregistered_tree_entries(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    manifest = source / 'manifest.json'
    manifest.write_text(json.dumps(tiny_manifest(source)))
    bundle = tmp_path / 'bundle'
    build_bundle(manifest, source, bundle)
    (bundle / 'unregistered-smoke-output.json').write_text('{}')

    with pytest.raises(ValueError, match='unregistered or missing files'):
        verify_bundle(bundle)


def test_bundle_verifier_rejects_unregistered_runtime_code_omission(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    manifest = source / 'manifest.json'
    manifest.write_text(json.dumps(tiny_manifest(source)))
    bundle = tmp_path / 'bundle'
    build_bundle(manifest, source, bundle)
    index_path = bundle / 'bundle.json'
    index = json.loads(index_path.read_text())
    index['files'] = [item for item in index['files']
                      if item['path'] != 'code/scripts/core_package.py']
    index_path.write_text(json.dumps(index))

    with pytest.raises(ValueError, match='missing required artifact registrations'):
        verify_bundle(bundle)


def test_bundle_verifier_rejects_legacy_v1_schema(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    manifest = source / 'manifest.json'
    manifest.write_text(json.dumps(tiny_manifest(source)))
    bundle = tmp_path / 'bundle'
    build_bundle(manifest, source, bundle)
    index_path = bundle / 'bundle.json'
    index = json.loads(index_path.read_text())
    index['schema'] = 'core.reader_bundle.v1'
    index_path.write_text(json.dumps(index))

    with pytest.raises(ValueError, match='unsupported bundle version'):
        verify_bundle(bundle)


@pytest.mark.parametrize('missing_name', ['core_fsverity.py', 'core_strict_json.py'])
def test_bundle_v2_rejects_unregistered_transitive_reader_dependency(tmp_path, missing_name):
    source = tmp_path / 'source'
    source.mkdir()
    manifest = source / 'manifest.json'
    manifest.write_text(json.dumps(tiny_manifest(source)))
    bundle = tmp_path / 'bundle'
    build_bundle(manifest, source, bundle)
    index_path = bundle / 'bundle.json'
    index = json.loads(index_path.read_text())
    index['files'] = [
        item for item in index['files']
        if item['path'] != f'code/scripts/{missing_name}'
    ]
    index_path.write_text(json.dumps(index))

    with pytest.raises(ValueError, match='missing required artifact registrations'):
        verify_bundle(bundle)


def test_cfd_source_bundle_is_normalized_and_relocatable(tmp_path):
    from test_core_cfd_dataset import _trajectory, _prepared
    from scripts.core_dataset import sha256_file
    source=tmp_path/'source';source.mkdir()
    _trajectory(source/'trajectory.h5')
    (source/'prepared.json').write_text(json.dumps(_prepared('F4')))
    manifest=source/'manifest.json'
    manifest.write_text(json.dumps({'schema':'core.cfd.dataset.v1','cases':[
        {'case_id':'f4','family':'F4','split':'validation',
         'prepared':str(source/'prepared.json'),'hdf5':'trajectory.h5',
         'sha256':sha256_file(source/'trajectory.h5')}]}))
    bundle=tmp_path/'bundle';build_bundle(manifest,source,bundle)
    relocated=tmp_path/'relocated';bundle.rename(relocated)
    import shutil
    shutil.rmtree(source)
    assert verify_bundle(relocated)['passed']
    assert verify_dataset(relocated/'dataset.json',relocated)['passed']
    record=json.loads((relocated/'dataset.json').read_text())['cases'][0]
    assert record['provenance']['prepared']=='prepared.json'


def test_bundle_carries_hashed_checkpoint_without_source_path(tmp_path):
    from scripts.core_dataset import sha256_file
    import torch
    source=tmp_path/'source';source.mkdir()
    manifest=source/'manifest.json';manifest.write_text(json.dumps(tiny_manifest(source)))
    weights=source/'weights.pt'
    torch.save({'schema':'core.checkpoint.v1','model_kind':'mlp','hidden':8,
                'seed':17,'update':500},weights)
    registered=source/'checkpoints.json'
    registered.write_text(json.dumps({'checkpoints':[{'path':str(weights),
        'sha256':sha256_file(weights),'model_kind':'mlp','seed':17,'update':500}]}))
    bundle=tmp_path/'bundle'
    report=build_bundle(manifest,source,bundle,checkpoint_manifest=registered)
    assert report['checkpoint_count']==1 and report['full_core_release'] is False
    relocated = tmp_path / 'relocated'
    bundle.rename(relocated)
    record=json.loads((relocated/'checkpoints.json').read_text())['checkpoints'][0]
    assert record['path']=='models/checkpoint-000.pt'
    assert verify_bundle(relocated)['passed']
    (relocated/record['path']).write_bytes(b'corrupt weights')
    with pytest.raises(ValueError,match='artifact integrity'):
        verify_bundle(relocated)


def _refresh_bundle_artifact_index(bundle, relative):
    index_path = bundle / 'bundle.json'
    index = json.loads(index_path.read_text())
    target = bundle / relative
    for item in index['files']:
        if item['path'] == relative:
            item['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
            item['bytes'] = target.stat().st_size
            break
    else:
        raise AssertionError(relative)
    index_path.write_text(json.dumps(index))


def _checkpoint_fixture_bundle(tmp_path):
    import torch
    from scripts.core_dataset import sha256_file
    source = tmp_path / 'source'
    source.mkdir(parents=True)
    manifest = source / 'manifest.json'
    manifest.write_text(json.dumps(tiny_manifest(source)))
    checkpoint = source / 'weights.pt'
    torch.save({'schema': 'core.checkpoint.v1', 'model_kind': 'mlp', 'hidden': 8,
                'seed': 17, 'update': 500}, checkpoint)
    registration = source / 'checkpoints.json'
    registration.write_text(json.dumps({'checkpoints': [{
        'path': str(checkpoint), 'sha256': sha256_file(checkpoint),
        'model_kind': 'mlp', 'seed': 17, 'update': 500,
    }]}))
    bundle = tmp_path / 'bundle'
    build_bundle(manifest, source, bundle, checkpoint_manifest=registration)
    return bundle


def test_checkpoint_registry_requires_hash_and_content_bound_bytes(tmp_path):
    bundle = _checkpoint_fixture_bundle(tmp_path)
    registry_path = bundle / 'checkpoints.json'
    registry = json.loads(registry_path.read_text())
    registry['checkpoints'][0].pop('sha256')
    registry_path.write_text(json.dumps(registry))
    _refresh_bundle_artifact_index(bundle, 'checkpoints.json')
    with pytest.raises(ValueError, match='checkpoint registry hash'):
        verify_bundle(bundle)

    bundle = _checkpoint_fixture_bundle(tmp_path / 'bytes')
    registry_path = bundle / 'checkpoints.json'
    registry = json.loads(registry_path.read_text())
    registry['checkpoints'][0]['bytes'] += 1
    registry_path.write_text(json.dumps(registry))
    _refresh_bundle_artifact_index(bundle, 'checkpoints.json')
    with pytest.raises(ValueError, match='checkpoint registry bytes'):
        verify_bundle(bundle)


def test_checkpoint_registry_rejects_content_identity_drift(tmp_path):
    bundle = _checkpoint_fixture_bundle(tmp_path)
    registry_path = bundle / 'checkpoints.json'
    registry = json.loads(registry_path.read_text())
    registry['checkpoints'][0]['update'] += 1
    registry_path.write_text(json.dumps(registry))
    _refresh_bundle_artifact_index(bundle, 'checkpoints.json')
    with pytest.raises(ValueError, match='update disagrees with checkpoint content'):
        verify_bundle(bundle)


def test_verify_rejects_manifest_asset_not_registered_in_bundle_index(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    manifest = source / 'manifest.json'
    manifest.write_text(json.dumps(tiny_manifest(source)))
    bundle = tmp_path / 'bundle'
    build_bundle(manifest, source, bundle)
    index_path = bundle / 'bundle.json'
    index = json.loads(index_path.read_text())
    index['files'] = [item for item in index['files'] if item['path'] != 'data.h5']
    index_path.write_text(json.dumps(index))
    with pytest.raises(ValueError, match='not registered in bundle.json'):
        verify_bundle(bundle)


def test_bundle_reproduction_gate_checks_bundle_before_reader_entrypoint(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    manifest = source / 'manifest.json'
    manifest.write_text(json.dumps(tiny_manifest(source)))
    bundle = tmp_path / 'bundle'
    build_bundle(manifest, source, bundle)
    output = tmp_path / 'reader-reproduction.json'
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    command = [sys.executable, str(bundle / 'code/scripts/core_benchmark.py'),
               'reproduce', '--manifest', str(bundle / 'dataset.json'),
               '--data-root', str(bundle), '--output', str(output)]
    valid = subprocess.run(command, cwd=tmp_path, env=environment,
                           capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr
    assert json.loads(output.read_text())['passed'] is True

    with (bundle / 'data.h5').open('ab') as stream:
        stream.write(b'unregistered mutation')
    rejected = subprocess.run(command, cwd=tmp_path, env=environment,
                              capture_output=True, text=True)
    assert rejected.returncode != 0
    assert 'bundle artifact integrity failure' in rejected.stderr

    from scripts.core_benchmark import reproduce
    with pytest.raises(ValueError, match='bundle artifact integrity'):
        reproduce(bundle / 'dataset.json', bundle)


def test_moving_geometry_survives_source_removal_and_isolated_reader(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    from test_core_cfd_dataset import _trajectory, _f2_prepared
    from scripts.core_dataset import sha256_file
    from scripts.core_cfd_dataset import open_dataset
    source = tmp_path / 'source'
    source.mkdir()
    _trajectory(source / 'trajectory.h5')
    config = _f2_prepared(source, dynamic=True)
    manifest = source / 'dataset.json'
    manifest.write_text(json.dumps({'schema': 'core.cfd.dataset.v1', 'cases': [
        {'case_id': 'f2', 'family': 'F2', 'split': 'validation',
         'prepared_record': {'config': config}, 'hdf5': 'trajectory.h5',
         'sha256': sha256_file(source / 'trajectory.h5')}]}))
    with open_dataset(manifest, source) as data:
        geometry = data.known_inputs('f2').geometry_at(.75)
        expected = {'triangles': geometry.triangles.tolist(),
                    'wall_velocity': geometry.wall_velocity.tolist()}
    bundle = tmp_path / 'bundle'
    build_bundle(manifest, source, bundle)
    moved = tmp_path / 'relocated'
    bundle.rename(moved)
    shutil.rmtree(source)
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    code = (
        'import sys,json; from pathlib import Path; '
        'root=Path(sys.argv[1]); sys.path.insert(0,str(root/"code")); '
        'import numpy as np; '
        'from scripts.core_cfd_dataset import open_dataset; '
        'from scripts.core_contract import State; '
        'from scripts.core_physics import moving_wall_crossings; '
        'data=open_dataset(root/"dataset.json",root); '
        'known=data.known_inputs("f2"); g=known.geometry_at(.75); '
        'previous=State(.75,np.array([[.1,.1,.1]]),np.zeros((1,3)),[1],[0],[1.],[True]); '
        'following=State(.78,np.array([[.1,.1,.1]]),np.zeros((1,3)),[1],[0],[1.],[True]); '
        'audit=moving_wall_crossings(previous,following,known.geometry); '
        'print(json.dumps({"triangles":g.triangles.tolist(),'
        '"wall_velocity":g.wall_velocity.tolist(),'
        '"audit_status":audit["status"],'
        '"audit_schema":audit["schema"],'
        '"sweep_segments":audit["rotation_sweep_error"]["sweep_segment_count"],'
        '"sweep_samples":audit["rotation_sweep_error"]["sweep_sample_count"]})); data.close()')
    result = subprocess.run([sys.executable, '-I', '-c', code, str(moved)],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["triangles"] == expected["triangles"]
    assert observed["wall_velocity"] == expected["wall_velocity"]
    assert observed["audit_status"] == "checked_prescribed_moving_saved_chords"
    assert observed["audit_schema"] == "core.physics.moving_wall_saved_step.v1"
    assert observed["sweep_segments"] == 1
    assert observed["sweep_samples"] == 17


def test_f3_f4_reader_preflight_is_read_only_and_fails_mixed_schema_closed():
    lab = Path(__file__).resolve().parents[1]
    f3 = lab / "campaigns/core-v1/f3-dataset-v2.json"
    f4 = lab / "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1" / (
        "f4-tallwall120-formal-reader-manifest-v1.json")
    before = (f3.read_bytes(), f4.read_bytes())
    report = inspect_reader_manifests(
        [f3, f4], data_root=lab, expected_families=("F3", "F4"),
        expected_cases_per_family=32, require_formal=True)
    assert report["schema"] == "core.reader_manifest_preflight.v1"
    assert report["family_case_counts"] == {"F3": 32, "F4": 32}
    assert report["portable"] is True
    assert report["composable"] is False
    assert report["formal_release"] is False
    assert report["formal_eligible"] is False
    assert any("mixed core.dataset.v1/core.dataset.v2" in reason
               for reason in report["hold_reasons"])
    assert any("formal_release=true" in reason for reason in report["hold_reasons"])
    assert report["trajectory_files_opened"] is False
    assert (f3.read_bytes(), f4.read_bytes()) == before


def test_reader_preflight_accepts_same_schema_formal_fixture(tmp_path):
    first = tiny_manifest(tmp_path)
    second = json.loads(json.dumps(first))
    for payload, family in ((first, "F3"), (second, "F4")):
        payload["formal_release"] = True
        row = payload["cases"][0]
        row["family"] = family
        row["case_id"] = f"{family}-fixture"
        row["physical_case_id"] = f"{family}-physical"
        row["lineage_group_id"] = f"{family}-lineage"
    report = inspect_reader_manifests(
        [first, second], expected_families=("F3", "F4"),
        expected_cases_per_family=1, require_formal=True)
    assert report["portable"] is True
    assert report["composable"] is True
    assert report["formal_release"] is True
    assert report["formal_eligible"] is True


def _compact_formal_fixture(tmp_path, family, count=4):
    """Make a compact v2 reader fixture without touching trajectory data."""
    import copy
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tiny_manifest(tmp_path)
    source.update({"schema": "core.dataset.v2", "dataset_id": f"{family}-compact",
                   "formal_release": True})
    template = source["cases"][0]
    template["known_inputs_ref"] = {
        "geometry": {"path": "assets/geometry.npz", "sha256": "a" * 64,
                      "format": "npz", "version": "core.input_asset.v1"},
        "control": {"path": "assets/control.npz", "sha256": "b" * 64,
                     "format": "npz", "version": "core.input_asset.v1"},
        "physics": {"reference_density_kgm3": 1000.0},
        "numerics": {"dp_m": 0.01, "h_m": 0.016},
        "coordinate_frame": "test", "contract_version": "core.inputs.v1",
    }
    template.pop("known_inputs")
    cases = []
    for index in range(count):
        row = copy.deepcopy(template)
        row.update({"case_id": f"{family}-validation-{index}",
                    "physical_case_id": f"{family}-physical-{index}",
                    "lineage_group_id": f"{family}-lineage-{index}",
                    "family": family, "split": "validation",
                    "qualification_case": False})
        cases.append(row)
    source["cases"] = cases
    return source


def test_f3_f4_normalization_plan_is_read_only_and_names_third_t1_blocker():
    lab = Path(__file__).resolve().parents[1]
    f3 = lab / "campaigns/core-v1/f3-dataset-v2.json"
    f4 = lab / "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1" / (
        "f4-tallwall120-formal-reader-manifest-v1.json")
    before = (f3.read_bytes(), f4.read_bytes())
    plan = plan_reader_manifest_normalization(
        [f3, f4], data_root=lab, expected_families=("F3", "F4"))
    assert plan["schema"] == "core.reader_manifest_normalization_plan.v1"
    assert plan["target_schema"] == "core.dataset.v2"
    assert plan["source_schema_versions"] == ["core.dataset.v1", "core.dataset.v2"]
    assert plan["normalization_ready"] is False
    assert plan["formal_ready"] is False
    assert plan["formal_eligible"] is False
    codes = {item["code"] for item in plan["blockers"]}
    assert {"mixed_source_schema", "inline_inputs_require_compact_assets",
            "source_not_formal", "formal_validation_family_gate"} <= codes
    assert plan["formal_gate"]["observed_validation_case_counts"] == {"F3": 4, "F4": 4}
    assert plan["formal_gate"]["third_family_required"] is True
    assert plan["normalization_contract"]["case_field_mapping"]["known_inputs.geometry"] == (
        "known_inputs_ref.geometry")
    assert "known_inputs_sha256" in plan["normalization_contract"]["preserve_case_fields"]
    assert "centre" in plan["normalization_contract"]["control_asset_payload"]
    f4_source = next(item for item in plan["sources"]
                      if item["source_schema"] == "core.dataset.v1")
    assert f4_source["normalization_status"] == "pending_asset_materialization"
    assert any("contract hash" in item for item in f4_source["required_inputs"])
    assert plan["read_only"] is True
    assert plan["trajectory_files_opened"] is False
    assert plan["future_state_inputs"] is False
    assert plan["training_started"] is False
    assert plan["manifest_written"] is False
    assert plan["registry_written"] is False
    assert (f3.read_bytes(), f4.read_bytes()) == before


def test_normalization_plan_passes_synthetic_three_family_compact_gate(tmp_path):
    manifests = [_compact_formal_fixture(tmp_path / family, family)
                 for family in ("F3", "F4", "T1")]
    first = plan_reader_manifest_normalization(
        manifests, expected_families=("F3", "F4", "T1"))
    second = plan_reader_manifest_normalization(
        manifests, expected_families=("F3", "F4", "T1"))
    assert first == second
    assert first["source_schema_versions"] == ["core.dataset.v2"]
    assert first["normalization_ready"] is True
    assert first["formal_ready"] is True
    # A plan can pass metadata gates while deliberately refusing to claim a
    # formal qualification result or publish a normalized manifest.
    assert first["formal_eligible"] is True
    assert first["formal_preflight_passed"] is True
    assert first["qualification_claimed"] is False
    assert first["formal_gate"]["observed_validation_cases"] == 12
    assert first["formal_gate"]["observed_validation_families"] == 3
    assert first["formal_gate"]["third_family_required"] is False
    assert first["blockers"] == []
    assert all(item["normalization_status"] == "already_target_schema"
               for item in first["sources"])
    assert first["trajectory_files_opened"] is False


def test_persisted_f4_compact_manifest_is_portable_but_core_gate_stays_blocked():
    lab = Path(__file__).resolve().parents[1]
    f3 = lab / "campaigns/core-v1/f3-dataset-v2.json"
    f4 = lab / "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1" / (
        "f4-tallwall120-formal-reader-manifest-v2-compact.json")
    report = inspect_reader_manifests(
        [f3, f4], data_root=lab, expected_families=("F3", "F4"),
        expected_cases_per_family=32, require_formal=True)
    assert report["schema_versions"] == ["core.dataset.v2"]
    assert report["portable"] is True
    assert report["composable"] is True
    assert report["trajectory_files_opened"] is False
    assert report["formal_release"] is False
    plan = plan_reader_manifest_normalization(
        [f3, f4], data_root=lab, expected_families=("F3", "F4"))
    assert plan["normalization_ready"] is True
    assert plan["formal_ready"] is False
    assert {item["code"] for item in plan["blockers"]} >= {
        "source_not_formal", "formal_validation_case_gate", "formal_validation_family_gate",
    }
