import subprocess
import sys
import signal
from pathlib import Path

import h5py
import numpy as np
import pytest
from scripts.core_material import (
    CurrentField,
    F4EventTracker,
    F4_AFFINE_BACKEND,
    F4_AFFINE_NEIGHBOURS,
    F4_ESS32_BACKEND,
    F4_ESS32_NEIGHBOURS,
    PredictedCurrent,
    PredictedStateH5Provider,
    ReferenceFrames,
    common_path_metrics,
    continuous_source_labels,
    f4_continuous_source_labels,
    f4_destination_membership,
    f4_destination_region,
    f4_source_membership,
    f4_source_region,
    f4_resting_pool_definition,
    f4_matrix,
    matrix,
    seeds_f4,
    trace,
    trace_f4_resting_pool,
    validate_predicted_state_h5,
    weighted_cdf,
)


def source(path):
    xyz=np.stack(np.meshgrid(*([np.linspace(-.025,.025,7)]*3),indexing='ij'),axis=-1).reshape(-1,3)
    with h5py.File(path,'w') as h:
        h['time']=[0.,.01,.02,.03]
        h['position']=np.tile(xyz,(4,1,1))
        h['velocity']=np.tile([.01,0.,0.],(4,len(xyz),1))
        valid=np.ones((4,len(xyz)),bool); valid[1:,0]=False
        h['valid']=valid; h['type']=np.full(valid.shape,3)


def test_resume_and_independence(tmp_path):
    s=tmp_path/'source.h5'; source(s)
    seeds=np.array([[-.001,0.,0.],[.001,0.,0.]])
    walls=np.empty((0,3,3))
    a=tmp_path/'a.h5'; b=tmp_path/'b.h5'
    trace(s,a,seeds,walls)
    trace(s,b,seeds,walls,stop_after=1)
    trace(s,b,seeds,walls,resume=True)
    with h5py.File(a) as x,h5py.File(b) as y:
        for name in ('position','reliable','first_passage','residence','returned'):
            np.testing.assert_equal(x[name][:],y[name][:])
        assert x['reliable'][:].all()
        np.testing.assert_allclose(x['position'][-1,:,0],seeds[:,0]+.0003)
    with pytest.raises(ValueError,match='provenance'):
        trace(s,b,seeds+.0001,walls,resume=True)


def test_duplicate_tracer_identity_is_rejected_before_writing(tmp_path):
    s = tmp_path / 'source.h5'; source(s)
    with pytest.raises(ValueError, match='tracer_ids must be unique'):
        trace(
            s, tmp_path / 'duplicate.h5',
            np.array([[-.001, 0., 0.], [.001, 0., 0.]]),
            np.empty((0, 3, 3)), tracer_ids=['same', 'same'],
        )


def test_current_field_has_no_future():
    p=np.random.default_rng(1).uniform(-.01,.01,(40,3)); v=np.ones_like(p)
    f=CurrentField(p,v)
    v[:]=1000
    result,_,_=f.sample(np.zeros((1,3)),np.empty((0,3,3)))
    np.testing.assert_allclose(result,1.)
    assert not hasattr(f,'h5')


def test_matrix_and_partial_paths():
    rows=matrix('F3'); assert len(rows)==33
    assert len({r['configuration_id'] for r in rows})==33
    subset=matrix('F3', subset=15)
    assert len(subset) == 15
    assert sum(row['matrix_stage'] == 'resolution_substep' for row in subset) == 12
    assert sum(row['matrix_stage'] == 'cadence' for row in subset) == 2
    assert sum(row['matrix_stage'] == 'seed_density' for row in subset) == 1
    assert all(row['q'] == .5 for row in subset if row['matrix_stage'] != 'resolution_substep')
    assert rows[24]['cadence'] == 'native_dense'
    assert rows[25]['interpolation_substitution'] is False
    r=common_path_metrics(np.zeros((3,3)),np.ones((3,3)),[True,True,False],[True,False,True],[.2,.3,.5])
    assert r['common_mass_fraction']==.2 and r['union_mass_fraction']==1
    assert r['rms']==pytest.approx(np.sqrt(3))


