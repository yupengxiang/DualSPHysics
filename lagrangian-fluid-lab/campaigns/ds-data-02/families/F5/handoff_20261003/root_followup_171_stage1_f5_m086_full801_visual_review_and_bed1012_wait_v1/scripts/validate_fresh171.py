#!/usr/bin/env python3
"""fresh171 verifier: JSON/XML metadata and derived PNGs only; never opens science payloads."""
import hashlib, json
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
M086=PKG/'metadata/fresh171-m086-t085-visual-review.json'
M095=PKG/'metadata/fresh171-m095-render-wait.json'
R1012=PKG/'metadata/fresh171-root1012-pre-dispatch-status.json'
DEDUP=PKG/'metadata/fresh171-accepted217-dedup.json'
EXPECTED={'total':194427,'fixed':158559,'moving':4210,'floating':0,'fluid':31658,'unknown':0}
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            h.update(b)
    return h.hexdigest()
def ok(value,msg):
    if not value: raise AssertionError(msg)
def load(path): return json.loads(path.read_text(encoding='utf-8'))
def check_pointer(p):
    path=Path(p['path']); ok(path.exists(),f'missing {path}'); ok(sha(path)==p['sha256'],f'sha {path}')

def main():
    d=load(M086); ok(d['source_only_package'] and d['no_science_payload_opened_or_hashed_by_source_owner'],'source safety')
    for p in [d['actual_producer']['execution_receipt'],d['actual_producer']['render_report'],d['actual_producer']['bed_report'],d['actual_producer']['bed_receipt'],d['actual_producer']['xmf_manifest'],d['actual_producer']['conversion_report']]: check_pointer(p)
    rec=load(Path(d['actual_producer']['execution_receipt']['path'])); ok(rec['status']=='completed' and rec['returncode']==0,'M086 receipt')
    rr=load(Path(d['render_report']['path'])); ok(rr['frames']==801 and rr['source_frames']==801 and rr['all_frames_rendered'] is True,'801 render')
    ok(rr['actual_times_preserved_exactly'] is True and rr['native_identity_axis_preserved'] is True and rr['nonfinite_active_states']==0,'render integrity')
    for x in rr['frame_diagnostics']:
        ok(x['active']==EXPECTED['total'] and x['missing']==0 and x['identity_axis_preserved'] is True,'frame identity')
        ok(x['finite_positions_active'] is True,'finite position')
        ok(x['type_counts_active']=={'fixed':EXPECTED['fixed'],'moving':EXPECTED['moving'],'floating':EXPECTED['floating'],'fluid':EXPECTED['fluid'],'unknown':EXPECTED['unknown']},'type counts')
        ok(all(v['finite_active'] is True and v['nonfinite_active']==0 for v in x['finite_fields'].values()),'finite fields')
    br=load(Path(d['bed_audit_metadata']['path'])); frames=br['frame_reports']; ok(len(frames)==801,'bed frames')
    for x in frames:
        ok(x['current_valid_type3_fluid_count']==EXPECTED['fluid'],'fluid denominator')
        ok(x['penetration']['one_dp']['count']==0 and x['penetration']['two_dp']['count']==0,'bed diagnostic bins')
        ok(x['uid_tracking']['missing_initial_uid']['count']==0 and x['uid_tracking']['unexpected_current_uid']['count']==0,'uid')
        ok(x['nonfinite_position_current_fluid_count']==0 and x['nonfinite_mass_current_fluid_count']==0,'finite bed state')
        ok(x['bed_domain']['x_outside_exact_profile_domain_count']==0 and x['bed_domain']['y_outside_actual_bed_footprint_with_x_in_domain_count']==0,'footprint')
    ok(d['png_review']['all_34_contact_sheets_reviewed'] is True and len(d['png_review']['all_34_contact_sheets'])==34,'contacts')
    for item in d['png_review']['all_34_contact_sheets']+d['png_review']['event_keyframes']:
        p=Path(item['path']); ok(p.exists() and sha(p)==item['sha256'],f'PNG {p}')
    ok(d['delegated_visual_decision']['decision']=='visual_pass_for_M086_T085_full801','visual decision')
    ok(d['delegated_visual_decision']['case_credit_granted_by_this_review'] is False and d['delegated_visual_decision']['q_n_granted_by_this_review'] is False,'no credit')
    ok(d['scope_separation']['canonical_legacy_source_plan_kept_distinct'] is True,'scope separation')
    w=load(M095); ok(w['status']=='WAIT' and w['completed'] is False and w['visual_review_performed'] is False,'M095 wait')
    r=load(R1012); ok(r['status']=='pre_dispatch_controller_failure' and r['scientific_attempts']==0 and r['bed_reports']==0 and r['case_credit']==0,'1012 pre-dispatch')
    a=load(DEDUP); ok(a['accepted_count']==217 and a['m086_t085_already_accepted'] is True and a['m095_t080_already_accepted'] is True,'accepted dedup')
    print(json.dumps({'status':'passed','case_id':d['case_id'],'frames':801,'contacts':34,'event_keys':d['png_review']['event_keyframes_reviewed'],'m086_decision':d['delegated_visual_decision']['decision'],'m095':'WAIT','root1012_science_attempts':0,'science_payload_opened':False},indent=2))
if __name__=='__main__': main()
