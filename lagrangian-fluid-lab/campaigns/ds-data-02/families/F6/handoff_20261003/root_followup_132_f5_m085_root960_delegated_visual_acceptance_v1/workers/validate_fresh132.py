#!/usr/bin/env python3
"""Metadata and PNG-only validator for F6 fresh132 Root960 visual handoff."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
FORBIDDEN={'.h5','.bi4','.csv','.dat','.vtk','.vtm','.vtu','.pvtu'}
def load(rel): return json.loads((PKG/rel).read_text())
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
def require(cond,msg):
    if not cond: raise SystemExit('FAIL: '+msg)
review=load('metadata/visual-review.json'); closure=load('metadata/chain-closure.json')
png=load('metadata/png-hashes.json'); evidence=load('metadata/evidence-files.json')
require(review['status']=='visual-approved-by-delegated-agent','unexpected visual status')
require(closure['status']==review['status'],'status mismatch')
require(review['case_credit']==0 and closure['case_credit']==0,'case credit must remain zero')
require(review['global_credit_updated_by_agent'] is False,'global credit mutation claim')
require(review['scientific_payload_read_or_hashed_by_reviewer'] is False,'scientific payload read/hash claim')
require(review['agent_personally_viewed_all_contact_sheets'] is True and review['agent_personally_viewed_all_key_frames'] is True,'view evidence incomplete')
require(len(png['contact_sheets'])==34 and [x['index'] for x in png['contact_sheets']]==list(range(34)),'contact sheet inventory')
require(len(png['key_frames'])==9 and [x['frame'] for x in png['key_frames']]==[0,100,200,300,400,500,600,700,800],'keyframe inventory')
for entry in png['contact_sheets']+png['key_frames']:
    p=Path(entry['path']); require(p.exists(),f'missing PNG {p}')
    require(p.suffix.lower()=='.png','non-PNG visual entry')
    require(p.stat().st_size==entry['bytes'],f'PNG size mismatch {p}')
    require(digest(p)==entry['sha256'],f'PNG digest mismatch {p}')
for entry in evidence['files']:
    p=Path(entry['path']); require(p.exists(),f'missing evidence {p}')
    require(p.suffix.lower() not in FORBIDDEN,f'forbidden scientific evidence {p}')
    require(p.stat().st_size==entry['bytes'],f'evidence size mismatch {p}')
    require(digest(p)==entry['sha256'],f'evidence digest mismatch {p}')
require(evidence['scientific_payload_read_or_hashed_by_reviewer'] is False,'evidence payload claim')
render=closure['producer_chain']['render']; require(render['status']=='completed/0','render not completed/0')
receipt=json.loads(Path(render['receipt']['path']).read_text())
require(receipt.get('status')=='completed' and receipt.get('returncode')==0,'render receipt terminal status')
report=json.loads(Path(render['report']['path']).read_text())
require(report['frames']==801 and report['source_frames']==801,'801 frame integrity')
require(report['all_frames_rendered'] is True and report['actual_times_preserved_exactly'] is True,'render integrity flags')
require(report['native_identity_axis_preserved'] is True and report['nonfinite_active_states']==0,'identity/nonfinite flags')
require(closure['scope_separation']['equality_claim']=='none','scope equality claim')
require(closure['lifecycle_disclosure']['final_uid_status']=='not inferred by visual reviewer','UID boundary')
require(closure['scientific_payload_read_or_hashed_by_reviewer'] is False,'closure payload claim')
print('PASS: fresh132 metadata, 34 contact PNGs, 9 keyframe PNGs, Root960 receipt/report, and producer chain validated')
