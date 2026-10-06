from pathlib import Path
import json,os,stat,re,hashlib,argparse,shutil,datetime,tempfile,fcntl
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
BI4=re.compile(r'Part_\d{4,}\.bi4\Z')
def load(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def put(p,v):
 p=Path(p);t=p.with_name(p.name+'.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');os.replace(t,p)
def check_file(item,data,preserved):
 p=Path(item['path']);data=Path(data)
 assert p.parent==data and BI4.fullmatch(p.name),'outside exact numeric frame scope'
 assert str(p) not in preserved,'protected frame'
 assert p.resolve(strict=True)==p and data.resolve(strict=True)==data,'symlink in path'
 s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1,'not singly linked regular file'
 assert (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)==(item['device'],item['inode'],item['size'],item['mtime_ns']),'file identity changed'
 return p

def live_uses(ar):
 uses=[]
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:cmd=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
  except OSError:cmd=''
  if str(ar) in cmd:uses.append({'pid':proc.name,'kind':'cmdline'})
  try:fds=list((proc/'fd').iterdir())
  except OSError:continue
  for f in fds:
   try:target=os.readlink(f)
   except OSError:continue
   if target.startswith(str(ar)+'/'):uses.append({'pid':proc.name,'kind':'open_fd','path':target})
 return uses

def main(plan_path,plan_sha,output):
 assert sha(plan_path)==plan_sha,'plan bytes changed';plan=load(plan_path);assert plan['no_data_deleted_by_audit'] and not plan['scientific_payload_contents_read_or_hashed']
 assert plan['accepted_decisions_protected']==199 and plan['q_n_negative_alone_never_cleanup_reason']
 out=Path(output);out.mkdir(exist_ok=False)
 result={'schema':'ds02.authorized-failed-native-cleanup.v1','started_at_utc':now(),'plan':str(plan_path),'plan_sha256':plan_sha,'status':'running','deleted_files':0,'deleted_payload_bytes':0,'deleted_allocated_bytes':0,'attempt_results':[],'Home_free_before_bytes':shutil.disk_usage('/home/jade').free,'scientific_payload_contents_read_or_hashed':False,'accepted_or_completed_products_deleted':False,'historical_receipts_and_budget_counters_unchanged':True}
 put(out/'cleanup-result.json',result)
 try:
  for candidate in plan['eligible_attempts']:
   ar=Path(candidate['root']);data=Path(candidate['data_root']);assert ar.is_relative_to(D/'families') and len(ar.relative_to(D/'families').parts)==3
   assert data==ar/'solver_output/data';assert ar.resolve(strict=True)==ar
   receipt=Path(candidate['receipt']);assert receipt==ar/'execution-receipt.json' and sha(receipt)==candidate['receipt_sha256']
   r=load(receipt);assert r['status']=='failed' and r['returncode'] not in [None,0]
   assert 0<candidate['actual_native_frame_file_count']<candidate['expected_frames_from_actual_recipe']
   with (D/'runtime/resource-ledger.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX);ledger=load(D/'runtime/resource-ledger.json')
    matches=[x for x in ledger['attempts'] if x['id']==candidate['id']];assert len(matches)==1 and matches[0]['status'] in ['failed','interrupted','launcher_missing']
    assert not any(x.get('id')==candidate['id'] for x in ledger['reservations'])
    fcntl.flock(lock,fcntl.LOCK_UN)
   preserved=set(candidate['preserved_frame_paths']);assert set(candidate['preserve_initial_and_last_native_frames'])<=preserved
   for p in candidate['preserve_initial_and_last_native_frames']:assert Path(p).is_file()
   paths=[check_file(v,data,preserved) for v in candidate['delete_files']];assert len(paths)==len(set(paths))
   assert not live_uses(ar),'new active use; candidate must remain untouched'
   sidecar=ar/'user-authorized-failed-native-cleanup-root965.json';assert not sidecar.exists()
   done={'attempt_id':candidate['id'],'original_receipt':str(receipt),'original_receipt_sha256':candidate['receipt_sha256'],'reason':candidate['reason'],'status':'running','preserved_frames':sorted(preserved),'headers_metadata_logs_retained':True,'native_sequence_intentionally_pruned':True,'full_sequence_reusable':False,'plan':str(plan_path),'plan_sha256':plan_sha,'deleted_files':0,'deleted_payload_bytes':0,'deleted_allocated_bytes':0}
   put(sidecar,done);result['attempt_results'].append(done)
   # Journal after each unlink. No payload is read, hashed, rewritten or copied.
   with (out/'deleted-files.jsonl').open('a',buffering=1) as journal:
    for item in candidate['delete_files']:
     p=check_file(item,data,preserved);p.unlink();journal.write(json.dumps({'path':str(p),'size':item['size'],'blocks_bytes':item['blocks_bytes']})+'\n')
     done['deleted_files']+=1;done['deleted_payload_bytes']+=item['size'];done['deleted_allocated_bytes']+=item['blocks_bytes']
   done['status']='completed';done['finished_at_utc']=now();assert sha(receipt)==candidate['receipt_sha256']
   done['preserved_initial_and_last_still_present']=all(Path(p).is_file() for p in candidate['preserve_initial_and_last_native_frames'])
   assert done['preserved_initial_and_last_still_present'];put(sidecar,done)
   result['deleted_files']+=done['deleted_files'];result['deleted_payload_bytes']+=done['deleted_payload_bytes'];result['deleted_allocated_bytes']+=done['deleted_allocated_bytes'];put(out/'cleanup-result.json',result)
   print(json.dumps({'attempt':candidate['id'],'deleted_files':done['deleted_files'],'deleted_GiB':done['deleted_payload_bytes']/1024**3}),flush=True)
  result['status']='completed'
 except BaseException as e:
  result['status']='failed';result['error']=repr(e);raise
 finally:
  result['finished_at_utc']=now();result['Home_free_after_bytes']=shutil.disk_usage('/home/jade').free;result['Home_floor_after_pass']=result['Home_free_after_bytes']>=500*1024**3
  result['free_delta_includes_concurrent_job_writes']=True;put(out/'cleanup-result.json',result)

def self_test():
 with tempfile.TemporaryDirectory(prefix='ds02-cleanup965-fencing-') as t:
  d=Path(t);p=d/'Part_0001.bi4';p.write_bytes(b'toy data only');s=p.stat();v={'path':str(p),'device':s.st_dev,'inode':s.st_ino,'size':s.st_size,'mtime_ns':s.st_mtime_ns};assert check_file(v,d,set())==p
  def rejected(fn):
   try:fn()
   except (AssertionError,FileNotFoundError):return
   raise AssertionError('unsafe input accepted')
  rejected(lambda:check_file(v,d,{str(p)}));rejected(lambda:check_file({**v,'inode':s.st_ino+1},d,set()));rejected(lambda:check_file(v,d/'wrong',set()))
  sy=d/'Part_0002.bi4';sy.symlink_to(p);rejected(lambda:check_file({**v,'path':str(sy)},d,set()));os.link(p,d/'Part_0003.bi4');rejected(lambda:check_file(v,d,set()))
  print('PASS: valid exact file; reject protected, changed inode, wrong directory, symlink and hard link. Toy temp files only.')
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--plan');a.add_argument('--plan-sha');a.add_argument('--output-dir');a.add_argument('--self-test',action='store_true');o=a.parse_args()
 if o.self_test:self_test()
 else:main(o.plan,o.plan_sha,o.output_dir)
