#!/usr/bin/env python3
"""Read-only validator for fresh164's source178 primary-evidence correction."""
from __future__ import annotations
import copy, hashlib, json, re
from pathlib import Path

PKG=Path(__file__).resolve().parents[1]
CAT=PKG/'metadata/dynamic-entry-catalog-corrected.json'
ATT=PKG/'metadata/source178-input-attestation.json'
SUMMARY=PKG/'metadata/correction-summary.json'
SRC_ROOT=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_178_f2_f3_f6_first24_dynamic_entry_catalog_v1')
SRC_CAT=SRC_ROOT/'metadata/dynamic-entry-catalog.json'
FORBIDDEN=('.h5','.bi4','.csv','.dat','.vtk','.vtu','.pvsm','.gif')
COMMIT='d2f3c31e1bf694007a79d4b462c003f57e2b3fdb'

def fail(msg): raise SystemExit('fresh164 validation failed: '+msg)
def load(p):
    try: return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception as e: fail(f'cannot load {p}: {e}')
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
def is_sha(x): return isinstance(x,str) and re.fullmatch(r'[0-9a-f]{64}',x) is not None
def walk(v,loc='$'):
    if isinstance(v,dict):
        for k,x in v.items(): yield from walk(x,loc+'.'+str(k))
    elif isinstance(v,list):
        for i,x in enumerate(v): yield from walk(x,loc+f'[{i}]')
    else: yield loc,v

def primary_list(decision,kind):
    vp=decision.get('verified_PNG_hashes') or {}
    if kind=='contact':
        for v in (decision.get('contact_sheets'),vp.get('contact_sheets')):
            if isinstance(v,list) and v: return v
    else:
        for v in (decision.get('keyframes'),decision.get('key_frames'),decision.get('key_events'),vp.get('keyframes'),vp.get('key_frames')):
            if isinstance(v,list) and v: return v
    return []

def direct_report_outputs(report, row, decision):
    out=report.get('outputs',{})
    paths=out.get('contact_sheets') or []
    c={x['path'] for x in row['contact_png_refs']}
    if paths and c != set(paths): fail(row['case_id']+' contacts differ from own report outputs')
    direct=primary_list(decision,'contact')
    if direct and c != {x.get('path') for x in direct}: fail(row['case_id']+' contacts differ from accepted own refs')
    k={x['path'] for x in row['key_png_refs']}
    directk=primary_list(decision,'key')
    if directk and k != {x.get('path') for x in directk}: fail(row['case_id']+' keys differ from accepted own refs')
    root=Path(row['actual_render_report']['ref']['path']).parent
    for name,vals in [('contact',c),('key',k)]:
        if not vals: fail(row['case_id']+' has no primary '+name+' PNG refs')
        if any(not Path(x).is_relative_to(root) for x in vals): fail(row['case_id']+' has foreign primary '+name+' PNG')
        for x in vals:
            ref=next(z for z in row['contact_png_refs']+row['key_png_refs'] if z['path']==x)
            if not is_sha(ref.get('sha256')): fail(row['case_id']+' primary PNG attestation SHA')

