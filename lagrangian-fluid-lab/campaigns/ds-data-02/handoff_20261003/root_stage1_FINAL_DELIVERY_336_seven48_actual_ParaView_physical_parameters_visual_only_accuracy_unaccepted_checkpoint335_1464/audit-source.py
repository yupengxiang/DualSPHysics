from pathlib import Path
import json, hashlib, datetime, os, subprocess
R = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
H = R / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
root = lambda n: next(H.glob(f'root*_{n:03d}'))
def load(p):
    assert Path(p).suffix == '.json'
    return json.loads(Path(p).read_text())
def sha(p):
    assert Path(p).suffix in {'.json', '.py', '.md'}
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
ref = lambda p: {'path': str(p), 'sha256': sha(p)}
def put(p, doc):
    with Path(p).open('x') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2); f.write('\n')
auditfile = root(1463) / 'STAGE1-FINAL-REQUIREMENT-AUDIT.json'
audit = load(auditfile); assert audit['stage1_goal_achieved'] and all(r['result'].startswith('pass') for r in audit['requirements'])
paramfile = Path(audit['actual_physical_parameters']['path']); assert sha(paramfile) == audit['actual_physical_parameters']['sha256']
params = load(paramfile); pm = {(r['family_id'], r['physical_case_id']): (i, r) for i, r in enumerate(params['rows'])}
lossref = audit['evidence']['full_lifecycle']; assert sha(lossref['path']) == lossref['sha256']
loss = load(lossref['path']); lm = {(r['family_id'], r['physical_case_id']): r for r in loss['rows']}
oldfile = root(1451) / 'DS-DATA-02-ACTUAL-USER-DELIVERY-INDEX.json'; idx = load(oldfile)
assert len(idx['cases']) == 336 and all(idx['families'][f]['accepted_actual_primary_cases'] == 48 for f in idx['families'])
O = H / 'root_stage1_FINAL_DELIVERY_336_seven48_actual_ParaView_physical_parameters_visual_only_accuracy_unaccepted_checkpoint335_1464'
O.mkdir(exist_ok=False); now = datetime.datetime.now(datetime.timezone.utc).isoformat()
idx.update(schema='ds02.main.actual-user-delivery-index.stage1-final.v2', at_utc=now,
    predecessor_delivery_index=ref(oldfile), delivery_complete=True, stage1_goal_achieved=True,
    goal_completion_audit_status='complete: actual336 full primary products, known numeric physical differences, real3D, full times, UID/state, official rigid histories, personal visual records and explicit membership verified; numerical accuracy remains unaccepted',
    final_requirement_audit=ref(auditfile), actual_physical_parameters=ref(paramfile),
    full_lifecycle_omission_evidence=lossref, stage2_remaining=audit['stage2_remaining'])
for r in idx['cases']:
    key = (r['family_id'], r['physical_case_id']); i, pr = pm[key]; lc = lm[key]
    r['actual_known_physical_parameters'] = pr['known_numeric_physical_parameters']
    r['physical_parameter_provenance'] = {**ref(paramfile), 'row_pointer': f'/rows/{i}', 'component_proof': pr['component_proof']}
    r['fluid_omission_disclosure'] = {k: lc[k] for k in ['initial_fluid_particles', 'maximum_missing_fluid_at_any_frame', 'maximum_missing_fraction_initial_fluid', 'first_missing_frame', 'missing_fluid_locations_states_causes']}
    r['scope_and_runtime_limits'] = 'Exact original initial-QA, geometry reuse, native/typed runtime, missing field, bed/rigid/mass and publication limitations remain at primary_delivery.product + row_pointer and physical_parameter_provenance; no absent field is backfilled.'
for f, r in idx['families'].items():
    r['known_physical_parameter_sample_range'] = params['families'][f]['actually_run_visual_usable_sample_range']
    r['parameter_domain_qualification'] = 'Visual sample coverage only; numerical qualification is unaccepted.'
indexfile = O / 'DS-DATA-02-STAGE1-FINAL-DELIVERY-INDEX.json'; put(indexfile, idx)
table = []
for f, family in idx['families'].items():
    fr = sorted({r['primary_delivery']['frames'] for r in idx['cases'] if r['family_id'] == f})
    table.append(f"| {f} | 48 | {' / '.join(map(str, fr))} | 8 ⊂ 24 ⊂ 48 |")
