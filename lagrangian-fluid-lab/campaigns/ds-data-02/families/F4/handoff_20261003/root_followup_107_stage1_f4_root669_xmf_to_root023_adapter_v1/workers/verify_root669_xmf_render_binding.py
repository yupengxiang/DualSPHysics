#!/usr/bin/env python3
"""Metadata-only Root669 -> Root023 preflight.

No scientific payload or referenced binary is opened here. Root's registered
worker supplies JSON metadata records after it independently reads/validates
its own receipt, XMF manifest, and typed648 report.
"""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from typing import Any,Mapping
HEX64=re.compile(r'^[0-9a-fA-F]{64}$')
WAIT='WAIT_ROOT669_XMF_COMPLETION'
READY='READY_FOR_ROOT023'

def fail(msg): raise ValueError(msg)
def digest(v,field):
    if not isinstance(v,str) or not HEX64.fullmatch(v): fail(f'{field} must be a 64-hex digest')
    return v
def absstr(v,field):
    if not isinstance(v,str) or not Path(v).is_absolute(): fail(f'{field} must be an absolute string path')
    return v
def record(v,field,*,marker=None,allow_null_sha=False):
    if not isinstance(v,Mapping): fail(f'{field} must be a metadata record')
    p=absstr(v.get('path'),field+'.path')
    if marker and marker not in p.lower(): fail(f'{field}.path is not bound to {marker}: {p}')
    if v.get('sha256') is None and allow_null_sha: return p
    digest(v.get('sha256'),field+'.sha256'); return p

def physical(binding,*,ready=False):
    scope=binding.get('physical_scope')
    if not isinstance(scope,Mapping): fail('physical_scope missing')
    if scope.get('source_owner_hash_reused') is not False: fail('source-owner hash reuse is not allowed')
    legacy=scope.get('legacy_owner_scope_sha256'); actual=scope.get('actual_scope_sha256')
    if legacy is not None: digest(legacy,'physical_scope.legacy_owner_scope_sha256')
    if actual is not None: digest(actual,'physical_scope.actual_scope_sha256')
    if ready and actual is None: fail('ready record needs actual_scope_sha256')
    digest(binding.get('physical_condition_sha256'),'physical_condition_sha256')
    owner=binding.get('physical_binding')
    if not isinstance(owner,Mapping): fail('physical_binding missing')
    absstr(owner.get('path'),'physical_binding.path'); digest(owner.get('sha256'),'physical_binding.sha256')
    return scope

def future_record(v,field):
    if not isinstance(v,Mapping): fail(f'{field} must be a WAIT record')
    absstr(v.get('path'),field+'.path')
    if v.get('sha256') is not None: fail(f'{field}.sha256 must remain null before Root669 executes')
    if str(v.get('status','')).upper() not in {'WAIT','PENDING','WAIT_ROOT669_XMF_COMPLETION'}: fail(f'{field} is not WAIT')

def typed648_ready(v:Mapping[str,Any], expected_condition:str):
    if not isinstance(v,Mapping): fail('typed648 actual metadata missing')
    receipt=v.get('receipt') or v.get('typed_receipt')
    if not isinstance(receipt,Mapping) or receipt.get('status')!='completed' or receipt.get('returncode')!=0: fail('typed648 receipt is not completed/0')
    record(receipt,'typed648.receipt')
    report=v.get('conversion_report') or v.get('report')
    if not isinstance(report,Mapping) or report.get('conversion_status')!='completed' or report.get('frames')!=1201: fail('typed648 conversion report is not completed/1201')
    if report.get('particles',0)<=0: fail('typed648 particles are not positive')
    if not isinstance(report.get('partvtk_validation'),Mapping) or report['partvtk_validation'].get('all_passed') is not True: fail('typed648 PartVTK report did not pass')
    if report.get('solver_dimension',{}).get('solver_dimension')!=3: fail('typed648 solver dimension is not 3')
    report_condition=report.get('physical_condition_sha256', expected_condition)
    digest(report_condition,'typed648.report.physical_condition_sha256')
    if report_condition!=expected_condition: fail('typed648 physical scope differs from binding')
    h5=next((report.get(k) for k in ('output_sha256','producer_h5_sha256','trajectory_h5_sha256','h5_sha256') if report.get(k) is not None),None)
    digest(h5,'typed648.producer_h5_sha256')
    traj=v.get('trajectory_h5') or v.get('trajectory')
    if traj is not None: record(traj,'typed648.trajectory_h5')
    native=v.get('native_receipt')
    if native is not None: record(native,'typed648.native_receipt')
    scope=v.get('physical_scope')
    if not isinstance(scope,Mapping) or scope.get('source_owner_hash_reused') is not False or scope.get('actual_scope_sha256') is None: fail('typed648 lacks actual separate physical scope')
    digest(scope['actual_scope_sha256'],'typed648.physical_scope.actual_scope_sha256')
    return {'h5_sha256':h5,'frames':1201,'particles':report['particles']}

