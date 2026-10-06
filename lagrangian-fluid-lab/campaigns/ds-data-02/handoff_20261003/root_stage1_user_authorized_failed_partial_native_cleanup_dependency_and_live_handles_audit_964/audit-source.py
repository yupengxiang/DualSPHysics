from pathlib import Path
from collections import deque
import json,re,hashlib,os,datetime,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');load=lambda p:json.loads(Path(p).read_text());root=lambda n:next(H.glob(f'root*_{n:03d}'));rows=load('/tmp/ds02-cleanup-ledger-negative-metadata-candidates.json');candidates=[]
for row in rows:
 ar=Path(row['root']);rc=load(ar/'execution-receipt.json')
 if rc.get('status')!='failed' or rc.get('returncode') in [None,0] or not row['solver'] or row['data_GiB']<0.05:continue
 cmd=rc['command'];tm=[float(x.split(':',1)[1]) for x in cmd if x.startswith('-tmax:')];to=[float(x.split(':',1)[1]) for x in cmd if x.startswith('-tout:')]
 if not tm or not to:
  prefix=next((x for x in cmd if x.startswith('/home/') and 'staged_inputs' in x),None)
  xp=Path(prefix+'.xml') if prefix else None
  if xp and xp.is_file():
   tree=ET.parse(xp)
   params={e.get('key'):e.get('value') for e in tree.findall('.//parameter')}
   if not tm and params.get('TimeMax'):tm=[float(params['TimeMax'])]
   if not to and params.get('TimeOut'):to=[float(params['TimeOut'])]
 if not tm or not to:continue
 expected=round(tm[0]/to[0])+1;data=ar/'solver_output/data';files=[]
 for p in data.iterdir():
  m=re.fullmatch(r'Part_(\d{4,})\.bi4',p.name)
  if m and not p.is_symlink():files.append((int(m.group(1)),p))
 files.sort();count=len(files)
 if not 0<count<expected:continue
 candidates.append({**row,'receipt':str(ar/'execution-receipt.json'),'receipt_sha256':hashlib.sha256((ar/'execution-receipt.json').read_bytes()).hexdigest(),'termination_reason':rc.get('termination_reason'),'tmax_s':tm[0],'tout_s':to[0],'expected_frames_from_actual_recipe':expected,'actual_native_frame_file_count':count,'data_root':str(data),'frame_files':[str(p) for _,p in files],'preserve_initial_and_last_native_frames':[str(files[0][1]),str(files[-1][1])]})
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_127.json');seeds=list(cp['accepted_decisions']);seeds.append(str(root(961)/'actual130-adoption-and-independent-metadata-closure.json'));seeds.extend([str(root(959)/'actual956-all801-bed-independent-review.json')]);controllers=[]
for n in [948,951,960,963]:
 o=root(n);c=load(o/'controller-launch-process.json');p=Path('/proc')/str(c['pid']);s=(p/'stat').read_text().split(') ',1)[1].split() if p.exists() else []
 if s and s[0]!='Z' and s[19]==c['proc_start_ticks']:
  cfg=load(o/'controller-config.json');qs=cfg.get('requests',cfg.get('outer_requests',[cfg.get('request')]));seeds.extend(q for q in qs if q);controllers.append({'root':n,'pid':c['pid'],'start_ticks':s[19],'source':c['controller']})
for family,num in [('F5',160),('F5',161),('F3',118)]:
 pp=list((L/f'campaigns/ds-data-02/families/{family}/handoff_20261003').glob(f'root_followup_{num}_*'))
 for p in pp:seeds.extend(str(q) for q in p.rglob('*.json'))
queue=deque(seeds);seen=set();refs=[];skipped=[]
def strings(v,key=''):
 if isinstance(v,dict):
  for k,x in v.items():yield from strings(x,str(k))
 elif isinstance(v,list):
  for x in v:yield from strings(x,key)
 elif isinstance(v,str) and v.startswith('/home/'):yield v,key
while queue:
 raw=queue.popleft();p=Path(raw)
 if str(p) in seen or p.suffix!='.json' or not p.is_file():continue
 seen.add(str(p));assert len(seen)<60000
 obj=load(p)
 if isinstance(obj,dict) and obj.get('schema','').startswith('ds02.execution') and obj.get('status')=='failed':skipped.append(str(p));continue
 if isinstance(obj,dict) and obj.get('status')=='failed' and 'request' in obj and 'command' in obj:skipped.append(str(p));continue
 for val,key in strings(obj):
  v=Path(val)
  # Failed historical receipt provenance is preserved but does not make all its command outputs active input.
  if v.suffix=='.json':queue.append(val)
  for c in candidates:
   dat=Path(c['data_root'])
   if val==c['root'] or val==str(dat.parent) or val==str(dat) or val.startswith(str(dat)+'/'):refs.append({'candidate':c['id'],'source_metadata':str(p),'key':key,'path':val})
