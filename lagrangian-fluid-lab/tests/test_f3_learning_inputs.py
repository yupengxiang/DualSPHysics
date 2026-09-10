import numpy as np
import pytest
import torch
from scripts.f3_control import AccelerationControl
from scripts.f3_learning_inputs import features,FEATURE_NAMES,LENGTH,SPEED
from experiments.r3_g4_baselines import model_for,local_neighbour_features


def control():
    values=np.zeros((11,7));values[:,0]=np.linspace(0,1,11);values[:,1:4]=[.1,.2,-9.81];values[:,4:7]=[.3,.4,.2]
    return AccelerationControl(values)


def test_gpu_ready_features_match_native_force_and_prefix():
    c=control();p=torch.tensor([[-.1,.03,.05],[.2,-.02,.03]],dtype=torch.float64);v=torch.tensor([[.2,.1,.3],[-.3,.2,.1]],dtype=torch.float64)
    kw=dict(time_s=.2,interval_s=.01,dp_m=.01,amplitude=1.)
    f=features(p,v,control=c,**kw)
    np.testing.assert_allclose(f[:,18:21].numpy(),c.body_acceleration(.2,p.numpy(),v.numpy())*LENGTH/SPEED**2,atol=1e-12)
    changed=c.values.copy();changed[4:,1:]+=100
    torch.testing.assert_close(f,features(p,v,control=AccelerationControl(changed),**kw),rtol=0,atol=0)
    assert len(FEATURE_NAMES)==48 and len(set(FEATURE_NAMES))==48


def test_finite_side_faces_end_at_open_rim():
    p=torch.tensor([[.5,0,.6]]);v=torch.zeros_like(p)
    f=features(p,v,time_s=0.,interval_s=.01,dp_m=.01,amplitude=1.,control=control())
    # Right face's nearest point is at its top edge, not an infinite plane.
    torch.testing.assert_close(f[0,25:28],torch.tensor([-.05,0.,-.09])/LENGTH)
    assert f[0,28]>.05/LENGTH


def test_existing_routes_accept_f3_adapter_and_real_neighbours():
    torch.manual_seed(11);p=torch.rand((16,3))*.04;v=torch.zeros_like(p)
    f=features(p,v,time_s=.2,interval_s=.01,dp_m=.01,amplitude=1.,control=control())
    local=local_neighbour_features(p,v,p,v,.01,.01)
    for route in ('particle_mlp','local_interaction'):
        out=model_for(route,len(FEATURE_NAMES),16)(f,local)
        assert out.shape==(16,3) and torch.isfinite(out).all()
    with pytest.raises(ValueError):features(p*float('nan'),v,time_s=.2,interval_s=.01,dp_m=.01,amplitude=1.,control=control())
