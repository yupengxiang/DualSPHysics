"""Interpolation-only manufactured checks; no advection or calibration runs."""
import numpy as np
import pytest

from scripts import f3_material_neighbors as fast
from scripts import passive_tracers as legacy


QUALITY = ('effective_sample_size', 'geometry_rank', 'anisotropy',
           'interpolation_reconstruction_error_mps', 'support_distance')


def wall(x=0., half=.5):
    a, b, c, d = [[x, -half, -half], [x, half, -half], [x, half, half], [x, -half, half]]
    return np.asarray([[a, b, c], [a, c, d]], dtype=np.float64)


def scalar_metrics(position, velocity, distance2, regularization):
    """Independent scalar assembly of the existing weighted support equations."""
    weights = np.where(np.isfinite(distance2), 1. / (distance2 + regularization**2), 0.)
    total = weights.sum()
    if total == 0:
        return np.full(3, np.nan), (0., 0, 0., np.inf)
    result = weights @ velocity / total
    center = weights @ position / max(total, legacy.EPSILON)
    offsets = position - center
    covariance = offsets.T @ (weights[:, None] * offsets) / max(total, legacy.EPSILON)
    eigenvalues = np.linalg.eigvalsh(covariance)
    largest = eigenvalues[-1]
    positive = eigenvalues[eigenvalues > max(largest * 1e-8, 1e-14)]
    anisotropy = positive[0] / largest if len(positive) and largest > 0 else 0.
    design = np.column_stack((np.ones(len(position)), offsets))
    root = np.sqrt(weights)[:, None]
    coefficients = np.linalg.pinv(root * design) @ (root * velocity)
    residual = design @ coefficients - velocity
    reconstruction = np.sqrt(np.sum(weights * np.sum(residual**2, axis=1)) / max(total, legacy.EPSILON))
    effective = total**2 / max(np.sum(weights**2), legacy.EPSILON)
    return result, (effective, len(positive), anisotropy, reconstruction)


def dense_oracle(query, position, velocity, *, neighbours=24, regularization=.004, barrier_triangles=None):
    """Exhaustive visible top-k, ordered by float64 distance squared then row.

    Scientific support is selected from every sample, independently of any
    candidate algorithm. A separate dense sorted frontier gives expected work
    diagnostics for the declared per-query doubling and completed shell rule.
    """
    query, position, velocity = [np.asarray(a, dtype=float) for a in (query, position, velocity)]
    n, k = len(position), min(neighbours, len(position))
    triangles = np.empty((0, 3, 3)) if barrier_triangles is None else np.asarray(barrier_triangles)
    all_visible = legacy.segment_visibility(query, position, triangles)
    results, supports, visible_counts, search_widths, exhaustives, selected_counts, metrics = [], [], [], [], [], [], []
    for q, visible in zip(query, all_visible):
        delta = q - position
        distances = np.einsum('ni,ni->n', delta, delta)
        masked = np.where(visible, distances, np.inf)
        chosen = np.lexsort((np.arange(n), masked))[:k]
        result, metric = scalar_metrics(position[chosen], velocity[chosen], masked[chosen], regularization)
        results.append(result)
        metrics.append(metric)
        supports.append(np.sqrt(masked[chosen].min()))
        selected_counts.append(np.isfinite(masked[chosen]).sum())
        width = min(4 * k if len(triangles) else k, n)
        while True:
            if width == n:
                pool = np.arange(n)
            else:
                cutoff = np.sqrt(np.sort(distances)[width - 1])
                radius = np.nextafter(cutoff, np.inf) + 16 * np.finfo(float).eps * max(1., cutoff)
                pool = np.flatnonzero(np.sqrt(distances) <= radius)
            count = visible[pool].sum()
            if count >= k or len(pool) == n:
                break
            width = min(2 * width, n)
        visible_counts.append(count if len(triangles) else n)
        search_widths.append(len(pool))
        exhaustives.append(len(pool) == n)
    metrics = np.asarray(metrics, dtype=float).reshape(len(query), 4)
    supports = np.asarray(supports, dtype=float)
    visible_counts = np.asarray(visible_counts, dtype=np.int64)
    diagnostics = dict(
        effective_sample_size=metrics[:, 0], geometry_rank=metrics[:, 1].astype(np.int8),
        anisotropy=metrics[:, 2], interpolation_reconstruction_error_mps=metrics[:, 3],
        support_distance=supports, visible_neighbours=visible_counts,
        visibility_search_width=np.asarray(search_widths, dtype=np.int64),
        visibility_search_exhaustive=np.asarray(exhaustives, dtype=bool),
        selected_visible_neighbours=np.asarray(selected_counts, dtype=np.int64),
    )
    return np.asarray(results).reshape(len(query), 3), supports, visible_counts, diagnostics


