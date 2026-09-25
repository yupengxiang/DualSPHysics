# Core 计划续推状态 UPDATE-153

## F8 R008 v2 timestep claim fail-closed

Terra High 先对 v2 风险收敛补丁给出窄范围 `REVISE`：尽管 `time_step_comparison.passed` 和总 gates 已恒为 false，输出仍包含 `caller_claimed_relation_passed=true` 的正向 caller claim 字段，容易被下游误读。

已将该布尔值改为无通过/失败语义的枚举码 `caller_claimed_relation_code`（`unverified_refinement_and_phase_relation_claimed/not_claimed`）；最大步长字段改名为 `*_claimed_solver_max_dt_s`。v2 timestep `passed` 仍固定 false，依赖它的 `all_metric_and_comparison_gates_passed` 也必定 false，并显式输出 attempt identity / normal completion 未验证。原阳性输入测试现在验证“caller claim code 可显示，但 timestep 和总 gates 均不通过”。

同一 Terra High reviewer 的窄范围 follow-up 为 `PASS`，确认唯一 REVISE 已关闭，且任意 caller 数值都不能使 timestep adjudication 或 all-gates 变为 true。Requested model/effort 为 `gpt-5.6-terra/high`；reviewer 说明环境没有可独立验证的模型身份签名，因此这里只记录指定模型的窄范围复核，不伪称密码学 attestation，也不据此刷新完整 implementation-review receipt。

matrix v2 + 旧 v1 metric-adapter 联合回归 **67 passed**，`py_compile` 与 `git diff --check` 通过。历史 matrix-review-v2/readiness-v5 收据保持不变且不计为当前 PASS。此改动是阻断旧 v2 caller claim 产生正向判定的安全收敛，不是 RunPARTs CSV 解析或执行来源验证：v2 仍不验证 CSV 内容、attempt identity、算法配置或正常完整终止，因此不能用于 T1/readiness/资格判定。下一步仍需独立版本的 RunPARTs 解析/同源重算和完整执行回执合同。
