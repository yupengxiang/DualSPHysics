"""Independently check UID alignment and paired error tails, without a Q-N gate."""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np


def load(path):
    with h5py.File(path, 'r') as h:
        return {name: h[name][:] for name in (
            'particle_id', 'initial_fluid_mass_kg', 'source_label',
            'first_passage_censor', 'first_passage_chord_time', 'first_passage_interval')}


def compare(nominal, candidate):
    for name in ('particle_id', 'initial_fluid_mass_kg', 'source_label'):
        if not np.array_equal(nominal[name], candidate[name]):
            raise ValueError('Paired identity / initial condition differs: ' + name)
    uid = nominal['particle_id']
    if len(np.unique(uid)) != len(uid):
        raise ValueError('Duplicate particle UID')
    fluid = nominal['initial_fluid_mass_kg'] > 0
    mass = nominal['initial_fluid_mass_kg']
    events = []
    for event in range(nominal['first_passage_censor'].shape[1]):
        a = (nominal['first_passage_censor'][:, event] == 0) & fluid
        b = (candidate['first_passage_censor'][:, event] == 0) & fluid
        joint = a & b
        delta = candidate['first_passage_chord_time'][joint, event] - nominal['first_passage_chord_time'][joint, event]
        ia = nominal['first_passage_interval'][joint, event, :]
        ib = candidate['first_passage_interval'][joint, event, :]
        if not np.all(np.isfinite(delta)) or not np.all(np.isfinite(ia)) or not np.all(np.isfinite(ib)):
            raise ValueError('Nonfinite observed event')
        if np.any(ia[:, 1] < ia[:, 0]) or np.any(ib[:, 1] < ib[:, 0]):
            raise ValueError('Reversed observed event bracket')
        nonoverlap = np.maximum(ia[:, 0], ib[:, 0]) > np.minimum(ia[:, 1], ib[:, 1])
        record = dict(event_index=event, jointly_observed=int(joint.sum()),
                      nominal_only_observed=int((a & ~b).sum()),
                      candidate_only_observed=int((b & ~a).sum()),
                      switching_uids_total=int((a ^ b).sum()),
                      net_observed_count_change=int(b.sum() - a.sum()),
                      switching_mass_kg=float(mass[a ^ b].sum()),
                      paired_brackets_nonoverlapping=int(nonoverlap.sum()))
        if len(delta):
            record.update(mean_signed_delta_s=float(delta.mean()), mean_absolute_delta_s=float(np.abs(delta).mean()),
                          absolute_delta_quantiles_s={str(q):float(np.quantile(np.abs(delta),q)) for q in (.5,.75,.9,.95,.99,1.)},
                          signed_delta_min_max_s=[float(delta.min()),float(delta.max())])
        events.append(record)
    return dict(uid_axis_exactly_equal=True, initial_mass_and_source_exactly_equal=True, events=events)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--comparison-request', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    request = json.loads(args.comparison_request.read_text())
    command = request['command']
    paths = {name:Path(command[command.index('--'+name+'-h5')+1]) for name in ('nominal','time','output')}
    data = {name:load(path) for name,path in paths.items()}
    result = dict(schema='ds02.f3.root-paired-transport-audit.v1', status='completed',
                  source_labels={name:str(path) for name,path in paths.items()},
                  nominal_vs_time=compare(data['nominal'],data['time']),
                  nominal_vs_output=compare(data['nominal'],data['output']),
                  scientific_interpretation='Signed means can cancel large positive and negative particle errors. Switching UID total differs from net count change. Neither a small signed mean nor cohort reconciliation establishes numerical qualification.',
                  scope='Original CELL3; weak-dual timing budget remains inapplicable',
                  q_n_granted=False, production_granted=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as out:
        json.dump(result,out,indent=2);out.write('\n')
    print(json.dumps(result),flush=True)