d=load(CAT); att=load(ATT); summary=load(SUMMARY); src=load(SRC_CAT)
if d.get('schema')!='ds02.f3.fresh164.source178-first24-dynamic-entry-catalog-correction.v1': fail('catalog schema')
if att.get('source178_commit')!=COMMIT: fail('source178 commit')
if att.get('catalog_sha256') != sha(SRC_CAT): fail('source178 catalog SHA changed')
if src.get('rows') and len(src['rows'])!=72: fail('source178 row count')
if len(d.get('rows',[]))!=72: fail('corrected row count')
if summary.get('rows')!=72 or summary.get('changed_rows') is None: fail('summary')
if d.get('membership') != src.get('membership'): fail('membership changed')
if d.get('authorities') != src.get('authorities'): fail('authorities changed')
# The accepted decision and membership identity/order are inherited byte-for-byte semantically.
for old,new in zip(src['rows'],d['rows']):
    for k in ('family_id','case_id','physical_case_id','first8_member','first24_member','accepted_decision','source_declared_roles','native_request_role_snapshot'):
        if old.get(k)!=new.get(k): fail(f'{new.get("case_id")} inherited field changed: {k}')
    if new.get('actual_render_report',{}).get('ref',{}).get('path','').endswith('.owner.json'): fail(new['case_id']+' owner JSON used as render report')
    if Path(new.get('actual_xmf_manifest',{}).get('path','')).name!='manifest.json': fail(new['case_id']+' non-manifest primary XMF ref')
    if new.get('fresh164_correction_status') not in ('corrected_primary_refs','source178_primary_refs_revalidated'): fail(new['case_id']+' correction status')
    report_ref=new['actual_render_report']['ref']; manifest_ref=new['actual_xmf_manifest']; xmf_ref=new['actual_xmf_xml']
    if not is_sha(report_ref.get('sha256')) or sha(report_ref['path'])!=report_ref['sha256']: fail(new['case_id']+' render report SHA')
    if not is_sha(manifest_ref.get('sha256')) or sha(manifest_ref['path'])!=manifest_ref['sha256']: fail(new['case_id']+' manifest SHA')
    report=load(report_ref['path']); manifest=load(manifest_ref['path'])
    if report.get('manifest_sha256') != manifest_ref['sha256']: fail(new['case_id']+' report manifest_sha256 mismatch')
    if new['primary_visual_evidence']['render_report_manifest_sha256'] != manifest_ref['sha256']: fail(new['case_id']+' primary binding SHA')
    if report.get('xdmf'):
        if xmf_ref['path'] != report.get('xdmf'): fail(new['case_id']+' XMF path differs from own report')
        if report.get('xdmf_sha256_after') and xmf_ref['sha256'] != report.get('xdmf_sha256_after'): fail(new['case_id']+' XMF SHA differs from own report')
    if Path(xmf_ref['path']).suffix.lower()!='.xmf': fail(new['case_id']+' XMF suffix')
    direct_report=report_ref['path']
    # Explicit regression guards for the source178 bug.
    if new['case_id'] in ('F3_STAGE1_DP006_P1000_AY0540','F3_STAGE1_DP006_P1000_AY0590'):
        if 'F3_CELL3_LONG_DP006_AY0P50' in direct_report or 'actual-converter-scope.owner.json' in manifest_ref['path']:
            fail(new['case_id']+' nested historical evidence remained primary')
        if new['case_id'].split('_')[-1] not in direct_report: fail(new['case_id']+' own render path')
    direct_report_outputs(report,new,load(new['accepted_decision']['path']))
    # Context refs are retained but never marked primary unless they are exact primary evidence.
    primary={ (x.get('path'),x.get('sha256') or x.get('declared_sha256')) for x in new['contact_png_refs']+new['key_png_refs']+[report_ref,manifest_ref,xmf_ref] }
    for ref in new.get('all_allowed_refs',[]):
        k=(ref.get('path'),ref.get('sha256') or ref.get('declared_sha256'))
        if bool(ref.get('primary')) != (k in primary): fail(new['case_id']+' context/primary role mismatch')
        if k not in primary and ref.get('role')!='historical_or_context': fail(new['case_id']+' historical ref not separated')
    if new['primary_visual_evidence'].get('primary_refs_case_local') is not True or new['primary_visual_evidence'].get('historical_or_context_refs_separated') is not True: fail(new['case_id']+' primary guard')
# Package metadata itself must not expose scientific payload paths. Policy suffix literals are allowed.
for label,obj in [('catalog',d),('attestation',att),('summary',summary)]:
    for loc,v in walk(obj):
        if isinstance(v,str) and v.lower().endswith(FORBIDDEN) and 'forbidden_payload_suffixes' not in loc:
            fail(f'{label}{loc} exposes scientific payload path')
# Membership subset invariants from source178 remain explicit.
if not d.get('membership',{}).get('F3',{}).get('first8_subset_actual24_subset_current37_subset_final48'): fail('F3 membership invariant')
if not d.get('membership',{}).get('F2',{}).get('first8_subset_first24_subset_final48'): fail('F2 membership invariant')
if not d.get('membership',{}).get('F6',{}).get('first8_subset_actual_delivery24'): fail('F6 membership invariant')
print(f'fresh164 PASS: 72 rows; {len(d["correction_audit"]["changed_primary_rows"])} primary evidence corrections; report/manifest SHA and case-local PNG guards valid')
