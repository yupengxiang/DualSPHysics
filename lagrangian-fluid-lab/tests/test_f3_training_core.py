"""CPU manufactured fixtures only; no CFD data, run launcher or ledger writes."""
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
from dataclasses import replace

import numpy as np
import pytest
import torch

from scripts import f3_training_core as core
from scripts.f3_control import AccelerationControl
from scripts.f3_learning_inputs import SPEED


DATA_HASHES = {'manufactured-fixture-v1': hashlib.sha256(b'manufactured 12 particle fixture v1').hexdigest()}
CATALOGUE = tuple(core.Transition(case, frame, (0, 2, 4, 6, 8, 10) if frame == 1 else None)
                  for case in ('manufactured_A', 'manufactured_B') for frame in range(3))


def fixture_config(route):
    return core.TrainConfig(route, seed=17, max_steps=12, hidden=8, dtype='float64',
                            max_targets=4, validation_patience=5, validation_min_delta=.01)


def fixture_loader(transition):
    """RNG use deliberately exercises all owned CPU streams across processes."""
    n = 12
    i = np.arange(n, dtype=float)
    case = 1 if transition.case_id == 'manufactured_A' else 2
    # Particle IDs differ from stable row indices, and include a coincident pair.
    position = np.column_stack((-.2 + i * .03, .02 * np.sin(i), .05 + .002 * i))
    position[1] = position[0]
    noise = random.random() + np.random.random() + torch.rand((), dtype=torch.float64).item()
    position[:, 2] += transition.frame * .001 + noise * 1e-5
    velocity = np.column_stack((.01 * np.cos(i), i * .001, np.full(n, .003 * case)))
    displacement = (velocity + .0003 * (transition.frame + 1)) * .01
    values = np.zeros((11, 7))
    values[:, 0] = np.linspace(0., 1., len(values))
    values[:, 1:4] = [.1 * case, -.05, -9.81]
    return core.TransitionBatch(position, velocity, np.arange(n, dtype=np.int64) * 7 + 101,
                                displacement, transition.frame * .01, .01, .01, 1.,
                                AccelerationControl(values))


def advance(state, count):
    rows = []
    for _ in range(count):
        rows.append(core.step(state, fixture_loader))
        # Exercise a best snapshot plus failures/staleness across the checkpoint.
        if state.global_step in (2, 4, 6, 8):
            metric = {2: .6, 4: .5, 6: None, 8: .3}[state.global_step]
            core.record_validation(state, metric)
    return rows


def assert_nested_equal(left, right):
    if isinstance(left, torch.Tensor):
        assert isinstance(right, torch.Tensor)
        torch.testing.assert_close(left, right, rtol=0, atol=0)
    elif isinstance(left, np.ndarray):
        np.testing.assert_array_equal(left, right)
    elif isinstance(left, dict):
        assert left.keys() == right.keys()
        for key in left:
            assert_nested_equal(left[key], right[key])
    elif isinstance(left, (list, tuple)):
        assert type(left) is type(right) and len(left) == len(right)
        for a, b in zip(left, right):
            assert_nested_equal(a, b)
    else:
        assert left == right


def checkpoint_payload(reference):
    path = Path(reference['path'])
    manifest = json.loads(path.read_text())
    return torch.load(path.parent / manifest['payload_file'], weights_only=True, map_location='cpu')


def _resume_worker(arguments):
    """Invoked in a separate interpreter, not a fork with inherited state."""
    request = json.loads(Path(arguments[0]).read_text())
    state = core.load_checkpoint(request['checkpoint'], expected_sha256=request['sha256'],
                                 config=replace(fixture_config(request['route']), dtype=request['dtype']),
                                 transitions=CATALOGUE,
                                 data_hashes=DATA_HASHES, device='cpu', cuda_devices=())
    rows = advance(state, 5)
    reference = core.save_checkpoint(state, request['result_checkpoint'])
    Path(request['result_json']).write_text(json.dumps(dict(pid=os.getpid(), rows=rows, reference=reference)))


