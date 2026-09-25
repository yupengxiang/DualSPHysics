# UPDATE-159：F8 R008 冻结时间步细化配对诊断

时间：2026-09-25（Asia/Shanghai）

## 本轮实现

新增 `scripts/f8_r008_timestep_comparison_diagnostic_v1.py`，按 matrix v2 冻结合同绑定 baseline `space-q0p5-dp0p0075` 与 refined `time-q0p5-dp0p0075-cfl0p1`，相位差门限固定为 `0.05 rad`。接口要求两例原始 RunPARTs 字节及调用方 completion/积分器声明，并对两侧重新调用 UPDATE-158 的逐案例诊断；拒绝传入序列化诊断代替原始输入。

只有两侧未认证 completion 条件均为真、RunPARTs 终点声明关系都恰为 `True`、且两例都声称 standard CPU single Verlet 并将 `DtMax` 标为应用步候选时，才计算 refined 记录 `DtMax < baseline`。endpoint `None` 保持 unresolved。相位差是调用方提供的未认证观测，仅与冻结 `0.05 rad` 门限比较。

Terra High 初轮只读复核指出上游 completion 诊断四个安全字段可能在保持 schema 不变时漂移为正值，且指出超大整数异常和精确边界缺测。实现现强制上游 `evidence_authenticated`、`solver_timestep_adjudicated`、`normal_completion_verified`、`trusted_acceptance_verdict_issued` 全为 `False`，并固定 completion schema/state；超大整数在转换前按范围拒绝；新增 `0.05` 精确边界及字段漂移回归。Terra High follow-up 为 `PASS`，无 P0–P2。

结果始终标明证据/执行身份、runtime 配置、积分器、native integrity、正常结束、solver timestep、T1 与 readiness 均未验证，`qualification_credit=0`；不含 `passed`，不发布 receipt。未读取生产 RunPARTs/bundle/HDF5/frame，未运行 GenCase/native decoder/solver/worker/GPU/queue，也未修改 registry、ledger 或分母。

## 验证

- 新配对诊断专属测试：**25 passed**。
- `py_compile` 与 `git diff --check` 通过。
- Terra High/gpt-5.6-terra/high follow-up 独立静态审查 `PASS`；reviewer 未运行测试，无密码学模型身份 attestation。

SHA-256：

- `f8_r008_timestep_comparison_diagnostic_v1.py`：`d29c2948ed1b761be2880396fe31992a84c02bd248baeb3cc2cbbd9ed069a12b`
- `test_f8_r008_timestep_comparison_diagnostic_v1.py`：`f35d3a48886fad7b2dcdd1b3bc2ecb8b4a770ef8502a5440122b992e08ae48fe`

## 计划状态

该配对层只增加未认证的时间步/相位观察，不改变 F8 R008 readiness、执行授权或资格信用。可信执行来源与 runtime identity、真实来源验证的 15-case 结果、native integrity/时间步 adjudication、Core 的 T1/T2、训练、全量评测和异机复现仍未完成。
