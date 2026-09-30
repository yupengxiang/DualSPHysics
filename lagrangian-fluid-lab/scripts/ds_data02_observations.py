#!/usr/bin/env python3
"""Extract mass, moments, energy and weighted coordinate quantiles from states.

These are descriptive spatial-reference evidence. Qualification additionally
requires registered event operators, integration/save controls, uncertainty,
and parameter-domain checks; this extractor never grants Q-N.
"""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np


def weighted_quantile(values, weights, quantiles):
    order=np.argsort(values)
    cumulative=np.cumsum(weights[order])
    return values[order][np.minimum(np.searchsorted(cumulative,np.asarray(quantiles)*cumulative[-1]),len(order)-1)]


def extract(source, *, continuous_initial_mass_kg):
    if continuous_initial_mass_kg<=0:
        raise ValueError('continuous physical initial mass must be positive')
    rows=[]
    with h5py.File(source,'r') as h:
        initial=h['valid'][0].astype(bool)&(h['type'][0]==3)
        initial_mass=np.where(initial,h['mass'][0],0).astype(float)
        for ti,t in enumerate(h['time'][:]):
            active=h['valid'][ti].astype(bool)&(h['type'][ti]==3)
            p,v,m=h['position'][ti][active],h['velocity'][ti][active],h['mass'][ti][active].astype(float)
            if len(m)==0 or not np.isfinite(p).all() or not np.isfinite(v).all() or not np.isfinite(m).all() or np.any(m<=0):
                raise ValueError('active native fluid state invalid')
            rows.append(dict(time_s=float(t),active_fluid_count=int(active.sum()),
                             fluid_mass_kg=float(m.sum()),mass_over_continuous_initial=float(m.sum()/continuous_initial_mass_kg),
                             missing_initial_mass_kg=float(initial_mass[initial&~active].sum()),
                             center_of_mass_m=np.average(p,axis=0,weights=m).tolist(),
                             mean_velocity_m_s=np.average(v,axis=0,weights=m).tolist(),
                             kinetic_energy_J=float(.5*np.sum(m*np.sum(v*v,axis=1))),
                             coordinate_quantiles_m=np.array([weighted_quantile(p[:,axis],m,[.05,.5,.95]) for axis in range(3)]).tolist()))
        return dict(schema='ds-data-02.native-observations.v1',source=str(source),
                    coordinate_frame=str(h.attrs['coordinate_frame']),
                    geometry_sha256=str(h.attrs.get('geometry_sha256','missing')),
                    control_sha256=str(h.attrs.get('control_sha256','missing')),
                    continuous_initial_mass_kg=continuous_initial_mass_kg,
                    numerical_initial_mass_kg=float(initial_mass.sum()),
                    initial_mass_relative_error=float(initial_mass.sum()/continuous_initial_mass_kg-1),
                    quantiles=[.05,.5,.95],rows=rows,q_n_status='not_assessed',
                    normalization='mass and energy retain physical scale; missing initial mass is explicit')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--continuous-initial-mass',type=float,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('observation artifact already exists')
    result=extract(args.source,continuous_initial_mass_kg=args.continuous_initial_mass)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(path=str(args.output),frames=len(result['rows']),
                          initial_mass_relative_error=result['initial_mass_relative_error'],q_n_status='not_assessed')))


if __name__=='__main__':main()
