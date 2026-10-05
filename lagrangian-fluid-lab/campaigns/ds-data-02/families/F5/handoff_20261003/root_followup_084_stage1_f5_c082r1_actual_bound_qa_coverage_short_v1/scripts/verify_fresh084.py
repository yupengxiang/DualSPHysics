#!/usr/bin/env python3
"""Static contract checks for F5 fresh084; no arrays or jobs are touched."""
from __future__ import annotations
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def req(v,m):
    if not v: raise AssertionError(m)
def load(n): return json.loads((ROOT/n).read_text())
def main():
    actual=load('actual-gencase-binding.json'); req(actual['status']=='actual_completed_metadata_bound','actual binding not completed metadata'); req(actual['actual_counts']=={'solver_dimension':3,'fixed_particles':158559,'floating_particles':0,'fluid_particles':31658,'moving_particles':4210,'total_particles':194427,'xml_particle_counts':{'fixed':158559,'fluid':31658,'floating':0,'moving':4210}},'actual counts mismatch')
    req(actual['physical_condition_sha256']=='280c865dae624ad8ee2c16ef1f3ca9ff72c4fd27b13846a192bfe620993faeaa','canonical hash mismatch'); req(actual['source_plan_physical_condition_sha256']=='b3ef5e5addf559a1e6b170ef7fd6964673374b6739009358dbc459c8f310bdeb','source hash mismatch')
    for name in ['initial-qa-request.json','central-bed-coverage-request.json','short-native-qualification-request.json','typed-conversion-request-template.json','xmf-request-template.json','short-bed-audit-request.json']:
        d=load(name); req(d.get('execution_allowed') is False and d.get('launch_allowed') is False,f'{name} is enabled'); req(d.get('full16_authorized') is False and d.get('full801_authorized') is False,f'{name} full gate'); req(d.get('arrays_allowed') is False,f'{name} arrays gate')
    qa=load('initial-qa-binding.json'); req(qa['actual_counts']['fluid_particles']==31658,'QA copied stale fluid count'); req(qa['native_bed_mk']==50 and qa['source_mkbound']==40,'marker mapping')
    cov=load('central-bed-coverage-binding.json'); req(cov['actual_counts']['total_particles']==194427 and cov['native_bed_mk']==50,'coverage actual binding')
    audit=load('short-bed-audit-binding-template.json'); req(audit['expected_particle_axis']==194427 and audit['expected_fluid_particles']==31658 and audit['bed_y_bounds_m']==[-0.22,0.22],'audit constants')
    active='\n'.join((ROOT/p).read_text(errors='ignore') for p in ['workers/initial_qa_worker.py','workers/direct_partvtk_initial_mk50_coverage.py','workers/bed_audit.py'])
    req('BED_MK=40' not in active and 'EXPECTED_FLUID_PARTICLES = 40710' not in active and 'EXPECTED_PARTICLE_AXIS = 214385' not in active,'stale active constants')
    req('qa054_tool' in active and 'sys.executable' in active,'official QA interpreter binding missing'); req('for block in iter' not in active,'old hash sentinel bug remains')
    req('all_51_frames_scanned' in load('short-bed-audit-request.json')['output_contract'],'51-frame contract missing')
    print('fresh084 static contract checks passed')
if __name__=='__main__': main()
