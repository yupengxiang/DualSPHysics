from pathlib import Path
import json,hashlib,datetime,os,stat,fcntl,shutil,argparse,tempfile
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.jsonl','.py','.md','.xml','.xmf','.log'}
 return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,v):
 p=Path(p);tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,p)
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
def identity(v):
 p=Path(v['path']);assert p.name=='trajectory.h5.partial' and p.parent==Path(v['attempt_root'])
 assert p.resolve(strict=True)==p and p.parent.resolve(strict=True)==p.parent
 s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
 assert (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_blocks*512)==(v['device'],v['inode'],v['size'],v['mtime_ns'],v['blocks_bytes'])
 return p
def live(ar):
 rows=[]
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:c=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
  except OSError:c=''
  if str(ar) in c:rows.append({'pid':proc.name,'kind':'cmdline'})
  try:fs=list((proc/'fd').iterdir())
  except OSError:continue
  for fd in fs:
   try:t=os.readlink(fd)
   except OSError:continue
   if t.startswith(str(ar)+'/'):rows.append({'pid':proc.name,'kind':'open_fd'})
 return rows
def main(plan_path,plan_sha,output):
 assert sha(plan_path)==plan_sha;plan=load(plan_path);assert not plan['data_deleted_by_plan'] and not plan['scientific_payload_contents_read_or_hashed']
 assert len(plan['eligible_files'])==2 and plan['accepted_cases_protected']==243
 out=Path(output);out.mkdir(exist_ok=False)
 result={'schema':'ds02.authorized-failed-unpublished-partial-cleanup.v1','status':'running','started_at_utc':now(),'plan':str(plan_path),'plan_sha256':plan_sha,'deleted_files':0,'deleted_payload_bytes':0,'deleted_allocated_bytes':0,'science_payload_contents_read_or_hashed':False,'completed_outputs_and_native_raw_deleted':False,'Home_free_before_bytes':shutil.disk_usage('/home/jade').free,'attempt_results':[]}
 put(out/'cleanup-result.json',result)
 try:
  for v in plan['eligible_files']:
   ar=Path(v['attempt_root']);assert ar.is_relative_to(D/'families') and len(ar.relative_to(D/'families').parts)==3
   assert str(ar.relative_to(D/'families'))==v['attempt_id']
   rp=ar/'execution-receipt.json';assert v['receipt']['path']==str(rp) and sha(rp)==v['receipt']['sha256']
   r=load(rp);assert r['status']=='failed' and r['returncode'] not in [None,0]
   assert not (ar/'trajectory.h5').exists() and not (ar/'conversion-report.json').exists()
   with (D/'runtime/resource-ledger.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX);ledger=load(D/'runtime/resource-ledger.json')
    entries=[a for a in ledger['attempts'] if a['id']==v['attempt_id']];assert len(entries)==1 and entries[0]['status']=='failed'
    assert not any(a.get('id')==v['attempt_id'] for a in ledger['reservations'])
    fcntl.flock(lock,fcntl.LOCK_UN)
   p=identity(v);assert not live(ar)
   marker=ar/'user-authorized-failed-unpublished-partial-cleanup-root1054.json';assert not marker.exists()
   row={'attempt_id':v['attempt_id'],'original_failed_receipt':v['receipt'],'path':str(p),'original_file_stat':v,'status':'prepared_for_unlink','plan':str(plan_path),'plan_sha256':plan_sha,'failure_metadata_and_logs_retained':True,'native_raw_untouched':True,'scientific_payload_contents_read_or_hashed':False}
   put(marker,row);identity(v).unlink()
   with (out/'deleted-files.jsonl').open('a') as journal:journal.write(json.dumps({'path':str(p),'size':v['size'],'blocks_bytes':v['blocks_bytes'],'inode':v['inode']})+'\n')
   assert not p.exists() and sha(rp)==v['receipt']['sha256']
   row.update(status='completed',finished_at_utc=now(),deleted_file_still_absent=True);put(marker,row)
   result['attempt_results'].append(row);result['deleted_files']+=1;result['deleted_payload_bytes']+=v['size'];result['deleted_allocated_bytes']+=v['blocks_bytes'];put(out/'cleanup-result.json',result)
   print(json.dumps({'attempt':v['attempt_id'],'deleted_allocated_GiB':v['blocks_bytes']/2**30}),flush=True)
  result['status']='completed'
 except BaseException as e:
  result.update(status='failed',error=repr(e));raise
 finally:
  result.update(finished_at_utc=now(),Home_free_after_bytes=shutil.disk_usage('/home/jade').free,free_delta_includes_concurrent_writes=True)
  result['Home_floor_pass']=result['Home_free_after_bytes']>=500*2**30;put(out/'cleanup-result.json',result)
def self_test():
 with tempfile.TemporaryDirectory(prefix='ds02-partial1054-fence-') as tmp:
  ar=Path(tmp);p=ar/'trajectory.h5.partial';p.write_text('synthetic fence fixture, not a scientific H5 payload')
  s=p.stat();v={'path':str(p),'attempt_root':str(ar),'device':s.st_dev,'inode':s.st_ino,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'blocks_bytes':s.st_blocks*512}
  assert identity(v)==p
  def rejected(x):
   try:identity(x)
   except (AssertionError,FileNotFoundError):return
   raise AssertionError('unsafe file accepted')
  rejected({**v,'inode':s.st_ino+1});rejected({**v,'attempt_root':str(ar/'wrong')})
  sy=ar/'symlink';sy.symlink_to(ar);rejected({**v,'path':str(sy/'trajectory.h5.partial'),'attempt_root':str(sy)})
  os.link(p,ar/'hardlink');rejected(v)
 print('PASS: exact toy file; reject changed inode, wrong parent, symlink and hardlink; no scientific payload IO.')
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--plan');a.add_argument('--plan-sha');a.add_argument('--output-dir');a.add_argument('--self-test',action='store_true');q=a.parse_args()
 if q.self_test:self_test()
 else:main(q.plan,q.plan_sha,q.output_dir)
