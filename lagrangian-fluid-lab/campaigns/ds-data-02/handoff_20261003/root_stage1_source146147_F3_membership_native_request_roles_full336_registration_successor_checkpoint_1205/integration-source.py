from pathlib import Path
import hashlib,json,subprocess,datetime,collections,os,copy
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';B=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics');F=Path('lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003');D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.py','.md','.xml','.xmf'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,d):
 with Path(p).open('x') as f:json.dump(d,f,ensure_ascii=False,indent=2);f.write('\n')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
cp_path=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_185.json';cp=load(cp_path);assert cp['stage1_visual_accepted_complete_independent_cases']==269
O=H/'root_stage1_source146147_F3_membership_native_request_roles_full336_registration_successor_checkpoint_1205';O.mkdir(exist_ok=False)
source_specs=[('ce5819a61c36641b4d5e67e2ebd1d4b7fe5ebf86',F/'root_followup_146_f3_first8_first24_roster_membership_audit_v1','scripts/validate_fresh146.py',[]),('28383aad4ceedacc447cbafd4cb36327edc547e2',F/'root_followup_147_f3_native_receipt_scope_closure_v1','metadata/validate_scope_closure.py',['--synthetic'])]
adopt=[];scoped=[]
for commit,pkg,validator,args in source_specs:
 files=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(pkg)],cwd=B,text=True).splitlines();assert files
 before={}
 for rel in files:
  blob=subprocess.check_output(['git','show',commit+':'+rel],cwd=B);src=B/rel;assert src.read_bytes()==blob;dst=R/rel
  if dst.exists():assert dst.read_bytes()==blob
  else:dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(blob)
  assert subprocess.check_output(['git','hash-object',str(dst)],cwd=R,text=True).strip()==subprocess.check_output(['git','rev-parse',commit+':'+rel],cwd=B,text=True).strip()
  before[str(src)]=sha(src);before[str(dst)]=sha(dst);scoped.append(rel)
 run=subprocess.run(['python3','-B',str(B/pkg/validator),*args],cwd=B/pkg,text=True,capture_output=True);assert run.returncode==0,run.stderr
 assert before=={p:sha(p) for p in before}
 adopt.append({'commit':commit,'package':str(pkg),'exact_files':files,'source_and_adopted_bytes_unchanged':before,'readonly_validator_stdout':run.stdout,'readonly_validator_returncode':run.returncode,'semantic_claims_adopted_only_with_main_role_corrections':True})
s147=load(B/source_specs[1][1]/'metadata/f3-native-receipt-scope-closure.json');f3={r['physical_case_id']:r for r in s147['rows']};oldp=root(1198)/'full336-physical-case-registration-progress-index.json';old=load(oldp);accepted={}
for p in cp['accepted_decisions']:
 a=load(p);assert a['physical_case_id'] not in accepted;accepted[a['physical_case_id']]=(Path(p),a)
assert len(accepted)==269

def native_refs(obj,trail=''):
 found=[]
 if isinstance(obj,dict):
  if 'native' in trail.lower() and obj.get('path','').endswith('/execution-receipt.json'):
   found.append(obj)
  for k,v in obj.items():found+=native_refs(v,trail+'.'+k)
 elif isinstance(obj,list):
  for i,v in enumerate(obj):found+=native_refs(v,trail+'.'+str(i))
 return found
