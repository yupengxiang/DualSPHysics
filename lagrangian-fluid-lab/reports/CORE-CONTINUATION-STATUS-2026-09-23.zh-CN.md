# Core 计划续接进展快照（2026-09-23）

本快照接续 `PLAN.md` 与 2026-09-22 收口报告，区分代码/静态设计、实际运行证据和科学资格。它不授予新的 worker、GenCase、solver、GPU 或训练运行权限；具体运行仍受用户在本任务中的明确范围限制。

## 本次已完成

- 修正 `scripts/core_campaign.py` 的独立复现完成门：诊断性 canary 不再满足产品复现；必须有非诊断的完整产品回执，覆盖另一台主机、不同数据根、reader、预测和评分，且无未来真值输入，并通过 root review。
- 增加回归测试并刷新 `campaigns/core-v1/completion.json`。定向测试：`35 passed`。当前 `independent_reproduction=false`、`can_finalize=false`，符合现有证据。
- 修复已提交并推送：`c7b694c fix: require full-product independent reproduction`。
- 三项并行只读审计（CFD 家族、材料/模型/评测、调度/复现）已完成；没有由这些审计启动或重试作业。

## Core 证据状态

| 门槛 | 当前有效证据 | 尚缺 |
|---|---|---|
| T1 家族 | F3、F4 两个合格家族；F4 tallwall120 的独立生产收集回执列出 32 个完整案例。 | 至少再有一个不同家族完成资格和生产；F1/F2 现有失败路线已闭合，不能靠复跑或改名补数。 |
| 宏观 T2 | F3、F4 均有材料代码、诊断数据和 gap audit。 | 合格家族为 0/2。F3 最新矩阵审计仍有 unknown 最大值 `0.015625 > 0.01`、CDF 差异 `0.061035 > 0.02`，33 行正式 acceptance 为 0；F4 既有 6 个侧车均未通过当前 validator，且事件窗/unknown 门未过。 |
| 正式训练 | 三种模型、三种 seed 的训练合同和 checkpoint 机制已实现；存在短期 pilot。 | 正式 32k 训练为 `0/9`；pilot 不计正式训练。 |
| T1 模型评测 | rollout/evaluator 与固定失败分母合同已实现。 | 正式评测为 `0/432` case-runs。 |
| 材料模型评测 | 材料重建、恢复和接受门代码已实现。 | 正式评测为 `0/288` case-runs。 |
| 异机产品复现 | 有跨机数值/诊断材料。 | 尚无不同主机、不同数据根上的完整 reader→预测→评分产品复现；旧 diagnostic-only 回执不计入。 |

当前总门仍为 `can_finalize=false`。可复核入口：`campaigns/core-v1/completion.json`、`campaigns/core-v1/registry.json`。

## 当前运行与一次性预检边界

- 2026-09-23 10:13 UTC 的只读观察：F3 material row30 R003 仍运行，CPU-only，无 GPU/solver；checkpoint 为 `533/835`，worker CPU 约 `99.5%`，主机 1 分钟 load 约 `146.57`，高于 128 个可用逻辑 CPU。该观察是瞬时状态；作业尚无终态回执，不能记作 T2。
- F4 supportcap R002 的一次 CPU-native canary **预检**授权仍未消耗。其单次合同禁止在 F3 material worker 活跃或 load 高于可用 CPU 数时启动；receipt 在资源探测前就会占用一次机会，因此只有所有条件已通过时才能执行。通过预检也不授权 tracer/canary runtime、solver、GPU、queue 或 T2 扩展。
- F8 R002 的历史静态审查失败，明确缺少 `hswl`；其 R001/R002 均保持关闭、零资格信用，不重试。F8 R008 的 15 项 T1 矩阵与 32 例生产设计已通过静态审查，但资源准入仍因 full-process-tree RAM cap 未验证及当时 CPU 排程阻塞而处于 blocked；request-only/静态审查不构成运行授权。
- F4 qualification root 中 `registered_production_cases_completed: 0` 是资格时点记录；后续独立 collection receipt 绑定了 32 个生产案例。两份记录描述不同阶段，不应覆盖或合并成一条可变回执。

## 后续顺序

1. 只监测 F3 R003；终态后先审计 immutable receipt、输入哈希、完整 835 区间及材料接受门。单个 row 即使通过，也不等于整个 F3 T2 矩阵通过。
2. F3 worker 退出且 load、RAM、磁盘和输出命名空间均满足绑定合同后，才消耗那一次 F4 CPU-native 预检；若任何条件未满足，暂不启动，避免把一次性授权消耗在必然 blocked 的结果上。
3. 继续第三家族静态工作以 F8 R008 为候选；资格仍为零。不得重试 F8 R001/R002，也不得把 request-only 包当成 GenCase 或 solver 授权。
4. 完成第三 T1 家族、F3/F4（或替代家族）的两套宏观 T2 矩阵与逐例侧车后，再按固定分母推进正式训练、rollout、评测和真正的异机产品复现。

`PLAN.md` 作为交付目标和设计依据；其中的波次、worker 或批量规则不单独扩大用户在当前任务中授予的运行范围。
