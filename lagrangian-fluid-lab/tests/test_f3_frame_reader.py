import json
import h5py
import numpy as np
import pytest
from scripts import f3_frame_reader as module
from scripts.l1r_q2_mdbc_bridge import sha256


def fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'LAB',tmp_path);monkeypatch.setattr(module,'OUT',tmp_path)
    name='fixture';path=tmp_path/'state.h5';drive=tmp_path/'control.csv'
    values=np.zeros((2,7));values[:,0]=[0,1];values[:,3]=-9.81
    np.savetxt(drive,values,delimiter=';')
    p=np.array([[.1,0,.02],[.2,0,.02],[.1,.01,.03],[.2,.01,.03]])
    with h5py.File(path,'w') as h:
        h['time']=np.arange(4)*.1;h['particle_id']=np.arange(4)
        h['position']=np.stack([p+[i*.01,0,0] for i in range(4)])
        h['velocity']=np.zeros((4,4,3));h['mass']=np.ones((4,4))
        h['valid']=np.ones((4,4),bool);h['type']=np.full((4,4),3)
    audit=dict(case_id=name,audit_status='pass_diagnostic',issues=[],unknowns=[],
        initial_identities_missing_at_final=0,identities_introduced_after_initial=0,identities_reappeared_after_gap=0,excluded_particles_from_solver_log=0,finite_bad_value_rows=0,
        penetration={'swept_crossing_count':0,'frames_with_penetration':0},frames=4,particle_axis_count=4,dp_m=.01,time_start_s=0.,time_end_s=.30000000000000004,initial_fluid_mass_kg=4.,hdf5='state.h5',hdf5_sha256=sha256(path))
    (tmp_path/(name+'-AUDIT.json')).write_text(json.dumps(audit))
    (tmp_path/(name+'-PREPARED.json')).write_text(json.dumps({'id':name,'dp_m':.01,'drive_amplitude':1.}))
    (tmp_path/(name+'-INPUT-PREFLIGHT.json')).write_text(json.dumps({'status':'passed','asset':{'path':'control.csv','sha256':sha256(drive)}}))
    return name,path,audit


def test_current_input_never_reads_future_state(tmp_path,monkeypatch):
    name,path,audit=fixture(tmp_path,monkeypatch)
    with module.F3FrameReader(name,purpose='engineering') as reader:
        current=reader.current_input(1,interval_s=.02)
        assert reader.frames_read==[0,1,0]
        np.testing.assert_allclose(current['velocity'],np.tile([.1,0,0],(4,1)))
        assert set(current)=={'position','velocity','time_s','interval_s','dp_m','amplitude','control'}
        assert not reader.training_qualified
        assert reader.target_displacement(1).shape==(4,3)
        assert reader.frames_read[-2:]==[1,2]


def test_training_and_failed_audit_rejected(tmp_path,monkeypatch):
    name,path,audit=fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='qualification required'):module.F3FrameReader(name,purpose='training')
    audit['issues']=['swept_finite_wall_or_obstacle_crossing']
    (tmp_path/(name+'-AUDIT.json')).write_text(json.dumps(audit))
    with pytest.raises(ValueError,match='hard audit'):module.F3FrameReader(name,purpose='engineering')


def test_changed_file_is_rejected_before_state_use(tmp_path,monkeypatch):
    name,path,audit=fixture(tmp_path,monkeypatch)
    with h5py.File(path,'r+') as h:h['position'][2,0,0]=.25
    with pytest.raises(ValueError,match='trajectory changed'):module.F3FrameReader(name,purpose='engineering')


def test_reader_never_silently_filters_an_invalid_identity(tmp_path,monkeypatch):
    name,path,audit=fixture(tmp_path,monkeypatch)
    # Exercise the read-time defence even when a supplied audit falsely claims a pass.
    with h5py.File(path,'r+') as h:h['valid'][2,1]=False
    audit['hdf5_sha256']=sha256(path)
    (tmp_path/(name+'-AUDIT.json')).write_text(json.dumps(audit))
    with module.F3FrameReader(name,purpose='engineering') as reader:
        with pytest.raises(ValueError,match='survivor filtering'):reader.read_state(2)