def test_provider_permissions_source_definition_and_cdf(tmp_path):
    s=tmp_path/'source.h5'; source(s)
    with ReferenceFrames(s) as frames:
        frames.field(0, .5)
        assert set(frames.loaded_indices) == {0, 1}
    predicted=PredictedCurrent(np.zeros((2,3)),np.zeros((2,3)))
    with pytest.raises(PermissionError): predicted.future()
    points=np.array([[-1.,0,0],[0.,0,0],[1.,0,0]])
    np.testing.assert_array_equal(continuous_source_labels(points),[0,1,1])
    cdf=weighted_cdf(np.array([.2,.1,np.nan]),np.array([1.,1.,1.]),denominator=3.)
    assert cdf['time_s']==[.1,.2] and cdf['event_mass_fraction']==pytest.approx(2/3)


def test_h2_k48_is_explicit_backend_variant(tmp_path):
    s=tmp_path/'source.h5'; source(s)
    seeds=np.array([[-.001,0.,0.],[.001,0.,0.]])
    out=tmp_path/'h2.h5'
    result=trace(s,out,seeds,np.empty((0,3,3)),stop_after=1,neighbour_variant='h2_k48')
    assert result['binding']['neighbour_variant']=='h2_k48'
    assert result['binding']['backend']=='f3_ckdtree_visible_shepard_distance_k48_v1'
    assert result['binding']['neighbours']==48
    with h5py.File(out) as h:
        binding=h.attrs['binding']
        assert 'f3_ckdtree_visible_shepard_distance_k48_v1' in binding
    with pytest.raises(ValueError,match='unknown neighbour variant'):
        trace(s,tmp_path/'bad.h5',seeds,np.empty((0,3,3)),neighbour_variant='k64')


def test_h1_affine_bound_retains_original_gate_and_binds_estimator(tmp_path):
    s=tmp_path/'source.h5'; source(s)
    seeds=np.array([[-.001,0.,0.],[.001,0.,0.]])
    out=tmp_path/'h1.h5'
    result=trace(s,out,seeds,np.empty((0,3,3)),stop_after=1,neighbour_variant='h1_affine_bound')
    assert result['binding']['backend']=='f3_ckdtree_visible_shepard_query_error_bound_v1'
    assert result['binding']['error_estimator']=='residual_plus_local_affine_query_bias'
    assert result['binding']['support_gate']['maximum_reconstruction_error_mps']==pytest.approx(.05*np.sqrt(9.81*.09))


@pytest.mark.parametrize(
    ('variant', 'backend', 'neighbours', 'estimator'),
    [
        ('f4_ess32_v2', F4_ESS32_BACKEND, F4_ESS32_NEIGHBOURS, 'local_residual'),
        ('f4_affine_bound_v2', F4_AFFINE_BACKEND, F4_AFFINE_NEIGHBOURS,
         'residual_plus_local_affine_query_bias'),
    ],
)
def test_f4_repair_candidates_are_explicit_and_keep_fixed_gate(tmp_path, variant, backend, neighbours, estimator):
    source_path = tmp_path / 'f4-reference.h5'
    rng = np.random.default_rng(21)
    cloud = np.vstack([
        np.array([0.4, 0.2, z]) + 0.01 * rng.normal(size=(40, 3))
        for z in np.arange(0.0, 0.61, 0.05)
    ])
    with h5py.File(source_path, 'w') as handle:
        handle['time'] = [0.0, 0.1, 0.2]
        handle['position'] = np.tile(cloud, (3, 1, 1))
        velocity = np.zeros((3, len(cloud), 3))
        velocity[:, :, 2] = -0.2
        handle['velocity'] = velocity
        handle['valid'] = np.ones((3, len(cloud)), dtype=bool)
        handle['type'] = np.full(len(cloud), 3, dtype=np.int32)
    output = tmp_path / f'{variant}.h5'
    result = trace_f4_resting_pool(
        source_path, output, np.array([[0.4, 0.2, 0.5]]), q=0.5,
        dp_m=0.0075, walls=np.empty((0, 3, 3)), stop_after=1,
        neighbour_variant=variant,
    )
    binding = result['binding']
    assert binding['backend'] == backend
    assert binding['neighbours'] == neighbours
    assert binding['error_estimator'] == estimator
    assert binding['support_gate']['minimum_effective_sample_size'] == pytest.approx(4.0)
    assert binding['support_gate']['maximum_reconstruction_error_mps'] == pytest.approx(.05*np.sqrt(9.81*.09))
    assert result['qualified_T2_macro'] is False