rows=[];unknown=[];native_nonterminal=[];disagreements=[]
for orig in old['cases']:
 pid=orig['physical_case_id'];row={'family_id':orig['family_id'],'physical_case_id':pid,'case_id':orig['case_id'],'new_case_credit':0,'old_roster_row_preserved_reference':ref(oldp),'old_roster_condition_field':{'field':'canonical_physical_condition_sha256' if 'canonical_physical_condition_sha256' in orig else 'declared_render_request_condition_sha256','sha256':orig.get('canonical_physical_condition_sha256',orig.get('declared_render_request_condition_sha256')),'role':'historical index declaration; no native canonical claim inferred'}}
 q=None;a=None;refs=[]
 if pid in accepted:
  p,a=accepted[pid];row.update(status='visual-approved-in-checkpoint185',accepted_decision=ref(p),case_credit_already_in_authoritative_checkpoint=1,accepted_decision_top_condition_sha256=a['physical_condition_sha256'],accepted_decision_top_hash_role='preserved decision field; compared independently to actual native request below',precision_status='视觉检查通过、数值精度未验收');refs=native_refs(a)
  row['declared_source_plan_condition_sha256']=a.get('source_plan_condition_sha256',a.get('source_plan_physical_condition_sha256'))
  row['declared_source_definition_sha256']=a.get('source_definition_sha256')
  row['declared_actual_converter_scope_sha256']=a.get('actual_converter_scope_sha256')
 else:
  qr=orig['latest_registered_render_request'];assert sha(qr['path'])==qr['sha256'];q=load(qr['path']);assert q['physical_case_id']==pid
  row.update(status='registered-render-awaiting-completion-and-personal-review',case_credit=0,latest_registered_render_request=qr,declared_render_request_condition_sha256=q.get('physical_condition_sha256'),declared_actual_converter_scope_sha256=q.get('actual_converter_scope_sha256'),expected_frames=q['expected_frames'],expected_contact_sheets=q['expected_contact_sheets'])
  for p in q.get('input_files',[]):
   if p.endswith('/execution-receipt.json') and 'native' in Path(p).parent.name.lower() and 'typed' not in Path(p).parent.name.lower():refs.append({'path':p,'sha256':q.get('input_sha256',{}).get(p)})
 if pid in f3:
  s=f3[pid];nr=s['native_receipt'];refs=[{'path':nr['path'],'sha256':nr['observed_sha256']}];row['F3_source147_raw_scope_fields_preserved']={k:s[k] for k in ('native_canonical_scope','source_plan_scope','actual_converter_legacy_scope','accepted_decision_top_hash','completion_semantics')};row['historical_native_alternate_completion_evidence']=s['alternate_completion_evidence'];row['declared_actual_converter_scope_sha256']=s['actual_converter_legacy_scope']['sha256']
 candidates={}
 for rr in refs:
  p=Path(rr['path']);assert p.suffix=='.json';actual=sha(p)
  if rr.get('sha256'):assert actual==rr['sha256'],p
  n=load(p);nq=n.get('request',{});binding=nq.get('physical_binding');physical=nq.get('physical_case_id') or (binding.get('physical_case_id') if isinstance(binding,dict) else None)
  if physical!=pid:continue
  cond=nq.get('physical_condition_sha256')
  if not cond:continue
  candidates[str(p)]={'receipt':ref(p),'status':n.get('status'),'returncode':n.get('returncode'),'returncode_field_present':'returncode' in n,'native_completed0':n.get('status')=='completed' and n.get('returncode')==0,'embedded_request_case_id':nq.get('case_id'),'embedded_request_physical_case_id':physical,'embedded_request_condition_sha256':cond,'receipt_request_sha256':n.get('request_sha256')}
 if len(candidates)==1:
  ev=next(iter(candidates.values()));row['native_request_scope']={'sha256':ev['embedded_request_condition_sha256'],'role':'actual native receipt embedded request condition','evidence':ev,'condition_is_not_inferred_from_accepted_top_or_source_plan':True}
  if not ev['native_completed0']:native_nonterminal.append(pid)
  raw=row.get('accepted_decision_top_condition_sha256',row.get('declared_render_request_condition_sha256'));row['top_or_render_declared_condition_equals_actual_native_request']=raw==ev['embedded_request_condition_sha256']
  if raw!=ev['embedded_request_condition_sha256']:disagreements.append({'physical_case_id':pid,'native_request_condition':ev['embedded_request_condition_sha256'],'decision_or_render_declaration':raw,'distinct_roles_preserved':True})
 else:
  row['native_request_scope']={'sha256':None,'role':'not independently resolved in this metadata-only pass','candidate_receipts':list(candidates.values())};unknown.append(pid)
 rows.append(row)