def unknown(result, *, strict=False):
    velocity, support, _, diagnostics = result
    gate = legacy._normalise_support_gate(dict(
        minimum_effective_sample_size=4., minimum_geometry_rank=3,
        minimum_anisotropy=.005, maximum_reconstruction_error_mps=.01) if strict else None)
    supported = legacy._support_gate_pass(diagnostics, gate)
    supported &= np.isfinite(velocity).all(axis=1) & np.isfinite(support) & (support <= 3.)
    return ~supported


def assert_oracle(actual, expected):
    np.testing.assert_allclose(actual[0], expected[0], rtol=2e-12, atol=2e-12, equal_nan=True)
    np.testing.assert_allclose(actual[1], expected[1], rtol=2e-12, atol=2e-12)
    np.testing.assert_array_equal(actual[2], expected[2])
    for name, value in expected[3].items():
        if isinstance(value, str):
            assert actual[3][name] == value
        elif value.dtype.kind in 'biu':
            np.testing.assert_array_equal(actual[3][name], value)
        else:
            np.testing.assert_allclose(actual[3][name], value, rtol=2e-11, atol=2e-12, equal_nan=True)
    for strict in (False, True):
        np.testing.assert_array_equal(unknown(actual, strict=strict), unknown(expected, strict=strict))
    assert actual[3]['visibility_mode'].startswith(fast.BACKEND)
    assert actual[3]['neighbour_tie_rule'] == fast.TIE_RULE


@pytest.mark.parametrize('barriers', (False, True))
@pytest.mark.parametrize('neighbours', (1, 7, 24))
def test_full_dense_oracle_quality_and_unknown_gates(barriers, neighbours):
    rng = np.random.default_rng(251)
    position = rng.uniform(-1., 1., (173, 3))
    query = rng.uniform(-.8, .8, (19, 3))
    velocity = np.column_stack((position[:, 0]**2, np.sin(position[:, 1]), position[:, 2]))
    triangles = wall(half=.3) if barriers else None
    arguments = dict(neighbours=neighbours, barrier_triangles=triangles)
    expected = dense_oracle(query, position, velocity, **arguments)
    actual = fast.shepard_velocity_with_diagnostics(query, position, velocity, chunk_size=6, **arguments)
    assert_oracle(actual, expected)


def test_doubling_past_96_and_192_is_per_query(monkeypatch):
    position = np.zeros((428, 3))
    position[:300, 0] = .01 + np.arange(300) * .0001  # Blocked near samples.
    position[300:, 0] = -1. - np.arange(128) * .001  # Far visible support.
    velocity = np.random.default_rng(64).normal(size=position.shape)
    query = np.array([[-2., 0., 0.], [-.1, 0., 0.]])
    calls = []
    original = fast._candidate_pools

    def traced(tree, q, p, width):
        calls.append((len(q), width))
        return original(tree, q, p, width)

    monkeypatch.setattr(fast, '_candidate_pools', traced)
    actual = fast.shepard_velocity_with_diagnostics(query, position, velocity, barrier_triangles=wall())
    assert calls == [(2, 96), (1, 192), (1, 384)]
    np.testing.assert_array_equal(actual[3]['visibility_search_width'], [96, 384])
    np.testing.assert_array_equal(actual[2], [96, 84])
    assert not actual[3]['visibility_search_exhaustive'].any()
    assert_oracle(actual, dense_oracle(query, position, velocity, barrier_triangles=wall()))


@pytest.mark.parametrize('barriers', (False, True))
def test_full_cutoff_shell_and_original_row_tie_rule(barriers):
    position = np.zeros((128, 3))
    position[:80, 0] = 1.
    position[80:, 0] = -1.
    query = np.zeros((1, 3))
    velocity = np.column_stack((np.arange(128), np.arange(128)**2, np.ones(128))).astype(float)
    triangles = wall(x=.5) if barriers else None
    actual = fast.shepard_velocity_with_diagnostics(query, position, velocity, barrier_triangles=triangles)
    # Initial width 24 or 96 must include the entire 128-sample cutoff shell.
    assert actual[3]['visibility_search_width'][0] == 128
    assert actual[3]['visibility_search_exhaustive'][0]
    selected = slice(80, 104) if barriers else slice(0, 24)
    np.testing.assert_allclose(actual[0][0], velocity[selected].mean(axis=0), rtol=2e-15)
    assert actual[2][0] == (48 if barriers else 128)
    assert_oracle(actual, dense_oracle(query, position, velocity, barrier_triangles=triangles))
    assert unknown(actual)[0]  # Coincident support geometry is not reliable.


