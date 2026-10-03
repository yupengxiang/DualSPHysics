"""Measure the registered full-window Symplectic floor diagnostic from native rows."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def run(config, output):
    c = json.loads(config.read_text())
    receipt = json.loads(Path(c['solver_receipt']).read_text())
    assert receipt['status'] == 'completed' and receipt['returncode'] == 0
    path = Path(c['run_parts'])
    with path.open() as stream:
        rows = [r for r in csv.DictReader(stream, delimiter=';') if r.get('Part','').isdigit()]
    assert len(rows) == 4176 and [int(r['Part']) for r in rows] == list(range(4176))
    times = [float(r['TimeStep [s]']) for r in rows]
    assert times[0] == 0 and times[-1] >= 8.35 and all(b > a for a,b in zip(times,times[1:]))
    counts = lambda field: [int(r[field].replace(',','')) for r in rows]
    steps, clamps, excluded = map(lambda k: sum(counts(k)), ['Steps','DTsMin','NpOut'])
    active = [r for r in rows if float(r['DtMin [s]']) > 0]
    assert steps > 0 and active
    params = {p.get('key'): p.get('value') for p in ET.parse(c['generated_xml']).getroot().findall('.//execution/parameters/parameter')}
    assert params['StepAlgorithm'] == '2', 'Registered denominator applies to Symplectic only'
    assert '-tout:0.002' in receipt['request']['command'], 'Require actual dense CLI override'
    active_steps = sum(counts('Steps')[1:])
    initial_sentinel_steps = counts('Steps')[0]
    intervals = [b-a for a,b in zip(times,times[1:])]
    fraction = clamps / (2*steps)
    result = {'schema':'ds02.f3.actual-adaptive-floor-diagnostic.v3-dense4176', 'full_window_s':[times[0],times[-1]], 'frames':len(rows), 'total_steps':steps, 'active_steps':active_steps, 'initial_sentinel_steps':initial_sentinel_steps, 'native_save_interval_min_s':min(intervals), 'native_save_interval_max_s':max(intervals), 'native_save_bracket_halfwidth_max_s':max(intervals)/2, 'effective_cli_save_s':.002, 'total_DT_adjustments':clamps, 'floor_incidence_fraction':fraction, 'floor_diagnostic_less_than_preregistered_one_percent':fraction < .01, 'denominator':'2 x sum per-PART Steps for Symplectic; counts floor-clamp evaluations, not solver-time fraction', 'native_excluded_count_interval_sum':excluded, 'dt_min_s':min(float(r['DtMin [s]']) for r in active), 'dt_max_s':max(float(r['DtMax [s]']) for r in active), 'observed_CFLnumber':float(ET.parse(c['generated_xml']).getroot().find('.//execution/constants/cflnumber').get('value')), 'observed_CoefDtMin':params['CoefDtMin'], 'source_sha256':{k:digest(v) for k,v in c.items()}, 'qualification':'none; floor diagnostic does not establish temporal accuracy or transport convergence'}
    if output.exists():
        raise FileExistsError(output)
    output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return result

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--config',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args(); run(a.config,a.output)
