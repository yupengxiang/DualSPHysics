# W12 结论：真实基线与冻结建议

状态：**简单基线、低分辨率 SPH 外部观测基线和两条真实学习路线均已走通；建议冻结协议和工具链，不冻结正式 v0.1 数据设计。**

## 真实实验，而非占位程序

W11 的严格 manifest 被直接用于训练。两条路线分别是 18,691 参数的逐粒子 MLP，以及 51,587 参数的 DeepSets 全局上下文模型；每条路线使用 17/29/43 三个种子，5 epoch，训练后从测试案例首帧开始全时域 autonomous rollout。六次实验绑定 GPU 4–7 的 UUID，逐次映射见 `experiments/w12/run-manifest.json`。

每个种子训练约 11–15 秒，峰值显存约 19–23 MiB。这说明训练/评测工程路径很轻，当前限制来自数据和建模语义，不是算力。

## 最重要的负结果

| 测试案例 | 常速度 RMSE/dp | Particle MLP（三种子均值） | DeepSets（三种子均值） |
|---|---:|---:|---:|
| F1 twin obstacle | 3.786 | 4.460 | 3.476 |
| F2 rotating pour | 28.704 | 222.316 | 173.353 |
| F3 transverse slosh | 5.090 | 2.220 | 3.103 |

学习器的单步验证误差约 0.05dp，却在 F2 长时倾倒中灾难性发散，且种子方差很大。这个结果直接证明：只发布 teacher-forced 一步误差会产生误导；自主 rollout、逐家族报告和简单基线都必须保留。它也表明后续模型至少需要局部邻域、边界几何和控制运动输入，当前两个小模型只能证明管线，不能作为有竞争力的 benchmark baseline。

这里的常速度对照和“灾难性退化”只作为学习器/输入管线诊断，不能作为物理场景的准入门槛；可信但困难的场景仍应保留，并单独报告模型失败。

低分辨率 SPH 作为另一条、不可混排的观测基线：W05 已给出 Test 02 液面/压力、Test 10 撞击压力和 Fekken 二维刚体位移。它们与粒子 rollout 不同单位、不同真值来源，`w12-baselines.json` 因而不制造跨赛道总排名。

## R3 验收补证交接

在本结论之后又完成了一轮受控补证，所有结果仍保持 candidate-only 或明确 rejected，不改变“暂不冻结正式物理设计”的决定：

- G1：协议指标门禁和 W11 原子发布坏文件回归已通过；无效平移、非法质量比例、中间身份复现、质量突变和 NaN 密度都会被拒绝。
- G2：F2 三背景×三分辨率、F1/F3 双背景×三分辨率、F6 Test 14 双偏移×三分辨率均有运行记录；独立示踪的 cadence/子步/数量、有限边界 sidecar 和身份置换对照也已落盘。它们证明路径和敏感性，不把同一求解器一致性冒充实验真值。
- G3：`r3-g3-coverage-audit.json` 现在逐阶段报告 declared→executable→run→structural→reference→training/eval；W08 的 204 张连续轴卡全部 `planned_not_run`。独立命名空间中的 F1 twin topology holdout 已完成可执行、求解、归一化和结构审计链，但仍 candidate/rejected；F2/F3/F6 topology holdout 仍未运行。
- G4：弱基线、局部相互作用和 physics-residual 路线均保留三种子结果；常速度退化只作为学习器诊断，绝不作为物理场景准入门槛。
- F4：O4 二维官方 impinging-jet 与隔离三维 head-on 液柱观测链路均已执行三档分辨率；F4 仍缺兼容外部锚点、材料碰撞谱系和可接受的 force 目标。
- F6：三维 Test 14 DBC 代理的静态/动态证据仍被拒绝；新增 CPU-only mDBC 预检确认 `Boundary=2`、`BoundNor` 与 ghost-normal 文件路径可执行，但 792 个 fixed/moving 零法向、Chrono collision warning 和过短时窗阻止物理验收。
- G1/G2/G3/F4/F6 之后的全量 Python 回归为 `166 passed`。机器报告中的 `execution_status`、`acceptance_status`、`validation_scope` 和 `open_blockers` 才是当前权威状态，旧 `status=complete` 仅为历史兼容字段。

## 冻结决定

现在可以冻结为**开发版接口/语义快照**：隔离式工程与不可变 attempt、闭域固定分辨率数值身份语义、独立材料示踪候选接口及可靠掩码含义、五类因果字段、lineage split、HDF5/manifest/指标契约，以及 W07/W08 的候选轴与受控研究结构。这里不冻结材料轨迹的物理正确性、wall-aware 可见性或目的地任务验收。

现在不能冻结：材料示踪的物理验收与目的地闭合、正式纳入哪些家族、每族参数数量、生产分辨率/事件输出频率，以及排行榜模型。具体缺口是 destination/open-face 语义与示踪收敛、F1 撞击压力，F2 外部观测与分辨率，F3 撞击时序，F4 兼容外部锚点与材料碰撞谱系，F5 稳定爬坡验证，以及 F6 DBC 代理的平衡偏差、mDBC 零法向/Chrono 配置和大域敏感性。W08 还需完成其余 topology holdout 的独立实体化，并对 F1 候选补做分辨率与外部参考验收。

优先顺序建议是先补 F2，因为其来源—去向任务最鲜明；再闭合 F1/F3 事件采样和收敛，并针对 F6 零法向与 Chrono 配置重建可接受的 mDBC/Test 14 运行；F4/F5 各找到并跑通外部锚点后再决定保留。W08 的连续轴卡继续保持设计态，先完成其余 topology holdout 的最小实体化和 F1 候选验收。只有通过这些门禁的家族才生成 20–30 例下一阶段 development tranche，复跑真实 AI baseline 后再冻结正式规模。

本轮可核算的 55 次成功 GPU 求解器运行加 6 次学习实验合计下界约 0.314 GPU·h；另有 CPU-only F6 mDBC 预检不计入 GPU 时数。该下界远低于最初 64 GPU·h 释放上限，不含失败尝试、缺 elapsed 字段的 W02、CPU 后处理和依赖安装，避免伪精确。