def test_sigkill_checkpoint_resume_is_equivalent(tmp_path):
    s=tmp_path/'source.h5'; source(s)
    killed=tmp_path/'killed.h5'; full=tmp_path/'full.h5'
    code=("import numpy as np, sys; from scripts.core_material import trace; "
          "trace(sys.argv[1], sys.argv[2], np.array([[-.001,0.,0.],[.001,0.,0.]]), "
          "np.empty((0,3,3)), kill_after=2)")
    process=subprocess.run([sys.executable,'-c',code,str(s),str(killed)], cwd=Path(__file__).resolve().parents[1],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.returncode == -signal.SIGKILL
    assert (tmp_path/'killed.h5.checkpoint.json').exists()
    trace(s,full,np.array([[-.001,0.,0.],[.001,0.,0.]]),np.empty((0,3,3)))
    trace(s,killed,np.array([[-.001,0.,0.],[.001,0.,0.]]),np.empty((0,3,3)),resume=True)
    with h5py.File(full) as a,h5py.File(killed) as b:
        for name in ('time','position','reliable','first_passage','return_time','residence',
                     'residence_left','residence_right','returned'):
            np.testing.assert_allclose(a[name][:],b[name][:],equal_nan=True)


def write_predicted_state(path, *, invalid=False):
    times = np.array([0.0, 0.1, 0.2])
    position = np.array([
        [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0]],
        [[0.01, 0.0, 0.0], [0.11, 0.0, 0.0]],
        [[0.02, 0.0, 0.0], [0.12, 0.0, 0.0]],
    ])
    velocity = np.zeros_like(position)
    valid = np.ones((3, 2), dtype=bool)
    if invalid:
        valid[-1, -1] = False
    with h5py.File(path, "w") as handle:
        handle.attrs.update(
            schema_version=1,
            state_schema="core.state.native_velocity.v1",
            velocity_semantics="native saved numerical velocity",
            future_state_inputs=False,
            autonomous_prediction=True,
            identity_semantics="particle_zone,particle_id",
        )
        handle["time"] = times
        handle["position"] = position
        handle["velocity"] = velocity
        handle["particle_id"] = np.array([10, 11], dtype=np.int64)
        handle["particle_zone"] = np.array([0, 0], dtype=np.int64)
        handle["mass"] = np.array([2.0, 3.0])
        handle["valid"] = valid


def test_f4_continuous_regions_and_events():
    assert len(f4_matrix()) == 15
    assert f4_matrix()[0]["case_id"] == "RESTING_CORE_F4_mdbc_native_q0p00000000_dp0p010000000000_qualification"
    assert f4_matrix()[-1]["design_cell"] == "native_output"
    definition = f4_resting_pool_definition(q=0.5, dp_m=0.0075)
    assert definition["scope_id"] == "F4_drop_resting_pool_x_v2"
    assert definition["destination_definition"]["pool_free_surface_z_m"] == pytest.approx(0.18)
    source_point = np.array([[0.49, 0.20, 0.47]])
    pool_point = np.array([[0.49, 0.20, 0.10]])
    outside_point = np.array([[0.01, 0.01, 0.30]])
    assert f4_source_membership(source_point, 0.5).tolist() == [True]
    assert f4_destination_membership(pool_point).tolist() == [True]
    np.testing.assert_array_equal(f4_continuous_source_labels(np.vstack((source_point, pool_point, outside_point))), [1, 0, -1])
    assert seeds_f4(512, 0.5).shape == (512, 3)
    assert f4_source_region(0.0)["box_low_m"][0] == pytest.approx(0.25)
    assert f4_destination_region()["box_size_m"] == [1.2, 0.4, 0.18]

    tracker = F4EventTracker(1)
    state = tracker.initial_state()
    tracker.advance(state, np.array([[0.49, 0.20, 0.40]]), np.array([[0.49, 0.20, 0.10]]),
                    -np.ones((1, 3)), -np.ones((1, 3)), 0.0, 0.3, [True])
    tracker.advance(state, np.array([[0.49, 0.20, 0.10]]), np.array([[0.49, 0.20, 0.30]]),
                    np.ones((1, 3)), np.ones((1, 3)), 0.3, 0.2, [True])
    tracker.advance(state, np.array([[0.49, 0.20, 0.30]]), np.array([[0.49, 0.20, 0.10]]),
                    -np.ones((1, 3)), -np.ones((1, 3)), 0.5, 0.2, [True])
    assert state["contact_time"][0] == pytest.approx(0.22)
    assert state["upward_time"][0] == pytest.approx(0.38)
    assert state["return_time"][0] == pytest.approx(0.62)
    assert state["residence"][0] == pytest.approx(0.24)