def xmf_ready(receipt:Mapping[str,Any],manifest:Mapping[str,Any],expected_condition:str,typed_h5:str):
    if not isinstance(receipt,Mapping) or receipt.get('status')!='completed' or receipt.get('returncode')!=0: fail('Root669 execution receipt is not completed/0')
    record(receipt,'root669.execution_receipt',marker='root669')
    digest(receipt.get('request_sha256'),'root669.execution_receipt.request_sha256')
    if not isinstance(manifest,Mapping) or manifest.get('frames')!=1201 or manifest.get('particles',0)<=0: fail('Root669 manifest lacks 1201 positive-particle metadata')
    if manifest.get('source_h5_read_only') is not True: fail('Root669 manifest missing source_h5_read_only=true')
    h5=manifest.get('source_h5_sha256'); digest(h5,'root669.manifest.source_h5_sha256')
    if h5!=typed_h5: fail('Root669 manifest H5 digest does not match typed648 producer report')
    xdmf=manifest.get('xdmf') or manifest.get('case_xmf')
    absstr(xdmf,'root669.manifest.xdmf')
    if manifest.get('uniform_grid_count')!=1201: fail('Root669 manifest lacks 1201 Uniform grid metadata')
    if manifest.get('n3_shapes') not in ({'positions':'N 3','velocity':'N 3'}, {'position':'N 3','velocity':'N 3'}): fail('Root669 manifest lacks N3 position/velocity metadata')
    condition=manifest.get('physical_condition_sha256',expected_condition); digest(condition,'root669.manifest.physical_condition_sha256')
    if condition!=expected_condition: fail('Root669 manifest physical condition differs')
    return {'frames':manifest['frames'],'particles':manifest['particles'],'h5_sha256':h5}

def preflight_root669_xmf_binding(binding:Mapping[str,Any],*,typed648:Mapping[str,Any]|None=None,xmf_receipt:Mapping[str,Any]|None=None,xmf_manifest:Mapping[str,Any]|None=None)->dict[str,Any]:
    if not isinstance(binding,Mapping): fail('binding must be an object')
    if binding.get('expected_frames',1201)!=1201 and binding.get('expected_frames') is not None: fail('expected_frames must be 1201')
    case=binding.get('case_id') or binding.get('physical_case_id')
    if not isinstance(case,str) or not case: fail('case_id missing')
    plan=binding.get('root669_plan')
    if not isinstance(plan,Mapping): fail('root669_plan missing')
    record(plan,'root669_plan')
    digest(plan.get('sha256'),'root669_plan.sha256')
    physical(binding,ready=typed648 is not None or xmf_receipt is not None or xmf_manifest is not None)
    for k in ('root669_request','root669_binding','root669_execution_receipt','root669_xmf_manifest','root669_case_xmf'):
        future_record(binding.get(k),k)
    if typed648 is None and xmf_receipt is None and xmf_manifest is None:
        return {'status':WAIT,'case_id':case}
    if typed648 is None or xmf_receipt is None or xmf_manifest is None: fail('ready Root669 record needs typed648, receipt, and manifest metadata together')
    t=typed648_ready(typed648,binding['physical_condition_sha256'])
    x=xmf_ready(xmf_receipt,xmf_manifest,binding['physical_condition_sha256'],t['h5_sha256'])
    return {'status':READY,'case_id':case,'frames':x['frames'],'particles':x['particles'],'h5_sha256':x['h5_sha256']}

