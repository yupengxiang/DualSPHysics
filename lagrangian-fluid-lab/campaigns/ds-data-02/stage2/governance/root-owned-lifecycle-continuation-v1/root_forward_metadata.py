from pathlib import Path
import json,hashlib,sys,importlib.util
lab=Path.cwd();stage=lab/'campaigns/ds-data-02/stage2';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lab.parent
sys.path.insert(0,str(lab/'scripts'));from ds_data02_runtime_v8 import _light_validate

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(4194304),b''):h.update(b)
 return h.hexdigest()
def write(q,orig,name,extra=(),deferred=None):
 q['attempt_id']+='-root-forward-030-001';q['worktree_root']=str(root);q['omp_threads']=1
 q['input_files']=list(dict.fromkeys(q['input_files']+[str(orig)]+[str(lab/'scripts'/x) for x in ['ds_data02_runtime_v2.py','ds_data02_runtime_v6.py','ds_data02_runtime_v8.py','ds_data02_batch_runner.py','ds_data02_stage2_dispatch_v8.py','ds_data02_strict_dispatch_v8.py']]+list(map(str,extra))))
 old=q.get('input_hashes',q.get('input_sha256',{}));h={}
 for p in q['input_files']:
  assert Path(p).is_file(),p
  if deferred and p in deferred:h[p]=deferred[p]
  else:
   h[p]=sha(p)
   if p in old:assert old[p]==h[p],p
 q['input_hashes']=q['input_sha256']=h
 q['root_forward_provenance']={'source_request':str(orig),'source_request_sha256':sha(orig),'actual_launch_git_receipt_required':True,'all_full_content_hashes':'actual parent after reservation and after execution','H5_BI4_read_by_root':False,'large_existing_result_JSON_rehashed_by_root':False,'scientific_qualification':'UNKNOWN'}
 _light_validate(q,data_root=D)
 out=stage/'requests'/name;assert not out.exists();out.write_text(json.dumps(q,indent=2,ensure_ascii=False)+'\n');print(out.relative_to(lab),sha(out),len(h))
