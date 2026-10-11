# 长期目标下发入口

本包包含可以下发的目标正文和详细执行方案。当前状态为待下发；编写文件没有创建活动目标、启动CFD或修改资源账本。

用户已选择：从正式下发时起14天，沿用DS-DATA-02累计上限。该窗口的起点不是文件生成时间，也不是最后一次“继续”的时间。NAS可以使用。

| 文件 | 用途 |
|---|---|
| GOAL_ZH.md | 可整体复制为长期目标，包含M1至M4、边界和停止条件 |
| PLAN_ZH.md | 母例、验收、资源、NAS、失败替代及接续的详细方案 |
| SHA256SUMS | 对本包文件做字节完整性检查；不代表科学验收 |

可以直接向当前聊天发送以下文字。发送即表示正式采纳本包并要求开始执行；现在阅读它不构成下发。

```text
请在当前聊天建立并开始执行长期目标，采用以下文件的完整目标正文和执行方案：
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first-plan-20261010/GOAL_ZH.md
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first-plan-20261010/PLAN_ZH.md

本轮从现在起14天，明确替换旧截止时间，保留历史消耗并沿用累计GPU 512小时、CPU 3840核小时、资格1024次、生产720次上限。新大文件可以使用NAS。先完成两套上游参考、一个可迁移三维数据包和两个单参数派生，然后按计划形成4至8个条件的小型三维内部版本。

请登记为当前聊天的持久目标，并开始实际执行。在目标、资源和期限范围内，完成检查点后自动继续下一项就绪工作，不需要我逐次确认。达到验收标准后结束；若预算、期限或真实外部阻塞导致无法完成，准确交付已有部分和恢复条件，不假称完成。
```

也可以使用应用支持的/goal入口，下发GOAL_ZH.md正文。持久目标有明确完成条件和用户控制，不意味着无条件24小时后台运行。[官方使用说明](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)

执行器首次接续需注意：最新科学基线位于 /home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics，当前主目录仍是较早工作区。不得仅因文件位于主目录就恢复旧的全流程PLAN.md或历史waiter。具体切入和隔离方法见PLAN_ZH.md。

本包中的14天及预算正文是可审阅的未来执行合同；正式下发时记录采纳时间、计划哈希、旧/新期限及起始账本。不要因为读到了本文件而自行创建目标或启动计算。
