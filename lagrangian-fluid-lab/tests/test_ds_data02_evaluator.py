from pathlib import Path
import shutil
import sys

import h5py
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ds_data02_evaluator import evaluate


def files(tmp_path):
    reference=tmp_path/'ref.h5';candidate=tmp_path/'candidate.h5'
    with h5py.File(reference,'w') as h:
        h.attrs.update(coordinate_frame='world',geometry_sha256='frozen_geometry',control_sha256='fixed')
        for name,data in dict(time=[0.,1.],particle_id=[11,12],particle_zone=[0,0],valid=[[1,1],[1,1]],
                              type=[[3,3],[3,3]],mass=[[2.,8.],[2.,8.]],
                              position=[[[.25,.5,.5],[.75,.5,.5]]]*2,velocity=[[[0.,0.,0.]]*2]*2).items():
            h.create_dataset(name,data=data)
    shutil.copyfile(reference,candidate)
    return reference,candidate


def run(reference,candidate,**kwargs):
    return evaluate(reference,candidate,length_scale_m=1.,velocity_scale_m_s=1.,**kwargs)


def test_reference_self_comparison_and_condition_binding(tmp_path):
    r,c=files(tmp_path)
    result=run(r,r)
    assert result['valid'] and result['position_error_per_initial_mass']==[0,0]
    with h5py.File(c,'r+') as h:h.attrs['control_sha256']='different'
    assert 'condition_mismatch:control_sha256' in run(r,c)['failures']


def test_missing_mass_negative_mass_and_nonfinite_state_are_exposed(tmp_path):
    r,c=files(tmp_path)
    with h5py.File(c,'r+') as h:h['valid'][1,1]=0
    result=run(r,c)
    assert result['missing_reference_mass_fraction']==[0,.8]
    assert not result['valid']
    with h5py.File(c,'r+') as h:
        h['valid'][1,1]=1;h['mass'][1,1]=-8;h['position'][1,0]=[np.nan,0,0]
    result=run(r,c)
    assert 'invalid_candidate_mass' in result['failures']
    assert 'nonfinite_candidate_state' in result['failures']
    assert result['unknown_reference_mass_fraction'][1]==1


def test_identity_mismatch_and_saved_time_shift(tmp_path):
    r,c=files(tmp_path)
    with h5py.File(c,'r+') as h:h['particle_id'][:]=[12,11]
    assert run(r,c)['position_error_per_initial_mass']==[.5,.5]
    with h5py.File(c,'r+') as h:h['time'][1]=1.01
    assert run(r,c)['failures']==['saved_time_mismatch']


def test_finite_wall_aperture_does_not_become_an_infinite_plane(tmp_path):
    r,c=files(tmp_path)
    wall=dict(axis=0,value=0.,aperture_bounds=[[0.,1.],[0.,1.]])
    with h5py.File(c,'r+') as h:
        h['position'][1,0]=[-.25,.5,.5]
        h['position'][0,1]=[.75,.5,2.]
        h['position'][1,1]=[-.75,.5,2.]
    result=run(r,c,closed_walls=[wall])
    assert result['finite_wall_crossing_count']==1
    assert 'finite_closed_wall_crossing' in result['failures']