# /proc descriptors and commands provide a fresh active-use exclusion.
active=[]
for proc in Path('/proc').iterdir():
 if not proc.name.isdigit():continue
 try:cmd=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
 except OSError:cmd=''
 for c in candidates:
  if c['root'] in cmd:active.append({'candidate':c['id'],'pid':int(proc.name),'kind':'cmdline'})
 try:fds=list((proc/'fd').iterdir())
 except OSError:continue
 for f in fds:
  try:target=os.readlink(f)
  except OSError:continue
  for c in candidates:
   if target.startswith(c['root']+'/'):active.append({'candidate':c['id'],'pid':int(proc.name),'kind':'open_fd','path':target})
plan=[];blocked=[]
for c in candidates:
 rr=[x for x in refs if x['candidate']==c['id']];aa=[x for x in active if x['candidate']==c['id']];data=Path(c['data_root']);directory_use=[x for x in rr if x['path'] in [c['root'],str(data.parent),str(data)]]
 if aa or directory_use:blocked.append({'id':c['id'],'GiB':c['data_GiB'],'active_uses':aa,'directory_references':directory_use[:20]});continue
 preserved=set(c['preserve_initial_and_last_native_frames'])|{x['path'] for x in rr};deletes=[]
 for name in c['frame_files']:
  if name in preserved:continue
  p=Path(name);st=p.stat()
  if st.st_nlink!=1:continue
  deletes.append({'path':name,'device':st.st_dev,'inode':st.st_ino,'size':st.st_size,'blocks_bytes':st.st_blocks*512,'mtime_ns':st.st_mtime_ns})
 if deletes:plan.append({**{k:v for k,v in c.items() if k!='frame_files'},'preserved_frame_paths':sorted(preserved),'delete_files':deletes,'delete_bytes':sum(v['size'] for v in deletes),'delete_allocated_bytes':sum(v['blocks_bytes'] for v in deletes),'reason':'Actual solver failed/nonzero and incomplete native file sequence against original tmax/tout. No accepted, pending, runnable or live dependency on removed frame files; metadata, headers, initial and final partial states preserved.'})
O=H/'root_stage1_user_authorized_failed_partial_native_cleanup_dependency_and_live_handles_audit_964';O.mkdir(exist_ok=False);out={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'user_authorization':'存储容量不太够了，你可以清理一下中间产生的一些的模拟结果。这些模拟结果假如说是不合格的，那么我们可以把它们清理掉，避免这些没有用的模拟结果大量地占用我们的存储空间。','scope':'DS-DATA-02 failed incomplete unused native numeric Part_*.bi4 only','accepted_decisions_protected':len(cp['accepted_decisions']),'pending130_and_F5_candidates_protected':True,'live_controllers':controllers,'metadata_graph_JSONs_read':len(seen),'metadata_graph_reference_rows':refs,'failed_receipt_provenance_skipped_from_active_output_expansion':skipped,'candidate_incomplete_count':len(candidates),'blocked_candidates':blocked,'eligible_attempts':plan,'planned_delete_bytes':sum(v['delete_bytes'] for v in plan),'planned_delete_allocated_bytes':sum(v['delete_allocated_bytes'] for v in plan),'scientific_payload_contents_read_or_hashed':False,'no_data_deleted_by_audit':True,'q_n_negative_alone_never_cleanup_reason':True};(O/'cleanup-plan.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');(O/'audit-source.py').write_bytes(Path(__file__).read_bytes());(O/'original-bound12000-audit-source.py').write_bytes(Path('/tmp/ds02-root964-cleanup-audit-original-bound12000.py').read_bytes());(O/'metadata-audit-bound-repair.json').write_text(json.dumps({'original_audit_exit':1,'original_reason':'Dependency graph exceeded 12000 JSON metadata nodes, before any output plan or deletion','repair':'Increase metadata-only finite graph node budget to 60000. All candidate and active-use protections unchanged.','payload_reads':False,'files_deleted':0,'repair_number':1})+'\n');print({'eligible':len(plan),'planned_GiB':out['planned_delete_bytes']/1024**3,'metadata_JSONs':len(seen),'eligible_summary':[(p['id'],round(p['delete_bytes']/1024**3,3)) for p in plan],'blocked_summary':[(p['id'],p['GiB']) for p in blocked]})
