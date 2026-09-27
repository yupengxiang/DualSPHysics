# Core continuation status — 2026-09-27 — UPDATE-232

## F8 R008 native-integrity semantics review

Terra High（`gpt-5.6-terra` / high）按用户指定的 subagent 模型，对 v5 做只读设计复核，结论 **REVISE**；未发现直接 false-pass。Reviewer identity 未 attested。该复核不是 v5 文档原计划标注的 GPT-6 Luna Max 复核；按用户后续要求统一使用 Terra High，本轮不调用其他模型替代。

复核识别的主要缺口：

1. “same authenticated attempt” 缺少防止跨重跑拼接的具体目录、配置、binary、进程 generation 和输出文件身份闭环。
2. `PartsOut->Clear()` 不等价于持久写入成功；CSV 先于 BI4 写入，后者失败可能留下孤立 CSV，故需各 writer 成功、flush/close、错误传播和退出后输出闭包复核。
3. PART 预期序列须按 `TimePartNext` 的源码递归迁移推导；单步跨越多个名义 cadence 时，不应虚构多个输出 PART。
4. 全可信零排除应确定映射为 `open`；不可信、缺失或不完整且无可信正事件映射为 `missing`；可信正排除事件可映射 `defined_fail`。
5. GPU `SaveFluidOut`、动态 `TERMINATE` 与 PartOut identity/timestamp 需明确源码锚及匹配条件。

新增 [native-integrity semantics proposal v6](F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V6-2026-09-27.zh-CN.md)，仅文档性修订：

- 为 attempt nonce、启动 generation、fresh output-root inode、每个 output file identity/raw bytes/hash 与 no-follow post-exit re-open 定义不可拼接闭包。
- 固定排除 gate 状态映射；可信完整全零仍为 `open`，未闭合且无可信正事件为 `missing`，可信正事件为 `defined_fail`。
- 从 CPU 初始化 `SaveData()` 起，按实际 `TimeStep`、`TimePartNext`、`OutputTime->GetNextTime(TimeStep)` 递归迁移定义 PART 序列。
- 明确 `Cpart`、PartOut binary64 `TimeStep` 与目标 RunPARTs 行/可信保存事件对应，并拒绝跨 block 重复 payload。
- 规定 writer 成功、错误/close 状态、清空与退出后文件集合稳定摘要的共同闭环；明确这不是额外的断电耐久性承诺。
- 在 checkout `c814847dc32926260fb9c7d53340d3b61a5ec6f6` 上固定 CPU/GPU/公共保存/PartOut/motive 源文件 SHA-256。哈希只绑定仓库快照，不声称上游 tag 或签名 attestation。

v6 等待 Terra High follow-up 只读复核。没有修改代码、运行测试、打开生产 bundle/frame、执行 GenCase/native decoder/solver/worker/GPU/queue 或改变资格。registry、gate、15×8 分母、threshold、T1/readiness/credit 及 execution authority 均不变。下一步：完成 v6 Terra High follow-up；若无阻断，再选择计划中另一个无需 runtime 权限的静态待办。