def test_coincident_samples_are_kept_and_regularized():
    query = np.zeros((1, 3))
    position = np.zeros((40, 3))
    velocity = np.arange(120, dtype=float).reshape(40, 3)
    actual = fast.shepard_velocity_with_diagnostics(query, position, velocity)
    assert_oracle(actual, dense_oracle(query, position, velocity))
    np.testing.assert_allclose(actual[0][0], velocity[:24].mean(axis=0))
    assert actual[1][0] == 0.
    assert actual[3]['effective_sample_size'][0] == pytest.approx(24.)
    assert actual[3]['geometry_rank'][0] == 0
    assert unknown(actual)[0]


def test_no_visible_support_stays_nan_and_zero_weight_without_filtering():
    position = np.zeros((13, 3))
    position[:, 0] = np.linspace(.01, .1, 13)
    velocity = np.ones_like(position)
    query = np.array([[-.1, 0., 0.], [.2, 0., 0.]])
    actual = fast.shepard_velocity_with_diagnostics(query, position, velocity, barrier_triangles=wall())
    assert_oracle(actual, dense_oracle(query, position, velocity, barrier_triangles=wall()))
    assert actual[0].shape == query.shape
    assert np.isnan(actual[0][0]).all() and np.isfinite(actual[0][1]).all()
    assert np.isinf(actual[1][0])
    assert actual[2][0] == 0
    assert actual[3]['selected_visible_neighbours'][0] == 0
    assert actual[3]['effective_sample_size'][0] == 0
    assert actual[3]['geometry_rank'][0] == 0
    assert actual[3]['anisotropy'][0] == 0
    assert np.isinf(actual[3]['interpolation_reconstruction_error_mps'][0])
    np.testing.assert_array_equal(unknown(actual), [True, False])


def test_finite_wall_and_open_segment_endpoint_semantics():
    query = np.array([[-1., 0., 0.], [-1., 2., 0.]])
    position = np.array([[1., 0., 0.], [1., 2., 0.]])
    velocity = np.array([[1., 0., 0.], [0., 2., 0.]])
    triangles = wall(half=.2)
    actual = fast.shepard_velocity_with_diagnostics(query, position, velocity, barrier_triangles=triangles)
    assert_oracle(actual, dense_oracle(query, position, velocity, barrier_triangles=triangles))
    np.testing.assert_array_equal(actual[2], [1, 2])
    np.testing.assert_allclose(actual[0][0], velocity[1])
    assert np.isfinite(actual[0][1]).all()  # An infinite plane would hide both.
    endpoint = fast.shepard_velocity_with_diagnostics(query[:1], np.zeros((1, 3)), velocity[:1], barrier_triangles=triangles)
    assert endpoint[2][0] == 1  # Original visibility uses open segments.
    np.testing.assert_allclose(endpoint[0][0], velocity[0])


@pytest.mark.parametrize('barriers', (False, True))
def test_no_distance_ties_matches_legacy_scientific_diagnostics(monkeypatch, barriers):
    rng = np.random.default_rng(682)
    position = rng.normal(size=(221, 3))
    query = rng.normal(size=(9, 3))
    velocity = rng.normal(size=position.shape)
    for q in query:
        assert len(np.unique(np.sum((position - q)**2, axis=1))) == len(position)
    # Deliberately compare against the legacy float64 dense distance path.
    # This also prevents its optional Torch thread/device configuration.
    monkeypatch.setattr(legacy, '_torch_nearest_support', lambda *args: None)
    arguments = dict(barrier_triangles=wall(half=.4) if barriers else None)
    original = legacy.shepard_velocity_with_diagnostics(query, position, velocity, **arguments)
    actual = fast.shepard_velocity_with_diagnostics(query, position, velocity, **arguments)
    np.testing.assert_allclose(actual[0], original[0], rtol=2e-12, atol=2e-12)
    np.testing.assert_allclose(actual[1], original[1], rtol=2e-12, atol=2e-12)
    for name in QUALITY:
        np.testing.assert_allclose(actual[3][name], original[3][name], rtol=2e-11, atol=2e-12)
    for strict in (False, True):
        np.testing.assert_array_equal(unknown(actual, strict=strict), unknown(original, strict=strict))
    assert actual[3]['visibility_mode'] != original[3]['visibility_mode']


