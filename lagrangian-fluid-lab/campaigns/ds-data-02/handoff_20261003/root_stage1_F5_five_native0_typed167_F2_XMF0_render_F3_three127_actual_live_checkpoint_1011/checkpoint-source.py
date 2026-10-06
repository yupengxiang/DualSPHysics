from pathlib import Path
import json,hashlib,subprocess,shutil,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.py','.xml','.xmf','.log','.md'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
O=H/'root_stage1_F5_five_native0_typed167_F2_XMF0_render_F3_three127_actual_live_checkpoint_1011';O.mkdir(exist_ok=False);cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_143.json');assert len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==217
# Resolve the missing census directory through frozen accepted mother evidence.
P=L/'campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_127_f3_alias_mother_typed0460_0500_0640_xmf_v1';alias=load(P/'metadata/alias/alias-correction.json');m=alias['accepted_mother_decision'];assert sha(m['path'])==m['sha256'] and m['path'] in cp['accepted_decisions'];decision=load(m['path']);resolution=alias['resolution'];assert decision['physical_case_id']==resolution['resolved_physical_case_id'] and decision['case_id']==resolution['resolved_case_id'] and decision['physical_condition_sha256']==resolution['resolved_physical_condition_sha256']
for r in alias['actual_mother_metadata_evidence']+alias['source_definition_evidence']:
 assert sha(r['path'])==r['sha256']
 if Path(r['path']).name=='execution-receipt.json':
  a=load(r['path']);assert (a['status'],a['returncode'])==('completed',0)
assert resolution['no_new_gencase_or_native_request'] and resolution['independent_case_count_increment']==0 and not list((P/'requests').rglob('*P1000_AY0500*'))
put(O/'actual-source127-mother-alias-independent-closure.json',{'source_alias':ref(P/'metadata/alias/alias-correction.json'),'actual_accepted_mother_decision':m,'all_actual_mother_receipts_and_frozen_first8_sources_unchanged':True,'resolved_physical_case_id':resolution['resolved_physical_case_id'],'current_F3_accepted_count':cp['accepted_per_family']['F3'],'no_duplicate_native_job_or_case_credit':True,'science_payload_IO':False})
# Explicit provenance repair of the stale informational decoder contract, without
# changing the immutable source167 package or scientific command.
P167=L/'campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_167_f5_native_ready_typed157_home4gib_remaining_v1';wc=load(P167/'metadata/worker-contract.json');q=load(load(root(1006)/'controller-config.json')['requests'][0]);tools=q['root_actual_converter_tool_bindings_from974'];tool=next(x for x in tools if x['path']==wc['decoder']['path']);assert wc['decoder']['sha256_producer_attested']!=tool['sha256']=='b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e'
a=load(tool['actual_receipt']);resolved=str(Path(tool['path']).resolve());assert a['input_hashes_at_launch'][resolved]==a['input_hashes_after_run'][resolved]==q['input_sha256'][tool['path']]==tool['sha256']
put(O/'immutable-source167-stale-tool-contract-grounded-actual974-binding.json',{'source_contract':ref(P167/'metadata/worker-contract.json'),'original_stale_informational_decoder_SHA':wc['decoder']['sha256_producer_attested'],'new_enabled_request_actual_binary_SHA':tool['sha256'],'actual_producer_receipt':ref(tool['actual_receipt']),'source_bytes_preserved':True,'original157_worker_and_decoder_CLI_path_unchanged':True,'old_stale_SHA_not_used_as_runtime_binding':True,'science_payload_IO':False,'case_credit':0})
observed=[]
for n in [951,972,978,983,984,987,988,991,998,1002,1003,1004,1006,1007,1008,1009,1010]:
 o=root(n);entry={'root':n,'live':False}
 for p in o.glob('*launch*.json'):
  x=load(p)
  if not isinstance(x,dict) or not x.get('pid'):continue
  st=Path(f"/proc/{x['pid']}/stat")
  if st.exists():
   raw=st.read_text().split(') ',1)[1].split()
   if raw[0]!='Z' and raw[19]==str(x.get('proc_start_ticks',x.get('start_ticks'))):entry.update(live=True,pid=x['pid'],start_ticks=raw[19],actual_launch_receipt=ref(p))
 for name in ['actual-progress.json','controller-result.json','actual-result.json']:
  p=o/name
  if p.exists():
   f=O/f'root{n}-{name}-frozen.json';f.write_bytes(p.read_bytes());entry[name]=ref(f)
 observed.append(entry)
