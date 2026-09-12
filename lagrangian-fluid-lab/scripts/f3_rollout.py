"""Engineering-only autonomous F3 prediction from a complete initial state.

The new adapter convention is raw output = displacement / (SPEED * dt).
This is an explicit engineering convention, not a contract established by the
historical trainer, whose next-velocity targets and trapezoidal integrator are
not used here. Formal reference qualification, training targets/loss wiring,
and full failure-aware scoring remain separate unfinished work.

Only the initial frame is read from a reader. Subsequent inputs use predicted
positions, velocity from the previous predicted displacement, current known
forcing, and a caller-supplied interval. Predictions are never clipped,
projected onto walls, or filtered to surviving particles. Finite but physically
invalid trajectories are retained for subsequent scoring, not certified here.
"""

from dataclasses import dataclass
import math

import numpy as np
import torch

from experiments.r3_g4_baselines import local_neighbour_features
from scripts.f3_local_neighbors import exact_local_summary
from scripts.f3_learning_inputs import SPEED, features


class RolloutFailure(ValueError):
    """An invalid state/output prevents committing the requested next step."""


@dataclass(frozen=True)
class RolloutState:
    position: torch.Tensor
    velocity: torch.Tensor
    particle_id: tuple[int, ...]
    time_s: float


@dataclass(frozen=True)
class RolloutStep:
    state: RolloutState
    displacement: torch.Tensor
    normalized_displacement: torch.Tensor
    interval_s: float


def _validate_state(position, velocity, particle_id, time_s):
    if not isinstance(position, torch.Tensor) or not isinstance(velocity, torch.Tensor):
        raise RolloutFailure('current states must be tensors')
    if position.ndim != 2 or position.shape[1] != 3 or not len(position) or velocity.shape != position.shape:
        raise RolloutFailure('expected nonempty matching [N,3] current states')
    if not position.is_floating_point() or position.dtype != velocity.dtype or position.device != velocity.device:
        raise RolloutFailure('state dtype/device mismatch')
    if len(particle_id) != len(position):
        raise RolloutFailure('particle identity count changed')
    if not torch.isfinite(position).all() or not torch.isfinite(velocity).all():
        raise RolloutFailure('nonfinite current state')
    if not math.isfinite(time_s):
        raise RolloutFailure('nonfinite current time')


