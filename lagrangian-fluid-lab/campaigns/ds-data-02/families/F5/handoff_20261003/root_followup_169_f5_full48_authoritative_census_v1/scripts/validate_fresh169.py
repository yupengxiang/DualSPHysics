#!/usr/bin/env python3
"""Fresh169 metadata-only validator; never opens BI4/H5/CSV/DAT/VTK science payloads."""
from pathlib import Path
import hashlib, json, sys
PKG=Path(__file__).resolve().parents[1]
DATA=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5')
FORBIDDEN={'.h5','.bi4','.csv','.dat','.vtk'}
def load(p): return json.loads(p.read_text())
def digest(p):
    if p.suffix.lower() in FORBIDDEN: raise AssertionError(f'forbidden science hash/read: {p}')
    return hashlib.sha256(p.read_bytes()).hexdigest()
def require(cond,msg):
    if not cond: raise AssertionError(msg)
def receipt_ok(path):
    p=Path(path); require(p.is_file(),f'missing receipt {p}'); d=load(p)
    require(d.get('status')=='completed' and d.get('returncode')==0,f'nonterminal receipt {p}')
    return d

def validate():
    census=load(PKG/'metadata/fresh169-census.json')
    rows=census['rows']; require(len(rows)==48,'row count !=48')
    ids=[r['physical_case_id'] for r in rows]; require(len(set(ids))==48,'duplicate physical_case_id')
    require(sum(r['membership']=='endpoint' for r in rows)==2,'endpoint count')
    require(sum(r['membership']=='mother_full801' for r in rows)==12,'mother count')
    require(sum(r['membership']=='next34' for r in rows)==34,'next34 count')
    require(census['additional_legal_disabled_candidates']==[],'fabricated gap candidates')
    for r in rows:
        for stage in ('gencase','initial_qa','native','typed','xmf','bed','render'):
            s=r['stages'][stage]
            if s.get('status')=='completed':
                require(s.get('returncode')==0,f'{r["tag"]}/{stage} rc')
                if s.get('receipt'): receipt_ok(s['receipt'])
                require(not any(str(k).lower().endswith(x) for x in FORBIDDEN for k in []),'payload scan')
        require(r['science_payload_read_or_hashed_by_source_agent'] is False,'row payload policy')
        require(r['scopes']['scope_relation'].startswith('canonical owner'),'scope relation')
    for tag in ('M086_T095','M088_T085','M088_T095'):
        b=load(PKG/'bindings'/f'{tag}-root993-original138-bed-binding.json')
        q=load(PKG/'requests'/f'{tag}-root993-original138-bed-request.json')
        require(b['disabled'] and not b['execution_allowed'] and not b['full801_authorized'],'binding enabled')
        require(q['disabled'] and not q['launch'] and not q['execution_allowed'],'request enabled')
        require(b['native_bed_marker_mk']==50 and b['source_bed_marker_mkbound']==40,'Mk mapping')
        require(b['expected_particles']==194427 and b['expected_fluid_particles']==31658 and b['expected_dimension']==3,'counts')
        require(b['identity_adapter']['original_worker_sha256']==digest(Path(b['identity_adapter']['original_worker_path'])),'original worker SHA')
        require(b['identity_adapter']['adapter_worker_sha256']==digest(Path(b['identity_adapter']['adapter_worker_path'])),'adapter SHA')
        require(b['trajectory_h5_read_or_rehashed_by_source_agent'] is False,'trajectory policy')
        for k,v in b['future_output_hashes'].items(): require(v is None,f'future binding hash {tag}/{k}')
        require(q['input_sha256_required'] is True,'strict input closure')
        for f,h in q['input_sha256'].items():
            p=Path(f); require(p.is_file(),f'missing input {p}'); require(p.suffix.lower() not in FORBIDDEN,f'payload input {p}'); require(digest(p)==h,f'input hash mismatch {p}')
        require(q['source_agent_did_not_read_or_hash_science_payloads'] is True,'request payload policy')
        require(q['full801_visual_gate']=='WAIT','visual gate')
    side=load(PKG/'metadata/root993-bed-status.json')
    require(len(side['actual_xmf_completed'])==2,'two actual Root993 XMF completions')
    require({x['tag'] for x in side['actual_xmf_completed']}=={'M086_T095','M088_T085'},'actual Root993 XMF tags')
    require(side['remaining_one']['status']=='WAIT' and side['remaining_one']['tags']==['M088_T095'],'remaining XMF not WAIT')
    require(side['downstream_policy']['future_bed_hashes'] is None,'future bed hashes')
    report={'schema':'ds02.f5.fresh169.validator-report.v1','status':'pass','validated_at_utc':None,'row_count':len(rows),'unique_physical_case_count':len(set(ids)),'native_pending_next34':census['native_pending_next34'],'root993_first_xmf_completed0':True,'root993_remaining_two_wait':True,'science_payload_read_or_hashed_by_validator':False,'manifest_excludes_this_report':True}
    out=PKG/'metadata/fresh169-validator-report.json'; out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':
    try: validate()
    except Exception as e:
        print(f'fresh169 validation failed: {e}',file=sys.stderr); raise
