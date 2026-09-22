# F3/F4 材料 T2 最小闭环审计（2026-09-20）

本报告记录一条不启动 solver、GPU 或 queue 的材料侧 CPU/JSON 闭环。它复用已经保留的 F3 source/window 审计、固定门槛 remediation preflight 和 F4 修复失败诊断，计算未来合法修复所需的最小整数缺口；它没有重写轨迹、补造 CFD 帧或把未知样本改标为可靠样本。

机器可读回执为 [`f3-f4-t2-minimal-repair-audit-20260920.json`](../campaigns/core-v1/material/evidence/f3-f4-t2-minimal-repair-audit-20260920.json)，SHA-256 为 `9a9799abd9e8f8f46b34496b61e60bf5cbab873336fb6d5c469748b72dcf4c20`。实现脚本 [`f3_f4_t2_minimal_repair_audit_v1.py`](../scripts/f3_f4_t2_minimal_repair_audit_v1.py) 的 SHA-256 为 `116888b89fc2a418a835a828dc5b7b5ae1f56155dad87eb4bd97f95ba635fc96`。

固定门槛保持不变：每个 source 的未知质量不超过 `0.01`，F3 CDF sup 差不超过 `0.02`，F4 必须拥有完整 `4.34 s` 事件窗。所有几何种子继续留在各 source 分母中；right-censor 仍是未知，zero credit 仍保持。

F3 保留的 row 29/31 各含两个 `2048` 的 source 分母。使当前未知门槛达到固定值至少需要恢复 26 条合法可靠路径：row 29 source 0 需 5 条，row 31 source 0 需 12 条，row 31 source 1 需 9 条；row 29 source 1 当前在整数预算内，但不能抵销其它 source 的失败。CDF 比较的最大差为 source 0 的 `0.06103515625` 和 source 1 的 `0.06005859375`，分别还差至少 85 和 83 个分母单位；这些是规划量，不等于可以回收的种子数。首要失败原因仍以 `wall_occluded` 为主，另有 low-ESS/no-support 记录。

F4 的 6 个保留 case 都有完整性有效的 checkpoint，但都在完整事件窗前结束，且未知门槛全部失败。对应未知种子数为 `434/512`、`459/512`、`459/512`、`473/512`、`489/512`、`512/512`；若只按未知整数门槛估算，至少需要恢复 `429`、`454`、`454`、`468`、`484`、`507` 条合法路径。前五个观察到约 `0.300003 s`，仍缺 `4.039997 s`；tallwall120 短 canary 观察到约 `0.400015 s`，仍缺 `3.939985 s`。有效 checkpoint 只证明可重启，不证明材料接受或事件窗完整。

本次执行约束的回执值为：`read_only=true`、`json_only=true`、`new_job_submitted=false`、`solver_started=false`、`gpu_started=false`、`terminal_h5_opened=false`、`registry_mutation=0`、`central_ledger_mutation=0`、`thresholds_changed=false`。因此 Core gate 没有改变：`T2_macro=false`、`T2_path=false`、`qualification_claim=none`、`qualification_credit=none`。后续若推进，必须取得新的合法 CFD/material evidence 来关闭未知、CDF 与完整事件窗缺口；本报告不构成资格授予。

验证：`tests/test_f3_f4_t2_cpu_source_window_audit_v1.py`、`tests/test_f3_f4_t2_minimal_repair_audit_v1.py`、`tests/test_f3_f4_t2_cpu_only_decision.py` 和 `tests/test_core_material_remediation_preflight.py` 共 `19 passed`。
