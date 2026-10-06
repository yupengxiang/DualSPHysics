#!/usr/bin/env python3
"""Fresh163 correction validator; derives omission limits from JSON metadata only."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DENIED={'.h5','.hdf5','.bi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
def safe_json(p):
    assert p.suffix.lower() not in DENIED, f'payload read denied: {p}'
    return json.loads(p.read_text())
def sha(p):
    assert p.suffix.lower() not in DENIED, f'payload hash denied: {p}'
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def main():
    source=safe_json(ROOT/'metadata/source-binding.json')
    deriv=safe_json(ROOT/'metadata/producer-limits-derived.json')
    closure=safe_json(ROOT/'metadata/limit-closure.json')
    visual=safe_json(ROOT/'metadata/visual-review.json')
    decision=safe_json(next((ROOT/'decisions').glob('*-decision.json')))
    old_chain=safe_json(Path(source['source_chain']['path']))
    report_path=Path(source['actual_conversion_report']['path']); report=safe_json(report_path)
    assert source['source_package_id']=='fresh162' and source['source_commit']=='d36c69b50c2e11ba6c721a7e310cc306c0aa1ae8'
    assert sha(report_path)==source['actual_conversion_report']['sha256']=='52ffafc0bd4a0412f35d03d285719e4ec9b8a68a96138667b6acdbc9cc0897e3'
    ledger=report['lifecycle']['frame_summary']; life=report['lifecycle']
    derived={'frame_count':len(ledger),'frames_with_any_missing_particles':sum(1 for x in ledger if x.get('missing_particles',0)>0),'particle_frame_omissions_sum':sum(x.get('missing_particles',0) for x in ledger),'maximum_missing_particles_single_frame':max(x.get('missing_particles',0) for x in ledger),'final_missing_particles':ledger[-1].get('missing_particles'),'first_missing_frame':next((x['frame'] for x in ledger if x.get('missing_particles',0)>0),None),'first_missing_frame_by_type':life.get('first_missing_frame_by_type'),'transient_missing_frame_count':life.get('transient_missing_frame_count'),'transient_missing_by_type_frame_events':life.get('transient_missing_by_type_frame_events'),'source_report_sha256':source['actual_conversion_report']['sha256'],'source_report_path':str(report_path),'derived_from':'conversion-report.lifecycle.frame_summary','scientific_payload_read_or_hashed':False}
    assert len(ledger)==401 and derived==deriv['derived'] | {'frame_count':401,'first_missing_frame':165,'transient_missing_frame_count':236,'transient_missing_by_type_frame_events':{'0':0,'1':0,'2':0,'3':1051},'source_report_sha256':source['actual_conversion_report']['sha256'],'source_report_path':str(report_path),'derived_from':'conversion-report.lifecycle.frame_summary','scientific_payload_read_or_hashed':False}
    expected={'frames_with_any_missing_particles':236,'particle_frame_omissions_sum':1051,'maximum_missing_particles_single_frame':7,'final_missing_particles':7,'first_missing_frame_by_type':{'3':165},'cause':'unknown; preserve producer lifecycle counts and do not infer final UID causality'}
    # Compare every producer-limit block: corrected decision, corrected visual, and unchanged fresh162 chain render-integrity.
    for label,block in [('decision',decision['producer_limits']),('visual_review',visual['producer_limits'])]: assert block==expected, label
    chain_block=old_chain['render_integrity']
    assert {k:chain_block[k] for k in ('frames_with_any_missing_particles','particle_frame_omissions_sum','maximum_missing_particles_single_frame','final_missing_particles')}=={k:expected[k] for k in ('frames_with_any_missing_particles','particle_frame_omissions_sum','maximum_missing_particles_single_frame','final_missing_particles')}
    assert chain_block['first_missing_frame']==165
    assert closure['derived_limits']==expected and closure['blocks']['decision']==expected and closure['blocks']['visual_review']==expected
    assert closure['blocks']['source_chain_render_integrity']=={'frames_with_any_missing_particles':236,'particle_frame_omissions_sum':1051,'maximum_missing_particles_single_frame':7,'final_missing_particles':7,'first_missing_frame':165}
    assert decision['case_credit']==0 and visual['case_credit']==0 and decision['global_acceptance'] is False and visual['global_acceptance'] is False
    assert source['published_png_evidence']['contact_sheets']==17 and source['published_png_evidence']['key_frames']==9 and Path(source['published_png_evidence']['path']).exists()
    assert source['scope_roles']['scope_equality_claimed'] is False
    assert source['actual_conversion_report']['raw_science_payload_opened_or_hashed'] is False
    print('fresh163 validator PASS: actual frame ledger derived and matched decision/visual/chain blocks; fresh162 immutable; no science payload IO')
if __name__=='__main__': main()
