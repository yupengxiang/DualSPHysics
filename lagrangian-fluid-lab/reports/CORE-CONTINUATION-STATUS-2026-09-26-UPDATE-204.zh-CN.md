# UPDATE-204：F8 R008 native-integrity semantics v5 只读复核

时间：2026-09-26（Asia/Shanghai）

## 设计复核

对 [proposal v5](F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V5-2026-09-26.zh-CN.md) 完成一轮只读源码/合同技术审阅，结论 **PASS（技术内容）**，无 P0–P2。审阅未能 attestate 模型身份，因此不记录为 GPT-6 Luna Max 或 Terra High 的正式签核；v5 首页所列模型复核仍待具备可验证身份的审阅。v5 内容本身继续限定为静态设计，不因此取得实现、执行或资格信用。

审阅确认：

- v5 对冻结 registry v1 的 open-gate allowed outcomes 逐项一致；15×8 固定矩阵保持不变，全零排除不能判 `defined_pass`。
- DualSPHysics v5.4 CPU loop 先执行 timestep、再按 cadence/minimum-fluid 保存；minimum-fluid、`TERMINATE` 与 `NstepsBreak` 均可能改变正常 horizon 结束语义；`FinishRun()` 不自动补最终 `SaveData()`。v5 没有另造 `T_end` 容差。
- `SaveData()` 的 PartOut 写入条件、随后清空 `PartsOut`、零事件不写 PartOut item，以及当前 parser 对 CPU 单-piece 文件/root 的边界描述一致；不声称覆盖 GPU/multi-piece。
- 冻结 scope receipt 与 Definition/control pack 的 SHA-256 和 registry pins 一致；未发现 scope、阈值、分母、权限或资格信用回归。

审阅留下 **P3**：未来 runtime trace 的具体可采集格式尚未审查。v5 已将其列为实现前置设计项；在 trace 来源、字段、完整性与执行身份认证方式冻结前，不得用其给 native-integrity gate 判定。v5 无需因此撤回，本轮未运行测试或任何 workload。

## 全局状态快照

只读运行 `scripts/core_campaign.py status` 得到 `can_finalize=false`、`issues=[]`；已合格 T1 家族为 F3/F4 两个，宏观 T2 为 0/2、正式训练为 0/9；固定目标仍缺 432 个 T1 与 288 个材料 case-run，observed T1/material case-run 均为 0。此刷新只读，不写 completion snapshot 或 campaign receipt。

本轮没有读取生产 bundle/HDF5/frame，没有运行 GenCase/native decoder/solver/worker/GPU/queue；没有改变冻结 scope、registry、ledger、分母或资格信用。详见 [PLAN UPDATE-204](../../PLAN.md)。
