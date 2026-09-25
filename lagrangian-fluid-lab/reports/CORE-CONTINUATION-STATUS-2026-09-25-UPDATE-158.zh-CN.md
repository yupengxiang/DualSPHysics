# UPDATE-158：F8 R008 单案例运行／时间步联合诊断

时间：2026-09-25（Asia/Shanghai）

## 本轮实现

新增 `scripts/f8_r008_runtime_timestep_adjudicator_v1.py`，将三类证据做只读、逐案例的联合诊断：

- RunPARTs 原始 CSV 经 v2 fresh-segment parser 重新解析并计算 `PartDtMax`；
- 当前 CPU timestep 静态源码审计及其源码/实现/测试 SHA 引用；
- caller-supplied runtime completion 字段的严格类型、范围、控制停止项和终点容差诊断。

明确区分两种积分器声明：Verlet 下，记录的 `PartDtMax` 仅在“未经验证的 runtime 确实选择标准 CPU single Verlet”这一条件成立时，才可被解释为该步所用 `dt` 的诊断候选；Symplectic 下它是 corrector 候选，不是该 PART 实际采用的 timestep。算法、backend、runtime 控制与 completion 字段都仍是未认证声明。RunPARTs footer 只说明 CSV 结构通过，不证明正常完成；最后记录时间晚于声明进程终止时间和容差时标记为不一致；若明显早于终止时间且没有输出 cadence/coverage 证据，则一致性为未充分判定，而不是通过。

结果始终输出 `effective_step_algorithm_verified=false`、`normal_completion_verified=false`、`solver_timestep_adjudicated=false`、`T1_numerical=false`、`readiness_pass=false`、`qualification_credit=0`；不包含 `passed` 字段，也不发布 JSON receipt。此模块未读取生产 RunPARTs、bundle、HDF5 或 solver frame，未运行 solver/worker/GPU/queue，未改 registry、ledger 或分母。

同时收紧既有源码审计 pack parser：拒绝 Python JSON 默认允许的 `NaN`、`Infinity`、`-Infinity` 常量，并加入回归测试。

## 验证

使用仓库既有 `neural_lagrangian_solver_torch212` Conda 环境运行新增与相邻模块联合回归：

- 新 adjudicator、源码语义、RunPARTs v2、matrix v4 与 readiness v6：**158 passed**；
- `py_compile` 与 `git diff --check` 通过。

系统默认 Python 的 NumPy/h5py ABI 不兼容，因此 matrix/readiness 初次收集未能开始；没有安装或更改依赖，改用仓库既有的兼容 Conda 环境后全套测试通过。

SHA-256：

- `f8_r008_runtime_timestep_adjudicator_v1.py`：`4f8c8dcacb4b97365238bc795aa6422b63e78367393ea3cc56604201a138b2ba`
- `test_f8_r008_runtime_timestep_adjudicator_v1.py`：`45c44e8261c8c8b9ee1ddc20ba4420fe8606c2df2f00e8da56e50dd6d27c173b`
- `f8_r008_timestep_source_semantics_v1.py`：`11502bd5322858993e9bd118d5a34e60ed9414361bda0431d3a18cb0f79c537e`
- `test_f8_r008_timestep_source_semantics_v1.py`：`4bcc2444bea29170b01eb0816cda08f530920b12b0d2f5eaac2996ad2fab876f`

GPT-6 Luna Max 初轮只读对抗审查为 `REVISE`，指出早于声明终点的 RunPARTs 记录在缺少 cadence/coverage 时不能标为 claims-consistent，以及 runtime dict 快照和 OS 读取错误包装两项低级健壮性问题。实现已按此修改并增加回归；follow-up 代码审查为 `PASS`，未发现 P0–P2。保留 P3 语义提示：容差是未认证 caller claim，故 `claims_consistent=true` 仅表示按该 claim 未发现矛盾，不是完成证据。该复审没有运行测试、没有密码学模型身份 attestation，也不代表真实 execution/T1 PASS。

## 计划状态

这只补上静态源码、RunPARTs 结构与 runtime claim 之间的 diagnostic 组合层，未解除 readiness v6 的任何真实执行阻塞。可信 supervisor/worker 与 runtime identity、15-case provenance-verified R008 结果、native integrity、实际时间步/正常结束裁决仍未完成；Core 的 T1/T2、训练、全量评测与异机复现目标仍未完成。资格信用保持零。
