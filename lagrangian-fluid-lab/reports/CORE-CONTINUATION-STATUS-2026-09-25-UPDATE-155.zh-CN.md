# Core 计划续推状态 UPDATE-155

## F8 RunPARTs parser v2 与 matrix adapter v4

UPDATE-154 的最终 Terra High 复核发现：原 parser v1 会拒绝 append/restart 段，且对非 timestep 列只检查非空；其 `REVISE` 不影响既有 fail-closed T1/credit，但不适合作为当前 source diagnostic implementation。未原地扩展旧 v1/v3，新增 `f8_r008_runparts_timestep_diagnostic_v2.py` 与 `f8_r008_t1_metric_matrix_adapter_v4.py`。

v2 明确是**所选的 R008 diagnostic input policy**，仅接受单段、Part 0、time 0 的输入形状，并 fail-closed 拒绝 restart/append。该输入策略不证明实际 solver invocation 使用了它。全部 26 列逐项做整数／无符号有限十进制类型与范围检查；不核验计数、内存等跨列运行语义，并显式报告 `cross_field_native_semantics_verified=false`。数值改名为最大已记录 PART `DtMax`，不推断有效 per-step 最大值、正常退出或到达冻结终点。

matrix v4 通过共享冻结矩阵 core 重算诊断源，但 execution attempt identity、runtime configuration、正常完成与 end-time 均保持 false；timestep comparison、aggregate gates、readiness、T1 不能通过，资格信用固定为零。Restart/append 的拒绝是 parser 输入边界，不构成 restart 未发生的执行证明。

## 复核与 readiness

Terra High/gpt-5.6-terra/high 对上一版本初轮给出 `REVISE`（restart append 边界及全列数值检查/表述问题）。修复后复核进一步要求不要把 diagnostic policy 说成冻结执行事实、拒绝 signed zero、区分字段类型/范围检查与跨列语义；最终窄范围 follow-up 为 `PASS`，无剩余 P3。请求模型/effort 没有密码学 attestation；reviewer 未运行测试，父代理验证单独记录。

新增 parent-authored source-bound [matrix implementation review v3](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/metric-matrix-review-v3/receipt.json)，绑定 parser v1/v2、matrix core/v4、测试与 DualSPHysics writer 源码。其 PASS 仅为静态实现审查；review receipt 明确不验证 solver invocation、执行身份、完整完成、native integrity 或 T1。

新增不可变 [readiness audit v6](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-execution-readiness-audit-v6/receipt.json)：保留 v5 原始收据并把旧 matrix-review 过期项更正为当前 matrix-v4 review PASS；其余三个 blocker 保留：可信 worker/source/runtime identity、真实且 provenance-verified 的 15-case 结果、native integrity 与 solver timestep adjudication。readiness/T1/执行 authority 仍 false、credit 0。针对 v6 的额外只读一致性意见为 PASS，但 reviewer 明确表示这不构成独立 Terra High review；它不作为独立认证收录。

parser v1/v2、matrix v2/v4、metric v1 与 review-v3/readiness-v6 联合回归 **153 passed**；相关模块 `py_compile` 与 `git diff --check` 通过。全部输入为合成 CSV/结果或既有静态合同；未读取生产 RunPARTs/bundle/frame，也未运行 GenCase、native decoder、solver、worker、GPU、queue，未改变 registry/ledger/分母。

只读 `core_campaign.py status` 仍为 `can_finalize=false`、`issues=[]`、evidence 与 causal-lineage 检查通过；T1 家族 F3/F4 为 2/3、macro T2 0/2、formal training 0/9，T1/material 目标缺 432/288。未写 completion snapshot。Core 仍未完成。
