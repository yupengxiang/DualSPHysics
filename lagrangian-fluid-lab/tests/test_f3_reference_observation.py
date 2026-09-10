"""Scientific contract tests: conserved mass and causal physical time alignment."""
import h5py
import numpy as np
import pytest
from scripts.f3_observation_v2 import observe_arrays,compare,U
from scripts.f3_reference_score import state


def test_closed_wall_kernel_never_loses_mass_and_outside_is_not_reinserted():
    p=np.array([[-.449,0,.001],[.6,0,.2]])
    out=observe_arrays(p,np.zeros_like(p),np.array([.4,.3]),1.)
    assert out['hist'][:-2].sum()==pytest.approx(.4)
    assert out['hist'][-2:]==pytest.approx([.3,.3])


def test_counterflow_with_zero_mean_is_not_misclassified_as_static():
    p=np.array([[-.2,0,.15],[.2,0,.15]])
    a=observe_arrays(p,np.zeros_like(p),np.array([.5,.5]),1.)
    b=observe_arrays(p,np.array([[U,0,0],[-U,0,0]]),np.array([.5,.5]),1.)
    score=compare(a,b)
    assert score['mean_velocity_over_U']==0
    assert score['energy_difference']==pytest.approx(1.)
    assert score['common_support_velocity_over_U']==pytest.approx(1.)


def test_known_linear_trajectory_interpolates_and_rejects_extrapolation(tmp_path):
    with h5py.File(tmp_path/'linear.h5','w') as h:
        h['time']=[0.,.02]
        h['position']=np.array([[[0,0,.1]],[[.04,0,.1]]])
        h['velocity']=np.array([[[2.,0,0]],[[2.,0,0]]])
        h['valid']=np.ones((2,1),bool)
        h['mass']=np.ones((2,1))
        p,v,m,t=state(h,.005)
        np.testing.assert_allclose(p,[[.01,0,.1]])
        np.testing.assert_allclose(v,[[2,0,0]])
        assert t==[0.,.02]
        with pytest.raises(ValueError,match='outside'):
            state(h,.021)
        h['valid'][1,0]=False
        with pytest.raises(ValueError,match='lifecycle'):
            state(h,.005)
