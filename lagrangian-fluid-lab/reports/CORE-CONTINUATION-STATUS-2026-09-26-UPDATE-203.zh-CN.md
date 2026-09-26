# UPDATE-203：F8 R008 exclusion semantics proposal v4 复核与 v5 修订

时间：2026-09-26（Asia/Shanghai）

## 设计审查结果

GPT-6 Luna Max 对现有 [proposal v4](F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V4-2026-09-26.zh-CN.md) 做只读审查，结论 **REVISE**。审查确认冻结 scope receipt 与 registry pin 一致、逐 PART 原因计数/payload 对账的基本方向符合源码，且当前 bounded parser 的缺失/未知输入保持 `open/missing`；同时发现三项需澄清的设计缺口：

1. v4 允许全零事件判 `defined_pass`，但冻结 registry v1 对 `excluded_fluid_particles_zero` 仅允许 `defined_fail/open/missing`；必须另行版本化 registry 才能增加 pass。
2. v4 使用没有注册依据的 PART 末时刻容差。官方 CPU 循环会应用完整 timestep 后再触发输出；`TimeMax` 可被动态改写，`FinishRun()` 不保证最终补存。运行完成须由精确跨越 `T_end` 的 timestep、有效 horizon、最后 `SaveData()` 成功以及 flush 证据共同证明，否则维持 `open/missing`。
3. 提案提及 CPU/GPU，但当前 bounded PartOut parser 仅接受单 piece 的 `PartOut_<block>.obi4` 与 `Piece=0,Npiece=1`。GPU/multi-piece 不得由现有 parser 覆盖声称。

基于上述 findings，新增 additive [proposal v5](F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V5-2026-09-26.zh-CN.md)，等待 GPT-6 Luna Max 复核。v4、既有 v3/v4 历史回执均不改写。v5 直接列出 registry v1 各 gate 的 allowed outcomes；把全零 exclusion 限定为 `open/missing`；收紧 `T_end` 到实际 binary64 timestep crossing、无动态 horizon/early stop、最后 `SaveData()` 和 `PartsOut` flush 的完整轨迹；并明确 parser 目前最多支持 CPU 单 piece，GPU/multi-piece 保持 open/missing，直到新版本覆盖并复审。

## 验证与边界

源码核对位置：DualSPHysics v5.4 `JSphCpuSingle.cpp` 主循环（1187–1235）、`JSph.cpp` 排除计数与 SaveData/flush（3187–3224、3293–3318）、`JPartOutBi4Save.cpp` 零计数不写 event item（219–232）、冻结 registry（46–54）及 bounded parser（27–34、root piece 检查）。本轮没有修改实现代码、registry、scope、receipt、ledger 或资格分母；没有访问生产 bundle/HDF5/frame，也没有运行 GenCase/native decoder/solver/worker/GPU/queue。v5 尚待独立设计复核，不构成实现或执行授权；T1/readiness/资格信用不变。

本轮较早运行的四个 F8 R008 synthetic diagnostic suites 共 **78 passed**，只验证现有诊断代码，不验证 v5 文档或任何生产执行行为。
