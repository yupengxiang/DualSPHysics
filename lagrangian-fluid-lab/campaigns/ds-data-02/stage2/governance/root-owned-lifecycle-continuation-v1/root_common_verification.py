from pathlib import Path
import json,hashlib,datetime,math,xml.etree.ElementTree as E
lab=Path.cwd();S=lab/'campaigns/ds-data-02/stage2';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');L=json.loads((D/'runtime/resource-ledger.json').read_text())
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(4194304),b''):h.update(b)
 return h.hexdigest()
def common(qp,status='completed'):
 q=load(qp);b=D/'families'/q['family_id']/q['case_id']/q['attempt_id'];rp=b/'execution-receipt.json';r=load(rp);assert r['request']==q and sha(qp)==r['request_sha256'];assert r['status']==status;assert r['source_preflight']['reservation_registered_before_content_hash'];assert r['input_hashes_at_launch']==r['input_hashes_after_run'];fresh=[]
 for p,h in r['input_hashes_at_launch'].items():
  if Path(p).suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.vtk'} and Path(p).stat().st_size<=10485760:assert sha(p)==h;fresh.append({'path':p,'sha256':h})
 ident='/'.join(q[k] for k in ['family_id','case_id','attempt_id']);c=[x for x in L['charges'] if x['id']==ident];assert len(c)==1 and not any(x['id']==ident for x in L['reservations']);c=c[0];tree=sum(p.stat().st_size for p in b.rglob('*') if p.is_file());assert tree==r['bytes']==c['new_storage_bytes'];assert r['cpu_core_seconds']==c['cpu_core_seconds'] and c['status']==status
 return q,b,r,{'schema':'ds02.stage2.root-actual-verification.v1','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'request':str(qp),'request_sha256':sha(qp),'receipt':str(rp),'receipt_sha256':sha(rp),'actual_launch_git':r['git_at_launch'],'parent_actual_prepost_content_hashes_equal':True,'fresh_small_inputs':fresh,'actual_cpu_core_seconds':r['cpu_core_seconds'],'wall_seconds':r['wall_seconds_from_entry'],'actual_tree_bytes':tree,'parent_charge':c,'parent_reservation_released':True,'H5_BI4_read_by_root':False,'scientific_qualification':{'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN'},'goal_complete':False}
def write(name,p):
 out=S/'checkpoints'/name;assert not out.exists();out.write_text(json.dumps(p,indent=2,ensure_ascii=False)+'\n');print(name,sha(out),p['status'])

