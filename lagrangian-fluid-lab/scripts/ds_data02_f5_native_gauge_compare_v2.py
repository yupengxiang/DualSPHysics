"""Compare available native F5 gauge prefix, explicitly excluding missing final sample under the original fixed scale."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_gauge(path, observed_end):
    with Path(path).open() as f:
        rows = list(csv.DictReader(f, delimiter=';'))
    time = np.array([float(r['time [s]']) for r in rows])
    z = np.array([float(r['swlz [m]']) for r in rows])
    if not np.isfinite(time).all() or not np.isfinite(z).all() or np.any(np.diff(time) <= 0):
        raise ValueError('Invalid native gauge values or times')
    if len(time) < 800 or time[0] != 0 or time[-1] < observed_end:
        raise ValueError('Native gauge prefix must cover the declared observed window')
    return time, z

def run(contract, output):
    if output.exists():
        raise FileExistsError(output)
    c=json.loads(contract.read_text())
    sources={p:digest(p) for p in c['expected_input_sha256']}
    if sources != c['expected_input_sha256']:
        raise ValueError('Native source binding differs')
    q=json.loads(Path(c['quality_contract']).read_text())
    height=q['physical_scale']['representative_height_m']
    budget=q['q_n']['macro_relative_error_budget']
    horizon=q['physical_scale']['event_window_s']
    observed_end=c['observed_prefix_end_s']
    if not 0 < observed_end < horizon:
        raise ValueError('Missing final native gauge sample must remain explicit')
    time=np.linspace(0,observed_end,800)
    results=[]
    for pair in c['pairs']:
        for gauge in ['WG1','WG2','WG3','WG4']:
            a,b=[read_gauge(Path(pair[k])/f'GaugesSWL_{gauge}.csv',observed_end) for k in ['coarse_solver_output','medium_solver_output']]
            x,y=np.interp(time,*a),np.interp(time,*b)
            difference=x-y
            rmse=float(np.sqrt(np.mean(difference**2)))
            maximum=float(np.max(np.abs(difference)))
            peak=float(abs(x.max()-y.max()))
            results.append({'mechanism':pair['mechanism'],'gauge':gauge,
                'observed_prefix_rmse_m':rmse,'observed_prefix_max_difference_m':maximum,
                'peak_difference_m':peak,'original_height_denominator_m':height,
                'rmse_over_height':rmse/height,'max_difference_over_height':maximum/height,
                'peak_difference_over_height':peak/height,
                'original_macro_budget':budget,
                'max_difference_diagnostic':'within_original_macro_budget' if maximum/height<=budget else 'exceeds_original_macro_budget',
                'native_frames_per_source':len(a[0]),'registered_target_window_s':[0,horizon],'observed_prefix_window_s':[0,observed_end],
                'native_last_times_s':[float(a[0][-1]),float(b[0][-1])],
                'missing_terminal_interval_s':[horizon-float(a[0][-1]),horizon-float(b[0][-1])]})
    if {p:digest(p) for p in sources}!=sources:
        raise ValueError('Original native sources changed')
    r={'schema':'ds02.f5.native-gauge-prefix-spatial-comparison.v2','contract':str(contract),
        'contract_sha256':digest(contract),'source_sha256':sources,'results':results,
        'scope':'DP005 versus DP025 same physical mother/control; four native SWL gauges, observed0--15.98s prefix only, original .4m scale',
        'alignment':'Linear interpolation at the original .02s save grid through15.98s; target16s final gauge sample absent; no extrapolation or discarded startup.',
        'q_n_status':'not_assessed','qualification_claim':'none; prefix diagnostic pair only; missing final native gauge sample prevents full-window acceptance; fine spatial and independent integration/save/path studies still required',
        'production_approval':'none'}
    output.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(results),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--contract',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.contract,a.output)