put(O/'actual-process-and-producer-observation.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'processes':observed,'no_restarts':True,'case_credit':0})
# F2 XMF true0 is already independently closed in the committed render binding.
z=load(root(1007)/'actual-progress.json')['results'][0];assert z['actual_full401_N3_XMF_pass'] and (z['status'],z['returncode'])==('completed',0)
put(O/'actual-downstream-registrations-and-terminal-summary.json',{'new_F5_full801_typed_native0_requests':ref(root(1006)/'source167-adoption-and-primary-five-case-metadata-review.json'),'new_F5_full801_XMF_requests':ref(root(1008)/'two-actual983-full801-independent-QI-and-XMF-registration.json'),'actual_F2_full401_XMF0':ref(z['actual_receipt']),'actual_F2_full401_manifest':ref(z['actual_manifest']),'actual_F2_full401_XML_N3_exact_typed_times_review':ref(root(1009)/'actual1007-full401-XMF-and995-typed-independent-review.json'),'new_F3_three_full836_typed0_to_XMF':ref(root(1010)/'source127-adoption-three-actual978991-independent-QI-review.json'),'visual_count_unchanged_until_actual_render_and_personal_review':217,'science_payload_IO':False})
raw=(D/'runtime/resource-ledger.json').read_bytes();(O/'resource-ledger-frozen.json').write_bytes(raw);ledger=json.loads(raw)
cp.update(checkpoint=144,at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),predecessor=str(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_143.json'),predecessor_sha256=sha(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_143.json'),new_accepted_decisions=[],home_free_gib=shutil.disk_usage('/home/jade').free/2**30,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),active_reservations=ledger['reservations'],attempt_counts={k:sum(x['kind']==k for x in ledger['attempts']) for k in ['qualification','production','cpu']},gpu_hours_charged=sum(x.get('gpu_seconds',0) for x in ledger['charges'])/3600,cpu_core_hours_charged=sum(x.get('cpu_core_seconds',0) for x in ledger['charges'])/3600,previous_goal_turn_classification='Progress: previous turn integrated six actual full-window visuals to217 and started downstream F3. This turn five independent existing F5 full801 native0 cases registered and admitted for4GiB typed167, two actual F5 typed0 XMF1008 admitted, actual F2 recovered typed0 XMF1007 completed0 and full401 render1009 admitted, three additional actual F3 typed0 source127 XMF1010 admitted. Missing P1000AY0500 source alias independently resolved against accepted mother, no duplicate science or credit.')
assert cp['home_free_gib']>=500
cp['actual_progress']['five_F5_native0_conversion_two_F5_XMF_F2_actual_XMF0_render_three_F3_XMF']=ref(O/'actual-downstream-registrations-and-terminal-summary.json')
cp['source_agents']['production_recovery']='fresh127 byte-exact adopted42files; unchanged original validator pass, existing accepted mother alias independently exact; three typed0 full836 XMF1010 launched; fresh128 full48 per-stage census and next<=3 actualtyped0 handoff active'
cp['source_agents']['f5_bed_recovery']='fresh167 byte-exact adopted17files, unchanged validator main all assertions pass with independent output only; five native0 full801 typed1006 admitted using actual974 tool binding; fresh169 bed firstM086T095/full48 census active'
cp['next_executable_tasks']=['Adopt fresh169 F5 first M086T095 original138 full801 bed handoff; actual993 first0 and actual998 two original XMF requests now terminal0.','Adopt fresh140 F2 remaining20 native0 <=12 typed157 capped requests, excluding successful995 case.','Integrate F3 fresh128 authoritative full48 per-physical-condition per-stage census and next<=3 true typed0 handoff; alias mother not recounted.','Only actual render0 951/972/984/987/1003/1004/1009 can enter delegated contact/key personal review; compare accepted217 and pending packages before credit.','Close next actual1002 or1010 truefull836 XMF0 to original116023 full836 render with bounded Home cap and shared2.','Advance remaining full801 F5 typed0 XMF then full-event bed audit then render; exact completed products reused, source roles retained, numerical negatives not granted precision.']
put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_144.json',cp);(O/'checkpoint-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str((H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_144.json').relative_to(R))]
for n in [1006,1007,1008,1009,1010]:paths.extend(str(p.relative_to(R)) for p in root(n).glob('*launch*.json'))
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: checkpoint217 and actual F2 dynamic0 F5 conversions F3 alias-safe downstream','--',*paths],cwd=R,check=True);print({'checkpoint':144,'accepted':217,'home_free_GiB':cp['home_free_gib'],'gpu_h':cp['gpu_hours_charged'],'cpu_core_h':cp['cpu_core_hours_charged'],'attempts':cp['attempt_counts'],'live_roots':[x['root'] for x in observed if x['live']],'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
