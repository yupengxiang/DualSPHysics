#!/usr/bin/env python3
"""Metadata-only preflight for F5 fresh099.

This file deliberately never opens a DAT/BI4/CSV/H5/VTK/XMF science product.  It
checks source XML, JSON contracts, Python AST, and the registered prior motion digest.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

PACKAGE = Path(__file__).resolve().parents[1]
BASE_XML = Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_090_stage1_f5_c082s1_solid_fluid_recovery_v1/source/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_Def.xml')
BASE_MOTION_SHA = '51e197f0831915a73534c619704658b06812c9d52c38c470ab4cbb8d59f5614a'
SCIENCE_SUFFIXES = {'.bi4','.csv','.h5','.hdf5','.vtk','.vtu','.xmf','.xdmf'}
CPU_KINDS = {'gencase','conversion','audit','labels','evaluator','preview','tests'}

def digest(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES or path.suffix.lower() == '.dat':
        raise AssertionError(f'preflight refuses science source: {path}')
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def require(cond, msg):
    if not cond:
        raise AssertionError(msg)

def canonical_hash(obj):
    obj=dict(obj); obj.pop('canonical_physical_condition_sha256',None)
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def load(path):
    return json.loads(path.read_text(encoding='utf-8'))

def check_candidate(tag, report):
    root=PACKAGE/'candidates'/tag
    xml=next(root.glob('*_Def.xml'))
    owner=load(root/'canonical-physical-owner.json')
    expected_scale={'A080':0.8,'A120':1.2}[tag]
    require(owner['motion_transform']['scale']==expected_scale, f'{tag}: scale')
    require(owner['source_plan_physical_condition_sha256']==owner['source_definition_sha256'], f'{tag}: source/canonical separation')
    require(owner['canonical_physical_condition_sha256']==canonical_hash(owner), f'{tag}: canonical hash')
    require(digest(xml)==owner['source_definition_sha256'], f'{tag}: XML hash')
    base=BASE_XML.read_text(encoding='utf-8')
    candidate=xml.read_text(encoding='utf-8')
    candidate_no_comment=candidate.replace(f'<!-- fresh099 {owner["candidate_id"]}: only the prescribed motion asset is transformed at runtime; geometry and initial fill are unchanged. -->\n    ','',1)
    expected=base.replace('assets/f5_compact_packet_motion.dat', f'assets/f5_c082s1_motion_s{tag[1:]}.dat')
    require(candidate_no_comment==expected, f'{tag}: geometry/control XML changed beyond motion reference')
    ET.fromstring(candidate)
    require(candidate.count(f'assets/f5_c082s1_motion_s{tag[1:]}.dat')==1, f'{tag}: motion reference')
    for path in sorted((PACKAGE/'requests').glob(f'{tag}-*.json')):
        d=load(path)
        if not path.name.endswith('-request.json'):
            continue
        require(d.get('disabled') is True and d.get('execution_allowed') is False and d.get('launch') is False and d.get('launch_allowed') is False, f'{path.name}: disabled contract')
        require(d.get('source_only') is True and d.get('arrays_allowed') is False and d.get('array_edit_allowed') is False, f'{path.name}: source-only contract')
        require(d.get('independent_case_count_increment')==0 and d.get('full801_authorized') is False, f'{path.name}: case/full gate')
        require(d.get('candidate_id')==owner['candidate_id'], f'{path.name}: candidate identity')
        require(d.get('physical_case_id')==owner['physical_case_id'], f'{path.name}: physical owner')
        require(d.get('canonical_physical_condition_sha256') in (None, owner['canonical_physical_condition_sha256']), f'{path.name}: owner hash')
        if d.get('kind')=='cpu':
            require(d.get('cpu_task_kind') in CPU_KINDS, f'{path.name}: CPU allowlist')
        if path.name.endswith('-motion-transform-request.json'):
            require(d.get('worker_kind')=='registered_compact_motion_transform', f'{path.name}: worker')
            require(d['motion_source']['sha256']==BASE_MOTION_SHA and d['motion_source']['read_or_rehashed_by_source_agent'] is False, f'{path.name}: source DAT provenance')
            require(d['motion_output']['sha256'] is None, f'{path.name}: future motion hash')
            require(d['motion_output']['rows']==641 and d['motion_output']['time_window_s']==[0.0,16.0], f'{path.name}: motion contract')
        if path.name.endswith('-gencase-request.json'):
            require(d.get('genuine_gencase') is True and d.get('genuine_gencase_required') is True, f'{path.name}: genuine GenCase')
            require(d.get('actual_counts') is None and d.get('generated_xml') is None and d.get('generated_bi4') is None, f'{path.name}: no future result')
        if path.name.endswith('-short-native-request.json'):
            require(d.get('kind')=='qualification' and d.get('expected_frames')==51 and d.get('expected_particles') is None, f'{path.name}: short qualification')
        if path.name.endswith('-short-bed-audit-request.json'):
            require(d.get('diagnostic_only') is True and d.get('binding_contract',{}).get('expected_frames')==51, f'{path.name}: dynamic audit')
        for input_path in d.get('input_files',[]):
            suffix=Path(input_path).suffix.lower()
            if suffix=='.dat':
                # The only existing DAT is the previously registered base motion. Candidate output is root-bound.
                if input_path==d.get('motion_source',{}).get('path'):
                    require(d.get('motion_source',{}).get('sha256')==BASE_MOTION_SHA, f'{path.name}: base motion digest')
                else:
                    require('<root-bind:' in input_path or d.get('input_sha256',{}).get(input_path) is None, f'{path.name}: unbound DAT')
            require(suffix not in SCIENCE_SUFFIXES, f'{path.name}: source request reads science suffix')
        report['requests_checked'] += 1
    report['candidates'].append({'tag':tag,'candidate_id':owner['candidate_id'],'scale':expected_scale,'source_definition_sha256':owner['source_definition_sha256'],'canonical_physical_condition_sha256':owner['canonical_physical_condition_sha256']})

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--write-report',action='store_true'); ap.add_argument('--report',type=Path)
    args=ap.parse_args()
    report={'schema':'ds02.f5.c082s1.fresh099-preflight.v1','status':'pass','source_only':True,'science_arrays_read':False,'science_arrays_hashed':False,'jobs_started':False,'shared_state_modified':False,'requests_checked':0,'candidates':[]}
    evidence=load(PACKAGE/'metadata/mechanism-recovery-evidence.json')
    require(evidence['root369_visual_decision']['case_increment']==0, 'Root369 case increment')
    require(evidence['root369_visual_decision']['full_runup_event_coverage']=='not demonstrated', 'Root369 event hold')
    require(evidence['root370_motion_audit']['status']=='completed' and evidence['root370_motion_audit']['frame_count']==801, 'Root370 metadata')
    require(evidence['root370_motion_audit']['full_visual_runup_event_not_granted'] is True, 'Root370 gate')
    require(evidence['frozen_source_baseline']['base_motion_sha256_from_prior_actual_receipt']==BASE_MOTION_SHA, 'base motion provenance')
    tree=ast.parse((PACKAGE/'workers/scale_compact_motion.py').read_text(encoding='utf-8'))
    imported={n.names[0].name for n in tree.body if isinstance(n,ast.Import) for _ in [0]}
    require(not imported.intersection({'numpy','h5py','subprocess'}), 'worker imports forbidden science/job package')
    for tag in ('A080','A120'): check_candidate(tag,report)
    for path in PACKAGE.rglob('*'):
        if path.is_file() and path.suffix.lower() in SCIENCE_SUFFIXES:
            raise AssertionError(f'science artifact was added to source package: {path}')
    report['legal_scales']=[0.8,1.0,1.2]
    report['future_hashes_null']=True
    report['full801_enabled']=False
    report['case_credit']=0
    out=args.report or PACKAGE/'metadata/fresh099-preflight-report.json'
    if args.write_report:
        out.write_text(json.dumps(report,indent=2,ensure_ascii=False,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2,ensure_ascii=False,sort_keys=True))
if __name__=='__main__': main()
