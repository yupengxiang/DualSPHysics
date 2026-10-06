from pathlib import Path
import os,json,stat,hashlib,datetime
H=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003')
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
O=H/'root_stage1_user_failed_storage_cleanup_current_residual_audit_1217'
O.mkdir(exist_ok=False)
(O/'audit-source.py').write_bytes(Path(__file__).read_bytes())
rows=[]; receipts=0; malformed=[]
for p in (D/'families').glob('*/*/*/execution-receipt.json'):
 try: d=json.loads(p.read_text())
 except Exception as e: malformed.append({'path':str(p),'error':str(e)});continue
 receipts+=1
 status=d.get('status'); rc=d.get('returncode')
 if not(status in ('failed','error','terminated','timeout','cancelled','aborted') or isinstance(rc,int) and rc!=0):continue
 allocated=0; logical=0; count=0; numeric=[]
 for base,dirs,files in os.walk(p.parent,followlinks=False):
  dirs[:]=[x for x in dirs if not (Path(base)/x).is_symlink()]
  for name in files:
   q=Path(base)/name
   try:s=q.lstat()
   except FileNotFoundError:continue
   if not stat.S_ISREG(s.st_mode):continue
   allocated+=s.st_blocks*512;logical+=s.st_size;count+=1
   if q.suffix.lower() in ('.h5','.hdf5','.bi4','.vtk','.vtu','.vtp','.dat','.csv') and s.st_size>1024*1024:
    numeric.append({'path':str(q),'bytes':s.st_size,'allocated_bytes':s.st_blocks*512,'inode':s.st_ino,'device':s.st_dev,'mtime_ns':s.st_mtime_ns})
 rows.append({'receipt':str(p),'receipt_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'status':status,'returncode':rc,'error':d.get('error'),'request_kind':d.get('request',{}).get('kind'),'total_allocated_bytes':allocated,'total_payload_bytes':logical,'total_files':count,'large_numeric_files':numeric})
rows.sort(key=lambda x:x['total_allocated_bytes'],reverse=True)
prior=[]
for n in (965,1054):
 r=next(H.glob(f'root*_{n}')); c=json.loads((r/'controller-result.json').read_text()); p=Path(c['actual_receipt']); result=p.parent/'cleanup'/'cleanup-result.json'; d=json.loads(result.read_text());prior.append({'root':n,'receipt':str(p),'receipt_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'result':str(result),'result_sha256':hashlib.sha256(result.read_bytes()).hexdigest(),'status':d['status'],'deleted_files':d['deleted_files'],'deleted_payload_bytes':d['deleted_payload_bytes'],'deleted_allocated_bytes':d['deleted_allocated_bytes']})
s=os.statvfs('/home/jade')
out={'schema':'ds02.current-failed-storage-residual-audit.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':str(D),'receipts_read':receipts,'failed_receipts':len(rows),'malformed_receipts':malformed,'prior_cleanup':prior,'failed_attempt_allocated_bytes':sum(x['total_allocated_bytes'] for x in rows),'home_available_bytes':s.f_bavail*s.f_frsize,'home_floor_bytes':500*1024**3,'scientific_payload_contents_read_or_hashed':False,'deletion_this_audit':False,'failed_attempts':rows}
(O/'failed-attempts-current-storage-audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k!='failed_attempts'},ensure_ascii=False))
for r in rows[:25]:print(json.dumps({k:v for k,v in r.items() if k not in ('large_numeric_files',)},ensure_ascii=False), 'largefiles',len(r['large_numeric_files']))
