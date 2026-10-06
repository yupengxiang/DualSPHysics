from pathlib import Path
import json,hashlib,datetime,os,stat,fcntl,argparse,re
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p); assert p.suffix in ('.json','.py','.md','.log','.jsonl')
 return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,d):
 p=Path(p);t=p.with_name(p.name+'.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');os.replace(t,p)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def free():
 s=os.statvfs('/home/jade');return s.f_bavail*s.f_frsize
def identity(v,ar):
 p=Path(v['path']);assert p.parent==ar/'partvtk/csv' and re.fullmatch(r'Particles_[0-9]+\.csv',p.name)
 assert p.resolve(strict=True)==p
 s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
 assert (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_blocks*512)==(v['device'],v['inode'],v['bytes'],v['mtime_ns'],v['allocated_bytes'])
 return p
def live(ar):
 matches=[]
 for pr in Path('/proc').iterdir():
  if not pr.name.isdigit():continue
  try:cmd=(pr/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
  except OSError:cmd=''
  if str(ar) in cmd:matches.append({'pid':pr.name,'kind':'cmdline'})
  try:
   if os.readlink(pr/'cwd').startswith(str(ar)):matches.append({'pid':pr.name,'kind':'cwd'})
  except OSError:pass
  try:fds=list((pr/'fd').iterdir())
  except OSError:continue
  for fd in fds:
   try:t=os.readlink(fd)
   except OSError:continue
   if t.startswith(str(ar)+'/'):matches.append({'pid':pr.name,'kind':'fd'})
 return matches
def main(q):
 assert sha(q.plan)==q.plan_sha;p=load(q.plan);assert p['user_authorized'] and p['completed_products_protected'] and p['no_dependent_consumers_found']
 out=Path(q.output_dir);out.mkdir(exist_ok=False)
 r={'schema':'ds02.failed-unused-converter-csv-cleanup.v1','status':'running','started_at_utc':now(),'plan':q.plan,'plan_sha256':q.plan_sha,'deleted_files':0,'deleted_payload_bytes':0,'deleted_allocated_bytes':0,'home_available_before_bytes':free(),'scientific_payload_IO':False,'accepted_or_pending_products_deleted':False,'attempt_results':[]}
 put(out/'cleanup-result.json',r)
 try:
  for a in p['attempts']:
   ar=Path(a['attempt_root']);assert ar.resolve(strict=True)==ar and ar.is_relative_to(D/'families/F2')
   assert len(ar.relative_to(D/'families').parts)==3
   rp=ar/'execution-receipt.json';assert sha(rp)==a['receipt_sha256'];d=load(rp);assert d['status']=='failed' and d['returncode']!=0 and d['returncode'] is not None
   assert not (ar/'trajectory.h5').exists() and not (ar/'conversion-report.json').exists()
   with (D/'runtime/resource-ledger.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX);ledger=load(D/'runtime/resource-ledger.json');es=[x for x in ledger['attempts'] if x['id']==a['attempt_id']];assert len(es)==1 and es[0]['status']=='failed';assert not any(x.get('id')==a['attempt_id'] for x in ledger['reservations']);fcntl.flock(lock,fcntl.LOCK_UN)
   assert not live(ar)
   for v in a['preserved_files']:identity(v,ar)
   for v in a['eligible_files']:identity(v,ar)
   marker=ar/'user-authorized-unused-failed-converter-csv-cleanup-root1219.json';assert not marker.exists()
   m={'status':'prepared','original_failed_receipt':str(rp),'original_failed_receipt_sha256':a['receipt_sha256'],'plan':q.plan,'plan_sha256':q.plan_sha,'preserved_files':a['preserved_files'],'original_failure_logs_and_inputs_preserved':True,'native_raw_untouched':True,'scientific_payload_IO':False,'deleted_files':0,'deleted_payload_bytes':0,'deleted_allocated_bytes':0};put(marker,m)
   for v in a['eligible_files']:
    f=identity(v,ar)
    with (out/'deleted-files.jsonl').open('a') as j:j.write(json.dumps({'path':str(f),'bytes':v['bytes'],'allocated_bytes':v['allocated_bytes'],'inode':v['inode'],'phase':'before_unlink'})+'\n')
    f.unlink();assert not f.exists();r['deleted_files']+=1;r['deleted_payload_bytes']+=v['bytes'];r['deleted_allocated_bytes']+=v['allocated_bytes'];m['deleted_files']+=1;m['deleted_payload_bytes']+=v['bytes'];m['deleted_allocated_bytes']+=v['allocated_bytes'];put(marker,m);put(out/'cleanup-result.json',r)
   assert sha(rp)==a['receipt_sha256']
   for v in a['preserved_files']:identity(v,ar)
   m.update(status='completed',finished_at_utc=now());put(marker,m);r['attempt_results'].append(m);put(out/'cleanup-result.json',r)
  r['status']='completed'
 except BaseException as e:r.update(status='failed',error=repr(e));raise
 finally:
  r.update(finished_at_utc=now(),home_available_after_bytes=free(),home_floor_pass=free()>=500*2**30,case_credit=0);put(out/'cleanup-result.json',r)
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--plan',required=True);a.add_argument('--plan-sha',required=True);a.add_argument('--output-dir',required=True);main(a.parse_args())
