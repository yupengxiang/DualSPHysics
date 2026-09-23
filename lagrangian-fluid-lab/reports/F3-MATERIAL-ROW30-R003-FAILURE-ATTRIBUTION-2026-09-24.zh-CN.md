# F3 material row30 R003 失败归因（2026-09-24）

## 结论

R003 已完成完整的 0–835 原生帧区间（终点 8.3500128 s），运行返回成功且质量闭合；它不是短窗或基础设施失败。但两个来源的 unknown 比例都略高于冻结的 1% 上限，且回执没有绑定独立 512-vs-4096 求积 CDF 对照，所以本行仍不接受、T2 credit=0。当前 root-decision receipt 仍为 `awaiting_user_root_decision_for_new_row30_attempt`；本归因不启动、排队或授权新 attempt。

## 核验范围与数据边界

- 读取并核对 [R003 terminal audit](../campaigns/core-v1/material/evidence/f3-material-row30-r003-terminal-audit-v1/receipt.json) 和其绑定的 `trace.summary.json`。summary 为 83,228 bytes，SHA-256 `6e310de7c343d8e67da7611870f54336a5585ed16f06296d2996e4d7704b457d`，与 terminal audit 声明一致。
- 没有打开或哈希 515 MB `trace.h5`，没有打开 checkpoint NPZ，也没有重新计算 tracer、启动 worker 或触碰 queue/registry/ledger。terminal audit 中的 HDF5 hash 仍是声明值，不是本次独立验证结果。
- 固定门槛来自 acceptance adapter：每来源 `unknown_fraction <= 0.01`；独立 CDF 对照上限 `sup_abs <= 0.02`。未改门槛。

## 失败量化

R003 共 4,096 seeds，两个来源各占 2,048 seeds。已 hash-verified 的汇总给出：

| 来源 | 最终 unknown | 计数（/2048） | 首次失败 | 汇总中的终态失败原因 | 结论 |
|---|---:|---:|---:|---|---|
| 0 | 1.07421875% | 22 | 4.220015 s | `wall_occluded`: 19；`low_effective_sample_size`: 3 | 超过 1% 门；22 个高于可接受整数上限 20 |
| 1 | 1.025390625% | 21 | 2.370005 s | `wall_occluded`: 21 | 超过 1% 门；21 个高于可接受整数上限 20 |

两来源合计 43 个最终 unknown seed：40 个终态原因为 `wall_occluded`、3 个为 `low_effective_sample_size`。summary 的 `stage_failure_counts` 是 RK 阶段查询计数（57 次 `wall_occluded`、5 次 `low_effective_sample_size`），不是不同失败 seed 数，不应与终态计数混用。

首个失败分别出现在 2.37 s 与 4.22 s，而全窗口继续运行到 8.35 s。由此可排除“仅因统一窗口没跑完”这一解释。`candidate_support_pass_fraction_final` 为来源 0 的 0.9921875、来源 1 的 0.9970703125；它们是诊断量，不抵消终态 unknown 或 acceptance gate 失败。

## 可支持与不可支持的判断

- 数据支持把主要失败方向定位在墙遮挡后的局部场支持可用性；来源 0 另有少量低有效样本量失效。当前仅有汇总，不足以区分几何视线误判、壁面邻域稀疏与真实近壁超出可靠域等不同机制。
- 不应单纯增加/替换 seeds 来删除失败样本，也不能因仅差 1–2 个 seed 而放宽 1% 门。失败和右删失质量必须保留。
- 未绑定的 512-vs-4096 CDF 是独立缺口，必须由同输入、匹配方案的证据闭合；不能从未登记的相关诊断或当前 R003 汇总推断通过。
- 因原始 HDF5/NPZ 未在本次检查中独立读取，不能据此声称逐 seed 的空间根因已完成审计，也不能把这份归因当作修复设计审查。

## 下一步边界

现有 [row30 root-decision packet](../campaigns/core-v1/material/evidence/f3-material-row30-root-decision-v1/packet.json) 要求新 attempt 前重新解决资源/调度、输出命名空间、checkpoint/resume 和独立比较等门。用户在当前任务明确授权的是一次资源/调度预检，而不是新 worker；该预检已有阻塞回执，R003 也已有终态。因此本记录不生成新 job spec、不启动 worker、不修改 33 行矩阵。任何新 attempt 都必须有新的 root decision 和独立运行授权，并先针对墙可见性/近壁支持问题给出可证伪的设计；现有阈值、失败分母及历史产物保持不变。
