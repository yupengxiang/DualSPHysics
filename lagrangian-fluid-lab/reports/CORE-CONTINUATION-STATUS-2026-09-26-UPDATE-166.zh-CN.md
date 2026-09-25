# UPDATE-166：Core formal source-closure v6 只读复核

时间：2026-09-26（Asia/Shanghai）

## 复核结论

按只读模式重新验证已封存的 `formal-release-candidate-v6` source-closure、audit 与 root-admission receipt。验证返回非零是预期的 fail-closed 结果：旧 closure 不再匹配当前 planner 所需源码；同时 `formal_jobs_closed=true`、`formal_release_closed=true`、`formal_training_closed=true`、`launch_remains_blocked=true`、`root_admission_not_granted=true`。这不是 v6 凭据损坏，也不是训练失败，而是源码演进后旧快照不能继续作为当前源码闭合证明。

当前 planner 要求 9 个源码文件，其中新增的 `scripts/core_strict_json.py` 不在 v6 冻结清单中；其余绑定文件也有源码摘要变化。当前重算 closure SHA-256 为 `857ca65f44562a0ed4614b6635547274da2a9cc7d14a518599e614737b48ceec`。与历史快照不一致的文件为：

- `scripts/core_cfd_dataset.py`
- `scripts/core_contract.py`
- `scripts/core_dataset.py`
- `scripts/core_evaluation.py`
- `scripts/core_formal_planner.py`
- `scripts/core_learning.py`
- `scripts/core_models.py`
- `scripts/core_strict_json.py`（历史快照未包含）

## 尚存门槛与处理

即使重算出当前源码哈希，也不会自动变成 admitted source snapshot。v6 receipt 还记录 `THIRD_T1_FAMILY`、`VALIDATION_DENOMINATOR`、`MATERIAL_CASE_RUN_DENOMINATOR`、`RESOURCE_FRONTIER_UNPROVEN` 和 `STALE_SOURCE_CLOSURE` 等未通过门槛。Core 总状态仍为 T1 家族 2/3、宏观 T2 0/2、正式训练 0/9、T1 case-run 缺 432、材料 case-run 缺 288、异机独立复现未通过。

本轮没有改写 v6 closure/audit/receipt 或其摘要，没有创建新版本 admission 凭据，没有写 registry/ledger/job spec，也没有启动训练、solver、worker、GPU 或 queue。v6 `--verify` 是只读调用；正式训练继续保持 fail-closed。只有在上游 Core 分母、资源与资格门槛发生真实变化后，才应创建新的、独立命名的 closure 提案并重新审查；不得把这次 live re-hash 当作 root admission。
