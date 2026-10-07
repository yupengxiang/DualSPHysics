from pathlib import Path
import json, hashlib, subprocess, datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
W=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics')
H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
prefix=Path('lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_169_f3_assigned_f6_fulltime_rigid_export_actual_metadata_review_v1')
commit='f40cd17c0f74b50ee3194e30ed279af6bef7f519'
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.py','.md'}
 return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):
 p=Path(p);assert p.suffix=='.json';return json.loads(p.read_text())
def ref(p):return {'path':str(p),'sha256':sha(p)}
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines()
assert len(names)==4
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
for n,b in blobs.items():
 assert (W/n).read_bytes()==b
 assert not (R/n).exists() or (R/n).read_bytes()==b
before={n:sha(W/n) for n in names}
rv=subprocess.run(['python3','-B',str(W/prefix/'validate_fresh169.py')],capture_output=True,text=True)
assert rv.returncode==0,(rv.stdout,rv.stderr)
assert before=={n:sha(W/n) for n in names}
manifest=load(W/prefix/'metadata/package-manifest.json')
for r in manifest['files']:
 assert r['path'] in names and sha(W/r['path'])==r['sha256'] and (W/r['path']).stat().st_size==r['bytes']
review=load(W/prefix/'metadata/fresh169-review.json')
productp=next(H.glob('root*_1305'))/'F6-FINAL48-FULLTIME-RIGID-MOTION-DELIVERY.json'
product=load(productp);assert review['main1305_final_delivery']['product']==ref(productp)
rows={r['physical_case_id']:r for r in product['rows']};assert len(rows)==48
fresh=review['fresh_worker_reports'];assert len(fresh)==47 and len({r['physical_case_id'] for r in fresh})==47
checked=[]
for s in fresh:
 r=rows[s['physical_case_id']]
 assert s['physical_condition_sha256']==r['actual_native_condition_sha256']
 assert s['report']==r['actual_export_report'] and s['outer_execution_receipt']==r['actual_export_receipt']
 for field in ['actual_export_report','actual_export_receipt','actual_complete_native_receipt','actual_runner_request','native_time_source']:
  e=r[field];assert ref(e['path'])==e
 report=load(r['actual_export_report']['path']);receipt=load(r['actual_export_receipt']['path']);request=load(r['actual_runner_request']['path'])
 assert report['status']==receipt['status']=='completed' and report['returncode']==receipt['returncode']==0
 assert receipt['request_sha256']==sha(r['actual_runner_request']['path'])
 assert receipt['input_hashes_at_launch']==receipt['input_hashes_after_run']==request['input_sha256']
 parse=report['parse'];assert parse['part_values_observed']==list(range(241)) and parse['rigid_fields_finite_rows']==241 and parse['required_rigid_field_count']==17
 assert parse['native_time_comparison']['max_abs_delta_s']<=1e-6 and r['frames']==241
 out=report['output'];c=r['official_rigid_motion_CSV'];assert out['csv']==c['path'] and out['sha256']==c['sha256_producer_attested'] and out['bytes']==Path(c['path']).stat().st_size==c['bytes_stat_verified']
 checked.append({'physical_case_id':r['physical_case_id'],'actual_export_report':r['actual_export_report'],'actual_export_receipt':r['actual_export_receipt'],'frames':241,'scientific_CSV_SHA_role':'registered producer attestation; main stat only'})
baseline=rows['F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE'];assert baseline['legacy_Part_column_validation_field_present'] is False and baseline['legacy_Part_unique_count'] is None
assert baseline['case_id']=='F6_ANGULAR_RELEASE_DP025' and baseline['full_saved_rigid_history_finite_and_monotone_through12'] is True
for key in ['actual_export_receipt','actual_export_report','actual_rigid_audit_receipt']:assert ref(baseline[key]['path'])==baseline[key]
assert review['historical_baseline_separate_role']['baseline_part_validation_independently_verified_by_fresh169'] is False
assert product['new_case_credit']==product['Q_N']==product['Q_E']==0
O=H/'root_stage1_source169_F6_actual48_fulltime_rigid_metadata_review_47new_one_legacy_Part_absence_byte_exact_adoption_1310';assert not O.exists();O.mkdir()
for n,b in blobs.items():p=R/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
proof={'schema':'ds02.main.source169.actual48-rigid-review-byte-exact-adoption.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_commit':commit,'source_files':[{**ref(R/n),'source_worktree_path':str(W/n)} for n in names],'source_before_after_SHA':before,'validator_stdout':rv.stdout,'validator_stderr':rv.stderr,'main_product_unchanged':ref(productp),'fresh47_independently_bound_metadata':checked,'historical_baseline_snapshot':baseline,'actual_fulltime_rigid_cases':48,'new_export_count':47,'legacy_full241_count':1,'main_scientific_payload_IO':False,'source_scientific_payload_IO':False,'new_visual_review':False,'new_case_credit':0,'Q_N':0,'Q_E':0,'remaining_visual_cases_not_overridden':41,'next_executable_task':'fresh170 fixed actual-first24 particle/XMF and actual fulltime rigid-history joined delivery; original F2 render publication and personal visual reviews continue.'}
(O/'source169-byte-exact-readonly-validator-and-main48-rigid-metadata-adoption.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
(O/'README.md').write_text('独立绑定并采纳 fresh169：47 个实际完成的 241 帧官方刚体导出，以及一个已有完整时域历史刚体案例。历史案例 Part 独立验证字段保持 false/null。只读验证源文件不变，主进程未打开或哈希科学载荷；不增加案例或视觉信用，Q-N/Q-E 保持0。\n')
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]
subprocess.run(['git','add','--',*paths],cwd=R,check=True)
subprocess.run(['git','commit','-q','-m','DS02: adopt independent metadata review of all48 fulltime rigid histories','--',*paths],cwd=R,check=True)
print({'source169':'byte-exact adopted','actual_fulltime_rigid_cases':48,'new_case_credit':0,'root1310':str(O),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
