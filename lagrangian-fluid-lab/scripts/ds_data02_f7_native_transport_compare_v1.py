"""Reuse immutable transport reducers on the explicitly registered F7 12s window."""
import argparse
import json
from pathlib import Path

import ds_data02_f3_transport_compare as transport
from ds_data02_native_labels import digest

def compare(baseline, variant, budget, baseline_report, variant_report, output):
    if output.exists():
        raise FileExistsError(output)
    allocation=json.loads(budget.read_text())
    reports=[json.loads(p.read_text()) for p in [baseline_report,variant_report]]
    for p,r in zip([baseline,variant],reports):
        if r['sha256']!=digest(p) or r['frames']!=601:
            raise ValueError('Label report is not bound to the complete601-state artifact')
    # Only this short-lived adapter process selects 12s. The consumed F3
    # source and its original 10s consumers remain untouched.
    transport.WINDOW_END_S=12.0
    b,c=[transport.summarize_labels(p) for p in [baseline,variant]]
    if b['event_ids']!=c['event_ids'] or b['coordinate_frame']!=c['coordinate_frame']:
        raise ValueError('Event or coordinate-frame mismatch')
    allowance=allocation['physical_scale']['save_or_integration_event_budget_s']
    total=allocation['physical_scale']['event_absolute_budget_s']
    events=[]
    for left,right in zip(b['passage'],c['passage']):
        x,y=left['mass_weighted_chord_time_s'],right['mass_weighted_chord_time_s']
        delta=None if x is None or y is None else y-x
        events.append({'event_id':left['event_id'],'baseline':left,'variant':right,
            'weighted_chord_delta_s':delta,'total_event_budget_s':total,
            'integration_allocation_s':allowance,
            'weighted_chord_integration_diagnostic_pass':None if delta is None else abs(delta)<=allowance,
            'censoring_and_observed_mass_retained':True})
    max_brackets=[max(r['maximum_all_event_half_bracket_s']) for r in reports]
    r={'schema':'ds02.f7.full-native-transport-comparison.v1','window_s':[0,12],
        'input_sha256':{str(p):digest(p) for p in [baseline,variant,budget,baseline_report,variant_report]},
        'baseline':b,'variant':c,'events':events,
        'all_observed_crossing_rows':[v['all_observed_crossing_rows'] for v in reports],
        'maximum_observed_half_bracket_s':max_brackets,
        'save_bracket_allocation_s':allowance,
        'save_bracket_allocation_pass':all(x<=allowance for x in max_brackets),
        'residence_specific_registered_budget':None,
        'residence_comparison':'native unnormalised seconds and kg*s reported; budget not registered, no residence pass claim',
        'native_exclusions_physical_fate':'unknown; no physical-exit inference',
        'q_n_status':'not_assessed','production_approval':'none',
        'claim_boundary':'source-bound full-window diagnostics only; actual old fixed-step clamp recorded separately; no qualification from means alone'}
    output.write_text(json.dumps(r,indent=2)+'\n')
    return r

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['baseline','variant','budget','baseline-report','variant-report','output']:
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    r=compare(a.baseline,a.variant,a.budget,a.baseline_report,a.variant_report,a.output)
    print(json.dumps({'events':[{'id':e['event_id'],'delta_s':e['weighted_chord_delta_s'],
        'integration_diagnostic_pass':e['weighted_chord_integration_diagnostic_pass']} for e in r['events']],
        'save_bracket_allocation_pass':r['save_bracket_allocation_pass'],'q_n_status':'not_assessed'}))
