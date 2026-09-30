#!/usr/bin/env python3
"""Bind full-window native solver accounting; never grant scientific Q-N."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def integer(value):
    return int(value.replace(',', ''))


def read_runparts(path):
    with Path(path).open() as stream:
        rows = list(csv.DictReader((line for line in stream if line.strip() and not line.startswith('#')), delimiter=';'))
    if len(rows) < 2:
        raise ValueError('no complete native time history')
    times = [float(r['TimeStep [s]']) for r in rows]
    if times[0] != 0 or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('native times do not start at zero and increase')
    # Native NpOut fields count each SAVE INTERVAL, not all previous time.
    out = {key: sum(integer(r[key]) for r in rows) for key in ('NpOut', 'NpOutPos', 'NpOutRho', 'NpOutMov')}
    births = sum(integer(r['NpNew']) for r in rows)
    initial, final = [integer(r['NpSim']) for r in (rows[0], rows[-1])]
    if out['NpOut'] != sum(out[k] for k in ('NpOutPos', 'NpOutRho', 'NpOutMov')):
        raise ValueError('native exclusion categories do not sum to total')
    if initial + births - out['NpOut'] != final:
        raise ValueError('native full-window population account does not close')
    dtmin = min(float(r['DtMin [s]']) for r in rows[1:])
    dtmax = max(float(r['DtMax [s]']) for r in rows[1:])
    if not 0 < dtmin <= dtmax:
        raise ValueError('invalid actual native integration bounds')
    return dict(saved_frames=len(rows), initial_total_particles=initial, final_total_particles=final,
                initial_native_npf_particles=integer(rows[0]['NpfSim']), final_native_npf_particles=integer(rows[-1]['NpfSim']),
                initial_fixed_and_moving_particles=integer(rows[0]['NpbSim']), final_fixed_and_moving_particles=integer(rows[-1]['NpbSim']),
                native_population_semantics='NpfSim includes fluid AND floating; NpbSim includes fixed AND moving (native JSph.cpp RunPARTs documentation)',
                final_time_s=times[-1], births=births, excluded_interval_sums=out,
                internal_steps=sum(integer(r['Steps']) for r in rows), actual_internal_dt_min_s=dtmin,
                actual_internal_dt_max_s=dtmax,
                native_dt_semantics='per-save interval extrema; every-step distribution unavailable',
                native_exclusion_semantics='sum all per-save interval NpOut fields; last-row zero does not imply zero full-window exclusions')


def summarize(receipt_path):
    receipt_path = Path(receipt_path).resolve()
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('status') != 'completed' or receipt.get('returncode') != 0:
        raise ValueError('only completed actual solver runs are summarized here')
    parts = list(receipt_path.parent.rglob('RunPARTs.csv'))
    if len(parts) != 1:
        raise ValueError('missing or ambiguous native solver history')
    log = parts[0].with_name('Run.out')
    text = log.read_text()
    dimension = re.findall(r'\*\*\s*([23])D[- ]Simulation parameters:', text)
    count = re.search(r'Excluded particles[^:]*:\s*([0-9,]+)', text)
    facts = read_runparts(parts[0])
    if len(set(dimension)) != 1 or count is None:
        raise ValueError('native dimension or terminal exclusions missing')
    if integer(count.group(1)) != facts['excluded_interval_sums']['NpOut']:
        raise ValueError('terminal native log and full-interval exclusion sum disagree')
    counts = {}
    for key in ('CaseNfixed', 'CaseNmoving', 'CaseNfloat', 'CaseNfluid'):
        match = re.search(r'\b' + key + r'\s*=\s*([0-9,]+)', text)
        if match is None:
            raise ValueError('actual native typed initial population missing: ' + key)
        counts[key] = integer(match.group(1))
    if counts['CaseNfluid'] + counts['CaseNfloat'] != facts['initial_native_npf_particles']:
        raise ValueError('initial native NpfSim fluid/floating account does not close')
    if counts['CaseNfixed'] + counts['CaseNmoving'] != facts['initial_fixed_and_moving_particles']:
        raise ValueError('initial native NpbSim fixed/moving account does not close')
    facts.update(initial_fluid_particles=counts['CaseNfluid'], initial_floating_particles=counts['CaseNfloat'],
                 initial_fixed_particles=counts['CaseNfixed'], initial_moving_particles=counts['CaseNmoving'],
                 final_fluid_particles=facts['final_native_npf_particles'] if counts['CaseNfloat'] == 0 else None,
                 final_fluid_count_semantics='fluid-only without floating; with floating requires actual typed identity ledger')
    return dict(schema='ds02.native-window-accounting.v1',
                case_id=receipt['request']['case_id'], attempt_id=receipt['request']['attempt_id'],
                receipt=str(receipt_path), receipt_sha256=sha(receipt_path),
                runparts=str(parts[0]), runparts_sha256=sha(parts[0]), run_out=str(log), run_out_sha256=sha(log),
                solver_dimension=int(dimension[0]), gpu_seconds=receipt['gpu_seconds'],
                launch_command=receipt['command'], facts=facts,
                q_n_status='not_granted', independent_production_case_increment=0)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipts', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError('preserve prior accounting artifacts')
    result = [summarize(path) for path in json.loads(args.receipts.read_text())]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(output=str(args.output), native_solver_views=len(result), q_n_status='not_granted')))