README = '''# DS-DATA-02 首阶段交付：336 个实际案例

七族各48个独立物理案例，完整生成、求解、状态保存、ParaView动态查看和个人视觉验收流程已打通。每族明确的前8例属于实际前24例，前24例属于最终48例；分辨率对照、复跑、时间切片和派生视图没有重复计数。

**视觉检查通过、数值精度未验收。Q-N/Q-E=0。** 所列范围是已经完整运行并视觉接受的样本覆盖，不是经过数值误差研究认证的参数域。

在本服务器使用 `DS-DATA-02-STAGE1-FINAL-DELIVERY-INDEX.json`：按 `family_id` / `physical_case_id` 选择案例，在 ParaView 中打开 `primary_delivery.open_with_ParaView_XMF.path`，播放完整时间序列。`contacts` 提供时序预览，`navigation_keys` 提供关键事件图片。`actual_known_physical_parameters` 和 `physical_parameter_provenance` 给出实际输入数值及逐字段/驱动变换来源；完整几何、初始化、求解参数、床面和刚体状态记录保留在 `primary_delivery.product.path` 的 `row_pointer` 行。

| 家族 | 独立案例 | 实际完整保存帧数 | 批次关系 |
| --- | ---: | --- | --- |
''' + '\n'.join(table) + '''

主进程独立核对了实际输入的数值物理差异：每族1128个两两比较均存在共享的已知物理字段差异。未知值、字段数量、ID、路径、哈希、数值设置、时域或视图没有作为区别。所有336例的实际XML动态入口、XYZ/三分量速度、身份与状态字段、完整时间和关联H5文件可用性已核对；完整动画生产者报告均记录非有限活动状态为0。视觉记录90例来自历史主进程、246例来自子代理。F6另有48份完整241帧官方刚体历史，基线的历史字段限制仍保留。

已知限制保留：F2、F4、F6 的部分案例存在少量流体粒子缺失，最大分别为118、6、7，最大占初始流体比例约0.480143%、0.010157%、0.002136%；具体缺失原因、位置、状态未知，不能补造，也不称为零丢失。四份原始F3 native059记录的结束状态/返回码/运行后输入哈希缺失，完成恢复审计单列，原记录未改写；F3旧复制的名义驱动描述与实际驱动来源分列。F5 A080/A120的时间倍率缺失、F6基线yaw字段缺失及旧UID/初态QA/质量/发布等限制保留在原行。部分旧视觉记录的末时刻声明有舍入或复制差异，实际时间以案例XMF manifest为准。

第二阶段仍需空间收敛、积分步及保存频率误差预算、长期逐粒子轨迹一致性、精确输运/事件标签、可信数值参数范围、无泄漏划分与无模型评测、外部实验验证。首阶段完成不等于精度或物理真值认证。

最终逐项验收见 `STAGE1-FINAL-REQUIREMENT-AUDIT.json`；物理参数及视觉样本范围见 `all336-final-known-physical-parameters-and-visual-sample-ranges.json`，本目录JSON中的 `final_requirement_audit` / `actual_physical_parameters` 提供其绝对路径与哈希。恢复入口为 `ROOT_LIVE_RESUMPTION_CHECKPOINT_335.json`。累计资源沿用原账本，无新增求解任务。
'''
(O / 'README.md').write_text(README)
prev = H / 'ROOT_LIVE_RESUMPTION_CHECKPOINT_334.json'; cp = load(prev)
assert sha(audit['evidence']['ledger']['path']) == cp['ledger_sha256_at_checkpoint']
assert load(audit['evidence']['ledger']['path'])['reservations'] == []
cp.update(checkpoint=335, at_utc=now, predecessor=str(prev), predecessor_sha256=sha(prev),
    authorized_work_state='Complete: stage1 delivered seven families with48 distinct actual physical cases each, total336; exact8-subset24-subset48, full actual3D dynamic products, state/UID/geometry/provenance, official F6 rigid histories and personal visual records verified. Numerical accuracy and external validation remain unaccepted; stage2 gaps are separate.',
    previous_goal_turn_classification='achieved: final native-pinned per-field/actual-forcing physical distinctions, full336 UID/state and scientific3D/fulltime/finite metadata screening, explicit eight-requirement audit and complete final delivery saved',
    goal_completion_audit_status='complete: stage1 actual336 independent visual cases; Q-N/Q-E remain0',
    stage1_goal_achieved=True, next_executable_tasks=[], source_agents={
        'f5_bed_recovery': 'completed fresh231 requirements snapshot +232/233 numeric provenance +234 exact F1 per-field pin proof',
        'production_recovery': 'completed fresh194 role/membership audit; main used corrected shared-known-field semantics and fresh195 actual F4/F5 native-pinned proof',
        'f6_endpoint_initial_qa': 'completed fresh208/209/210/211 actual F3 producer forcing and original native059 role disclosure'},
    stage2_remaining=audit['stage2_remaining'])
cp['actual_progress']['stage1_final_explicit_requirement_audit'] = ref(auditfile)
cp['actual_progress']['stage1_final_actual336_known_physical_parameters'] = ref(paramfile)
cp['actual_progress']['stage1_final_user_delivery_index'] = ref(indexfile)
cp['actual_progress']['stage1_final_user_delivery_README'] = ref(O / 'README.md')
stat = os.statvfs('/home/jade'); cp['home_free_gib'] = stat.f_bavail * stat.f_frsize / 2**30; assert cp['home_free_gib'] >= 500
checkpointfile = H / 'ROOT_LIVE_RESUMPTION_CHECKPOINT_335.json'; put(checkpointfile, cp)
(O / 'audit-source.py').write_bytes(Path(__file__).read_bytes())
assert load(indexfile)['delivery_complete'] and load(checkpointfile)['stage1_goal_achieved']
assert len(load(indexfile)['cases']) == 336 and not load(checkpointfile)['next_executable_tasks']
rel = [str(p.relative_to(R)) for p in O.iterdir()] + [str(checkpointfile.relative_to(R))]
subprocess.run(['git', 'add', '--', *rel], cwd=R, check=True)
subprocess.run(['git', 'commit', '-q', '-m', 'DS02: deliver final336 stage1 cases and checkpoint335 preserving numerical accuracy unaccepted', '--', *rel], cwd=R, check=True)
print(json.dumps({'stage1_goal_achieved': True, 'final_delivery': str(indexfile), 'README': str(O / 'README.md'),
    'checkpoint': str(checkpointfile), 'home_free_GiB': cp['home_free_gib'],
    'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip()}))