def local_summary(position, velocity, *, dp_m, interval_s, max_pairwise_elements):
    """Historical v1 comparison helper; float32 self exclusion is unreliable.

    The active F3 rollout uses exact_local_summary with explicit particle IDs.

    The legacy last column is the mean neighbour fraction across all targets.
    Restore that global mean after concatenating target blocks so the summary
    retains the full-call semantics even for coincident/very small contexts.
    The complete current particle context remains present in every block.
    """
    n = len(position)
    if max_pairwise_elements < n:
        raise RolloutFailure('local distance budget cannot hold one complete context row')
    batch = min(n, max_pairwise_elements // n)
    blocks = [local_neighbour_features(
        position[start:start + batch], velocity[start:start + batch],
        position, velocity, dp_m, interval_s,
    ) for start in range(0, n, batch)]
    result = torch.cat(blocks, dim=0)
    # Match the existing float32 mean followed by scalar division by N.
    # Blocking can still change reduction rounding at float32 precision.
    result[:, -1] = (result[:, -1] * n).float().mean().item() / n
    return result


class EngineeringF3Rollout:
    """A bounded inference state machine; it does not qualify or train a model.

    ``model`` follows the existing ParticleMLP/LocalInteraction call interface
    and must already be in evaluation mode. Only its raw output is reused.
    A step is committed only after shape, identity count, and finite checks.
    """

    training_qualified = False

    def __init__(self, model, *, route, position, velocity, particle_id, time_s,
                 dp_m, amplitude, control, max_steps,
                 max_pairwise_elements=4_194_304):
        if route not in ('particle_mlp', 'local_interaction'):
            raise ValueError('unsupported F3 direct-displacement route')
        if model.training:
            raise ValueError('engineering inference requires model.eval()')
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
            raise ValueError('max_steps must be a positive finite integer')
        if isinstance(max_pairwise_elements, bool) or not isinstance(max_pairwise_elements, int) or max_pairwise_elements <= 0:
            raise ValueError('max_pairwise_elements must be a positive integer')
        ids = np.asarray(particle_id)
        if ids.ndim != 1 or ids.dtype.kind not in 'iu' or len(np.unique(ids)) != len(ids):
            raise RolloutFailure('expected unique integer particle identities')
        identity = tuple(int(value) for value in ids)
        _validate_state(position, velocity, identity, time_s)
        if not math.isfinite(dp_m) or dp_m <= 0 or not math.isfinite(amplitude) or not .9 <= amplitude <= 1.1:
            raise ValueError('invalid resolution or registered amplitude')
        self.state = RolloutState(position.detach().clone(), velocity.detach().clone(), identity, float(time_s))
        self.model = model
        self.route = route
        self.dp_m = float(dp_m)
        self.amplitude = float(amplitude)
        self.control = control
        self.max_steps = max_steps
        self.max_pairwise_elements = max_pairwise_elements
        self.steps_completed = 0

    @classmethod
    def from_reader(cls, reader, model, *, route, max_steps, device='cpu',
                    dtype=torch.float32, max_pairwise_elements=4_194_304):
        """Copy frame zero from the engineering reader and retain no reader.

        Initial velocity is the native initial velocity. No next frame, target,
        source time schedule, or future-fluid accessor is retained or queried.
        Qualification remains false even when the reader's hard audit passes.
        """
        now = reader.read_state(0)
        return cls(
            model, route=route,
            position=torch.as_tensor(np.array(now['position'], copy=True), dtype=dtype, device=device),
            velocity=torch.as_tensor(np.array(now['native_velocity'], copy=True), dtype=dtype, device=device),
            particle_id=now['particle_id'], time_s=now['time_s'],
            dp_m=reader.record['dp_m'], amplitude=reader.record.get('drive_amplitude', 1.),
            control=reader.control, max_steps=max_steps,
            max_pairwise_elements=max_pairwise_elements,
        )

    @torch.inference_mode()
    def step(self, interval_s):
        """Predict one displacement without reading any source fluid state."""
        if self.steps_completed >= self.max_steps:
            raise RolloutFailure('declared rollout step bound reached')
        if not math.isfinite(interval_s) or interval_s <= 0:
            raise RolloutFailure('prediction interval must be positive and finite')
        if self.model.training:
            raise RolloutFailure('model left evaluation mode')
        old = self.state
        _validate_state(old.position, old.velocity, old.particle_id, old.time_s)
        next_time = old.time_s + float(interval_s)
        if not math.isfinite(next_time) or next_time <= old.time_s:
            raise RolloutFailure('prediction interval does not advance finite time')
        # Coverage is prescribed-input metadata, not a future fluid read.
        coverage = self.control.values[:, 0]
        if not coverage[0] <= old.time_s < next_time <= coverage[-1]:
            raise RolloutFailure('prediction interval outside known control coverage')
        base = features(
            old.position, old.velocity, time_s=old.time_s,
            interval_s=float(interval_s), dp_m=self.dp_m,
            amplitude=self.amplitude, control=self.control,
        )
        local = None
        if self.route == 'local_interaction':
            local = exact_local_summary(
                old.position, old.velocity, old.particle_id, dp_m=self.dp_m,
                interval_s=float(interval_s),
            )
        if not torch.isfinite(base).all() or (local is not None and not torch.isfinite(local).all()):
            raise RolloutFailure('nonfinite derived model input')
        normalized = self.model(base, local)
        if not isinstance(normalized, torch.Tensor) or normalized.shape != old.position.shape:
            raise RolloutFailure('model output must preserve the complete [N,3] particle axis')
        if normalized.dtype != old.position.dtype or normalized.device != old.position.device:
            raise RolloutFailure('model output dtype/device mismatch')
        if not torch.isfinite(normalized).all():
            raise RolloutFailure('nonfinite model displacement output')
        displacement = normalized * (SPEED * float(interval_s))
        if not torch.isfinite(displacement).all():
            raise RolloutFailure('nonfinite physical displacement')
        position = old.position + displacement
        velocity = displacement / float(interval_s)
        _validate_state(position, velocity, old.particle_id, next_time)
        next_state = RolloutState(position, velocity, old.particle_id, next_time)
        self.state = next_state
        self.steps_completed += 1
        return RolloutStep(next_state, displacement, normalized, float(interval_s))
