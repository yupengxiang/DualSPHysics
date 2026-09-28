# F4 Tallwall120 宏观材料 T2 只读 readiness / authorization 审计

审计日期：2026-09-28
审计模式：只读、fail-closed
范围：`F4_resting_pool_laminar_tallwall120_x_v1`。本审计不覆盖正在运行的 F3 rollout、Nash 的 F1/F2 后备审计，也不重复实现已完成的 F4 reader CLI。

## 结论

当前不存在可以合法启动的 F4 Tallwall120 coarse material path。结论为 `blocked_fail_closed`：当前 T2 acceptance bridge 为 blocked，宏观 sidecar preflight 的 6 个已注册输入全部 blocked、0 个通过、0 个 formal acceptance receipt；所有现有 material candidate 都停在 proposal/root-review 或 preflight-only，当前没有 runtime authorization、fresh output namespace 或可用的当前 resource admission。

当前没有新增 material label，也没有 T2 credit：`T2_macro=false`、`T2_path=false`、`qualification_claim=none`、credit 为 0。

## 已核对事实

1. 当前 bridge 是 `scripts/f4_tallwall120_t2_acceptance_bridge_v4.py`，schema 为 `core.material.f4.tallwall120.t2_acceptance_bridge.v4`，verifier status 为 `blocked`。27 个 input bindings 只连接 acceptance/readiness 证据；namespace binding 和 launch authorization 均不存在。桥接约束显示没有打开 source/terminal HDF5、没有 solver/GPU/queue 启动，也没有 registry/ledger/matrix/queue mutation。

2. 当前 `f4_macro_t2_sidecar_preflight_v2.py` 的 6/6 validator invocation 全部 blocked，0/6 passed，formal receipt 数为 0。`material_matrix_ready=false`、`event_window_pass=false`、`f4_calibration_pass=false`、`unknown_mass_pass=false`；只有 sidecar provenance gate 为 true。这是 acceptance fail-closed 结果，不是 launch authorization。

3. Core material entry `core-f4-tallwall120-material-full434-s2-v1.json` 仍是 `proposal_only_root_review_required`、`qualification_only=true`、`material_reliability_status=uncalibrated`。它绑定的是 qualification cell-04 trajectory（SHA-256 `78631c…74cad`），不是已经由 reader smoke 遍历的 32-case production collection；217 个 interval 的 4.34 s material trace 仍要求新的 native source 才能扩展，且没有 full-canary extension。该 entry 只是候选计划，不是可启动 receipt。

4. 当前候选 `f4_supportcap_affine_query_bound_v3` 与 root-review receipt 都是 `proposal_only_root_review_required`，`authorized_one_cpu_only=false`。R002 文件即使显示 `authorized_one_cpu_native_canary_preflight_runtime_not_authorized` / `preflight_passed_runtime_not_authorized`，也只代表一次受限 preflight 合同，不代表 runtime material authorization；本审计没有消费它。

5. registry 已注册 F4 Tallwall120 的 32 个 CFD cases，但没有 F4 `material_qualification` entry，也没有任何 F4 case 的 `material_audit` entry。completion 当前为 `can_finalize=false`、`macro_t2_families=[]`、`observed_material_case_runs=0`、`missing_target_material_case_runs=288`。runtime queue 的 queued/running/reserved/launching 均为 0，且 `scientific_completion=not_inferred_from_queue`。旧 `RESOURCE-LEDGER.json` 的 conservative expiry 为 2026-09-16，不能当作当前授权。

6. 已完成的 F4 reader smoke 是可复用的数据路径证据：32/32 case 可打开、32/32 source SHA 校验通过、每 case 218 frames / 217 transitions、时间范围 0–4.340002980805959 s，known inputs 与 sampled state 均可读。但 reader 自身仍报告 `reader_formal_eligible=false`、diagnostic only、credit 0。因此它可以复用 manifest/source/time/state adapter，不能继承为 material labels、formal material receipts 或 T2 credit。

7. 已有 DEV_07 source-bound baseline24 diagnostic 确实绑定生产 source（SHA-256 `6ae8ca…f0976ae`），并完整读取 218/217 frame/transition，但结果为 negative：mass closure true，event window `right_censored_or_unresolved`，`unknown_fraction_max=1.0`，common reliable path coverage 为 0，unknown gate false，T1/T2/credit 均为 false/0。历史 cell-14 native004 trace 的 source SHA 为 `918468…7c096e`，只提交 101/1086 native frames，不能重标为 DEV_07，也不能作为 T2 证据。

## 最小缺口与下一步

最小合法下一步不是直接启动现有 proposal，而是：

1. 选择一个明确的 F4 production case，生成新的 source-bound material proposal，显式固定该 case 的 trajectory path 与 SHA；不能借用 cell-04/cell-14 或 reader smoke 的 manifest 代替 material binding。
2. 获取当前 root/scheduler/resource admission 与 fresh output namespace；不得复用过期 resource ledger，也不得消费当前 one-shot preflight authorization。
3. 获得授权后，才运行不改阈值的 material path，完成完整 event window 并产出 source-bound formal per-case receipt。当前 DEV_07 baseline24 只能作为 negative diagnostic，不能提升为 accepted coarse path。
4. 第一个 coarse path 闭环后，再由授权 producer 扩展至 32-case sidecar/matrix，并由正式 producer 写入 registry/completion/ledger/denominator/gate；本审计不执行这些写入。

本次未重新大规模读取 HDF5，未启动 solver、worker、native、GenCase、GPU 或 queue，未消费 one-shot authorization，未修改 PLAN.md、registry、completion、ledger、denominator 或 gate。

机器可核验明细见同名 JSON：`F4-TALLWALL120-T2-READINESS-AUDIT-2026-09-28.json`。
