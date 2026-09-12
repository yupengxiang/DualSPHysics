"""Bounded F3 training mechanics, without data qualification or a run launcher.

This module does not unlock production training. An outer, qualified loader
declares a train-only transition catalogue and binds its data to ``data_hashes``.
Each load supplies the complete current particle axis, rollout-consistent input
velocity, prescribed control and a separate displacement label. No future label
is used in the 48 input features or the eight exact-ID neighbour features.

Raw model output is direct displacement / (SPEED * caller interval), supervised
by mean squared component error. This prospective F3 convention is distinct
from the historical velocity target, bounded prediction and trapezoidal rollout.
There is no AMP, accumulation, scheduler, output/gradient clipping or filtering.

States are owned by one caller; concurrent calls on a state are unsupported.
Only the selected device's RNG is touched. Checkpoints are immutable hashed
payloads, published by an atomic manifest replacement. The caller must retain
the manifest hash outside the checkpoint to authenticate a later load.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import platform
import random
import re
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Mapping

import numpy as np
import scipy
import torch

from experiments.r3_g4_baselines import model_for
from scripts.f3_control import AccelerationControl
from scripts.f3_learning_inputs import FEATURE_NAMES, SPEED, features
from scripts.f3_local_neighbors import exact_local_summary

LAB = Path(__file__).resolve().parents[1]
SCHEMA = 'f3.training.core_checkpoint.v1'
SEMANTICS = {
    'schema': 'f3.training.core_semantics.v1',
    'production_qualified': False,
    'base_feature_names': list(FEATURE_NAMES),
    'base_width': 48,
    'local_width': 8,
    'local': 'complete_current_state_exact_id_self_exclusion_distance_then_id_v2',
    'output_and_target': 'direct_displacement_m / (SPEED_m_per_s * interval_s)',
    'speed_m_per_s': SPEED,
    'loss': 'mean squared error over sampled particles and three components',
    'target_indices': 'stable zero-based rows of the complete particle axis; not particle IDs',
    'input_velocity': 'native initial velocity; then previous reference displacement / its interval',
    'reference_alignment': 'outer qualified loader; labels excluded from current-state features',
    'sampling': 'one declared transition per update; state-owned PCG64; no replacement',
    'amp': False, 'gradient_accumulation_steps': 1, 'scheduler': None,
    'gradient_clipping': None, 'output_clipping': None, 'particle_filtering': False,
    'cpu_thread_policy': 'F3_TORCH_NUM_THREADS environment variable, default 1',
}


def _configure_cpu_threads(device):
    """Make CPU checkpoint runtime stable across independent interpreters.

    OMP/OpenBLAS settings are often applied before importing torch, so two
    processes can otherwise report different ``torch.get_num_threads()``
    values even with the same training config.  The explicit F3 variable is
    the checkpoint contract; its default is the bounded single-thread policy
    used by the lab.  Inter-op threads remain part of the runtime fingerprint.
    """
    if device.type != 'cpu':
        return
    raw = os.environ.get('F3_TORCH_NUM_THREADS', '1')
    try:
        threads = int(raw)
    except (TypeError, ValueError) as error:
        raise ValueError('F3_TORCH_NUM_THREADS must be a positive integer') from error
    if threads < 1:
        raise ValueError('F3_TORCH_NUM_THREADS must be a positive integer')
    if torch.get_num_threads() != threads:
        torch.set_num_threads(threads)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _hashes(values, name):
    if not isinstance(values, Mapping) or not values:
        raise ValueError(f'{name} must be a nonempty mapping of names to SHA256')
    result = dict(values)
    if any(not isinstance(k, str) or not k or not isinstance(v, str)
           or not re.fullmatch('[0-9a-f]{64}', v) for k, v in result.items()):
        raise ValueError(f'invalid {name}')
    return result


def code_hashes():
    """Read actual implementation files; no provisional module hash is frozen."""
    paths = ('scripts/f3_training_core.py', 'scripts/f3_learning_inputs.py',
             'scripts/f3_local_neighbors.py', 'scripts/f3_control.py',
             'experiments/r3_g4_baselines.py')
    return {name: _sha(LAB / name) for name in paths}


def _integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')


@dataclass(frozen=True)
class Transition:
    """One train transition; optional targets are stable rows, never particle IDs."""
    case_id: str
    frame: int
    target_indices: tuple[int, ...] | None = None

    def __post_init__(self):
        if not isinstance(self.case_id, str) or not self.case_id:
            raise ValueError('nonempty case_id required')
        _integer(self.frame, 'frame')
        if self.target_indices is not None:
            indices = tuple(self.target_indices)
            if not indices or len(set(indices)) != len(indices):
                raise ValueError('target_indices must be nonempty unique stable rows')
            for index in indices:
                _integer(index, 'target row')
            object.__setattr__(self, 'target_indices', indices)


@dataclass(frozen=True)
class TransitionBatch:
    """Full current axis plus separate full-axis displacement supervision.

    Arrays may be NumPy arrays or Torch tensors. The outer loader guarantees
    stable particle order/identity across transitions and train-only membership.
    Current velocity must follow SEMANTICS, not next native solver velocity.
    """
    position: np.ndarray | torch.Tensor
    velocity: np.ndarray | torch.Tensor
    particle_id: np.ndarray | torch.Tensor
    target_displacement: np.ndarray | torch.Tensor
    time_s: float
    interval_s: float
    dp_m: float
    amplitude: float
    control: AccelerationControl


@dataclass(frozen=True)
class TrainConfig:
    route: str
    seed: int
    max_steps: int
    hidden: int = 64
    learning_rate: float = 1e-3
    weight_decay: float = 1e-2
    max_targets: int | None = 256
    shuffle: bool = True
    dtype: str = 'float32'
    adam_betas: tuple[float, float] = (.9, .999)
    adam_eps: float = 1e-8
    validation_patience: int | None = None
    validation_min_delta: float = 0.

    def __post_init__(self):
        if self.route not in ('particle_mlp', 'local_interaction'):
            raise ValueError('only the two F3 routes are supported')
        for name in ('seed', 'max_steps', 'hidden'):
            _integer(getattr(self, name), name, 0 if name == 'seed' else 1)
        if self.seed >= 2**32:
            raise ValueError('seed must fit NumPy legacy RNG seed range')
        for name in ('max_targets', 'validation_patience'):
            if getattr(self, name) is not None:
                _integer(getattr(self, name), name, 1)
        if not isinstance(self.shuffle, bool) or self.dtype not in ('float32', 'float64'):
            raise ValueError('invalid shuffle or dtype')
        for name in ('learning_rate', 'weight_decay', 'adam_eps', 'validation_min_delta'):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0 or (name in ('learning_rate', 'adam_eps') and value == 0):
                raise ValueError(f'invalid {name}')
        betas = tuple(self.adam_betas)
        if len(betas) != 2 or any(not math.isfinite(v) or not 0 <= v < 1 for v in betas):
            raise ValueError('invalid AdamW betas')
        object.__setattr__(self, 'adam_betas', betas)


def _catalogue(transitions):
    result = tuple(transitions)
    if not result or any(not isinstance(item, Transition) for item in result):
        raise ValueError('nonempty declared Transition catalogue required')
    if len({(item.case_id, item.frame) for item in result}) != len(result):
        raise ValueError('duplicate case/frame in transition catalogue')
    return result


def _device(device, cuda_devices):
    device = torch.device(device)
    selected = tuple(cuda_devices)
    if device.type == 'cpu':
        if selected or device.index is not None:
            raise ValueError('CPU state requires an empty CUDA device list')
    elif device.type == 'cuda':
        if device.index is None or selected != (device.index,):
            raise ValueError('explicit cuda:index and exactly that selected RNG device required')
        if not torch.are_deterministic_algorithms_enabled():
            raise ValueError('CUDA exact recovery requires deterministic algorithms')
        if os.environ.get('CUBLAS_WORKSPACE_CONFIG') not in (':4096:8', ':16:8'):
            raise ValueError('CUDA deterministic CUBLAS config must be set before initialization')
    else:
        raise ValueError('only CPU or one explicitly selected CUDA device supported')
    return device, selected


def _runtime(device, cuda_devices):
    result = dict(python=platform.python_version(), torch=str(torch.__version__),
                  numpy=np.__version__, scipy=scipy.__version__, machine=platform.machine(),
                  device=str(device), cuda_devices=list(cuda_devices),
                  num_threads=torch.get_num_threads(), interop_threads=torch.get_num_interop_threads(),
                  deterministic_algorithms=torch.are_deterministic_algorithms_enabled(),
                  deterministic_warn_only=torch.is_deterministic_algorithms_warn_only_enabled(),
                  matmul_precision=torch.get_float32_matmul_precision())
    if cuda_devices:
        props = torch.cuda.get_device_properties(device)
        result['cuda'] = dict(version=torch.version.cuda, name=props.name,
                              uuid=str(getattr(props, 'uuid', 'unavailable')),
                              capability=[props.major, props.minor],
                              cublas_workspace=os.environ['CUBLAS_WORKSPACE_CONFIG'],
                              cudnn_deterministic=torch.backends.cudnn.deterministic,
                              cudnn_benchmark=torch.backends.cudnn.benchmark,
                              matmul_allow_tf32=torch.backends.cuda.matmul.allow_tf32,
                              cudnn_allow_tf32=torch.backends.cudnn.allow_tf32)
    return result


@dataclass
class TrainState:
    config: TrainConfig
    transitions: tuple[Transition, ...]
    data_hashes: dict[str, str]
    code_hashes: dict[str, str]
    device: torch.device
    cuda_devices: tuple[int, ...]
    runtime: dict
    rng: np.random.Generator
    python_rng: tuple
    numpy_legacy_rng: tuple
    torch_cpu_rng: torch.Tensor
    cuda_rng: dict[int, torch.Tensor]
    model: torch.nn.Module | None = None
    optimizer: torch.optim.Optimizer | None = None
    order: list[int] = field(default_factory=list)
    cursor: int = 0
    global_step: int = 0
    epoch: int = 0
    best_metric: float | None = None
    best_model: dict | None = None
    best_step: int | None = None
    validation_count: int = 0
    stale_validations: int = 0
    early_stop: bool = False
    failed_reason: str | None = None
    # A recorded fingerprint catches external optimizer/config mutation.
    optimizer_groups: list[dict] = field(default_factory=list)

    @classmethod
    def create(cls, config: TrainConfig, transitions, data_hashes, *, device='cpu', cuda_devices=()):
        if not isinstance(config, TrainConfig):
            raise ValueError('TrainConfig required')
        device, selected = _device(device, cuda_devices)
        _configure_cpu_threads(device)
        state = cls(config, _catalogue(transitions), _hashes(data_hashes, 'data_hashes'),
                    code_hashes(), device, selected, _runtime(device, selected),
                    np.random.default_rng(config.seed), random.Random(config.seed).getstate(),
                    np.random.RandomState(config.seed).get_state(),
                    torch.Generator(device='cpu').manual_seed(config.seed).get_state(),
                    {i: torch.Generator(device=f'cuda:{i}').manual_seed(config.seed).get_state()
                     for i in selected})
        with _rng_scope(state):
            # Construct on CPU so initialization consumes only the owned CPU RNG.
            state.model = model_for(config.route, inputs=48, hidden=config.hidden).to(
                device=device, dtype=getattr(torch, config.dtype))
            state.model.train()
            state.optimizer = torch.optim.AdamW(
                state.model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay,
                betas=config.adam_betas, eps=config.adam_eps, foreach=False, fused=False)
        state.optimizer_groups = _cpu_copy(state.optimizer.state_dict()['param_groups'])
        state.order = list(range(len(state.transitions)))
        if config.shuffle:
            state.rng.shuffle(state.order)
        return state


@contextmanager
def _rng_scope(state):
    """Use owned RNG streams while preserving unrelated caller global streams."""
    outside = (random.getstate(), np.random.get_state(), torch.get_rng_state(),
               {i: torch.cuda.get_rng_state(i) for i in state.cuda_devices})
    try:
        random.setstate(state.python_rng)
        np.random.set_state(state.numpy_legacy_rng)
        torch.set_rng_state(state.torch_cpu_rng)
        for i, rng in state.cuda_rng.items():
            torch.cuda.set_rng_state(rng, i)
        try:
            yield
        finally:
            state.python_rng = random.getstate()
            state.numpy_legacy_rng = np.random.get_state()
            state.torch_cpu_rng = torch.get_rng_state()
            state.cuda_rng = {i: torch.cuda.get_rng_state(i) for i in state.cuda_devices}
    finally:
        random.setstate(outside[0])
        np.random.set_state(outside[1])
        torch.set_rng_state(outside[2])
        for i, rng in outside[3].items():
            torch.cuda.set_rng_state(rng, i)


def _cpu_copy(value):
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().clone()
    if isinstance(value, dict):
        return {k: _cpu_copy(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return type(value)(_cpu_copy(v) for v in value)
    return copy.deepcopy(value)


def _finite(value):
    if isinstance(value, torch.Tensor):
        return bool(torch.isfinite(value).all())
    if isinstance(value, dict):
        return all(_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(_finite(v) for v in value)
    return not isinstance(value, float) or math.isfinite(value)


def _live(state):
    if state.failed_reason is not None:
        raise ValueError(f'state failed; restore last committed checkpoint: {state.failed_reason}')
    if state.runtime != _runtime(state.device, state.cuda_devices):
        raise ValueError('runtime changed; exact recovery contract no longer holds')
    if state.optimizer.state_dict()['param_groups'] != state.optimizer_groups:
        raise ValueError('optimizer configuration changed outside the effective config')


def _batch_tensors(state, batch):
    if not isinstance(batch, TransitionBatch) or not isinstance(batch.control, AccelerationControl):
        raise ValueError('loader must return TransitionBatch with declared AccelerationControl')
    dtype = getattr(torch, state.config.dtype)
    p, v, target = (torch.as_tensor(a, dtype=dtype, device=state.device).detach()
                    for a in (batch.position, batch.velocity, batch.target_displacement))
    if p.ndim != 2 or p.shape[1:] != (3,) or len(p) == 0 or v.shape != p.shape or target.shape != p.shape:
        raise ValueError('loader must supply the complete matching nonempty [N,3] axis')
    ids = batch.particle_id.detach().cpu().numpy() if isinstance(batch.particle_id, torch.Tensor) else np.asarray(batch.particle_id)
    if ids.shape != (len(p),) or ids.dtype.kind not in 'iu' or len(np.unique(ids)) != len(p):
        raise ValueError('complete axis needs unique integer particle IDs')
    if not all(_finite(a) for a in (p, v, target)):
        raise ValueError('nonfinite current state or displacement label')
    if not all(math.isfinite(t) for t in (batch.time_s, batch.interval_s)) or batch.time_s < 0 or batch.interval_s <= 0:
        raise ValueError('finite nonnegative time and positive interval required')
    if batch.time_s < batch.control.values[0, 0] or batch.time_s + batch.interval_s > batch.control.values[-1, 0] + 1e-12:
        raise ValueError('transition exceeds real prescribed control coverage')
    return p, v, ids, target


def step(state: TrainState, loader: Callable[[Transition], TransitionBatch]):
    """Commit one AdamW update, returning exact selected rows and particle IDs.

    An exception makes this in-memory state terminal: no checkpoint can be
    published from a partially executed update. Restore a prior committed one.
    No qualification, CFD, rollout, validation or resource accounting runs here.
    """
    _live(state)
    if state.early_stop or state.global_step >= state.config.max_steps:
        raise ValueError('early stop or declared maximum step bound reached')
    try:
        with _rng_scope(state), torch.enable_grad():
            if state.cursor == len(state.order):
                state.epoch += 1
                state.cursor = 0
                state.order = list(range(len(state.transitions)))
                if state.config.shuffle:
                    state.rng.shuffle(state.order)
            transition = state.transitions[state.order[state.cursor]]
            batch = loader(transition)
            p, v, ids, displacement = _batch_tensors(state, batch)
            candidates = np.arange(len(p), dtype=np.int64) if transition.target_indices is None else np.asarray(transition.target_indices, dtype=np.int64)
            if candidates.max() >= len(p):
                raise ValueError('declared target row is outside the complete particle axis')
            count = len(candidates) if state.config.max_targets is None else min(len(candidates), state.config.max_targets)
            selected = candidates if count == len(candidates) else state.rng.choice(candidates, size=count, replace=False)
            row = torch.as_tensor(selected, dtype=torch.long, device=state.device)
            # Full current context is retained for the exact-ID spatial index.
            base = features(p[row], v[row], time_s=batch.time_s, interval_s=batch.interval_s,
                            dp_m=batch.dp_m, amplitude=batch.amplitude, control=batch.control)
            local = None
            if state.config.route == 'local_interaction':
                local = exact_local_summary(p, v, ids, dp_m=batch.dp_m, interval_s=batch.interval_s)[row]
            state.model.train()
            state.optimizer.zero_grad(set_to_none=True)
            raw = state.model(base, local)
            target = displacement[row] / (SPEED * batch.interval_s)
            if raw.shape != target.shape or not _finite(raw) or not _finite(target):
                raise ValueError('invalid raw prediction or normalized target')
            loss = (raw - target).square().mean()
            if not _finite(loss):
                raise ValueError('nonfinite training loss')
            loss.backward()
            if any(p.grad is None or not _finite(p.grad) for p in state.model.parameters()):
                raise ValueError('missing or nonfinite gradients')
            state.optimizer.step()
            if not _finite(state.model.state_dict()) or not _finite(state.optimizer.state_dict()):
                raise ValueError('nonfinite parameters or AdamW state')
            state.optimizer.zero_grad(set_to_none=True)
            state.cursor += 1
            state.global_step += 1
            return dict(case_id=transition.case_id, frame=transition.frame,
                        target_indices=selected.tolist(), sampled_particle_ids=[int(v) for v in ids[selected]],
                        particle_count=len(p), epoch=state.epoch, global_step=state.global_step,
                        loss=float(loss.detach().cpu()))
    except BaseException as error:
        state.failed_reason = f'{type(error).__name__}: {error}'
        raise


def record_validation(state: TrainState, metric: float | None):
    """Record an externally computed metric; failed/nonfinite validation is stale.

    The caller must score every required case, including rollout failures. This
    helper never runs validation or silently removes cases from an aggregate.
    """
    _live(state)
    if state.early_stop:
        raise ValueError('validation after early stop is not supported')
    good = metric is not None and math.isfinite(metric)
    state.validation_count += 1
    improved = good and (state.best_metric is None or metric < state.best_metric - state.config.validation_min_delta)
    if improved:
        state.best_metric = float(metric)
        state.best_model = _cpu_copy(state.model.state_dict())
        state.best_step = state.global_step
        state.stale_validations = 0
    else:
        state.stale_validations += 1
    patience = state.config.validation_patience
    state.early_stop = patience is not None and state.stale_validations >= patience
    return bool(improved)


def _bindings(state):
    return dict(semantics=copy.deepcopy(SEMANTICS), config=asdict(state.config),
                transitions=[asdict(t) for t in state.transitions], data_hashes=state.data_hashes,
                code_hashes=state.code_hashes, runtime=state.runtime)


def _validate_progress(state):
    n = len(state.transitions)
    if not isinstance(state.order, list):
        raise ValueError('checkpoint transition order must be a list')
    for index in state.order:
        _integer(index, 'transition order index')
    if sorted(state.order) != list(range(n)):
        raise ValueError('checkpoint transition order is not a permutation')
    for name in ('epoch', 'cursor', 'global_step', 'validation_count', 'stale_validations'):
        _integer(getattr(state, name), name)
    if not 0 <= state.cursor <= n or state.global_step != state.epoch * n + state.cursor or state.global_step > state.config.max_steps:
        raise ValueError('inconsistent checkpoint transition cursor/epoch/step')
    if state.stale_validations > state.validation_count or not isinstance(state.early_stop, bool):
        raise ValueError('inconsistent validation state')
    expected_stop = state.config.validation_patience is not None and state.stale_validations >= state.config.validation_patience
    if state.early_stop != expected_stop:
        raise ValueError('inconsistent early-stop state')
    if state.best_metric is None:
        if state.best_model is not None or state.best_step is not None:
            raise ValueError('best model exists without a finite metric')
    elif not math.isfinite(state.best_metric) or state.best_model is None or state.best_step is None or not 0 <= state.best_step <= state.global_step:
        raise ValueError('invalid best metric/model/step')
    if not _finite(state.model.state_dict()) or not _finite(state.optimizer.state_dict()) or not _finite(state.best_model):
        raise ValueError('nonfinite checkpoint tensors')


def _payload(state):
    legacy = state.numpy_legacy_rng
    return dict(schema=SCHEMA, bindings=_bindings(state),
                model=_cpu_copy(state.model.state_dict()), model_training=state.model.training,
                optimizer=_cpu_copy(state.optimizer.state_dict()),
                rng=dict(python=state.python_rng,
                         numpy_generator=copy.deepcopy(state.rng.bit_generator.state),
                         numpy_legacy=[legacy[0], legacy[1].tolist(), *legacy[2:]],
                         torch_cpu=state.torch_cpu_rng.clone(), cuda=_cpu_copy(state.cuda_rng)),
                progress={name: _cpu_copy(getattr(state, name)) for name in (
                    'order', 'cursor', 'global_step', 'epoch', 'best_metric', 'best_model',
                    'best_step', 'validation_count', 'stale_validations', 'early_stop')})


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_checkpoint(state: TrainState, path):
    """Publish a committed state; return path, manifest hash and payload hash.

    Only the small JSON manifest is replaced. Earlier manifests or interrupted
    writes still refer to immutable payloads; no optimizer state is overwritten.
    """
    _live(state)
    _validate_progress(state)
    if state.code_hashes != code_hashes():
        raise ValueError('implementation code changed since state creation')
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.f3-checkpoint-', delete=False) as stream:
            temporary = Path(stream.name)
            torch.save(_payload(state), stream)
            stream.flush()
            os.fsync(stream.fileno())
        payload_sha = _sha(temporary)
        payload_path = path.with_name(f'{path.name}.payload-{payload_sha}.pt')
        if payload_path.exists():
            if _sha(payload_path) != payload_sha:
                raise ValueError('existing content-addressed payload is corrupt')
            temporary.unlink()
        else:
            os.replace(temporary, payload_path)
        temporary = None
        _sync_directory(path.parent)
        manifest = dict(schema=SCHEMA, payload_file=payload_path.name, payload_sha256=payload_sha,
                        bindings=_bindings(state), global_step=state.global_step)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.f3-manifest-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(_json(manifest) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        _sync_directory(path.parent)
        return dict(path=str(path), sha256=_sha(path), payload_sha256=payload_sha)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_checkpoint(path, *, expected_sha256, config: TrainConfig, transitions,
                    data_hashes, device='cpu', cuda_devices=(), expected_code_hashes=None):
    """Verify bindings and hashes before deserialization; restore an exact state.

    Data hashes are a binding supplied by the qualified outer loader, not proof
    that data is qualified. Resume accounting belongs to the external launcher.
    Device/runtime migration requires a separate policy; exact loads reject it.
    """
    path = Path(path).resolve()
    _hashes({'manifest': expected_sha256}, 'expected checkpoint hash')
    if _sha(path) != expected_sha256:
        raise ValueError('checkpoint manifest SHA256 mismatch')
    manifest = json.loads(path.read_text())
    if manifest.get('schema') != SCHEMA:
        raise ValueError('checkpoint schema mismatch')
    current = code_hashes()
    if expected_code_hashes is not None and _hashes(expected_code_hashes, 'expected_code_hashes') != current:
        raise ValueError('expected code hashes do not match current implementation')
    state = TrainState.create(config, transitions, data_hashes, device=device, cuda_devices=cuda_devices)
    if _json(manifest.get('bindings')) != _json(_bindings(state)):
        raise ValueError('checkpoint semantics/config/catalogue/data/code/runtime mismatch')
    name = manifest.get('payload_file')
    if not isinstance(name, str) or Path(name).name != name or not name.startswith(path.name + '.payload-'):
        raise ValueError('invalid checkpoint payload path')
    expected_payload = manifest.get('payload_sha256')
    _hashes({'payload': expected_payload}, 'payload hash')
    payload_path = path.parent / name
    if _sha(payload_path) != expected_payload:
        raise ValueError('checkpoint payload SHA256 mismatch')
    payload = torch.load(payload_path, map_location='cpu', weights_only=True)
    if payload.get('schema') != SCHEMA or _json(payload.get('bindings')) != _json(_bindings(state)):
        raise ValueError('payload checkpoint bindings mismatch')
    state.model.load_state_dict(payload['model'], strict=True)
    if not isinstance(payload['model_training'], bool):
        raise ValueError('invalid model mode')
    state.model.train(payload['model_training'])
    state.optimizer.load_state_dict(payload['optimizer'])
    for name in ('order', 'cursor', 'global_step', 'epoch', 'best_metric', 'best_model',
                 'best_step', 'validation_count', 'stale_validations', 'early_stop'):
        setattr(state, name, payload['progress'][name])
    rng = payload['rng']
    if rng['numpy_generator'].get('bit_generator') != 'PCG64' or set(rng['cuda']) != set(state.cuda_devices):
        raise ValueError('checkpoint RNG engine/device mismatch')
    state.rng.bit_generator.state = rng['numpy_generator']
    state.python_rng = rng['python']
    legacy = rng['numpy_legacy']
    state.numpy_legacy_rng = (legacy[0], np.asarray(legacy[1], dtype=np.uint32), *legacy[2:])
    state.torch_cpu_rng = rng['torch_cpu']
    state.cuda_rng = rng['cuda']
    _live(state)
    _validate_progress(state)
    if manifest['global_step'] != state.global_step:
        raise ValueError('manifest/payload step mismatch')
    # Validate restored RNG streams without advancing them or caller streams.
    with _rng_scope(state):
        pass
    return state