@pytest.mark.parametrize('route', ('particle_mlp', 'local_interaction'))
@pytest.mark.parametrize('dtype', ('float32', 'float64'))
def test_independent_process_exact_resume_and_attempt_directory_rename(tmp_path, route, dtype):
    config = replace(fixture_config(route), dtype=dtype)
    state = core.TrainState.create(config, CATALOGUE, DATA_HASHES)
    first = advance(state, 4)
    assert len(first) == 4
    partial = tmp_path / 'attempt.partial'
    reference = core.save_checkpoint(state, partial / 'checkpoint.json')
    complete = tmp_path / 'attempt.complete'
    partial.rename(complete)
    checkpoint = complete / 'checkpoint.json'
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == reference['sha256']
    expected_rows = advance(state, 5)
    # Crosses a shuffled epoch boundary, with both explicit and sampled targets.
    assert expected_rows[-1]['epoch'] == 1
    assert all(row['sampled_particle_ids'] != row['target_indices'] for row in expected_rows)
    expected_reference = core.save_checkpoint(state, tmp_path / 'continuous.json')
    request = dict(checkpoint=str(checkpoint), sha256=reference['sha256'], route=route, dtype=dtype,
                   result_checkpoint=str(tmp_path / 'child-checkpoint.json'),
                   result_json=str(tmp_path / 'child-result.json'))
    request_path = tmp_path / 'request.json'
    request_path.write_text(json.dumps(request))
    worker = 'import runpy,sys; d=runpy.run_path(sys.argv[1]); d["_resume_worker"](sys.argv[2:])'
    environment = dict(os.environ, CUDA_VISIBLE_DEVICES='', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    child = subprocess.run([sys.executable, '-c', worker, str(Path(__file__).resolve()), str(request_path)],
                            cwd=core.LAB, env=environment, capture_output=True, text=True, timeout=60)
    assert child.returncode == 0, child.stdout + child.stderr
    result = json.loads(Path(request['result_json']).read_text())
    assert result['pid'] != os.getpid()
    assert result['rows'] == expected_rows  # Includes exact losses, not a tolerance.
    continuous = checkpoint_payload(expected_reference)
    resumed = checkpoint_payload(result['reference'])
    assert_nested_equal(continuous, resumed)  # Model, every AdamW tensor, RNGs, best/early stop.
    assert continuous['optimizer']['state']
    assert continuous['progress']['best_metric'] == .3
    assert continuous['progress']['validation_count'] == 4


def test_current_features_and_complete_neighbours_exclude_labels(monkeypatch):
    cfg = replace(fixture_config('local_interaction'), shuffle=False)
    captures = []
    real_summary = core.exact_local_summary

    def summary(position, velocity, ids, **kwargs):
        assert len(position) == len(velocity) == len(ids) == 12
        return real_summary(position, velocity, ids, **kwargs)

    monkeypatch.setattr(core, 'exact_local_summary', summary)
    states = [core.TrainState.create(cfg, CATALOGUE, DATA_HASHES) for _ in range(2)]
    for state in states:
        state.model.register_forward_pre_hook(
            lambda model, args: captures.append(tuple(a.detach().clone() for a in args)))
    result_a = core.step(states[0], fixture_loader)

    def altered_label(transition):
        batch = fixture_loader(transition)
        return replace(batch, target_displacement=batch.target_displacement + .01)

    result_b = core.step(states[1], altered_label)
    assert captures[0][0].shape == (4, 48) and captures[0][1].shape == (4, 8)
    assert_nested_equal(captures[0], captures[1])
    assert result_a['sampled_particle_ids'] == result_b['sampled_particle_ids']
    assert result_a['loss'] != result_b['loss']


@pytest.mark.parametrize('route', ('particle_mlp', 'local_interaction'))
def test_raw_direct_displacement_target_without_clipping(route):
    cfg = replace(fixture_config(route), shuffle=False, weight_decay=0., max_targets=None)
    state = core.TrainState.create(cfg, CATALOGUE, DATA_HASHES)
    raw = torch.tensor([12., -.7, .2], dtype=torch.float64)
    with torch.no_grad():
        for parameter in state.model.parameters():
            parameter.zero_()
        state.model.net[-1].bias.copy_(raw)

    def exact_label(transition):
        batch = fixture_loader(transition)
        # dp and input velocity are deliberately unrelated to this target.
        return replace(batch, dp_m=.02, target_displacement=
                       np.broadcast_to(raw.numpy() * SPEED * batch.interval_s, (12, 3)).copy())

    result = core.step(state, exact_label)
    assert result['loss'] < 1e-28
    # AdamW can amplify a roundoff-sized residual by its epsilon denominator.
    # The near-zero loss above proves the raw target, including a value > 8.
    torch.testing.assert_close(state.model.net[-1].bias, raw, rtol=0, atol=1e-9)


def test_rng_ownership_preserves_callers_and_cpu_never_queries_cuda(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError('CPU core queried a CUDA RNG/device')

    monkeypatch.setattr(torch.cuda, 'get_rng_state', forbidden)
    monkeypatch.setattr(torch.cuda, 'get_rng_state_all', forbidden)
    monkeypatch.setattr(torch.cuda, 'set_rng_state', forbidden)
    monkeypatch.setattr(torch.cuda, 'manual_seed_all', forbidden)
    outside = (random.getstate(), np.random.get_state(), torch.get_rng_state())
    state = core.TrainState.create(fixture_config('particle_mlp'), CATALOGUE, DATA_HASHES)
    core.step(state, fixture_loader)
    ref = core.save_checkpoint(state, tmp_path / 'checkpoint.json')
    core.load_checkpoint(ref['path'], expected_sha256=ref['sha256'], config=state.config,
                          transitions=CATALOGUE, data_hashes=DATA_HASHES)
    assert_nested_equal(outside, (random.getstate(), np.random.get_state(), torch.get_rng_state()))


@pytest.mark.parametrize('changed', ('config', 'data', 'catalogue', 'code', 'semantics'))
def test_checkpoint_rejects_binding_mismatch(tmp_path, monkeypatch, changed):
    cfg = fixture_config('particle_mlp')
    state = core.TrainState.create(cfg, CATALOGUE, DATA_HASHES)
    ref = core.save_checkpoint(state, tmp_path / 'checkpoint.json')
    args = dict(expected_sha256=ref['sha256'], config=cfg, transitions=CATALOGUE, data_hashes=DATA_HASHES)
    if changed == 'config':
        args['config'] = replace(cfg, learning_rate=.002)
    elif changed == 'data':
        args['data_hashes'] = {'manufactured-fixture-v1': 'f' * 64}
    elif changed == 'catalogue':
        args['transitions'] = CATALOGUE[::-1]
    elif changed == 'code':
        existing = core.code_hashes()
        monkeypatch.setattr(core, 'code_hashes', lambda: {**existing, 'scripts/f3_training_core.py': 'f' * 64})
    else:
        monkeypatch.setitem(core.SEMANTICS, 'output_and_target', 'wrong velocity target')
    with pytest.raises(ValueError, match='mismatch'):
        core.load_checkpoint(ref['path'], **args)


@pytest.mark.parametrize('corruption', ('manifest', 'payload'))
def test_checkpoint_rejects_byte_corruption(tmp_path, corruption):
    state = core.TrainState.create(fixture_config('particle_mlp'), CATALOGUE, DATA_HASHES)
    ref = core.save_checkpoint(state, tmp_path / 'checkpoint.json')
    path = Path(ref['path'])
    if corruption == 'payload':
        path = path.parent / json.loads(path.read_text())['payload_file']
    with path.open('ab') as stream:
        stream.write(b'corruption')
    with pytest.raises(ValueError, match='SHA256 mismatch'):
        core.load_checkpoint(ref['path'], expected_sha256=ref['sha256'], config=state.config,
                              transitions=CATALOGUE, data_hashes=DATA_HASHES)


def test_interrupted_manifest_publish_preserves_prior_checkpoint(tmp_path, monkeypatch):
    state = core.TrainState.create(fixture_config('particle_mlp'), CATALOGUE, DATA_HASHES)
    core.step(state, fixture_loader)
    ref = core.save_checkpoint(state, tmp_path / 'checkpoint.json')
    original = Path(ref['path']).read_bytes()
    core.step(state, fixture_loader)
    real_replace = core.os.replace

    def interrupted(source, destination):
        if Path(destination) == Path(ref['path']):
            raise OSError('manufactured manifest publication interruption')
        return real_replace(source, destination)

    monkeypatch.setattr(core.os, 'replace', interrupted)
    with pytest.raises(OSError, match='publication interruption'):
        core.save_checkpoint(state, ref['path'])
    assert Path(ref['path']).read_bytes() == original
    restored = core.load_checkpoint(ref['path'], expected_sha256=ref['sha256'], config=state.config,
                                    transitions=CATALOGUE, data_hashes=DATA_HASHES)
    assert restored.global_step == 1


@pytest.mark.parametrize('bad', ('nan_state', 'nan_label', 'duplicate_ids', 'missing_rows', 'target_row', 'control_end'))
def test_invalid_batch_fails_without_a_publishable_checkpoint(tmp_path, bad):
    catalogue = (core.Transition('manufactured_A', 0, (12,) if bad == 'target_row' else None),)
    state = core.TrainState.create(fixture_config('particle_mlp'), catalogue, DATA_HASHES)

    def broken(transition):
        batch = fixture_loader(transition)
        if bad == 'nan_state':
            batch.position[0, 0] = np.nan
        elif bad == 'nan_label':
            batch.target_displacement[0, 0] = np.inf
        elif bad == 'duplicate_ids':
            batch.particle_id[0] = batch.particle_id[1]
        elif bad == 'missing_rows':
            batch = replace(batch, velocity=batch.velocity[:-1])
        elif bad == 'control_end':
            batch = replace(batch, time_s=.999)
        return batch

    with pytest.raises(ValueError):
        core.step(state, broken)
    assert state.global_step == 0 and state.failed_reason is not None
    with pytest.raises(ValueError, match='state failed'):
        core.save_checkpoint(state, tmp_path / 'must-not-exist.json')
    assert not (tmp_path / 'must-not-exist.json').exists()


def test_bounds_best_state_and_early_stop_survive_checkpoint(tmp_path):
    cfg = replace(fixture_config('particle_mlp'), max_steps=1, validation_patience=2)
    state = core.TrainState.create(cfg, CATALOGUE, DATA_HASHES)
    core.step(state, fixture_loader)
    assert core.record_validation(state, .5)
    assert not core.record_validation(state, float('nan'))
    ref = core.save_checkpoint(state, tmp_path / 'checkpoint.json')
    restored = core.load_checkpoint(ref['path'], expected_sha256=ref['sha256'], config=cfg,
                                    transitions=CATALOGUE, data_hashes=DATA_HASHES)
    assert restored.stale_validations == 1 and restored.best_metric == .5
    assert not core.record_validation(restored, None)
    assert restored.early_stop
    with pytest.raises(ValueError, match='step bound'):
        core.step(restored, fixture_loader)
    with pytest.raises(ValueError, match='step bound'):
        core.step(state, fixture_loader)
    assert_nested_equal(state.best_model, restored.best_model)


def test_rejects_implicit_gpu_and_invalid_catalogue():
    cfg = fixture_config('particle_mlp')
    for device, selected in (('cuda', (0,)), ('cuda:0', ()), ('cpu', (0,))):
        with pytest.raises(ValueError, match='explicit|CPU'):
            core.TrainState.create(cfg, CATALOGUE, DATA_HASHES, device=device, cuda_devices=selected)
    with pytest.raises(ValueError, match='duplicate'):
        core.TrainState.create(cfg, (CATALOGUE[0], CATALOGUE[0]), DATA_HASHES)
    with pytest.raises(ValueError, match='unique'):
        core.Transition('manufactured_A', 0, (1, 1))
    with pytest.raises(ValueError, match='integer'):
        core.Transition('manufactured_A', 0, (False,))
