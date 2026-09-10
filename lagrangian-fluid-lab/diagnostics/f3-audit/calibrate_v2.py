"""Freeze and evaluate a manufactured-only fixed-scale observation candidate."""
import hashlib
import json
from pathlib import Path
import tempfile
import h5py
import numpy as np
from numpy.polynomial.legendre import leggauss
from scripts.f3_observation_v2 import LOW,HIGH,U,observe_arrays,compare,axis_weights,edges_for
from scripts.l1r_f3_metrics import observe

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[1]
OUT = LAB/'campaigns/l1-resume/continuation'
DESIGN = {
    'status':'candidate registered before manufactured results and new long CFD',
    'operator':'separable integrated tent kernel; solid-wall truncated/normalized, open top retained as outside',
    'plain_only':True, 'bandwidth_halfwidth_m':.06, 'bin_width_m':.06,
    'kernel_support_diameter_m':.12,
    'manufactured_tv_budget':.01, 'reference_quadrature_budget':.001,
    'velocity_reconstruction_budget_over_U':.01,
    'sensitivity_bin_widths_m':[.03,.06,.09],
    'sensitivity_origin_shifts_m':[0,.015,.03],
    'solver_dp_m':[.01,.0075,.006],
    'manufactured_design':['uniform_static','vertical_translation_006','rotation_y_031','smooth_volume_preserving_shear'],
    'held_out_negatives':['vertical_translation_042','counterflow_same_mean','missing_mass_10pct','all_mass_outside'],
    'negative_detection_budget':.05,
    'scope':'kernel-scale distribution and velocity; no pointwise, thin-film, droplet or material-path claim',
    'old_v1_status':'unaltered', 'new_v2_qualification':'requires calibration then independent new CFD and internal parameter evidence',
}


def cloud(dp,case,quadrature=None):
    size = np.array([.9,.18,.09]) if case.startswith('uniform') or case.startswith('vertical') else np.array([.18,.12,.12])
    center = np.array([0,0,.045]) if size[0] == .9 else np.array([0,0,.24])
    if quadrature:
        x,w = leggauss(quadrature)
        axes = [x*s/2 for s in size]
        weights = np.einsum('i,j,k->ijk',w/2,w/2,w/2).ravel()
    else:
        axes = [(np.arange(round(s/dp))+.5)*dp-s/2 for s in size]
        weights = np.full(np.prod([len(x) for x in axes]),1/np.prod([len(x) for x in axes]))
    p = np.stack(np.meshgrid(*axes,indexing='ij'),axis=-1).reshape(-1,3)
    v = np.zeros_like(p)
    if case == 'rotation_y_031':
        c,s = np.cos(.31),np.sin(.31)
        p = p @ np.array([[c,0,s],[0,1,0],[-s,0,c]]).T
        v = np.cross(np.array([0,.7,0]),p)
    elif case == 'smooth_volume_preserving_shear':
        p[:,0] += .018*np.sin(2*np.pi*p[:,2]/size[2])
        v[:,0] = .03*np.sin(2*np.pi*p[:,2]/size[2])
    p += center
    if case.startswith('vertical'):
        p[:,2] += .006 if case.endswith('006') else .042
        v[:,2] = .1
    return p,v,weights


def old_observe(p,v,m):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'manufactured.h5'
        with h5py.File(path,'w') as h:
            h['time']=[0.]; h['position']=p[None]; h['velocity']=v[None]
            h['mass']=m[None]; h['valid']=np.ones((1,len(m)),bool)
        return observe({},[0.],path=path)[0]


def exact_uniform(case,width,shift):
    # Tensor-product 1-D integration has an analytic rectangular source volume.
    # High-order quadrature integrates only the observer, not a CFD trajectory.
    edges=edges_for(width,shift)
    x,w=leggauss(512)
    low=LOW+np.array([0,0,.006 if case.endswith('006') else 0])
    size=np.array([.9,.18,.09])
    axis=[np.sum(axis_weights(low[k]+(x+1)*size[k]/2,edges[k],k,.06)*w[:,None]/2,axis=0) for k in range(3)]
    bins=np.einsum('i,j,k->ijk',*axis).ravel()
    v=np.array([0,0,.1 if case.startswith('vertical') else 0])
    return dict(hist=np.r_[bins,1-bins.sum(),0],momentum=bins[:,None]*v,
                com=low+size/2,q90=low[0]+.9*size[0],mean_velocity=v,
                energy_normalized=float(v@v/U**2),mass_fraction=1.)


