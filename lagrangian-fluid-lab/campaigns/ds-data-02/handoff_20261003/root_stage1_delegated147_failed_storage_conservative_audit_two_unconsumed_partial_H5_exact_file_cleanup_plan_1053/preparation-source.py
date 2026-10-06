from pathlib import Path
import json,hashlib,subprocess,datetime,os,stat,shutil
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');W=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics')
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.jsonl','.py','.md','.log','.xmf','.xml'}
 return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
prefix='lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_147_failed_artifact_storage_audit_v1';commit='199f30c3ecef5569c42bd1dad2ca810cb81477cc';names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',prefix],cwd=W,text=True).splitlines();assert len(names)==8
adopted=[]
for name in names:
 assert Path(name).suffix in {'.json','.py','.md'}
 raw=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=W);assert raw==(W/name).read_bytes();p=R/name;assert not p.exists() or p.read_bytes()==raw;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);adopted.append(ref(p))
P=R/prefix;O=H/'root_stage1_delegated147_failed_storage_conservative_audit_two_unconsumed_partial_H5_exact_file_cleanup_plan_1053';assert not O.exists();O.mkdir()
before={name:sha(R/name) for name in names};rv=subprocess.run([str(L/'.venv/bin/python'),'-B',str(P/'scripts/validate_fresh147.py')],capture_output=True,text=True);assert rv.returncode==0 and before=={name:sha(R/name) for name in names}
put(O/'actual-original147-validator.json',{'returncode':rv.returncode,'stdout':rv.stdout,'stderr':rv.stderr,'source_reports_unchanged':True})
rows=[D/'families/F4/F4_DROP_CENTERED_REFERENCE_001_DP0025/root-centered-fullstate-conversion-001',D/'families/F1/F1_REF_DUAL_NOMINAL_MEDIUM/native-conversion-reference-003']
targets=[ar/'trajectory.h5.partial' for ar in rows];scope=[L/'campaigns/ds-data-02']+[Path(f'/home/jade/.codex/worktrees/ds-data-02-{f}/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02') for f in ['f3','f5','f6']]+[D/'families']
command=['rg','-l','-F','--glob','*.json','--glob','*.xmf']
for target in targets:command.extend(['-e',str(target)])
command.extend(map(str,scope));rg=subprocess.run(command,capture_output=True,text=True);assert rg.returncode in [0,1] and not rg.stderr
hits=rg.stdout.splitlines();oldpreserve=L/'campaigns/ds-data-02/families/F4/handoff_20261002/centered_reference_matrix_001/root_drop_nvme_conversion_review_002/owned-decoder-scratch-reclamation.json'
assert hits==[str(oldpreserve)],hits
old=load(oldpreserve);assert old['preserved_partial_h5']==str(targets[0]) and old['own_child_confirmed_terminated'] and old['native_solver_raw_untouched']
put(O/'exact-file-JSON-XMF-reference-search.json',{'command':command,'returncode':rg.returncode,'stdout':rg.stdout,'stderr':rg.stderr,'scope_integration_and_three_active_family_worktrees_and_data_metadata':True,'only_matching_reference':ref(oldpreserve),'matching_reference_role':'Historical Oct2 scratch cleanup recorded preservation of incomplete partial H5; no completed artifact, runnable input or dynamic file references this temporary file. Current user authorized failed intermediate cleanup.','scientific_payload_contents_read_or_hashed':False})
ledger=load(D/'runtime/resource-ledger.json');candidates=[]
for ar,p in zip(rows,targets):
 rp=ar/'execution-receipt.json';r=load(rp);assert r['status']=='failed' and r['returncode'] not in [None,0]
 aid=str(ar.relative_to(D/'families'));a=[v for v in ledger['attempts'] if v['id']==aid];assert len(a)==1 and a[0]['status']=='failed'
 assert not any(v.get('id')==aid for v in ledger['reservations'])
 cmd=r['command'];output=Path(cmd[cmd.index('--output')+1]);assert output==ar/'trajectory.h5' and p==output.with_suffix('.h5.partial')
 assert not output.exists() and not (ar/'conversion-report.json').exists()
 assert p.resolve(strict=True)==p and ar.resolve(strict=True)==ar
 s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
 live=[]
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:cmdline=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
  except OSError:cmdline=''
  if str(ar) in cmdline:live.append({'pid':proc.name,'kind':'cmdline'})
  try:fds=list((proc/'fd').iterdir())
  except OSError:continue
  for fd in fds:
   try:v=os.readlink(fd)
   except OSError:continue
   if v.startswith(str(ar)+'/'):live.append({'pid':proc.name,'kind':'open_fd'})
 assert not live,live
 candidates.append({'attempt_id':aid,'attempt_root':str(ar),'receipt':ref(rp),'path':str(p),'device':s.st_dev,'inode':s.st_ino,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'blocks_bytes':s.st_blocks*512,'hard_links':s.st_nlink,'absence_of_successful_published_H5_and_conversion_report':True,'actual_failed_status':r['status'],'actual_failed_returncode':r['returncode'],'live_references':live,'reason':'Actual failed nonzero converter left only unpublished trajectory.h5.partial; no completed conversion report or published H5, no live process/fd and no completed/runnable metadata input reference to exact temporary file. Preserve native raw and failure receipt/logs.'})
put(O/'partial-cleanup-plan.json',{'schema':'ds02.failed-unpublished-partial-cleanup-plan.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'user_authorization':'清理不合格且无用的中间模拟结果以释放存储；保留有效/待验收/live数据和失败证据。','accepted_cases_protected':243,'source147_original_conservative_directory_reference_audit':ref(P/'metadata/failure-artifact-reference-audit.json'),'additional_exact_file_reference_closure':ref(O/'exact-file-JSON-XMF-reference-search.json'),'eligible_files':candidates,'planned_allocated_bytes':sum(v['blocks_bytes'] for v in candidates),'planned_payload_bytes':sum(v['size'] for v in candidates),'scientific_payload_contents_read_or_hashed':False,'data_deleted_by_plan':False,'numeric_QN_failure_alone_not_deletion_reason':True,'completed_H5_F3_half_save_preserved_even_when_parent_receipt_failed':True,'original_metadata_and_failure_receipts_preserved':True})
put(O/'adoption-and-file-level-independent-storage-review.json',{'source_commit':commit,'adopted_files':adopted,'source_original_validator':ref(O/'actual-original147-validator.json'),'source147_zero_safe_candidates_is_conservative_directory_match_snapshot_not_global_no_partial_file_claim':True,'partial_file_cleanup_plan':ref(O/'partial-cleanup-plan.json'),'no_source147_reports_modified':True,'science_payload_IO':False,'files_deleted':0,'Home_free_GiB':shutil.disk_usage('/home/jade').free/2**30,'case_credit':0})
(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(Path(z['path']).relative_to(R)) for z in adopted]+[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: close failed storage audit and exact unpublished partial file cleanup scope','--',*paths],cwd=R,check=True)
print({'planned_files':2,'planned_allocated_GiB':sum(v['blocks_bytes'] for v in candidates)/2**30,'science_payload_IO':False,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