counts=collections.Counter(r['family_id'] for r in rows);assert len(rows)==len({r['physical_case_id'] for r in rows})==336;assert counts=={f'F{i}':48 for i in range(1,8)}
assert next(r for r in rows if r['case_id']=='F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005')['native_request_scope']['sha256']=='86562c5afee8228131d58c1b53f360eb6c6a700381c01bf807a0f268bbc675c0'
assert next(r for r in rows if r['case_id']=='F3_STAGE1_DP006_P1000_AY0340')['native_request_scope']['sha256']=='f8c54693a891fd2ad7d9b166c0adeeb489a680d8991255b6770db641fc83dbd4'
assert next(r for r in rows if r['case_id']=='F3_STAGE1_DP006_P1000_AY0270')['native_request_scope']['sha256']=='a6a7dfcc6a3c45b895ae096d652c4bf4d203b6b3b9d228e40c7c7518e8d109e9'
s146=load(B/source_specs[0][1]/'metadata/f3-first8-first24-current48-membership-audit.json');membership=[]
for x in s146['membership_proof']['first24_rows']:
 r=next(r for r in rows if r['physical_case_id']==x['source_physical_case_id']);assert r['case_id']==x['case_id'];membership.append({'case_id':r['case_id'],'physical_case_id':r['physical_case_id'],'order':x['order'],'in_first8':x['in_first8_frozen_membership'],'first24_declared_condition':x['source_condition_sha256'],'actual_native_request_condition':r['native_request_scope']['sha256'],'condition_equal':x['source_condition_sha256']==r['native_request_scope']['sha256'],'old_index_role_comparison':x['membership_relation']})
assert len(membership)==24 and sum(x['in_first8'] for x in membership)==8
put(O/'source146147-exact-adoption-and-readonly-validator-proof.json',{'sources':adopt,'new_case_credit':0})
put(O/'F3-first8-first24-physical-membership-with-actual-native-request-roles.json',{'first8_subset_first24_subset48':True,'first8_physical_ids':8,'first24_physical_ids':24,'current48_physical_ids':48,'source146_preserved':ref(B/source_specs[0][1]/'metadata/f3-first8-first24-current48-membership-audit.json'),'rows':membership,'aliases_never_silently_equated':True,'new_case_credit':0})
roster=O/'full336-role-aware-physical-registration-progress-index.json';put(roster,{'schema':'ds02.stage1.full336.role-aware-progress-index.v2','source_checkpoint':ref(cp_path),'old_index_preserved':ref(oldp),'accepted':269,'registered_pending':67,'physical_cases':336,'per_family_physical_cases':dict(counts),'delivery_complete':False,'Q_N':0,'Q_E':0,'native_request_scope_resolved_cases':336-len(unknown),'native_request_scope_not_resolved_here':unknown,'native_nonterminal_original_receipts_preserved':native_nonterminal,'decision_or_render_vs_native_scope_role_differences':disagreements,'original_147_anchor_canonical_label_not_adopted_as_actual_native_role':True,'cases':rows,'main_scientific_payload_IO':False,'new_case_credit':0})
for k,p in [('runtime_v2_sha256',L/'scripts/ds_data02_runtime_v2.py'),('strict_dispatch_sha256',L/'scripts/ds_data02_strict_dispatch_v1.py'),('Root142_launch_sha256',root(142)/'launch.py')]:assert sha(p)==cp['unmodified_guards'][k]
raw=(D/'runtime/resource-ledger.json').read_bytes();(O/'resource-ledger-frozen.json').write_bytes(raw);ledger=json.loads(raw);s=os.statvfs('/home/jade');free=s.f_bavail*s.f_frsize/2**30;assert free>=500
handles=[]
for n in (1128,951):
 p=root(n);z=load(p/'controller-launch-process.json');stat=Path('/proc')/str(z['pid'])/'stat';same=False
 if stat.exists():parts=stat.read_text().rsplit(')',1)[1].split();same=parts[0]!='Z' and parts[19]==str(z['proc_start_ticks'])
 terminal=p/'controller-result.json';assert same or terminal.exists();handles.append({'root':n,'launch':ref(p/'controller-launch-process.json'),'same_PID_startticks_live':same,'actual_terminal':ref(terminal) if terminal.exists() else None})
