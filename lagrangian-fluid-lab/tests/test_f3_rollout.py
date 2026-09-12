import numpy as np
import pytest
import torch

from experiments.r3_g4_baselines import local_neighbour_features, model_for
from scripts.f3_control import AccelerationControl
from scripts.f3_learning_inputs import FEATURE_NAMES, LENGTH, SPEED
from scripts.f3_rollout import EngineeringF3Rollout, RolloutFailure, local_summary


def control():
    values = np.zeros((11, 7))
    values[:, 0] = np.linspace(0, 1, 11)
    values[:, 1:4] = [.1, .2, -9.81]
    return AccelerationControl(values)


class VelocityIncrement(torch.nn.Module):
    """A declared fake model: add a fixed normalized velocity each step."""

    def __init__(self):
        super().__init__()
        self.inputs = []

    def forward(self, base, local=None):
        assert not torch.is_grad_enabled()
        self.inputs.append(base.clone())
        return base[:, 3:6] + base.new_tensor([.1, -.05, 0.])


class Constant(torch.nn.Module):
    def __init__(self, value):
        super().__init__()
        self.value = value

    def forward(self, base, local=None):
        return torch.full((len(base), 3), self.value, dtype=base.dtype, device=base.device)


def inputs(n=4):
    p = torch.tensor([[.449, .01, .05]], dtype=torch.float64).repeat(n, 1)
    p[:, 1] += torch.arange(n) * .01
    return dict(position=p, velocity=torch.ones_like(p) * .02,
                particle_id=np.arange(7, 7 + n), time_s=0., dp_m=.01,
                amplitude=1., control=control(), max_steps=3)


def test_variable_interval_autonomy_and_direct_displacement_convention():
    model = VelocityIncrement().eval()
    given = inputs()
    run = EngineeringF3Rollout(model, route='particle_mlp', **given)
    expected_p = given['position'].clone()
    expected_v = given['velocity'].clone()
    t = 0.
    for index, dt in enumerate((.01, .02, .005)):
        previous_p, previous_v = expected_p.clone(), expected_v.clone()
        expected_v += expected_v.new_tensor([.1, -.05, 0.]) * SPEED
        expected_p += expected_v * dt
        t += dt
        prediction = run.step(dt)
        torch.testing.assert_close(prediction.state.position, expected_p)
        torch.testing.assert_close(prediction.state.velocity, expected_v)
        torch.testing.assert_close(prediction.displacement, expected_v * dt)
        torch.testing.assert_close(prediction.normalized_displacement, expected_v / SPEED)
        torch.testing.assert_close(model.inputs[index][:, :3], previous_p / LENGTH)
        torch.testing.assert_close(model.inputs[index][:, 3:6], previous_v / SPEED)
        assert prediction.state.particle_id == tuple(given['particle_id'])
        assert prediction.state.time_s == t
        assert not prediction.state.position.requires_grad
    # The x prediction crosses the wall; retaining it proves there is no clamp.
    assert (run.state.position[:, 0] > .45).all()
    assert not run.training_qualified
    assert run.steps_completed == 3
    with pytest.raises(RolloutFailure, match='step bound'):
        run.step(.01)
    torch.testing.assert_close(given['position'], inputs()['position'])


def test_reader_is_only_used_for_initial_frame_then_can_be_closed():
    class InitialOnlyReader:
        training_qualified = False
        record = {'dp_m': .01, 'drive_amplitude': 1.}
        control = control()

        def __init__(self):
            self.calls = []
            self.closed = False

        def read_state(self, frame):
            assert not self.closed and frame == 0, 'unexpected fluid read'
            self.calls.append(frame)
            given = inputs()
            return dict(position=given['position'].numpy(),
                        native_velocity=given['velocity'].numpy(),
                        particle_id=given['particle_id'], time_s=0.)

        @property
        def times(self):
            raise AssertionError('source time axis must not schedule predictions')

        def target_displacement(self, frame):
            raise AssertionError('future supervision was queried')

        def current_input(self, *args, **kwargs):
            raise AssertionError('teacher state was queried')

    reader = InitialOnlyReader()
    run = EngineeringF3Rollout.from_reader(
        reader, VelocityIncrement().eval(), route='particle_mlp', max_steps=3,
    )
    reader.closed = True
    for dt in (.01, .02, .03):
        run.step(dt)
    assert reader.calls == [0]
    assert len(run.state.particle_id) == 4
    assert not any(value is reader for value in vars(run).values())


def test_blocked_local_summary_matches_existing_full_context():
    # Duplicate points and N < 8 exercise the global neighbour-fraction field.
    p = torch.tensor([[0., 0., 0.], [.01, 0., 0.], [.02, 0., 0.],
                      [0., 0., 0.], [0., .01, 0.]], dtype=torch.float64)
    v = torch.arange(15, dtype=p.dtype).reshape(5, 3) / 30
    expected = local_neighbour_features(p, v, p, v, .01, .02)
    actual = local_summary(p, v, dp_m=.01, interval_s=.02, max_pairwise_elements=10)
    torch.testing.assert_close(actual, expected, rtol=1e-12, atol=1e-12)
    with pytest.raises(RolloutFailure, match='complete context'):
        local_summary(p, v, dp_m=.01, interval_s=.02, max_pairwise_elements=4)


@pytest.mark.parametrize('route', ['particle_mlp', 'local_interaction'])
def test_real_untrained_cpu_routes_keep_full_shape_without_gradients(route):
    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(17)
        model = model_for(route, len(FEATURE_NAMES), 16).double().eval()
    given = inputs(16)
    run = EngineeringF3Rollout(model, route=route, max_pairwise_elements=64, **given)
    for dt in (.01, .02):
        step = run.step(dt)
        assert step.state.position.shape == (16, 3)
        assert torch.isfinite(step.state.position).all()
        assert torch.isfinite(step.state.velocity).all()
        assert step.state.position.device.type == 'cpu'
        assert step.state.particle_id == tuple(given['particle_id'])
    assert all(parameter.grad is None for parameter in model.parameters())


@pytest.mark.parametrize('bad', [float('nan'), float('inf')])
def test_nonfinite_output_fails_without_committing_or_dropping_ids(bad):
    run = EngineeringF3Rollout(Constant(bad).eval(), route='particle_mlp', **inputs())
    before = run.state
    with pytest.raises(RolloutFailure, match='nonfinite model'):
        run.step(.01)
    assert run.state is before and run.steps_completed == 0
    assert len(run.state.particle_id) == 4


def test_invalid_state_identity_shape_and_interval_are_explicit_failures():
    given = inputs()
    given['position'][0, 0] = float('nan')
    with pytest.raises(RolloutFailure, match='nonfinite current'):
        EngineeringF3Rollout(Constant(0.).eval(), route='particle_mlp', **given)
    given = inputs()
    given['particle_id'][1] = given['particle_id'][0]
    with pytest.raises(RolloutFailure, match='unique integer'):
        EngineeringF3Rollout(Constant(0.).eval(), route='particle_mlp', **given)

    class MissingParticle(torch.nn.Module):
        def forward(self, base, local=None):
            return base[:-1, :3]

    run = EngineeringF3Rollout(MissingParticle().eval(), route='particle_mlp', **inputs())
    with pytest.raises(RolloutFailure, match='complete'):
        run.step(.01)
    for dt in (0., -.1, float('nan'), float('inf'), 2.):
        with pytest.raises(RolloutFailure):
            run.step(dt)
    assert run.steps_completed == 0
