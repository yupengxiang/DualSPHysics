# L1 Autonomous Fluid Qualification：范围采纳记录

日期：2026-09-09

## 采纳依据

本轮用户明确要求查看引用任务的最后一轮 reviewer 规划，按该规划继续推进，完成后推送远程并向云端 reviewer 交接审阅文档。随消息附带的 L1 任务包包含一次性范围模板；本记录将上述用户要求解释为采纳该模板的 L1 范围，但不把附件本身伪装成额外签名或 reviewer 回写。

附件：`Lagrangian_Fluid_L1_Autonomous_dc9533e.zip`

附件 SHA-256：`2140048e019b2074668799aef145314af90eae242498450c069bbdb910aab5e3`

附件内部 `SHA256SUMS` 已验证通过；`PLAN_VALIDATION.json` 为 `16/16`，其范围仅是规划元数据静态检查，不是 solver 或物理验收。

## 起始事实

- 起始分支：`codex/lagrangian-fluid-exploration`
- 起始提交：`dc9533eecf7ee608a1db04ea4e26bb80cd2b456a`
- 起始远程同名分支：与上述提交一致
- N4：4/4 attempt 已封存，不能重用 N4 额度或启动第五次
- 上游 DualSPHysics、`vendor/` 和历史 `v0.1-candidate` 证据只读；本活动新产物位于本目录下的 `campaigns/l1-qualification/`

## 本次有效范围

目标是获得至少一个范围明确的 F1 数值参考配方，或在所有有界分支耗尽后给出可证伪的根因与适用范围图。所有结果均需区分 `execution_status`、`evidence_status`、`acceptance_status`、`validation_scope` 和 `open_blockers`。

资源上限为：64 GPU·h、512 CPU core·h、96 次 solver attempt（资格最多 56、条件试产最多 40）、12 次训练 attempt、32 组完整材料积分、512 GiB 新存储、168 小时活动有效期。失败、中断和重复都计数；上限不是必须耗满的目标。

只使用实时核验为空闲的 GPU 4--7，最多 4 个 GPU 重任务；GPU 0--3 受保护，不终止外来进程。最多 2 个 CPU 重任务，每个默认 8 线程；磁盘至少保留 100 GiB 且不低于容量的 10%。不正式发布、不生成 hidden test、不强推、不合并主线。

## 顺序与当前分支

1. W0：核对历史原始帧、规范化帧、全时域审计和几何/数值语义，锁定新门禁。
2. W1：在 `dp=0.014 m` 上比较 CFL 0.1/0.05，必要时补 0.025；随后按 `dp=0.020/0.014/0.010 m` 和高度 `0.414/0.460/0.506 m` 做空间研究。
3. 若细化改善但未准入，最多补登记的 `0.014/0.010/0.007 m` 阶梯；否则进入最多两类、每类最多两次的受控根因后备。
4. 只有 T1、参数内部点、输入 lineage 和批次硬门通过，才允许 8 例起步的 development tranche；F6 本活动新 solver 次数固定为 0。

历史失败不得被新配方改名覆盖。T1 只表示锁定 DualSPHysics 离散下的数值粒子动力学参考，不自动表示连续流体实验真值；T2、外部观测和模型能力分别判定。
