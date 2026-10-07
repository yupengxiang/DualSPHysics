#!/usr/bin/env python3
"""Read-only validator for the fresh206 personal visual review package.

The validator may stat published PNGs and read producer-declared PNG metadata,
but never hashes or opens PNG bytes and never touches scientific payloads.
"""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
META=HERE/'metadata/m106-t085-personal-visual-review.json'
MANIFEST=HERE/'package-manifest.json'
BANNED=('.h5','.bi4','.dat','.csv','.vtk','.vtu')

def load(p):
    return json.loads(p.read_text())

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()

def fail(msg):
    raise SystemExit('FAIL: '+msg)

def main():
    m=load(META)
    if m.get('schema')!='ds02.f6.fresh206.f5.m106-t085.personal-visual-review.v1': fail('schema')
    ident=m['identity']
    if ident.get('family_id')!='F5' or ident.get('case_id')!='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M106_T085_NEXT34': fail('case identity')
    if ident.get('physical_case_id')!='F5_COMPACT_RUNUP_RECOVERY_C082S1_M106_T085': fail('physical identity')
    if m['assignment_roles'] != {'assigned_family':'F6','actual_family':'F5','case_credit':0,'role_separation_preserved':True}: fail('assignment roles')
    method=m['review_method']
    if method.get('tool')!='functions.view_image' or method.get('contact_sheets_viewed')!=34 or method.get('key_frames_viewed')!=9: fail('review method')
    if not method.get('visual_review_complete'): fail('visual review incomplete')
    if not method.get('no_science_payload_opened_or_hashed') or not method.get('no_png_sha256_computed_by_source_agent'): fail('boundary method')
    ct=m['counts_and_time']
    if (ct['frames'],ct['expected_particles'],ct['dimension'])!=(801,194427,3): fail('counts/shape')
    if (ct['fixed'],ct['moving'],ct['floating'],ct['fluid'])!=(158559,4210,0,31658): fail('particle counts')
    if ct['actual_time_first_s']!=0.0 or ct['actual_time_last_s']!=16.00014041930218 or not ct['time_is_actual_producer_evidence'] or not ct['nominal_end_not_substituted']: fail('time')
    sr=m['scope_roles']
    if sr['canonical_native_physical_condition_sha256']!='0c0013f50e2bca5bee381eadcf19a031f1a4463e550fffc02d41097f911f46bb': fail('native scope')
    if sr['typed_converter_legacy_scope_sha256']!='61d53c17e86f01264f08e92fa855f2d0056b9d834bb4509083267db1afb4ec83': fail('typed scope')
    if sr['source_definition_xml_sha256']!='6562d493dde651c415ad5eef9cf9aaae6fa7938ee21ab4e10f99ef398fa84fac': fail('SourceDef scope')
    if sr['source_plan_json_sha256']!='366adc5200604490871116a0a5b8503c9bef4bfb1e72195df94995605fa7d324': fail('source plan')
    if sr['native_request_field_presence'] != {'physical_condition_sha256':True,'source_definition_sha256':False,'source_plan_condition_sha256':False,'source_plan_physical_condition_sha256':True}: fail('native field mask')
    if sr['xmf_manifest_field_presence'] != {'source_definition_sha256':True,'source_plan_condition_sha256':False,'source_plan_physical_condition_sha256':True}: fail('XMF field mask')
    ev=m['visual_evidence']
    cs=ev['contact_sheets']; keys=ev['key_frames']
    if len(cs)!=34 or len(keys)!=9 or not ev['all_contact_sheets_viewed'] or not ev['all_key_frames_viewed']: fail('visual cardinality')
    if [x['relative_path'] for x in cs] != [f'all_frames_{i:03d}.png' for i in range(34)]: fail('contact order')
    if [x['frame_index'] for x in keys] != [0,100,200,300,400,500,600,700,800]: fail('key order')
    for item in cs+keys:
        p=Path(item['path'])
        if p.suffix.lower()!='.png' or not p.exists(): fail('missing PNG '+str(p))
        if p.stat().st_size != item['bytes_at_review']: fail('PNG stat drift '+str(p))
        if item.get('sha256_computed_by_source_agent') is not False: fail('PNG self hash flag')
        if item.get('producer_declared_sha256') is None or item.get('producer_declared_bytes') != item['bytes_at_review']: fail('producer PNG declaration '+str(p))
    chain=m['producer_chain']
    if chain['render_execution_receipt']['status']!='completed' or chain['render_execution_receipt']['sha256'] is None: fail('render receipt')
    if chain['render_report']['frames']!=801 or not chain['render_report']['all_frames_rendered'] or not chain['render_report']['actual_times_preserved_exactly']: fail('render report')
    if chain['publish_receipt']['status']!='published_after_atomic_rename': fail('publish status')
    if chain['root_qi']['status']!='completed_once_by_root' or not Path(chain['root_qi']['path']).exists(): fail('QI proof')
    lim=m['limitations_and_boundary']
    if any(lim[k] for k in ('strict_containment_claim','subdp_or_numerical_claim','q_n','q_e','science_payload_opened_or_hashed','new_jobs_started','shared_state_written','rerendered','png_self_hash_by_source_agent')): fail('boundary/claim')
    if lim['case_credit']!=0: fail('credit')
    # Validate only JSON/XML/Python/text metadata refs. PNG is intentionally excluded from this loop.
    for ref in m['metadata_refs']:
        p=Path(ref['path'])
        if any(str(p).lower().endswith(s) for s in BANNED) or p.suffix.lower() in {'.png','.jpg','.jpeg'}: fail('payload/image ref in metadata refs '+str(p))
        if not p.exists(): fail('missing metadata ref '+str(p))
        if sha(p)!=ref['sha256']: fail('metadata SHA drift '+str(p))
    # Check package manifest itself and package files; no source mutation is performed.
    man=load(MANIFEST)
    for item in man['files']:
        p=HERE/item['path']
        if not p.exists(): fail('missing package file '+str(p))
        if sha(p)!=item['sha256']: fail('package SHA drift '+str(p))
    print(f'PASS fresh206: viewed {len(cs)} contact sheets + {len(keys)} keyframes; render completed/0; PNGs stat-checked only')
    return 0

if __name__=='__main__': sys.exit(main())
