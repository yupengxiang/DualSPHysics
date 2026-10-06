#!/usr/bin/env python3
"""Metadata-only structural validator for fresh154."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parents[1]; AUDIT=HERE/'metadata/registered-render-handle-audit.json'; SCI={'.h5','.bi4','.csv','.dat','.vtk','.xmf','.hdf5','.png'}
def sha(p):
 assert p.suffix.lower() not in SCI, f'payload hash refused: {p}'
 return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 d=json.loads(AUDIT.read_text()); assert d['schema']=='ds02.f3.registered-render-handle-live-audit.v1'; assert d['policy']['read_only'] and not d['policy']['jobs_started'] and not d['policy']['jobs_restarted']; assert d['policy']['science_payload_opened_or_hashed'] is False and d['policy']['png_viewed'] is False
 assert d['summary']['handles_total']==12 and d['summary']['visual_review_eligible']==0 and d['summary']['view_image_performed'] is False
 assert d['summary']['published_reports']==0
 assert d['summary']['running_receipts']==1
 assert {c['handle'] for c in d['cases'] if not c['frame_contract_consistent']} == {'987','1031','1033','1046','1047'}
 for c in d['cases']:
  for key in ['request_path','wrapper_path','review_metadata_path']:
   if c.get(key):
    p=Path(c[key]); assert p.exists() and p.suffix.lower() not in SCI
  assert c['visual_review_eligible'] is False and c['view_image_performed'] is False
 for ref in d['source_metadata_refs']:
  p=Path(ref['path']); assert p.exists() and p.suffix.lower() not in SCI and sha(p)==ref['sha256']
 print('fresh154 metadata validator: PASS (0 visual candidates; all registered handles preserved)'); return 0
if __name__=='__main__': raise SystemExit(main())
