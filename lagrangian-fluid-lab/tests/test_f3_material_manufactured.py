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


def _constant_source(path,valid):
    time=np.linspace(0,.2,5)
    axis=np.arange(-.04,.04001,.01)
    cloud=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),axis=-1).reshape(-1,3)
    with h5py.File(path,'w') as h:
        h['time']=time
        h['position']=np.broadcast_to(cloud,(len(time),len(cloud),3))
        h['velocity']=np.broadcast_to([.02,0.,0.],(len(time),len(cloud),3))
        h['valid']=np.broadcast_to(np.asarray(valid)[:,None],(len(time),len(cloud)))
        h['type']=np.full((len(time),len(cloud)),3)
    return time


def test_support_dropout_never_recovers_trusted_history(tmp_path):
    path=tmp_path/'dropout.h5';time=_constant_source(path,[True,True,False,True,True])
    trace=advect_hdf5(path,[[-.01,.005,.005]],substeps_per_interval=2,maximum_support_distance=.03)
    np.testing.assert_array_equal(trace['reliability_history'][:,0],[True,True,False,False,False])
    left,right,unknown=residence_times(time,trace['position'],trace['reliability_history'])
    np.testing.assert_allclose([left[0],right[0],unknown[0]],[.05,0.,.15],atol=1e-12)


def test_actual_advection_marks_wall_crossing_unknown(tmp_path):
    from scripts.passive_tracers import box_surface_triangles
    path=tmp_path/'wall.h5';time=_constant_source(path,[True]*5)
    wall=box_surface_triangles([-.1,-.1,-.1],[0.,.1,.1],sides=('xmax',))
    trace=advect_hdf5(path,[[-.0015,.005,.005]],substeps_per_interval=2,
        maximum_support_distance=.03,barrier_provider=lambda h,f0,f1,alpha:wall)
    assert trace['wall_crossing'].any()
    assert not trace['reliable'].any()
    ok=trace['reliability_history'][:,0]
    assert not ok[np.flatnonzero(~ok)[0]:].any()
    left,right,unknown=residence_times(time,trace['position'],trace['reliability_history'])
    assert unknown[0]>0
    np.testing.assert_allclose(left+right+unknown,[.2],atol=1e-12)
