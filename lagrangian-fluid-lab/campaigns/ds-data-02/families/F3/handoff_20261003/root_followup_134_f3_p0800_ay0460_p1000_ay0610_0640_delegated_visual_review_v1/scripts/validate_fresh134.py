#!/usr/bin/env python3
from pathlib import Path
import hashlib,json,sys
PKG=Path(__file__).resolve().parents[1]
MARKER='ce1bb0e5649bc06bbef862f4b0915f310efac3c0'
def load(p): return json.loads(p.read_text())
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
errors=[]
prov=load(PKG/'metadata/source-review-provenance.json')
if prov.get('fresh_id')!='fresh134' or prov.get('source_only') is not True: errors.append('provenance')
selected=load(PKG/'metadata/selection-and-dedup.json')
cp=load(PKG/'metadata/accepted-checkpoint-audit.json')
if cp['checkpoint']['checkpoint_number']!=158 or cp['checkpoint']['accepted_decision_paths_checked']!=243: errors.append('checkpoint')
if not cp['selected_cases_not_in_checkpoint']: errors.append('dedup')
for dec_path in sorted((PKG/'metadata/visual-review').glob('*.json')):
 d=load(dec_path); cid=d['case_id']
 if d.get('status')!='visual-approved-by-delegated-agent': errors.append(cid+':status')
 if d.get('source_review_commit')!=MARKER: errors.append(cid+':marker')
 if d.get('agent_personally_viewed_all_contacts_and_keys') is not True or d.get('main_personally_viewed_pngs') is not False: errors.append(cid+':reviewer')
 if d.get('precision_status')!='not_accepted' or d.get('q_n')!='not_granted' or d.get('production_scope_approval') is not False: errors.append(cid+':scope')
 chain=PKG/'metadata/chain-audit'/f'{cid}.json'; png=PKG/'metadata/png-hashes'/f'{cid}.json'
 if not chain.exists() or not png.exists(): errors.append(cid+':sidecars'); continue
 cj=load(chain); pj=load(png)
 for st in ['native','typed','xmf','render']:
  obj=cj['stages'][st]; r=obj.get('receipt',obj)
  if r.get('status')!='completed' or r.get('returncode')!=0: errors.append(cid+':'+st)
 if cj['metadata_observations']['native_full_saved_frames']!=836 or cj['metadata_observations']['typed_frames']!=836 or cj['metadata_observations']['render_max_missing']!=0: errors.append(cid+':frames')
 if len(pj.get('contact_sheets',[]))!=35: errors.append(cid+':contacts')
 expected_keys=9 if cid.endswith('P0800_AY0460') else 6
 if len(pj.get('keyframes',[]))!=expected_keys: errors.append(cid+':keys')
 for item in pj.get('contact_sheets',[])+pj.get('keyframes',[]):
  p=Path(item['path'])
  if not p.exists() or sha(p)!=item['sha256']: errors.append(cid+':png:'+str(p))
# package must not contain scientific payload files.
for p in PKG.rglob('*'):
 if p.is_file() and p.suffix.lower() in {'.h5','.bi4','.csv','.dat','.vtk','.vtu','.pvtu'}: errors.append('scientific:'+str(p))
if errors:
 print('FAIL')
 print('\n'.join(errors))
 sys.exit(1)
print('PASS fresh134 metadata/PNG validation; scientific payload files absent')
