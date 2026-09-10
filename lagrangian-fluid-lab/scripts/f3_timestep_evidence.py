"""Read measured native time-step ranges from completed solver runs."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
from scripts.l1r_continuation_evidence import LAB,OUT,write
from scripts.l1r_q2_mdbc_bridge import sha256


def evidence(name):
    solver=json.loads((OUT/(name+'-SOLVER.json')).read_text())
    if solver['status']!='completed':raise ValueError('solver not completed')
    path=Path(solver['attempt_directory'])/'RunPARTs.csv'
    with path.open() as f:
        rows=list(csv.DictReader((line for line in f if line.strip() and not line.lstrip().startswith('#')),delimiter=';'))
    active=[r for r in rows if float(r['DtMin [s]'])>0]
    if not active:raise ValueError('no measured time-step rows')
    return dict(case=name,csv_path=str(path.relative_to(LAB)),csv_sha256=sha256(path),
        dt_min_s=min(float(r['DtMin [s]']) for r in active),
        dt_max_s=max(float(r['DtMax [s]']) for r in active),
        median_interval_min_dt_s=float(np.median([float(r['DtMin [s]']) for r in active])),
        total_steps=sum(int(row['Steps'].replace(',','')) for row in rows),
        step_count_basis='sum of native per-PART Steps counts; not the final Run.out step index',
        last_time_s=float(rows[-1]['TimeStep [s]']),
        elapsed_seconds=solver['elapsed_seconds'])


def main(first,second):
    a,b=evidence(first),evidence(second)
    minratio=b['dt_min_s']/a['dt_min_s'];maxratio=b['dt_max_s']/a['dt_max_s']
    r=dict(cases=[a,b],actual_min_dt_ratio=minratio,actual_max_dt_ratio=maxratio,
        effective_halving=bool(np.isclose(minratio,.5,rtol=1e-10) and np.isclose(maxratio,.5,rtol=1e-10)),
        temporal_accuracy_qualified=False,note='Native step refinement is execution evidence, not proof of source quality or temporal accuracy.')
    write(first+'--'+second+'-TIME-EVIDENCE.json',r);print(json.dumps(r,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('first');p.add_argument('second');a=p.parse_args();main(a.first,a.second)
