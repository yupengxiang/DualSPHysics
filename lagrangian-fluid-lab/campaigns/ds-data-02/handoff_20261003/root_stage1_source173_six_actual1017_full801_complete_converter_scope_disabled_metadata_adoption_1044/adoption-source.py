from pathlib import Path
import json,hashlib,subprocess,datetime,runpy,contextlib,io,re,shutil
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';W=Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.jsonl','.py','.md','.xml','.xmf','.sh','.toml','.ini'}
 return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
prefix='lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_173_f5_native1017_remaining6_typed157_home4gib_disabled_v1'
commit='baab880f6a5810dd1227f353f963da937f533ae9';P=W/prefix
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',prefix],cwd=W,text=True).splitlines();assert len(names)==20
adopted=[]
for name in names:
 raw=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=W);assert raw==(W/name).read_bytes()
 target=R/name;assert not target.exists() or target.read_bytes()==raw;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);adopted.append(ref(target))
O=H/'root_stage1_source173_six_actual1017_full801_complete_converter_scope_disabled_metadata_adoption_1044';assert not O.exists();O.mkdir()
before={name:sha(W/name) for name in names};validator=P/'scripts/validate_fresh173.py';ns=runpy.run_path(str(validator))
with contextlib.redirect_stdout(io.StringIO()):result=ns['main']()
assert result['status']=='pass-disabled-metadata-only' and len(result['cases'])==6
assert before=={name:sha(W/name) for name in names}
put(O/'actual-original173-validator-returned-report.json',result)
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_157.json');accepted=[load(p) for p in cp['accepted_decisions']];assert len(accepted)==240
ids={v.get('physical_case_id',v['case_id']) for v in accepted};scopes={v['physical_condition_sha256'] for v in accepted}
for n in [983,988,1006,1028]:
 for p in (root(n)/'requests').glob('*.json'):
  q=load(p);ids.add(q['physical_case_id']);scopes.add(q['physical_condition_sha256'])
converter=runpy.run_path(str(L/'scripts/ds_data02_direct_convert.py'));rows=[]
for p in sorted((P/'requests').glob('*.json')):
 q=load(p);assert q['disabled'] and q['source_only'] and not q['launch'] and not q['arrays_allowed']
 assert q['physical_case_id'] not in ids and q['physical_condition_sha256'] not in scopes
 ids.add(q['physical_case_id']);scopes.add(q['physical_condition_sha256'])
 n=load(q['actual_native_receipt']);g=load(q['gencase_receipt']);a=load(q['actual_initial_qa_receipt'])
 assert all((v['status'],v['returncode'])==('completed',0) for v in [n,g,a])
 assert n['request']['case_id']==q['case_id'] and n['request']['physical_case_id']==q['physical_case_id']
 assert n['request']['physical_condition_sha256']==q['physical_condition_sha256']
 assert sha(q['actual_native_receipt'])==q['actual_native_receipt_sha256'] and sha(q['actual_native_request'])==q['actual_native_request_sha256']
 assert n['request']['gencase_receipt']==q['gencase_receipt'] and n['request']['gencase_receipt_sha256']==sha(q['gencase_receipt'])
 assert n['input_hashes_at_launch'][q['generated_xml']]==n['input_hashes_after_run'][q['generated_xml']]==q['generated_xml_sha256']==sha(q['generated_xml'])
 counts=q['actual_counts'];assert (counts['total_particles'],counts['fluid_particles'],counts['solver_dimension'])==(194427,31658,3)
 dr=Path(q['native_solver_data_root']);assert sorted(f.name for f in dr.iterdir() if re.fullmatch(r'Part_[0-9]+\.bi4',f.name))==[f'Part_{i:04d}.bi4' for i in range(801)]
 owner=load(q['owner_metadata']);scope=converter['_physical_condition_scope'](owner);digest=converter['canonical_hash'](scope)
 assert owner['physical_case_id']==q['physical_case_id'] and scope==q['source_h5_legacy_scope']['scope_fields']
 assert digest==q['source_h5_legacy_scope']['sha256']==q['root_prospective_legacy_scope_sha256']
 assert set(scope)>={'schema','semantic_binding_status','initial_state','continuum_geometry','gravity_m_s2','parameters','geometry'}
 assert q['source_plan_physical_condition_sha256']==sha(q['source_definition'])
 assert all(v is None for v in q['future_output_hashes'].values())
 tools=[]
 for tool in q['registered_tool_attestations'].values():
  receipt=load(tool['source_receipt']);assert sha(tool['source_receipt'])==tool['source_receipt_sha256']
  assert (receipt['status'],receipt['returncode'])==('completed',0)
  exe=Path(tool['path']);assert exe.suffix.lower() not in ns['SCI']
  current=hashlib.sha256(exe.resolve().read_bytes()).hexdigest();resolved=tool['resolved_receipt_path']
  assert current==tool['sha256']==receipt['input_hashes_at_launch'][resolved]==receipt['input_hashes_after_run'][resolved]
  tools.append({'registered_executable':str(exe),'actual_producer_receipt':ref(tool['source_receipt']),'current_executable_sha256':current})
 rows.append({'tag':q['tag'],'source_request':ref(p),'adopted_request':ref(R/p.relative_to(W)),'physical_case_id':q['physical_case_id'],'native_receipt':ref(q['actual_native_receipt']),'gencase_receipt':ref(q['gencase_receipt']),'initial_qa_receipt':ref(q['actual_initial_qa_receipt']),'source_native_canonical_scope_sha256':q['physical_condition_sha256'],'source_plan_own_definition_file_sha256':q['source_plan_physical_condition_sha256'],'prospective_complete_converter_scope_sha256':digest,'native801_filenames':True,'actual_counts':counts,'future_output_hashes':q['future_output_hashes'],'registered_tools':tools,'science_payload_contents_IO':False,'case_credit':0})
assert len(rows)==6
put(O/'source173-six-full801-independent-metadata-review.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_commit':commit,'adopted_files':adopted,'actual_original_validator':ref(validator),'original_validator_executed_in_source_worktree_to_preserve_self_location_binding':True,'original_validator_report':ref(P/'metadata/fresh173-validation-report.json'),'actual_returned_validator_output':ref(O/'actual-original173-validator-returned-report.json'),'source_all_bytes_unchanged':True,'cases':rows,'current_accepted240_and_live98398810061028_identity_excluded':True,'unchanged_complete_converter_scope_helper':ref(L/'scripts/ds_data02_direct_convert.py'),'scope_hashes_are_metadata_not_future_scientific_payload_hashes':True,'future_scientific_hashes_null':True,'requests_remain_disabled':True,'scientific_tasks_started':0,'main_scientific_payload_IO':False,'Home_free_GiB':shutil.disk_usage('/home/jade').free/2**30,'Home_floor_GiB':500,'numeric_precision_negatives_preserved':True,'q_n_granted':False,'q_e_granted':False,'case_credit':0})
(O/'adoption-source.py').write_bytes(Path(__file__).read_bytes())
paths=[str(Path(v['path']).relative_to(R)) for v in adopted]+[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: adopt six actual full801 F5 disabled conversions with complete prospective scope','--',*paths],cwd=R,check=True)
print({'source_files':len(adopted),'reviewed_native801_cases':6,'requests_disabled':True,'case_credit':0,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