def main():
    spec=OUT/'F3-V2-OBSERVATION-DESIGN.json'
    if spec.exists():
        assert json.loads(spec.read_text()) == DESIGN, 'do not overwrite frozen design'
    else:
        spec.write_text(json.dumps(DESIGN,indent=2)+'\n')
    rows=[]; reference_checks=[]
    for case in DESIGN['manufactured_design']:
        refs={}
        for width in DESIGN['sensitivity_bin_widths_m']:
            for shift in DESIGN['sensitivity_origin_shifts_m']:
                kw=dict(cell_width=width,origin_shift=shift)
                if case.startswith('uniform') or case.startswith('vertical'):
                    ref=exact_uniform(case,width,shift)
                else:
                    ref=observe_arrays(*cloud(None,case,64),1.,**kw)
                    coarse=observe_arrays(*cloud(None,case,48),1.,**kw)
                    err=compare(ref,coarse)
                    reference_checks.append(dict(case=case,width=width,shift=shift,errors=err))
                refs[width,shift]=ref
        for dp in DESIGN['solver_dp_m']:
            p,v,m=cloud(dp,case)
            old=old_observe(p,v,m)
            for (width,shift),ref in refs.items():
                actual=observe_arrays(p,v,m,1.,cell_width=width,origin_shift=shift)
                row=dict(case=case,dp_m=dp,particles=len(m),width_m=width,origin_shift_m=shift,
                         errors=compare(actual,ref),mass_closure_error=abs(float(actual['hist'].sum())-1),
                         old_v1_com_error=float(np.linalg.norm(old['com']-ref['com'])))
                rows.append(row)
        print('calibrated',case,flush=True)
    p,v,m=cloud(.006,'uniform_static')
    base=observe_arrays(p,v,m,1.)
    shifted=p+np.array([0,0,.042])
    counter=v.copy(); counter[:,0]=np.where(p[:,0]>0,U,-U)
    negatives={
        'vertical_translation_042':compare(base,observe_arrays(shifted,v,m,1.)),
        'counterflow_same_mean':compare(base,observe_arrays(p,counter,m,1.)),
    }
    missing=observe_arrays(p[:len(p)*9//10],v[:len(p)*9//10],m[:len(p)*9//10],1.)
    outside=observe_arrays(p+[0,0,.6],v,m,1.)
    checks={
        'fixed_scale_tv':max(r['errors']['tv'] for r in rows if r['width_m']==.06 and r['origin_shift_m']==0)<=.01,
        'fixed_scale_velocity':max(r['errors']['common_support_velocity_over_U'] for r in rows if r['width_m']==.06 and r['origin_shift_m']==0)<=.01,
        'reference_quadrature':max(r['errors']['tv'] for r in reference_checks)<=.001,
        'mass_closure':max(r['mass_closure_error'] for r in rows)<1e-12,
        'heldout_translation_detected':negatives['vertical_translation_042']['tv']>.05,
        'heldout_counterflow_detected':negatives['counterflow_same_mean']['common_support_velocity_over_U']>.05 and negatives['counterflow_same_mean']['energy_difference']>.05,
        'missing_mass_preserved':abs(missing['hist'][-1]-.1)<1e-12,
        'outside_mass_preserved':abs(outside['hist'][-2]-1)<1e-12,
    }
    checks={k:bool(v) for k,v in checks.items()}
    report=dict(design_sha256=hashlib.sha256(spec.read_bytes()).hexdigest(),rows=rows,
                reference_checks=reference_checks,held_out=negatives,checks=checks,
                calibrated=all(checks.values()),cfd_executed=False,
                operator_sha256=hashlib.sha256((LAB/'scripts/f3_observation_v2.py').read_bytes()).hexdigest(),
                qualification='manufactured observation only; CFD qualification pending')
    (HERE/'v2-calibration.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(checks),flush=True)
    if not all(checks.values()):
        raise SystemExit('candidate calibration failed; do not qualify CFD with it')


if __name__=='__main__':
    main()
