from pathlib import Path
import os,json,hashlib,subprocess,datetime,stat,re
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
A=root(1217);audit=A/'failed-converter-csv-dependency-reference-audit-complete-worktree-paths.json';a=load(audit);assert a['metadata_files_scanned']>50000 and not a['live_process_references']
fields=load(A/'exact-reference-field-classification.json')['references']
for ref in fields:
 path=Path(ref['metadata']);assert sha(path)==ref['sha256']
 if path.is_relative_to(A) or path==Path(ref['candidate_attempt'])/'execution-receipt.json':continue
 assert not any('/partvtk' in x['value'] for x in ref['matched_fields']),ref
O=H/'root_stage1_user_authorized_two_failed_unused_converter_CSV_cleanup_registered_CPU2_1219';O.mkdir(exist_ok=False)
rows=load(A/'failed-attempts-current-storage-audit.json')['failed_attempts'];attempts=[]
for prefix in a['candidate_attempts']:
 ar=Path(prefix);r=next(x for x in rows if x['receipt']==str(ar/'execution-receipt.json'));assert r['status']=='failed' and r['returncode']==-15 and sha(r['receipt'])==r['receipt_sha256']
 assert not (ar/'trajectory.h5').exists() and not (ar/'conversion-report.json').exists()
 fs=[]
 for p in sorted((ar/'partvtk/csv').glob('Particles_*.csv')):
  if not re.fullmatch(r'Particles_[0-9]+\.csv',p.name):continue
  assert re.fullmatch(r'Particles_[0-9]+\.csv',p.name);s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and p.resolve(strict=True)==p
  fs.append({'path':str(p),'bytes':s.st_size,'allocated_bytes':s.st_blocks*512,'inode':s.st_ino,'device':s.st_dev,'mtime_ns':s.st_mtime_ns})
 assert len(fs)>200
 attempts.append({'attempt_root':str(ar),'attempt_id':str(ar.relative_to(D/'families')),'receipt_sha256':r['receipt_sha256'],'preserved_files':[fs[0],fs[-1]],'eligible_files':fs[1:-1],'reason':'Actual reserved-storage conversion termination (-15), unpublished H5/report absent, no temp-CSV consumer or live process, retain first/last CSV, original native raw, inputs and failure logs.'})
plan=O/'exact-failed-unused-csv-cleanup-plan.json';put(plan,{'schema':'ds02.exact-failed-unused-csv-cleanup-plan.v1','user_authorized':True,'user_request':'清理不合格且无用的中间模拟结果，避免占用存储。','completed_products_protected':True,'accepted_cases_protected':271,'all336_native_pending_and_visual_deliverables_protected':True,'no_dependent_consumers_found':True,'full_dependency_audit':{'path':str(audit),'sha256':sha(audit)},'historical_requests_output_paths_not_CSV_consumers':True,'historical_failed_ledgers_and_receipts_preserved':True,'attempts':attempts,'eligible_files':sum(len(x['eligible_files']) for x in attempts),'eligible_payload_bytes':sum(v['bytes'] for x in attempts for v in x['eligible_files']),'eligible_allocated_bytes':sum(v['allocated_bytes'] for x in attempts for v in x['eligible_files']),'scientific_payload_IO':False,'case_credit':0})
worker=O/'cleanup-worker.py';worker.write_bytes(Path('/tmp/ds02-failed-csv-cleanup-worker-1219.py').read_bytes());controller=O/'registered-cleanup-controller.py';controller.write_bytes((root(1054)/'registered-cleanup-controller.py').read_bytes())
policy=O/'user-authorization-and-retention-policy.json';put(policy,{'actual_failed_unpublished_converter_temp_CSV_only':True,'first_and_last_CSV_samples_retained':True,'failure_receipts_and_logs_native_raw_and_accepted_pending_products_retained':True,'Home_floor_GiB':500,'case_credit':0})
fair=root(928)/'fair_CPU_dispatch.py';assert sha(fair)=='e2796fb88cc989278bcc4d194493f11e5ded7e6d2fb79ef37349d7ae7d8d679f'
base=load(root(1054)/'enabled-cleanup-request.json');ps=[plan,audit,A/'exact-reference-field-classification.json',worker,controller,policy,fair,root(142)/'launch.py',root(142)/'root_home_floor_inventory_policy.py',root(64)/'resource-window-approval.json',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py']+[Path(x['attempt_root'])/'execution-receipt.json' for x in attempts];md={str(p):sha(p) for p in ps}
aid='root-stage1-user-authorized-failed-unused-converter-csv-cleanup-root1219';ar=D/'families/infra/failed-csv-cleanup'/aid;assert not ar.exists()
q={**base,'case_id':'failed-csv-cleanup','attempt_id':aid,'attempt_root':str(ar),'command':[str(L/'.venv/bin/python'),str(worker),'--plan',str(plan),'--plan-sha',sha(plan),'--output-dir','{attempt_root}/cleanup'],'input_files':sorted(md),'input_sha256':md,'physical_condition_sha256':sha(plan),'physical_condition_hash_semantics':'Cleanup manifest only; no physical case or Q-N claim','case_credit':0};qp=O/'enabled-cleanup-request.json';put(qp,q);put(O/'controller-config.json',{'request':str(qp),'fair_dispatch':str(fair),'case_credit':0});(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes())
(A/'README.md').write_text('当前失败存储审计，仅读取元数据与文件 stat。首轮依赖扫描遗漏工作树目录层，未据此删除文件；完整工作树路径扫描为 authoritative successor，原记录保留。完整扫描 52,913 份文件，没有候选临时 CSV 的消费者或运行进程。失败状态不等同物理不合格，已被恢复使用的完整产物继续保留。实际清理通过 root1219 的 CPU2 注册任务完成。\n')
paths=[str(p.relative_to(R)) for od in (A,O) for p in od.iterdir() if p.is_file()];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: register bounded failed converter CSV cleanup with live dependency protection','--',*paths],cwd=R,check=True)
print(json.dumps({'eligible_files':load(plan)['eligible_files'],'eligible_GiB':load(plan)['eligible_allocated_bytes']/2**30,'root':str(O),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
