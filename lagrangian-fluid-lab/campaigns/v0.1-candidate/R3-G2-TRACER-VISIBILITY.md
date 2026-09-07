# R3 G2 示踪材料可见性 synthetic 诊断

状态：**candidate-only / rejected；CPU-only，未运行 CFD、未使用 GPU，也未改生产代码。**

## 结论

当前仓库没有名为 `r3_g2_tracer_wall_aware.py` 的脚本；实际 wall-aware 路径是 `scripts/passive_tracers.py` 的 `segment_visibility` 和 `corresponding_segments_blocked`。合成反例确认：给出有限三角墙时，已有路径能阻止跨墙样本；没有墙几何时，它不能从空间分离本身推断液团拓扑。

| Probe | legacy 24-neighbor 污染权重 | existing wall-aware 污染权重 | legacy 错向率 | wall-aware 错向率 |
|---|---:|---:|---:|---:|
| 隔板两侧切向流 | 0.875 | 0.000 | 1.000 | 0.000 |
| 窄间隙（仅统计被墙挡住的近样本） | 0.681 | 0.000 | 1.000 | 0.000 |
| 分离液团（无 barrier） | 0.672 | 0.672 | 1.000 | 1.000 |

## 逐例观察

- 隔板：legacy 的平均错误侧权重为 `0.875`，16 个查询中错向率 `1.000`；wall-aware 将错误侧权重降为 `0.000`，错向率为 `0.000`。这证明有限三角视线过滤确实参与了邻居选择。
- 窄间隙：wall-aware 对 20 个墙后近样本的可见保留率为 `0.000`，但对真实开口的 15 个样本保留率为 `1.000`。每个查询只有 23 个可见样本，少于 24；因此最小可见支撑 guard 会安全拒绝这组 probe，而不能在没有 open-face policy 时直接接纳。
- 分离液团：无 triangle 时 wall-aware 与 legacy 相同（错向率 `1.000`，错误侧权重 `0.672`）。已知 synthetic region-label gate 可将错向率降为 `0.000`，但该标签不是当前生产 API 的材料 lineage，故标记 rejected candidate。

## Candidate guard 决策

本轮只保留两个独立 candidate-only 选项用于后续设计：

1. `minimum_visible_support`：要求可见样本数至少达到 24；它对跨墙混合采取拒绝策略，但会把窄间隙合法 transport 也判为欠支撑。
2. `known_region_label_gate`：在 synthetic 中按已知 blob 标签筛选同区域样本；它能修复分离液团，但缺少生产 region/lineage contract，且静态标签无法独立表达开口连通性。

两者均为 **rejected candidate-only**，没有替换 `passive_tracers.py`。正式接纳前仍需冻结 wall component 的 open/closed/rim/supporting policy、材料 destination/region 语义，并在收敛矩阵中报告欠支撑拒绝率。

机器可读证据：`r3-g2-tracer-visibility.json`；可重复入口：`diagnostics/r3_g2_tracer_visibility/probe.py`。
