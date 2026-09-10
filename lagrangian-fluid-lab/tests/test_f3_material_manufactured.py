"""Analytic path and full-denominator checks; not CFD source qualification."""
import h5py
import numpy as np
import pytest
from scripts.passive_tracers import advect_hdf5
from scripts.f3_material_labels import residence_times


def test_independent_seeds_constant_translation_and_residence(tmp_path):
    time=np.linspace(0,.2,11)
    cloud=np.stack(np.meshgrid(np.arange(-.05,.051,.01),np.arange(-.04,.041,.01),np.arange(0,.061,.01),indexing='ij'),axis=-1).reshape(-1,3)
    velocity=np.array([.03,0.,0.])
    path=tmp_path/'manufactured.h5'
    with h5py.File(path,'w') as h:
        h['time']=time
        h['position']=cloud[None]+time[:,None,None]*velocity
        h['velocity']=np.broadcast_to(velocity,(len(time),len(cloud),3))
        h['valid']=np.ones((len(time),len(cloud)),bool)
        h['type']=np.full((len(time),len(cloud)),3)
    seeds=np.array([[-.003,.004,.025],[.002,-.007,.035]])
    output=advect_hdf5(path,seeds,substeps_per_interval=2,maximum_support_distance=.03,
        support_gate={'minimum_effective_sample_size':4.,'minimum_geometry_rank':3,'minimum_anisotropy':.005,'maximum_reconstruction_error_mps':.01})
    expected=seeds[None]+time[:,None,None]*velocity
    assert output['reliability_history'].all()
    np.testing.assert_allclose(output['position'],expected,atol=1e-12,rtol=0)
    left,right,unknown=residence_times(time,output['position'],output['reliability_history'])
    np.testing.assert_allclose(left,[.1,0.],atol=1e-12)
    np.testing.assert_allclose(right,[.1,.2],atol=1e-12)
    np.testing.assert_array_equal(unknown,[0.,0.])


def test_unknown_nan_positions_retain_entire_interval_duration():
    p=np.array([[[-.1,0,0]],[[.1,0,0]],[[np.nan,np.nan,np.nan]]])
    left,right,unknown=residence_times([0.,1.,2.],p,[[True],[True],[False]])
    np.testing.assert_allclose([left[0],right[0],unknown[0]],[.5,.5,1.])
    with pytest.raises(ValueError):residence_times([0.,1.,2.],p,[[True],[True],[True]])