put(O/'current-original1128-and951-handle-verification.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'handles':handles,'no_restart':True})
cp.update(checkpoint=186,at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),predecessor=str(cp_path),predecessor_sha256=sha(cp_path),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(O/'resource-ledger-frozen.json'),active_reservations=ledger['reservations'],attempt_counts={k:sum(a['kind']==k for a in ledger['attempts']) for k in ['qualification','production','cpu']},gpu_hours_charged=sum(a.get('gpu_seconds',0) for a in ledger['charges'])/3600,cpu_core_hours_charged=sum(a.get('cpu_core_seconds',0) for a in ledger['charges'])/3600,previous_goal_turn_classification='Progress: exact adopted source146147 metadata, independently separated actual native embedded request condition from historical accepted/index top roles, corrected anchor060 role as a new sidecar, closed F3 first8/24 physical membership; no science rerun or new visual credit.',authorized_work_state='Active269/336. Full336 role-aware registration index successor preserves old1198 and source146147, native OS unknown statuses and semantic aliases. Root1120 actual full401 completed0 assigned fresh164 personal review. Root1128 and951 reverified original handles; registered pending67 awaits real full rendering and personal review.')
cp['actual_progress']['full336_role_aware_physical_registration_index']=ref(roster);cp['actual_progress']['source146147_independent_scope_adoption']=ref(O/'source146147-exact-adoption-and-readonly-validator-proof.json');cp['actual_progress']['F3_first8_first24_physical_membership_actual_native_roles']=ref(O/'F3-first8-first24-physical-membership-with-actual-native-request-roles.json')
cp['next_executable_tasks']=['Adopt fresh164 actual1120 F2 personal17contacts9keys; derive own full401 lifecycle statistics and preserve unknown omissions','Root1128 same original actualhandle: after real0 andpublish, fresh148 personal35contacts9keys; no rerun','Fresh148 investigate anchor060 actualnative vs source semantic alias; preserve four P1000 historical native OS returncode unknown and valid recovered065 artifact evidence','Adopt fresh190 F5first8/24physicalmembership without arbitrary sorting or counting seven sharedmotheraliases as duplicate physical cases','Continue all67 registeredpending full visual deliveries including lastF6 original951; no precision certification']
cp['source_agents'].update(production_recovery='fresh148 nextactual1128 personal full836 review and historical scope alias clarification',f6_endpoint_initial_qa='fresh164 actual1120 completed0 personal full401 review',f5_bed_recovery='fresh190 F5first8/24physicalmembership and next actualpublished0 full801review')
put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_186.json',cp);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes());scoped += [str(p.relative_to(R)) for p in root(1203).iterdir() if p.is_file()]+[str(p.relative_to(R)) for p in root(1204).iterdir() if p.is_file()]+[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str((H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_186.json').relative_to(R)),str((root(1120)/'controller-result.json').relative_to(R))];subprocess.run(['git','add','--',*scoped],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: preserve actual native scope roles and close F3 staged physical membership','--',*scoped],cwd=R,check=True)
print(json.dumps({'checkpoint':186,'accepted':269,'pending':67,'native_scope_resolved':336-len(unknown),'nonterminal_native':len(native_nonterminal),'role_differences':len(disagreements),'Home_free_GiB':free,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
