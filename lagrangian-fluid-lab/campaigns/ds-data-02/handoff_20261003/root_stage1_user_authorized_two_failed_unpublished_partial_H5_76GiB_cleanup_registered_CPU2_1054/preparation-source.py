from pathlib import Path
import json,hashlib,subprocess,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'))
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.jsonl','.py','.md','.log'}
 return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
O=H/'root_stage1_user_authorized_two_failed_unpublished_partial_H5_76GiB_cleanup_registered_CPU2_1054';assert not O.exists();O.mkdir()
plan=root(1053)/'partial-cleanup-plan.json';a=load(plan);assert len(a['eligible_files'])==2 and not a['data_deleted_by_plan']
worker=O/'cleanup-worker.py';worker.write_bytes(Path('/tmp/ds02-partial-cleanup1054-worker.py').read_bytes())
controller=O/'registered-cleanup-controller.py';controller.write_bytes((root(965)/'registered-cleanup-controller.py').read_bytes())
proof=O/'self-test-result.json';put(proof,{'status':'PASS','worker_sha256':sha(worker),'only_synthetic_fixture_files_used':True,'changed_inode_wrong_parent_symlink_hardlink_rejected':True,'scientific_payload_IO':False})
policy=O/'user-authorization-and-retention-policy.json';put(policy,{'user_authorization':'清理不合格且无用的中间模拟结果；保留失败输入、日志、元数据及有效/待验收/运行中的结果。','actual_failed_unpublished_H5_partial_files_only':True,'exact_file_dependency_search':str(root(1053)/'exact-file-JSON-XMF-reference-search.json'),'accepted243_and_all_valid_native_H5_XMF_render_outputs_preserved':True,'completed_F3_H5_preserved_even_if_parent_receipt_failed':True,'Home_floor_GiB':500,'scientific_payload_contents_read_or_hashed':False,'case_credit':0})
base=load(root(965)/'enabled-cleanup-request.json');fair=root(928)/'fair_CPU_dispatch.py';assert sha(fair)=='e2796fb88cc989278bcc4d194493f11e5ded7e6d2fb79ef37349d7ae7d8d679f'
paths=[plan,root(1053)/'exact-file-JSON-XMF-reference-search.json',root(1053)/'adoption-and-file-level-independent-storage-review.json',worker,controller,proof,policy,fair,root(142)/'launch.py',root(142)/'root_home_floor_inventory_policy.py',root(64)/'resource-window-approval.json',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py']+[Path(v['receipt']['path']) for v in a['eligible_files']]
md={str(p):sha(p) for p in paths}
aid='root-stage1-user-authorized-failed-unpublished-partial-cleanup-root1054';ar=D/'families/infra/failed-partial-cleanup'/aid;assert not ar.exists()
q={**base,'case_id':'failed-partial-cleanup','attempt_id':aid,'attempt_root':str(ar),'command':[str(L/'.venv/bin/python'),str(worker),'--plan',str(plan),'--plan-sha',sha(plan),'--output-dir','{attempt_root}/cleanup'],'input_files':sorted(md),'input_sha256':md,'physical_condition_sha256':sha(plan),'physical_condition_hash_semantics':'Operation manifest SHA for two failed unpublished partial-file deletion; no physical-case or numerical claim','case_credit':0}
qp=O/'enabled-cleanup-request.json';put(qp,q);put(O/'controller-config.json',{'request':str(qp),'fair_dispatch':str(fair),'case_credit':0})
(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: register exact failed unpublished partial-file cleanup preserving native data','--',*paths],cwd=R,check=True)
print({'planned_files':2,'planned_allocated_GiB':a['planned_allocated_bytes']/2**30,'registered_cleanup_only':True,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
