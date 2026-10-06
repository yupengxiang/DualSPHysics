from pathlib import Path
import json,hashlib,subprocess,datetime,shutil
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def ref(p):
    p=Path(p);assert p.suffix in {'.json','.jsonl','.py','.md','.xml','.txt'}
    return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_133.json')
assert cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==205
O=H/'root_stage1_storage_cleanup_preserved_actual974971_completions_977981983984_live_scoped_checkpoint_985';O.mkdir(exist_ok=False)
rows=[];paths=[]
for n in [948,951,971,972,974,977,978,981,982,983,984]:
    folder=root(n);launch=folder/'controller-launch-process.json';j=load(launch);proc=Path('/proc')/str(j['pid'])/'stat'
    live=proc.exists() and proc.read_text().split(') ')[1].split()[19]==str(j['proc_start_ticks'])
    z={'root_number':n,'controller_launch':ref(launch),'controller_pid':j['pid'],'proc_start_ticks':j['proc_start_ticks'],'same_PID_start_live':live}
    for f in ['actual-progress.json','controller-result.json']:
        p=folder/f
        if p.exists():
            raw=p.read_bytes();snapshot=O/f'actual{n}-{f}-immutable-snapshot.json';snapshot.write_bytes(raw);data=json.loads(raw)
            z[f]=ref(snapshot)
            if f=='actual-progress.json':
                rr=data.get('results',[]);z.update(actual_completed0=sum(v.get('status')=='completed' and v.get('returncode')==0 for v in rr),not_submitted=data.get('not_submitted',data.get('pending_not_submitted')))
            else:z['terminal_controller_result']=data
    if j.get('request'):
        q=load(j['request']);receipt=Path(q['attempt_root'])/'execution-receipt.json'
        z['actual_registered_attempt_receipt_exists']=receipt.exists()
        if receipt.exists():
            a=load(receipt);z.update(actual_registered_status=a['status'],actual_registered_returncode=a.get('returncode'),actual_producer_pid=a.get('pid'))
            if a['status']=='completed':z['terminal_actual_receipt']=ref(receipt)
    rows.append(z)
    paths.append(str(launch.relative_to(R)))
free=shutil.disk_usage('/home/jade').free/1024**3
assert free>=500
report=O/'actual-metadata-progress-storage-and-next-actions.json'
put(report,{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'actual_handles_and_terminal_results':rows,
    'failed_unused_native_cleanup':ref(root(966)/'actual-cleanup-independent-review.json'),
    'failed_unused_native_cleanup_reclaimed_GiB':439.00610971078277,'failed_attempts_cleaned':14,
    'current_Home_free_GiB':free,'Home_floor_GiB':500,'floor_pass':True,
    'accepted_cases':205,'new_unaccepted_products_do_not_add_case_credit':True,
    'actual974_full836_conversion_independent_closure':ref(root(977)/'actual974-full836-independent-metadata-review.json'),
    'actual971_full801_bed_and968_XMF_independent_closure':ref(root(984)/'actual971-all801-bed-and968-XMF-independent-review.json'),
    'source165_actual982_prelaunch_tool_digest_rejection':ref(root(982)/'actual-prelaunch-decoder-digest-failure-classification.json'),
    'source165_actual983_tool_binding_successor':ref(root(983)/'actual-tool-metadata-repair-and-12-request-closure.json'),
    'fresh136_delegated3_source_commit':'b2c5091f417671e2a191f6dfe3286a2a6dfc73fe',
    'fresh136_case_credit_pending_primary_independent_closure':0,
    'scientific_payload_contents_IO_by_primary':False,'registered_tool_binary_digest_only_by_primary':True,
    'numeric_negative_cleanup_criterion':False,'all_accepted_pending_live_completed_usable_products_protected':True,
    'next_executable_tasks':['Integrate fresh136 three actual completed delegated physical visual cases after full family-specific QI, scope and lifecycle checks.',
        'Observe actual977 first F3 full836 XMF; bind actual0 manifest and register unchanged116/023 full836 renderer.',
        'Close each actual978/981/983 conversion completed0 report and immediately admit original XMF/bed/render downstream.',
        'Integrate fresh137 next <=3 actual render completed0 delegated visuals; adopt only justified actual native-ready fresh166 disabled sources.']})
cp.update(checkpoint=134,at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    predecessor=str(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_133.json'),
    predecessor_sha256=ref(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_133.json')['sha256'],
    home_free_gib=free,previous_goal_turn_classification='Progress: one F6 actual full241 angular/state/QI visual integrated to205; original135 live routing evidence failure preserved and strictly rebound to frozen snapshot. Actual first F3 full836 typed974 completed0 and native948 all9 terminal0; F5 full801 bed971 completed0. Registered original downstream977/984 and typed981/983 successor batches, preserving actual982 strict prelaunch stale tool digest rejection.')
raw=(D/'runtime/resource-ledger.json').read_bytes();ledger=json.loads(raw)
cp.update(ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),active_reservations=ledger['reservations'],
    attempt_counts={k:sum(z['kind']==k for z in ledger['attempts']) for k in ['qualification','production','cpu']},
    gpu_hours_charged=sum(z.get('gpu_seconds',0) for z in ledger['charges'])/3600,
    cpu_core_hours_charged=sum(z.get('cpu_core_seconds',0) for z in ledger['charges'])/3600)
cp['actual_progress']['current985_verified_handles_storage_and_downstream']=ref(report)
cp['actual_progress']['first_F3_full836_typed974_actual_completed0']=ref(root(977)/'actual974-full836-independent-metadata-review.json')
cp['actual_progress']['F5_M095T080_full801_bed971_actual_completed0']=ref(root(984)/'actual971-all801-bed-and968-XMF-independent-review.json')
cp['source_agents'].update(production_recovery='fresh124 byte-exact36files adopted, validators actualPASS, seven-case typed controller981 live; fresh125 bounded next typed-to-XMF-render handoff active',
    f5_bed_recovery='fresh165 adopted30files; actual982 strict no-science prelaunch tool digest failure preserved; actual974 tool receipt-correlated successor983 live; fresh166 remaining native-ready disabled requests active',
    f6_endpoint_initial_qa='fresh135 accepted205 after primary evidence closure; fresh136 three completed visual reviews ready pending independent integration, fresh137 next<=3 active')
cp['next_executable_tasks']=load(report)['next_executable_tasks']
checkpoint=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_134.json';assert not checkpoint.exists();put(checkpoint,cp)
(O/'checkpoint-source.py').write_bytes(Path(__file__).read_bytes())
paths += [str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str(checkpoint.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True)
subprocess.run(['git','commit','-q','-m','ds02: checkpoint205 accepted cases and actual downstream completions after safe failed-native cleanup','--',*paths],cwd=R,check=True)
print({'checkpoint':134,'accepted':205,'Home_free_GiB':free,'gpu_hours':cp['gpu_hours_charged'],
    'cpu_core_hours':cp['cpu_core_hours_charged'],'attempt_counts':cp['attempt_counts'],
    'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