def test_chunk_size_does_not_change_per_query_science_or_search():
    rng = np.random.default_rng(41)
    position, query = rng.uniform(-1., 1., (181, 3)), rng.uniform(-1., 1., (13, 3))
    velocity = rng.normal(size=position.shape)
    one = fast.shepard_velocity_with_diagnostics(query, position, velocity, chunk_size=1, barrier_triangles=wall())
    many = fast.shepard_velocity_with_diagnostics(query, position, velocity, chunk_size=128, barrier_triangles=wall())
    assert_oracle(one, many)


def test_empty_queries_empty_samples_and_single_sample():
    position = np.array([[.1, .2, .3]])
    velocity = np.array([[.4, .5, .6]])
    empty = fast.shepard_velocity_with_diagnostics(np.empty((0, 3)), position, velocity)
    assert empty[0].shape == (0, 3) and empty[1].shape == (0,) and empty[2].shape == (0,)
    query = np.array([[0., 0., 0.], [.1, .2, .3]])
    actual = fast.shepard_velocity_with_diagnostics(query, position, velocity)
    assert_oracle(actual, dense_oracle(query, position, velocity))
    np.testing.assert_allclose(actual[0], np.repeat(velocity, 2, axis=0))
    assert unknown(actual).all()  # One point has rank zero, despite finite v.
    with pytest.raises(ValueError, match='empty particle frame'):
        fast.shepard_velocity_with_diagnostics(query, np.empty((0, 3)), np.empty((0, 3)))


def test_index_queries_are_cpu_one_worker_and_do_not_use_legacy_torch(monkeypatch):
    real_tree = fast.cKDTree
    calls = []

    class Tree:
        def __init__(self, position):
            self.tree = real_tree(position)

        def query(self, *args, **kwargs):
            assert kwargs['workers'] == 1 and kwargs['eps'] == 0.
            calls.append('query')
            return self.tree.query(*args, **kwargs)

        def query_ball_point(self, *args, **kwargs):
            assert kwargs['workers'] == 1 and kwargs['eps'] == 0.
            calls.append('shell')
            return self.tree.query_ball_point(*args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError('new CPU index called legacy Torch neighbour backend')

    monkeypatch.setattr(fast, 'cKDTree', Tree)
    monkeypatch.setattr(legacy, '_torch_nearest_support', forbidden)
    rng = np.random.default_rng(82)
    position, velocity, query = rng.normal(size=(3, 50, 3))
    result = fast.shepard_velocity_with_diagnostics(query, position, velocity)
    assert calls == ['query', 'shell']
    assert_oracle(result, dense_oracle(query, position, velocity))


@pytest.mark.parametrize('bad', ('query_nan', 'position_nan', 'velocity_nan', 'shape', 'wall_nan',
                               'neighbours_zero', 'neighbours_bool', 'chunk_zero',
                               'regularization_zero', 'regularization_inf', 'regularization_overflow'))
def test_invalid_inputs_fail_explicitly(bad):
    query, position, velocity = np.zeros((2, 3)), np.ones((3, 3)), np.ones((3, 3))
    kwargs = {}
    if bad == 'query_nan':
        query[0, 0] = np.nan
    elif bad == 'position_nan':
        position[0, 0] = np.nan
    elif bad == 'velocity_nan':
        velocity[0, 0] = np.nan
    elif bad == 'shape':
        velocity = velocity[:-1]
    elif bad == 'wall_nan':
        kwargs['barrier_triangles'] = wall() * np.nan
    elif bad == 'neighbours_zero':
        kwargs['neighbours'] = 0
    elif bad == 'neighbours_bool':
        kwargs['neighbours'] = True
    elif bad == 'chunk_zero':
        kwargs['chunk_size'] = 0
    else:
        kwargs['regularization'] = {'regularization_zero': 0., 'regularization_inf': np.inf,
                                    'regularization_overflow': 1e308}[bad]
    with pytest.raises(ValueError):
        fast.shepard_velocity_with_diagnostics(query, position, velocity, **kwargs)
