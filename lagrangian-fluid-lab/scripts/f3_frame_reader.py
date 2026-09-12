"""Bounded engineering reads with full identity/mass and causal-input contracts.

Hard integrity is necessary but is not numerical-reference qualification. This
reader intentionally exposes only engineering mode until a separate verified
recipe/domain qualification layer exists.
"""
import json
import h5py
import numpy as np
from scripts.l1r_continuation_evidence import LAB,OUT
from scripts.l1r_q2_mdbc_bridge import sha256
from scripts.f3_control import AccelerationControl


class F3FrameReader:
    training_qualified=False

    def __init__(self,case_id,*,purpose):
        if purpose!='engineering':raise ValueError('reference and control-domain qualification required before training')
        self.case_id=case_id;self.frames_read=[]
        a=json.loads((OUT/(case_id+'-AUDIT.json')).read_text())
        if a['audit_status']!='pass_diagnostic' or a['issues'] or a['unknowns']:
            raise ValueError('source hard audit failed or remains unknown')
        for key in ('initial_identities_missing_at_final','identities_introduced_after_initial','identities_reappeared_after_gap','excluded_particles_from_solver_log','finite_bad_value_rows'):
            if a[key]!=0:raise ValueError('source loses identities or finite state')
        if a['penetration']['swept_crossing_count'] or a['penetration']['frames_with_penetration']:
            raise ValueError('source wall integrity failed')
        self.record=json.loads((OUT/(case_id+'-PREPARED.json')).read_text())
        if a['case_id']!=case_id or self.record['id']!=case_id:raise ValueError('case provenance mismatch')
        if a['dp_m']!=self.record['dp_m']:raise ValueError('audited resolution mismatch')
        pre=json.loads((OUT/(case_id+'-INPUT-PREFLIGHT.json')).read_text())
        asset=pre['asset'];drive=LAB/asset['path']
        if pre['status']!='passed' or sha256(drive)!=asset['sha256']:raise ValueError('driving asset changed or unverified')
        if self.record.get('drive_sha256',asset['sha256'])!=asset['sha256']:raise ValueError('declared drive differs from preflight')
        self.control=AccelerationControl.from_csv(drive)
        source=LAB/a['hdf5'];self.source_sha256=sha256(source)
        if self.source_sha256!=a['hdf5_sha256']:raise ValueError('audited trajectory changed')
        self._h5=h5py.File(source,'r')
        try:
            self.times=self._h5['time'][:];self.ids=self._h5['particle_id'][:]
            if len(self.times)<2 or not len(self.ids) or len(self.times)!=a['frames'] or len(self.ids)!=a['particle_axis_count'] or len(np.unique(self.ids))!=len(self.ids):raise ValueError('frame/identity axis mismatch')
            if not np.isfinite(self.times).all() or np.any(np.diff(self.times)<=0):raise ValueError('invalid time axis')
            if self.times[0]!=a['time_start_s'] or self.times[-1]!=a['time_end_s']:raise ValueError('audited time interval changed')
            self._mass0=self._h5['mass'][0].astype(float)
            if not np.isfinite(self._mass0).all() or np.any(self._mass0<=0):raise ValueError('invalid initial particle masses')
            if not np.isclose(self._mass0.sum(),a['initial_fluid_mass_kg'],rtol=1e-12,atol=1e-12):raise ValueError('initial mass denominator mismatch')
            self.times.setflags(write=False);self.ids.setflags(write=False)
            self.read_state(0)
        except BaseException:
            self._h5.close();raise

    def read_state(self,frame):
        if not isinstance(frame,(int,np.integer)) or not 0<=frame<len(self.times):raise ValueError('frame outside source')
        h=self._h5
        if not h['valid'][frame].all() or not (h['type'][frame]==3).all():raise ValueError('invalid/nonfluid identity; survivor filtering is forbidden')
        p=h['position'][frame];v=h['velocity'][frame];m=h['mass'][frame].astype(float)
        if p.shape!=(len(self.ids),3) or v.shape!=p.shape or not np.isfinite(p).all() or not np.isfinite(v).all() or not np.array_equal(m,self._mass0):raise ValueError('nonfinite state or changed identity mass')
        self.frames_read.append(int(frame))
        return {'position':p,'native_velocity':v,'mass':m,'particle_id':self.ids,'time_s':float(self.times[frame])}

    def current_input(self,frame,*,interval_s):
        """Read current/past state only; requested future interval is caller input."""
        if not np.isfinite(interval_s) or interval_s<=0:raise ValueError('invalid requested prediction interval')
        now=self.read_state(frame)
        if frame==0:velocity=now['native_velocity']
        else:
            previous=self.read_state(frame-1)
            velocity=(now['position'].astype(float)-previous['position'].astype(float))/(self.times[frame]-self.times[frame-1])
        return dict(position=now['position'],velocity=np.asarray(velocity,dtype=np.float32),
            time_s=now['time_s'],interval_s=float(interval_s),dp_m=self.record['dp_m'],
            amplitude=self.record.get('drive_amplitude',1.),control=self.control)

    def target_displacement(self,frame):
        """Supervision is read separately and is never merged into model input."""
        now=self.read_state(frame);following=self.read_state(frame+1)
        return following['position'].astype(float)-now['position'].astype(float)

    def close(self):self._h5.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
