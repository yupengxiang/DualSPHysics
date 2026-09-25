# Core 计划续推状态 UPDATE-148

## 刷新 F8 R008 execution-readiness 静态审计，保持零资格信用

UPDATE-136 中“缺少经审查的逐案例 verifier”已被后续工作取代：当前 B/C/D per-case implementation-review receipt 与 native-fluid-table metric-bundle implementation-review receipt 均能通过源绑定复核。新增不可覆盖的 R008 execution-readiness audit v5，明确将该旧缺口改记为可信 worker/执行来源及 runtime identity 尚缺，而不是把静态 verifier 误报为执行信任。

15-case metric-matrix 的历史 implementation-review receipt 仍不计为当前 PASS：当前 adapter 实现文件与归档绑定一致，但 `tests/test_f8_r008_t1_metric_matrix_adapter_v2.py` 已发生绑定漂移，因此需要刷新独立实现审查。v5 保留四项未决阻塞：matrix review 绑定过期、可信执行来源/runtime identity 缺失、无完整来源验证的真实 15-case T1 结果，以及 native-integrity 与 solver timestep adjudication 未完成。

v5 收据路径：`campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-execution-readiness-audit-v5/receipt.json`。收据的 readiness、full T1、数值 T1、solver/worker/GPU/queue 权限均为 false，资格信用为 0；未改 registry、ledger 或分母，未启动 worker、GenCase/native decoder、solver、GPU 或 queue。新审计回归 **4 passed**，锁定环境下 `py_compile` 与 `git diff --check` 通过。此项只校正 readiness 静态状态，不构成执行准入或 Core 完成。

同轮只读 `core_campaign.py status` 仍为 `can_finalize=false`：T1 家族 2/3、宏观 T2 0/2、正式训练 0/9；目标 T1 case-run 缺 432（其中 144 尚未登记），材料 case-run 缺 288，异机复现未通过。`issues=[]` 不表示 Core 完成。
