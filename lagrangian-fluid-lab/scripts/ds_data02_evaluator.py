#!/usr/bin/env python3
"""Model-free state evaluator with reference denominators and explicit failures.

This evaluates numerical histories on matching saved times and typed identity
keys. It does not grant numerical recipe qualification, interpolate time,
discard missing mass, or load a learned model.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import h5py
import numpy as np

from ds_data02_native_labels import finite_crossing


def identities(handle):
    keys = list(zip(handle['particle_zone'][:].tolist(), handle['particle_id'][:].tolist()))
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate typed identities')
    return keys


def evaluate(reference, candidate, *, length_scale_m, velocity_scale_m_s, closed_walls=()):
    if length_scale_m <= 0 or velocity_scale_m_s <= 0:
        raise ValueError('physical scales must be positive')
    failures = []
    with h5py.File(reference, 'r') as ref, h5py.File(candidate, 'r') as cand:
        for name in ('time','particle_id','particle_zone','valid','type','mass','position','velocity'):
            if name not in ref or name not in cand:
                raise ValueError(f'missing required state: {name}')
        if not np.array_equal(ref['time'][:], cand['time'][:]):
            return dict(schema='ds-data-02.evaluation.v1', valid=False, failures=['saved_time_mismatch'],
                        numerical_qualification='not_assessed', model_invoked=False)
        for attr in ('coordinate_frame', 'geometry_sha256', 'control_sha256'):
            if attr not in ref.attrs or attr not in cand.attrs:
                failures.append(f'missing_condition_binding:{attr}')
            elif ref.attrs[attr] != cand.attrs[attr]:
                failures.append(f'condition_mismatch:{attr}')
        ref_keys, cand_keys = identities(ref), identities(cand)
        lookup = {key:i for i,key in enumerate(cand_keys)}
        mapping = np.array([lookup.get(key,-1) for key in ref_keys])
        present = mapping >= 0
        extra = len(set(cand_keys)-set(ref_keys))
        if extra:
            failures.append('unexpected_candidate_identities')
        initial_fluid = ref['valid'][0].astype(bool) & (ref['type'][0] == 3)
        initial_mass = np.where(initial_fluid, ref['mass'][0], 0).astype(float)
        if not np.isfinite(initial_mass).all() or np.any(initial_mass[initial_fluid] <= 0):
            raise ValueError('reference initial mass invalid')
        denominator = float(initial_mass.sum())
        if denominator <= 0:
            raise ValueError('reference has no initial fluid mass')
        position_error, velocity_error, missing, unknown, mass_error = [],[],[],[],[]
        wall_crossings = 0
        previous_pos, previous_good = None,None
        for ti in range(len(ref['time'])):
            rv = ref['valid'][ti].astype(bool) & initial_fluid
            cp = np.full((len(ref_keys),3), np.nan)
            cv = np.full_like(cp,np.nan)
            cm = np.full(len(ref_keys),np.nan)
            candidate_active = np.zeros(len(ref_keys),bool)
            # Read one frame, then reorder in memory: HDF5 requires sorted indices.
            cp[present] = cand['position'][ti][mapping[present]]
            cv[present] = cand['velocity'][ti][mapping[present]]
            cm[present] = cand['mass'][ti][mapping[present]]
            candidate_active[present] = cand['valid'][ti][mapping[present]].astype(bool)
            raw_active = cand['valid'][ti].astype(bool) & (cand['type'][ti] == 3)
            raw_mass = cand['mass'][ti]
            raw_pos, raw_vel = cand['position'][ti],cand['velocity'][ti]
            if np.any(raw_active & (~np.isfinite(raw_mass) | (raw_mass <= 0))):
                failures.append('invalid_candidate_mass')
            if np.any(raw_active & (~np.isfinite(raw_pos).all(axis=1) | ~np.isfinite(raw_vel).all(axis=1))):
                failures.append('nonfinite_candidate_state')
            good = candidate_active & np.isfinite(cp).all(axis=1) & np.isfinite(cv).all(axis=1) & np.isfinite(cm) & (cm > 0)
            common = rv & good
            missing.append(float(initial_mass[rv & ~candidate_active].sum()/denominator))
            unknown.append(float(initial_mass[rv & candidate_active & ~good].sum()/denominator))
            mass_error.append(float(np.abs(cm[common]-ref['mass'][ti][common]).sum()/denominator))
            rp, rvel = ref['position'][ti],ref['velocity'][ti]
            if not np.isfinite(rp[rv]).all() or not np.isfinite(rvel[rv]).all():
                raise ValueError('reference active state invalid')
            # Fixed initial denominator. Missing and unknown fractions are separate
            # compulsory outputs; callers cannot report displacement error alone.
            position_error.append(float((initial_mass[common]*np.linalg.norm(cp[common]-rp[common],axis=1)).sum()/denominator/length_scale_m))
            velocity_error.append(float((initial_mass[common]*np.linalg.norm(cv[common]-rvel[common],axis=1)).sum()/denominator/velocity_scale_m_s))
            if ti:
                paired = previous_good & good & initial_fluid
                for wall in closed_walls:
                    forward,backward,_ = finite_crossing(previous_pos,cp,wall)
                    wall_crossings += int(((forward|backward)&paired).sum())
            previous_pos,previous_good = cp,good
        if max(missing,default=0)>0:
            failures.append('missing_reference_mass')
        if max(unknown,default=0)>0:
            failures.append('unknown_reference_mass')
        if wall_crossings:
            failures.append('finite_closed_wall_crossing')
        return dict(schema='ds-data-02.evaluation.v1',valid=not failures,
                    failures=sorted(set(failures)),time=ref['time'][:].tolist(),
                    initial_reference_mass_kg=denominator,extra_candidate_identities=extra,
                    missing_reference_mass_fraction=missing,unknown_reference_mass_fraction=unknown,
                    mass_absolute_error_fraction=mass_error,position_error_per_initial_mass=position_error,
                    velocity_error_per_initial_mass=velocity_error,finite_wall_crossing_count=wall_crossings,
                    numerical_qualification='not_assessed',model_invoked=False,
                    reference_survival_normalization=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--length-scale',type=float,required=True)
    parser.add_argument('--velocity-scale',type=float,required=True)
    parser.add_argument('--walls',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=evaluate(args.reference,args.candidate,length_scale_m=args.length_scale,
                    velocity_scale_m_s=args.velocity_scale,
                    closed_walls=json.loads(args.walls.read_text()) if args.walls else [])
    if args.output.exists():
        raise FileExistsError('evaluation artifact already exists')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
