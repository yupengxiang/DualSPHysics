# Core 计划续推状态 UPDATE-154

## F8 R008 RunPARTs diagnostic parser 与 matrix adapter v3

针对 UPDATE-151/153 暴露的 caller-supplied `max_solver_dt_s` 风险，新增只读 diagnostic 路径：`f8_r008_runparts_timestep_diagnostic_v1.py` 从固定 basename `RunPARTs.csv` 安全打开文件，以有界字节读取重新解析内容，并按 `src/source/JSph.cpp` 的真实 26 列表头和 `SaveRunPartsCsvFinal()` 完整 footer 校验结构；计算值严格命名为“最大已记录 PART `DtMax`”，不解释为完整执行期的实际最大 solver step。路径逐级 no-follow，文件要求 single-link regular file，并在读取前后复核稳定身份。

首行现在支持 DualSPHysics restart 的合法 `PartBeginFirst` / `TimeStepIni` 非零来源，同时要求初始记录 `Steps=0`、`DtMin=DtMax=0`，后续 PART 连续且时间严格递增。输入固定限制为 8 MiB、20,000 个数据行；冻结 Definition/control pack 最大 full-axis 为 1,497 行，因此该行数限有超过 13 倍余量。此为 diagnostic 的有界容量策略，不是任意长 RunPARTs 文件的通用承诺，扩容需新版本复核。

`f8_r008_t1_metric_matrix_adapter_v3.py` 通过 shared metric core 消费 parser 实时重算值，不读取旧 audit JSON。输出明确标为 unverified diagnostic；attempt/source identity、runtime configuration、正常完成、到达冻结终点仍均为 false，time-step comparison 与 aggregate gates 恒 false，readiness/T1=false、qualification credit=0。早停、append、Symplectic 下 PART 记录语义等问题仍不能从 CSV 单独排除。v2 保留为历史兼容 fail-closed 入口；旧 review-v2/readiness-v5 收据未被覆盖或刷新。

## 静态复核与验证

请求 Terra High（`gpt-5.6-terra/high`）对 parser、matrix v3 和测试做只读审查。初轮结论 `REVISE`，无 P0/P1，指出两项 P2：拒绝合法 restart 首行，以及 256 MiB 全量解析无数据行上限。修正 restart 语义、把输入上限降至 8 MiB 并增加 20,000 行上限后，Terra High follow-up 对两项给出 `PASS`、未发现新的 P0/P1/P2；其 P3 容量策略文档建议已在模块常量旁注明。CRLF 负测的独立窄范围 follow-up 也为 `PASS`。审查环境没有可密码学验证的模型身份/effort attestation，因此仅记录所请求的模型配置，不伪称独立模型身份证明，也不将窄范围 follow-up 冒充为新的完整归档 review receipt。

联合回归：RunPARTs parser + matrix v2/v3 共用测试 + 旧 v1 metric adapter **100 passed**；相关 Python 文件 `py_compile` 通过，`git diff --check` 通过。测试输入均为 synthetic CSV/结果与临时文件；没有读取 F8 production RunPARTs/bundle/frame，也没有运行 GenCase、native decoder、solver、worker、GPU 或 queue。

因此本次仅补齐可复算的 RunPARTs 诊断来源，不证明执行身份、配置、正常完整终止或数值资格。可信执行来源合同、真实 15-case 结果验证、native-integrity 与 timestep adjudication 仍未闭合；Core 完成状态不变。