def preflight_render_binding(binding:Mapping[str,Any],**kwargs)->dict[str,Any]:
    if not isinstance(binding,Mapping): fail('render binding must be an object')
    if binding.get('case_xmf') is not None or binding.get('manifest') is not None: fail('disabled render binding cannot claim future XMF paths')
    return preflight_root669_xmf_binding(binding,**kwargs)

def _base():
    return {'case_id':'SYNTHETIC','physical_case_id':'SYNTHETIC','physical_condition_sha256':'c'*64,'physical_scope':{'legacy_owner_scope_sha256':'a'*64,'actual_scope_sha256':None,'source_owner_hash_reused':False},'physical_binding':{'path':'/metadata/owner.json','sha256':'d'*64},'root669_plan':{'path':'/metadata/plan.json','sha256':'e'*64},'root669_request':{'path':'/metadata/request.json','sha256':None,'status':'WAIT'},'root669_binding':{'path':'/metadata/binding.json','sha256':None,'status':'WAIT'},'root669_execution_receipt':{'path':'/data/root669/execution-receipt.json','sha256':None,'status':'WAIT'},'root669_xmf_manifest':{'path':'/data/root669/xmf/manifest.json','sha256':None,'status':'WAIT'},'root669_case_xmf':{'path':'/data/root669/xmf/case.xmf','sha256':None,'status':'WAIT'}}

def synthetic_tests():
    b=_base(); assert preflight_render_binding(b)['status']==WAIT; checks=['valid WAIT/null Root669 record']
    bad=_base(); bad['root669_execution_receipt']['sha256']='f'*64
    try: preflight_render_binding(bad)
    except ValueError: checks.append('future receipt hash rejected')
    else: raise AssertionError('future receipt hash accepted')
    bad=_base(); bad['physical_scope']['source_owner_hash_reused']=True
    try: preflight_render_binding(bad)
    except ValueError: checks.append('source-owner scope reuse rejected')
    else: raise AssertionError('scope reuse accepted')
    ready=_base(); ready['physical_scope'].update(actual_scope_sha256='c'*64,status='actual_confirmed')
    typed={'receipt':{'path':'/data/root648/execution-receipt.json','sha256':'1'*64,'status':'completed','returncode':0},'conversion_report':{'path':'/data/root648/conversion-report.json','sha256':'2'*64,'conversion_status':'completed','frames':1201,'particles':83233,'partvtk_validation':{'all_passed':True},'solver_dimension':{'solver_dimension':3},'output_sha256':'3'*64,'physical_condition_sha256':'c'*64},'trajectory_h5':{'path':'/data/root648/trajectory.h5','sha256':'3'*64},'physical_scope':{'actual_scope_sha256':'c'*64,'source_owner_hash_reused':False}}
    receipt={'path':'/data/root669/execution-receipt.json','sha256':'4'*64,'status':'completed','returncode':0,'request_sha256':'5'*64}
    manifest={'frames':1201,'particles':83233,'source_h5_read_only':True,'source_h5_sha256':'3'*64,'xdmf':'/data/root669/xmf/case.xmf','uniform_grid_count':1201,'n3_shapes':{'positions':'N 3','velocity':'N 3'},'physical_condition_sha256':'c'*64}
    out=preflight_render_binding(ready,typed648=typed,xmf_receipt=receipt,xmf_manifest=manifest); assert out['status']==READY; checks.append('completed Root648+Root669 closure accepted')
    badm=dict(manifest); badm['frames']=1200
    try: preflight_render_binding(ready,typed648=typed,xmf_receipt=receipt,xmf_manifest=badm)
    except ValueError: checks.append('wrong XMF frame count rejected')
    else: raise AssertionError('wrong frame count accepted')
    return checks

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--binding',type=Path); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test: print('fresh107 synthetic preflight: PASS ('+'; '.join(synthetic_tests())+')'); return
    if not a.binding: ap.error('--binding is required unless --self-test')
    print(json.dumps(preflight_render_binding(json.loads(a.binding.read_text(encoding='utf-8')),indent=2),sort_keys=True))
if __name__=='__main__': main()
