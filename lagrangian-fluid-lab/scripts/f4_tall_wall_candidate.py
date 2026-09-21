"""Prepare an independent tall-wall F4 physical candidate; never qualify it."""
import argparse
import copy
import json
from pathlib import Path
from scripts.core_cfd import prepare, digest, write_json, stamp


def candidate(source):
    cfg = copy.deepcopy(source['config'])
    cfg.update(container_height_m=1.2,
               scope_id='F4_resting_pool_laminar_tallwall120_x_v1',
               recipe_id='F4_mdbc_laminar_nu1e6_tallwall120_v1',
               case_id='F4_TALLWALL120_Q075_DP005_CANARY_V1',
               physical_case_id='F4_tallwall120_drop_x_q0p75',
               lineage_group_id='F4_tallwall120_drop_x_q0p75',
               stage='canary', qualification_claim='none', qualified=False,
               qualification_only=True, time_max_s=4.34)
    cfg['wall_bounds'] = dict(cfg['wall_bounds'], zmax=1.2)
    assert cfg['parameter']['q'] == .75 and cfg['dp_m'] == .005
    assert cfg['physical_kinematic_viscosity_m2_s'] == 1e-6
    return cfg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lab-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    lab = args.lab_root.resolve()
    source_path = lab / 'campaigns/core-v1/cfd/prepared/F4_resting_pool_laminar_qualification_v1/cell-12/prepared.json'
    source = json.loads(source_path.read_text())
    cfg = candidate(source)
    card = dict(schema='core.f4.tallwall_candidate.v1', created_at=stamp(),
                source_prepared=str(source_path), source_sha256=digest(source_path),
                config=cfg, physical_change='side-wall top .6 m to 1.2 m, open top retained',
                hypothesis='contain splash without the former rim crossing and external free fall',
                motivation='prior q0/q.25 rim events and q.75 over-rim domain losses',
                height_policy='one declared geometry candidate, not an inferred qualified height range',
                limits='new physical scope; old failures retained; no inherited qualification',
                acceptance='full 4.34 s native identity, unchanged hard wall gate, source mass and event completeness',
                qualification_claim=False)
    write_json(args.output.parent / (args.output.name + '-candidate-card.json'), card)
    result = prepare(cfg, lab, args.output)
    print(json.dumps({'prepared': str(args.output / 'prepared.json'),
                      'initial_state': result.get('initial_state'),
                      'qualification_claim': False}))


if __name__ == '__main__':
    main()