def test_predicted_state_h5_contract_is_complete_and_future_isolated(tmp_path):
    path = tmp_path / "predicted.h5"
    write_predicted_state(path)
    receipt = validate_predicted_state_h5(path)
    assert receipt["schema"] == "core.state.native_velocity.v1"
    assert receipt["future_state_inputs"] is False
    with PredictedStateH5Provider(path) as provider:
        assert provider.provider_role == "predicted"
        assert provider.state(0).count == 2
        assert provider.field(0, 0.5).valid_count == 2
        with pytest.raises(PermissionError):
            provider.future(1)
    incomplete = tmp_path / "incomplete.h5"
    write_predicted_state(incomplete, invalid=True)
    with pytest.raises(ValueError, match="complete predicted State H5"):
        PredictedStateH5Provider(incomplete)


def test_f4_trace_emits_events_and_resumes_from_sidecar(tmp_path):
    source_path = tmp_path / "f4-reference.h5"
    rng = np.random.default_rng(2)
    clouds = []
    for z in np.arange(0.0, 0.61, 0.05):
        directions = rng.normal(size=(60, 3))
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        clouds.append(np.array([0.4, 0.2, z]) + 0.01 * directions)
    points = np.vstack(clouds)
    times = np.array([0.0, 0.4, 0.8, 1.2])
    velocity = np.zeros((len(times), len(points), 3))
    velocity[0, :, 2] = -1.0
    velocity[1, :, 2] = -1.0
    velocity[2, :, 2] = 1.0
    velocity[3, :, 2] = -1.0
    with h5py.File(source_path, "w") as handle:
        handle["time"] = times
        handle["position"] = np.tile(points, (len(times), 1, 1))
        handle["velocity"] = velocity
        handle["valid"] = np.ones((len(times), len(points)), dtype=bool)
        handle["type"] = np.full(len(points), 3, dtype=np.int32)
    seed = np.array([[0.4, 0.2, 0.5]])
    full = tmp_path / "full.h5"
    resumed = tmp_path / "resumed.h5"
    full_result = trace_f4_resting_pool(source_path, full, seed, q=0.5, dp_m=0.0075,
                                        walls=np.empty((0, 3, 3)), substeps=4)
    trace_f4_resting_pool(source_path, resumed, seed, q=0.5, dp_m=0.0075,
                          walls=np.empty((0, 3, 3)), substeps=4, stop_after=1)
    trace_f4_resting_pool(source_path, resumed, seed, q=0.5, dp_m=0.0075,
                          walls=np.empty((0, 3, 3)), substeps=4, resume=True)
    assert full_result["binding"]["f4_definition"]["dp_m"] == pytest.approx(0.0075)
    with h5py.File(full, "r") as expected, h5py.File(resumed, "r") as actual:
        for name in ("time", "position", "reliable", "contact_time", "upward_time", "return_time", "residence", "event_status"):
            np.testing.assert_allclose(expected[name][:], actual[name][:], equal_nan=True)
        assert np.isfinite(actual["contact_time"][-1, 0])
        assert np.isfinite(actual["upward_time"][-1, 0])
        assert np.isfinite(actual["return_time"][-1, 0])
        assert actual.attrs["schema"] == "core.material.f4.resting_pool.v2"
