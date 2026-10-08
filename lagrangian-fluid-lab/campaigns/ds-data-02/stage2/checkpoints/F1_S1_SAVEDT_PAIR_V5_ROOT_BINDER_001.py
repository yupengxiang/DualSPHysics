from pathlib import Path
import json,hashlib,copy,xml.etree.ElementTree as ET
root=Path('/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics');lab=root/'lagrangian-fluid-lab';stage=lab/'campaigns/ds-data-02/stage2';scripts=lab/'scripts'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def signature(node):return (node.tag,tuple(sorted(node.attrib.items())),(node.text or '').strip(),tuple(signature(c) for c in node))
for mode in ['same','half']:
 src=stage/'requests/stage2-priority-four-savedt-v2'/('f1_s1_'+mode+'_cfl_savedt_v2.json');d=json.loads(src.read_text());b=d['source_binding'];source=b['source']['current_bi4'];overlay=b['overlay_exact']['bi4'];assert sha(source['path'])==source['sha256']==sha(overlay['path'])
 source_tree=ET.parse(b['source']['current_xml']['path']).getroot();other_tree=ET.parse(b['overlay_exact']['xml']['path']).getroot()
 for tree in [source_tree,other_tree]:
  for parent in tree.iter():
   for ch in list(parent):
    if ch.tag=='savedt' or (ch.tag=='special' and len(ch)==1 and ch[0].tag=='savedt' and not ch.attrib):parent.remove(ch)
  if mode=='half':
   for ch in tree.iter('cflnumber'):ch.set('value','EXPECTED_MODE_CFL')
 assert signature(source_tree)==signature(other_tree),'undeclared physics/geometry change'
 assert b['current_source_exact']['source_particles']==141636 and b['current_source_exact']['source_fluid_particles']==40200
 d=copy.deepcopy(d);d['attempt_id']='f1-s1-'+mode+'cfl-dense-savedt-v2-primary-001-v5';d['launch_allowed']=True;d['execution_allowed']=True;d['launch_disabled']=False;d['canonical_ready']=True;d['launch_owner']='root';d['cwd']=str(root);d['worktree_root']=str(root);d['max_wall_seconds']=1800
 maps=d['input_hashes'];decl={}
 for path in d['input_files']:
  actual=sha(path);expected=maps[path]
  if len(expected)==64:assert actual==expected,path
  else:
   assert expected=='PARENT_V4_GUARD_REQUIRED'
   if path.endswith('.bi4'):assert actual==source['sha256']
   else:assert path==d['command'][0] and actual=='0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29'
  decl[path]=actual
 closure=[scripts/n for n in ['ds_data02_stage2_dispatch_v5.py','ds_data02_strict_dispatch_v5.py','ds_data02_runtime_v5.py','ds_data02_runtime_v2.py']]+[src,Path(__file__)]
 # The root binder itself is copied into a versioned evidence file before use.
 binder=stage/'checkpoints/F1_S1_SAVEDT_PAIR_V5_ROOT_BINDER_001.py'
 if not binder.exists():binder.write_bytes(Path(__file__).read_bytes())
 closure[-1]=binder
 for path in closure:decl[str(path)]=sha(path)
 d['input_files']=list(decl);d['input_hashes']=dict(decl);d['input_sha256']=dict(decl)
 d['root_canonical_binding']={'prior_request':str(src),'prior_request_sha256':sha(src),'actual_solver_binary_sha_verified':True,'actual_BI4_same_source_overlay_sha_verified':True,'normalized_XML_equal_except_preregistered_SaveDt_CFL':True,'reference_credit':'UNKNOWN_UNTIL_ACTUAL_CALIBRATED_OBSERVABLES','runner':'ds_data02_stage2_dispatch_v5.py','v5_pre_and_post_hash_CPU_accounting':'small 6MB source; root will conservatively charge supplemental pre/post overhead separately without declaring complete v5 timing','full_stage2_goal_continues':True}
 d['launch_policy']=dict(d.get('launch_policy',{}),launch_disabled=False,execution_allowed=True,parent_guard=str(scripts/'ds_data02_stage2_dispatch_v5.py'),gpu_uuid_authorization='LIVE_SHARED_INVENTORY_AT_ATOMIC_RESERVATION_REQUIRED')
 d['qualification']={'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN'}
 d['sha256']=hashlib.sha256(json.dumps({k:v for k,v in d.items() if k!='sha256'},sort_keys=True,separators=(',',':'),ensure_ascii=True,default=str).encode()).hexdigest()
 out=stage/'requests'/(d['attempt_id']+'.json');assert not out.exists();out.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');print(out,len(decl),d['attempt_id'])
