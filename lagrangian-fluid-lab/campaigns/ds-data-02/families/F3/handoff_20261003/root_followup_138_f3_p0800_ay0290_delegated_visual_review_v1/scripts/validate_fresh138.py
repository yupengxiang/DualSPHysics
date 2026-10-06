#!/usr/bin/env python3
from pathlib import Path
import hashlib, json, sys
PKG = Path(__file__).resolve().parents[1]
MARKER = 'b6615477e64361577f0b5b05a176b57c8c429682'
CASES = {'F3_STAGE1_DP006_P0800_AY0290': 9}
def load(p): return json.loads(Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
 return h.hexdigest()
errors=[]
prov=load(PKG/'metadata/source-review-provenance.json')
if prov.get('fresh_id') != 'fresh138' or prov.get('source_only') is not True: errors.append('provenance')
if prov.get('marker_commit') != MARKER: errors.append('marker')
cp=load(PKG/'metadata/accepted-checkpoint-audit.json')
if cp.get('checkpoint',{}).get('checkpoint_number') != 170: errors.append('checkpoint')
if not cp.get('selected_cases_not_in_checkpoint'): errors.append('dedup')
for cid, key_count in CASES.items():
 d=load(PKG/'metadata/visual-review'/f'{cid}-delegated-visual-decision.json')
 if d.get('status') != 'visual-approved-by-delegated-agent': errors.append(cid+':status')
 if d.get('source_review_commit') != MARKER: errors.append(cid+':marker')
 if d.get('agent_personally_viewed_all_contacts_and_keys') is not True or d.get('main_personally_viewed_pngs') is not False: errors.append(cid+':reviewer')
 if d.get('precision_status') != 'not_accepted' or d.get('q_n') != 'not_granted' or d.get('production_scope_approval') is not False: errors.append(cid+':approval')
 if d.get('global_state_written_by_this_package') is not False: errors.append(cid+':global')
 if not d.get('reviewed_at_utc'): errors.append(cid+':review_time')
 chain=PKG/'metadata/chain-audit'/f'{cid}.json'; png=PKG/'metadata/png-hashes'/f'{cid}.json'
 if not chain.exists() or not png.exists(): errors.append(cid+':sidecars'); continue
 cj=load(chain); pj=load(png)
 if cj.get('source_payload_read_or_hashed_by_this_agent') is not False: errors.append(cid+':payload')
 if cj.get('metadata_observations',{}).get('typed_frames') != 836: errors.append(cid+':typedframes')
 if cj.get('metadata_observations',{}).get('render_full_frame_selection') is not True: errors.append(cid+':renderframes')
 if cj.get('metadata_observations',{}).get('partvtk_all_passed') is not True: errors.append(cid+':partvtk')
 for st in ('native','typed','xmf','render'):
  obj=cj['stages'][st]; r=obj.get('receipt',obj)
  if r.get('status') != 'completed' or r.get('returncode') != 0: errors.append(cid+':'+st)
 if len(pj.get('contact_sheets',[])) != 35: errors.append(cid+':contacts')
 if len(pj.get('keyframes',[])) != key_count: errors.append(cid+':keys')
 for item in pj.get('contact_sheets',[]) + pj.get('keyframes',[]):
  p=Path(item['path'])
  if not p.exists() or sha(p) != item['sha256']: errors.append(cid+':png:'+str(p))
for p in PKG.rglob('*'):
 if p.is_file() and p.suffix.lower() in {'.h5','.bi4','.csv','.dat','.vtk','.vtu','.pvtu'}: errors.append('scientific:'+str(p))
if errors:
 print('FAIL')
 print('\n'.join(errors))
 sys.exit(1)
print('PASS fresh138 metadata/PNG validation; Root1003 terminal chain and 35/9 PNG sidecars closed; no scientific payload files in package')
