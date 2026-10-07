from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN=(".h5",".hdf5",".bi4",".csv",".dat",".vtk",".vtu",".pvtu")
CASE='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C0821'  # unused sentinel, identity checked below

def read(p): return json.loads(p.read_text())
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def walk(v):
 if isinstance(v,dict):
  for x in v.values(): yield from walk(x)
 elif isinstance(v,list):
  for x in v: yield from walk(x)
 elif isinstance(v,str): yield v
def fail(x): raise AssertionError(x)

def main():
 d=read(ROOT/'metadata/f5-m115-t080-visual-review.json')
 e=read(ROOT/'metadata/png-evidence/f5-m115-t080.json')
 if (d['case_id'],d['physical_case_id'],d['actual_family_id'],d['assigned_worktree_family_id']) != ('F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1','F5_COMPACT_RUNUP_RECOVERY_C082S1_M115_T080','F5','F3'): fail('identity')
 if d['status']!='visual-approved-by-delegated-agent' or d['case_credit']!=0 or d['independent_case_increment']!=0: fail('status/credit')
 if d['q_n_granted'] or d['q_e_granted'] or d['numerical_precision_accepted']: fail('precision/Q boundary')
 if d['actual_terminal']['status']!='completed' or d['actual_terminal']['returncode']!=0: fail('terminal')
 if d['actual_terminal']['atomic_publish']['status']!='published_after_atomic_rename': fail('publish')
 if d['production_dimensions'] != {**d['production_dimensions']}: pass
 dim=d['production_dimensions']
 for k,v in {'particles':194427,'initial_fluid_uids':31658,'fixed_particles':158559,'moving_particles':4210,'frames':801,'expected_contacts':34,'expected_keyframes':9}.items():
  if dim[k]!=v: fail('dimension '+k)
 if dim['keyframe_indices'] != [0,100,200,300,400,500,600,700,800]: fail('keyframes')
 roles=d['physical_scope_roles']
 if roles['canonical_actual_native_request_condition_sha256']!='88b7675cc646f6be00dd6af97c9cfdbd4e0610816bb14e516e5f450b74fc3895': fail('canonical')
 if roles['actual_converter_legacy_scope_sha256']!='705c765d036403c6d7c9bbb2f18e70f24c60831abf2ffd0ddb3d5f532d762fe1': fail('legacy')
 if roles['actual_native_source_plan_condition_sha256'] is not None or roles['actual_native_source_plan_field_present']: fail('native plan')
 src=Path(roles['source_def']['path'])
 if not src.exists() or sha(src)!=roles['source_def']['sha256'] or roles['source_def']['sha256']!='7a8f29182215a61c600dba59ec656fc2cd3086656c9978bc808a65d1ed01fb37': fail('SourceDef')
 r=d['render_binding']; report=Path(r['report']['path']); manifest=Path(r['manifest']['path']); xmf=Path(r['xmf']['path']); publish=Path(r['publish_receipt']['path']); execution=Path(d['actual_terminal']['execution_receipt']['path']); qi=Path(d['main_qi_binding']['path'])
 for name,p,expected in [('report',report,r['report']['sha256']),('manifest',manifest,r['manifest']['sha256']),('xmf',xmf,r['xmf']['sha256']),('publish',publish,r['publish_receipt']['sha256']),('execution',execution,d['actual_terminal']['execution_receipt']['sha256']),('QI',qi,d['main_qi_binding']['sha256'])]:
  if not p.exists() or sha(p)!=expected: fail(name+' metadata sha')
 rep=read(report); pub=read(publish); exe=read(execution)
 if rep['manifest_sha256'] != r['manifest']['sha256']: fail('report/manifest mismatch')
 if rep['xdmf_sha256_after'] != r['xmf']['sha256']: fail('report/XMF mismatch')
 if rep['frames']!=801 or not rep['all_frames_rendered'] or not rep['actual_times_preserved_exactly']: fail('render report')
 if pub['status']!='published_after_atomic_rename' or pub['published_output_root'] != e['published_root']: fail('publisher')
 if exe['status']!='completed' or exe['returncode']!=0: fail('execution')
 # exact contact/key lists and producer receipt attestations
 entries=e['entries']; contacts=[x for x in entries if x['role']=='contact_sheet']; keys=[x for x in entries if x['role']=='event_keyframe']
 if len(entries)!=43 or len(contacts)!=34 or len(keys)!=9: fail('PNG count')
 if sorted(x['contact_index'] for x in contacts)!=list(range(34)): fail('contact indices')
 if sorted(x['frame_index'] for x in keys)!=[0,100,200,300,400,500,600,700,800]: fail('key indices')
 byrel={x['relative_path']:x for x in pub['files_excluding_receipt']}
 report_contacts=rep['outputs']['contact_sheets']
 if [x['path'] for x in sorted(contacts,key=lambda z:z['contact_index'])] != report_contacts: fail('contact report exact')
 for x in entries:
  p=Path(x['path'])
  if p.suffix.lower()!='.png' or not p.exists() or not x['viewed'] or x['view_method']!='view_image': fail('PNG view '+str(p))
  if p.stat().st_size != x['bytes'] or sha(p)!=x['sha256']: fail('PNG bytes/hash '+str(p))
  if x['relative_path'] not in byrel or byrel[x['relative_path']]['bytes']!=x['bytes'] or byrel[x['relative_path']]['sha256']!=x['sha256']: fail('publisher PNG '+x['relative_path'])
  if not str(p).startswith(e['published_root']+'/'): fail('PNG outside published root')
 if not d['visual_review']['physical_screen'] or not d['retained_limits']: fail('screen/limits')
 boundary=d['read_boundary']
 for k in ('scientific_payload_opened_or_hashed_by_this_reviewer','h5_bi4_csv_dat_vtk_opened_or_hashed_by_this_reviewer','jobs_started_restarted_or_stopped','shared_state_or_ledger_modified'):
  if boundary[k]: fail('boundary '+k)
 if any(s.lower().endswith(FORBIDDEN) for s in walk(d)) or any(s.lower().endswith(FORBIDDEN) for s in walk(e)): fail('payload path in package metadata')
 # package integrity excludes itself to avoid a self-hash cycle
 integ=read(ROOT/'metadata/package-integrity.json'); listed={x['path']:x for x in integ['files']}
 actual={str(p.relative_to(ROOT)):p for p in ROOT.rglob('*') if p.is_file() and p.name!='package-integrity.json'}
 if set(listed)!=set(actual): fail('package file set')
 for rel,item in listed.items():
  p=actual[rel]
  if p.stat().st_size!=item['bytes'] or sha(p)!=item['sha256']: fail('package '+rel)
 print('fresh165 PASS: F5 M115/T080 terminal0; 34 contact sheets + 9 keyframes personally viewed; physical screen recorded; role boundaries and atomic publish verified')
if __name__=='__main__': main()
