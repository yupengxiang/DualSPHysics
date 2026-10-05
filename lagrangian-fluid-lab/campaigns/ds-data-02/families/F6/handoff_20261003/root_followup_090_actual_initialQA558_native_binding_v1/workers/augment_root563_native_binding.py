#!/usr/bin/env python3
"""Attach the live Root563 full-native request/receipt paths to fresh090.

This is a metadata-only adapter. It reads Root563 request and execution-receipt
JSON, hashes JSON metadata only, and never opens solver output, BI4, H5, CSV,
DAT, Run.out, or any array payload. It leaves fresh089 immutable.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, shutil
from pathlib import Path
from typing import Any


def sha(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def load(p: Path) -> dict[str,Any]:
    d=json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(d,dict): raise RuntimeError(f'expected JSON object: {p}')
    return d

def dump(p: Path,d: Any) -> None:
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n',encoding='utf-8')

def case_from_file(p: Path) -> str:
    return p.name.removesuffix('-native-request.json')

def receipt_meta(p: Path) -> dict[str,Any]:
    out={'path':str(p),'sha256':None,'status':'not_started','returncode':None,'completed0':False}
    if not p.exists(): return out
    try: d=load(p)
    except (OSError,ValueError):
        out['status']='unreadable'; return out
    out['status']=d.get('status'); out['returncode']=d.get('returncode')
    if d.get('status')=='completed' and d.get('returncode')==0:
        out['completed0']=True; out['sha256']=sha(p)
    return out

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--package',required=True,type=Path)
    ap.add_argument('--handoff563',required=True,type=Path)
    ap.add_argument('--data-f6',required=True,type=Path)
    a=ap.parse_args(); pkg=a.package.resolve(); hand=a.handoff563.resolve(); data=a.data_f6.resolve()
    req_dir=pkg/'qualification'/'requests'
    native563=sorted(hand.glob('*-native-request.json'))
    if len(native563)!=24: raise RuntimeError(f'expected 24 Root563 requests, found {len(native563)}')
    by_case={case_from_file(p):p for p in native563}
    if len(by_case)!=24: raise RuntimeError('duplicate Root563 case IDs')
    map_rows=[]
    root563_cases={}
    for p in native563:
        d=load(p); cid=str(d['case_id']);
        if cid not in by_case: raise RuntimeError(cid)
        attempt=Path(str(d['attempt_root'])); receipt=receipt_meta(attempt/'execution-receipt.json')
        row={'case_id':cid,'request':str(p),'request_sha256':sha(p),'attempt_id':d.get('attempt_id'),'attempt_root':str(attempt),'status':d.get('status'),'execution_allowed':d.get('execution_allowed'),'disabled':d.get('disabled'),'receipt':receipt,'future_outputs':copy.deepcopy(d.get('future_outputs') or {}),'actual_initial_qa':copy.deepcopy(d.get('actual_initial_qa') or {})}
        map_rows.append(row); root563_cases[cid]=row
    map_path=pkg/'metadata'/'root563-native-binding.json'
    mapping={'schema':'ds02.f6.fresh090.root563-native-binding.v1','family_id':'F6','fresh_id':'fresh090','source_native_recipe_fresh089':True,'root563_handoff':str(hand),'case_count':24,'actual_initial_qa_all24_pass':True,'status':'metadata_only_live_native_receipt_binding','no_science_payload_read_or_hash':True,'native_receipt_policy':'Only a Root563 execution-receipt completed/0 is recorded with a JSON receipt SHA; running/missing receipts remain null. Solver output and arrays are never read.','cases':map_rows}
    dump(map_path,mapping); map_sha=sha(map_path)
    # Add Root563 mapping to every effective disabled native request while
    # keeping its no-suffix fresh089 source template disabled/superseded.
    for p in sorted(req_dir.glob('*.json')):
        d=load(p); cid=str(d['case_id']); row=root563_cases[cid]; rec=row['receipt']
        d['actual_root563_native_request']={'request':row['request'],'request_sha256':row['request_sha256'],'attempt_id':row['attempt_id'],'attempt_root':row['attempt_root'],'execution_receipt':rec['path'],'execution_receipt_sha256':rec['sha256'],'receipt_status':rec['status'],'receipt_returncode':rec['returncode'],'completed0':rec['completed0'],'future_outputs':row['future_outputs']}
        d['actual_root563_native_binding']=str(map_path); d['actual_root563_native_binding_sha256']=map_sha
        d['superseded_by_actual_root563']=True
        d['status']='source_only_disabled_root563_actual_request_bound'
        d['disabled_reason']='fresh090 metadata only; Root563 is the already registered Root230 native attempt. Do not launch the no-suffix fresh090 template; wait for the actual Root563 receipt completed/0 before FloatingInfo state0.'
        d['future_outputs']={'native_execution_receipt':rec['path'],'native_execution_receipt_sha256':rec['sha256'],'native_data_root':str(Path(row['future_outputs'].get('native_solver_output',row['attempt_root']+'/solver_output'))/'data'),'native_frames':241,'floatinginfo_state0':None,'typed_conversion':None}
        dump(p,d)
    # Rebind QA binding endpoint rows with Root563 metadata.
    qbp=pkg/'qa'/'initial-native-qa-root558-binding.json'; qb=load(qbp)
    for e in qb['endpoints']:
        row=root563_cases[e['case_id']]
        e['actual_root563_native_request']=row['request']; e['actual_root563_native_request_sha256']=row['request_sha256']; e['actual_root563_attempt_id']=row['attempt_id']; e['actual_root563_attempt_root']=row['attempt_root']; e['actual_root563_receipt']=row['receipt']['path']; e['actual_root563_receipt_sha256']=row['receipt']['sha256']; e['actual_root563_receipt_status']=row['receipt']['status']; e['actual_root563_receipt_returncode']=row['receipt']['returncode']; e['actual_root563_completed0']=row['receipt']['completed0']
    qb['root563_native_binding']=str(map_path); qb['root563_native_binding_sha256']=map_sha; qb['root563_live_request_policy']='Root563 request/attempt paths are authoritative; no-suffix fresh089/fresh090 native outputs are not used.'
    dump(qbp,qb)
    # State0 binding: its per-case native source is Root563, and all receipt
    # hashes remain null unless a JSON execution receipt is completed/0.
    sbp=pkg/'floatinginfo'/'state0-binding.json'; sb=load(sbp)
    for c in sb['cases']:
        row=root563_cases[c['case_id']]; rd=load(Path(row['request']))
        fut=rd.get('future_outputs') or {}; attempt=Path(row['attempt_root'])
        c['native_request']=row['request']; c['native_request_sha256']=row['request_sha256']; c['native_data']=str(Path(str(fut.get('native_solver_output',attempt/'solver_output')))/'data'); c['run_out']=str(attempt/'solver_output'/'Run.out'); c['solver_receipt']=row['receipt']['path']; c['solver_receipt_sha256']=row['receipt']['sha256']; c['solver_status_snapshot']=row['receipt']['status']; c['solver_returncode_snapshot']=row['receipt']['returncode']; c['state0_future_outputs']['audit_sha256']=None
    sb['native_qualification_requests_dir']=str(hand); sb['root563_native_binding']=str(map_path); sb['root563_native_binding_sha256']=map_sha; sb['actual_native_receipts_completed0_count']=sum(x['receipt']['completed0'] for x in root563_cases.values()); sb['actual_native_receipts_pending_count']=sum(not x['receipt']['completed0'] for x in root563_cases.values()); sb['status']='source_only_disabled_waiting_actual_root563_full241_then_state0'; sb['future_hashes_null']=True
    dump(sbp,sb); sb_sha=sha(sbp)
    srp=pkg/'floatinginfo'/'state0-request.json'; sr=load(srp); sr['binding_sha256']=sb_sha; sr['root563_native_binding']=str(map_path); sr['root563_native_binding_sha256']=map_sha; sr['status']='source_only_disabled_waiting_actual_root563_full241_then_state0'; sr['disabled_reason']='disabled until every Root563 native execution receipt is terminal completed/0; then run the independent per-case FloatingInfo state0 audit. V0=0 is not angular proof.'
    # Do not rewrite future input hashes for solver payloads. They remain null
    # or producer-bound from source, and this source package does not read them.
    dump(srp,sr)
    review_path=pkg/'metadata'/'root558-review.json'; review=load(review_path); review['root563_native_binding']=str(map_path); review['root563_native_binding_sha256']=map_sha; review['root563_completed0_count']=sum(x['receipt']['completed0'] for x in root563_cases.values()); review['root563_pending_count']=sum(not x['receipt']['completed0'] for x in root563_cases.values()); review['native_receipt_policy']='Root563 actual request/attempt paths are authoritative; no-suffix source089/fresh090 attempts are not treated as actual.'; dump(review_path,review)
    # Add a copy of this adapter under workers for later metadata-only refresh.
    dest=pkg/'workers'/'augment_root563_native_binding.py'; shutil.copy2(Path(__file__).resolve(),dest); dest.chmod(0o755)
    # Update manifest fields/file inventory without claiming solver completion.
    mp=pkg/'manifest.json'; mf=load(mp); mf['root563_native_binding']=str(map_path); mf['root563_completed0_count']=sum(x['receipt']['completed0'] for x in root563_cases.values()); mf['root563_pending_count']=sum(not x['receipt']['completed0'] for x in root563_cases.values()); mf['claim_boundary']='Root558 initial QA completed/0 metadata and Root563 live native request paths are bound; native receipts, FloatingInfo state0, typed/XMF/render, visual, Q-N, precision, and production status remain actual-runtime dependent'; mf['files']=sorted(str(x.relative_to(pkg)) for x in pkg.rglob('*') if x.is_file() and x.name!='manifest.json'); dump(mp,mf)
    print(json.dumps({'case_count':24,'root563_completed0':sum(x['receipt']['completed0'] for x in root563_cases.values()),'root563_pending':sum(not x['receipt']['completed0'] for x in root563_cases.values()),'map':str(map_path)},sort_keys=True))
    return 0
if __name__=='__main__': raise SystemExit(main())
