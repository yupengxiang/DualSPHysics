"""Compare full-window F7 curves using the original frozen reference scales."""
import argparse
import json
from pathlib import Path

import numpy as np

from ds_data02_native_labels import digest

def compare(baseline, variant, reference, normalizers, budget, output):
    if output.exists():
        raise FileExistsError(output)
    paths=[baseline,variant,reference,normalizers,budget]
    base,current,frozen,norm,allocation=[json.loads(p.read_text()) for p in paths]
    grid=np.linspace(0,12,601)
    def curve(data):
        t=np.asarray(data['time_s'],dtype=float)
        v=np.asarray(data['values'],dtype=float)
        if t[0]!=0 or t[-1]<12 or np.any(np.diff(t)<=0) or not np.isfinite(t).all() or not np.isfinite(v).all():
            raise ValueError('Full increasing finite native0-12s curve required')
        return np.column_stack([np.interp(grid,t,v[:,i]) for i in range(v.shape[1])])
    if not base['operators']==current['operators']==frozen['operators']:
        raise ValueError('Macro operators disagree')
    if not base['physical_condition_sha256']==current['physical_condition_sha256']==frozen['physical_condition_sha256']:
        raise ValueError('Physical mother differs')
    b,c,old=map(curve,[base,current,frozen])
    # The prior frozen protocol uses the original DP016 fine peak. Never
    # renormalize the temporal comparison by a new candidate's peak.
    scales=np.array([norm['continuous_initial_mass_kg'],*norm['com_axis_scales_m'],old[:,4].max()])
    if not np.isfinite(scales).all() or np.any(scales<=0):
        raise ValueError('Frozen reference scales invalid')
    error=np.abs(c-b)/scales
    full_budget=allocation['thresholds']['macro_relative']
    share=allocation['thresholds']['save_or_integration_share']
    metrics={name:{'scale':float(scales[i]),'max_scaled_error':float(error[:,i].max()),
        'rms_scaled_error':float(np.sqrt(np.mean(error[:,i]**2))),
        'full_macro_budget_pass':bool(error[:,i].max()<=full_budget),
        'integration_share_diagnostic_pass':bool(error[:,i].max()<=full_budget*share)}
        for i,name in enumerate(base['operators'])}
    result={'schema':'ds02.f7.registered-temporal-macros.v1',
        'input_sha256':{str(p):digest(p) for p in paths},
        'baseline_source':base['source'],'baseline_source_sha256':base['source_sha256'],
        'variant_source':current['source'],'variant_source_sha256':current['source_sha256'],
        'physical_condition_sha256':base['physical_condition_sha256'],
        'window_s':[0,12],'grid_step_s':.02,'startup_included':True,
        'kinetic_denominator_provenance':'original DP016 reference peak on original registered0-12s/.02 grid; reference-derived, not a physical MU^2 scale',
        'frozen_reference_peak_J':float(scales[4]),'macro_budget':full_budget,
        'integration_share_diagnostic_budget':full_budget*share,'metrics':metrics,
        'full_macro_budget_pass':bool(error.max()<=full_budget),
        'integration_share_diagnostic_pass':bool(error.max()<=full_budget*share),
        'q_n_status':'not_assessed','production_approval':'none',
        'limitations':['macro curves only; actual clamped half-step is explicitly separate from floor-safe study',
            'event brackets, flux, residence, spatial reconstruction and pose remain independent gates']}
    output.write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['baseline','variant','reference','normalizers','budget','output']:
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    r=compare(a.baseline,a.variant,a.reference,a.normalizers,a.budget,a.output)
    print(json.dumps({'full_macro_budget_pass':r['full_macro_budget_pass'],
        'integration_share_diagnostic_pass':r['integration_share_diagnostic_pass'],
        'metrics':r['metrics'],'q_n_status':'not_assessed'}))
