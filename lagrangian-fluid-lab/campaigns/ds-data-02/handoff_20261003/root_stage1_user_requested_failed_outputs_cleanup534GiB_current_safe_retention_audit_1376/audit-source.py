from pathlib import Path
import os,json,hashlib,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix=='.json';return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
prior=next(H.glob('root*_1235'))/'cleanup-actual-results-and-retention-proof.json';a=load(prior);deleted=[];preserved=[];failed_refs=[];results=[]
for x in a['actual_cleanup_receipts']:
 rp=Path(x['result']);receipt=Path(x['actual_receipt']);assert sha(rp)==x['result_sha256'];assert sha(receipt)==x['receipt_sha256'];r=load(rp);assert r['status']=='completed';rc=load(receipt);assert rc['status']=='completed' and rc['returncode']==0
 pp=Path(r['plan']);assert sha(pp)==r['plan_sha256'];p=load(pp)
 if x['root']==965:
  for z in p['eligible_attempts']:
   deleted.extend(f['path'] if isinstance(f,dict) else f for f in z['delete_files']);preserved.extend(z['preserved_frame_paths']);failed_refs.append({'path':z['receipt'],'sha256':z['receipt_sha256']})
 elif x['root']==1054:
  for z in r['attempt_results']:deleted.append(z['path']);failed_refs.append(z['original_failed_receipt'])
 else:
  for z in p['attempts']:
   deleted.extend(f['path'] if isinstance(f,dict) else f for f in z['eligible_files']);preserved.extend(f['path'] if isinstance(f,dict) else f for f in z['preserved_files'])
  for z in r['attempt_results']:failed_refs.append({'path':z['original_failed_receipt'],'sha256':z['original_failed_receipt_sha256']})
 results.append({'root':x['root'],'receipt':ref(receipt),'result':ref(rp),'plan':ref(pp),'deleted_files':r['deleted_files'],'deleted_allocated_bytes':r['deleted_allocated_bytes']})
assert len(deleted)==17203 and len(set(deleted))==17203
assert all(not os.path.lexists(p) for p in deleted);assert all(Path(p).is_file() for p in preserved)
assert all(sha(z['path'])==z['sha256'] for z in failed_refs)
oldp=next(H.glob('root*_1217'))/'failed-attempts-current-storage-audit.json';old=load(oldp);oldfailed={z['receipt']:z['receipt_sha256'] for z in old['failed_attempts']};failed=[];counts={};errors=[]
for parent,dirs,files in os.walk(D,followlinks=False):
 dirs[:]=[x for x in dirs if not (Path(parent)/x).is_symlink()]
 if 'execution-receipt.json' not in files:continue
 p=Path(parent)/'execution-receipt.json'
 try:j=load(p)
 except Exception as e:errors.append({'path':str(p),'error':str(e)});continue
 status=j.get('status','absent');counts[status]=counts.get(status,0)+1
 if status=='failed':failed.append({'path':str(p),'sha256':sha(p),'returncode':j.get('returncode'),'error':j.get('error')})
newfailed=[z for z in failed if z['path'] not in oldfailed];changedfailed=[z for z in failed if z['path'] in oldfailed and z['sha256']!=oldfailed[z['path']]]
# Only filename/stat metadata of old failed attempts; no scientific payload reads.
rows=[]
for z in failed:
 root=Path(z['path']).parent;alloc=0;count=0;large=[]
 for parent,dirs,files in os.walk(root,followlinks=False):
  dirs[:]=[n for n in dirs if not (Path(parent)/n).is_symlink()]
  for n in files:
   p=Path(parent)/n
   if p.is_symlink():continue
   try:s=p.stat()
   except FileNotFoundError:continue
   alloc+=s.st_blocks*512;count+=1
   if s.st_size>=100*2**20:large.append({'path':str(p),'bytes':s.st_size,'allocated_bytes':s.st_blocks*512})
 rows.append({**z,'current_allocated_bytes':alloc,'files':count,'large_files':large})
vfs=os.statvfs('/home/jade');free=vfs.f_bavail*vfs.f_frsize
proof={'schema':'ds02.user-storage-current-cleanup-and-failed-residual-reverification.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_cumulative_cleanup_proof':ref(prior),'verified_cleanup_results':results,'deleted_paths_checked':len(deleted),'all_deleted_paths_still_absent':True,'preserved_diagnostic_samples_checked':len(preserved),'all_preserved_samples_present':True,'original_failed_receipts_checked':len(failed_refs),'original_failed_receipts_bytes_unchanged':True,'cumulative_released_allocated_GiB':sum(z['deleted_allocated_bytes'] for z in results)/2**30,'receipt_status_counts':counts,'malformed_receipts':errors,'prior_failed_inventory':ref(oldp),'new_failed_receipts_since_prior_inventory':newfailed,'changed_failed_receipts_since_prior_inventory':changedfailed,'current_failed_attempt_allocated_GiB':sum(z['current_allocated_bytes'] for z in rows)/2**30,'current_home_available_GiB':free/2**30,'home_floor_GiB':500,'floor_pass':free>=500*2**30,'new_deletions_this_verification':0,'scientific_payloads_read_or_hashed':False,'case_credit':0,'scope':'Prior exact safe cleanup reverified; current failed receipt inventory and filename/stat residual inventory. A failed receipt alone is not evidence that all its outputs are unused; consumed and diagnostic evidence remain protected.'}
O=H/'root_stage1_user_requested_failed_outputs_cleanup534GiB_current_safe_retention_audit_1376';O.mkdir(exist_ok=False)
(O/'current-storage-cleanup-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');(O/'current-failed-attempt-residual-inventory.json').write_text(json.dumps({'schema':'ds02.failed-attempt-stat-only-residual-inventory.v1','at_utc':proof['at_utc'],'scientific_payload_IO':False,'attempts':rows},ensure_ascii=False,indent=2)+'\n');(O/'audit-source.py').write_bytes(Path(__file__).read_bytes())
(O/'README.md').write_text('用户授权的失败输出清理复核。此前四次注册清理累计释放 534.4086 GiB；本次逐一复核 17,203 个删除路径、保留诊断样本和原始失败收据，并刷新失败任务文件 stat 清单。本次未新增删除；失败状态不意味着产物未被使用。已交付、待验收、正在运行和被诊断证据引用的产物继续保留。\n')
print(json.dumps({k:proof[k] for k in ['at_utc','deleted_paths_checked','preserved_diagnostic_samples_checked','original_failed_receipts_checked','cumulative_released_allocated_GiB','receipt_status_counts','new_failed_receipts_since_prior_inventory','changed_failed_receipts_since_prior_inventory','current_failed_attempt_allocated_GiB','current_home_available_GiB','new_deletions_this_verification']},ensure_ascii=False))
for z in sorted(rows,key=lambda x:x['current_allocated_bytes'],reverse=True)[:8]:print(round(z['current_allocated_bytes']/2**30,3),z['path'])
print('OUTPUT',O)
