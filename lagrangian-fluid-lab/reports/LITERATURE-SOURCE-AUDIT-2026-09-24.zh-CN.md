# PLAN 文献来源审计（2026-09-24）

## 结论

PLAN 第 1.3 节列出的六项工作均已对照原论文出版页、官方论文页或项目页进行人工来源核对。页面信息支持其书目信息和下表所列的主要研究事实；但当前环境没有 `research-lit` 的规范自动引用校验器，因此六项自动交叉验证状态一律保留为 **UNVERIFIED**。本报告不把人工核对等同于自动校验通过。

没有在仓库或可用本地文献库中找到这六项工作的 PDF；当前也没有 Zotero／Obsidian 连接器，且仓库中没有 `research-wiki/`。因此本次按可访问的官方在线来源完成核对，未做本地全文检索或知识库导入。

## 逐项核对

| 工作与书目信息 | 官方来源中可确认的内容 | 对 PLAN 的含义 | 自动状态 |
|---|---|---|---|
| **Learning to Simulate Complex Physics with Graph Networks** — Alvaro Sanchez-Gonzalez, Jonathan Godwin, Tobias Pfaff, Rex Ying, Jure Leskovec, Peter Battaglia. ICML 2020, PMLR 119, pp. 8459–8468. [PMLR 论文页](https://proceedings.mlr.press/v119/sanchez-gonzalez20a.html) | 学习的图网络模拟器将粒子作为节点、相互作用作为边，并以消息传递更新状态；论文研究了长时程预测及误差累积。 | 支持把长 rollout 与误差累积纳入基线和评测；仅有单步误差不够。 | **UNVERIFIED** |
| **LagrangeBench: A Lagrangian Fluid Mechanics Benchmarking Suite** — Artur Toshev, Andrea Galletti, Nils Fritz, Nikolaus A. Adams, Johannes Brandstetter. NeurIPS 2023 Datasets and Benchmarks. [NeurIPS 论文页](https://proceedings.neurips.cc/paper_files/paper/2023/hash/ccac3b120c7dc86d45f56830732b62be-Abstract.html), [arXiv](https://arxiv.org/abs/2309.16342) | 提供七个 SPH 流体数据集（四个二维、三个三维）、统一 JAX 接口及邻域搜索实现，并使用动能误差和 Sinkhorn 距离等指标。 | PLAN 需要强调多家族、可信参考、完整评测和任务设计，而不能仅以“粒子轨迹数据集”作为差异点。 | **UNVERIFIED** |
| **Neural SPH: Improved Neural Modeling of Lagrangian Fluid Dynamics** — Artur Toshev, Jonas A. Erbesdobler, Nikolaus A. Adams, Johannes Brandstetter. ICML 2024, PMLR 235, pp. 48428–48452. [PMLR 论文页](https://proceedings.mlr.press/v235/toshev24a.html), [arXiv](https://arxiv.org/abs/2402.06275) | 论文针对粒子聚团问题，在训练与 rollout 中纳入 SPH 压力、黏性及外力成分，并报告长期模拟改善。 | 支持 PLAN 对聚团和物理先验对照的关注；项目当前外力残差模型不应称作完整 Neural SPH。 | **UNVERIFIED** |
| **FD-Bench: A Modular and Fair Benchmark for Data-driven Fluid Simulation** — Haixin Wang, Ruoyan Li, Fred Xu, Fang Sun, Kaiqiao Han, Zijie Huang, Ching Chang, Xiao Luo, Wei Wang, Yizhou Sun. arXiv:2505.20349（当前核对版本 v2，页面标示修订于 2026-05-21）。[arXiv 论文页](https://arxiv.org/abs/2505.20349) | 页面描述包含 10 个场景、85 个基线，并将空间模型、时间推进、损失函数和数值求解器比较模块化。页面 comments 标示 KDD 2026 接收；本次未找到并单独核对对应会议论文集记录。 | 支持分别控制空间架构、时间推进、损失和求解器变量。会议接收信息应视作 arXiv 页面所载元数据，而非已由会议论文集独立确认。 | **UNVERIFIED** |
| **A Pioneering Neural Network Method for Efficient and Robust Fuel Sloshing Simulation in Aircraft** — Yu Chen, Shuai Zheng, Nianyi Wang, Menglong Jin, Yan Chang. AAAI 2025, 39(15), pp. 15957–15965. DOI: 10.1609/aaai.v39i15.33752. [AAAI 官方论文页](https://ojs.aaai.org/index.php/AAAI/article/view/33752), [官方 PDF](https://ojs.aaai.org/index.php/AAAI/article/view/33752/35907) | 官方论文页和 PDF 确认 FuelTank 数据集包含 320,000 帧、四类油箱及多方向旋转工况；论文讨论相应神经模拟方法。 | 三维燃料晃荡、多方向激励已有相关工作，因此不能仅凭这些特征主张新颖性。 | **UNVERIFIED** |
| **FluidLab: A Differentiable Environment for Benchmarking Complex Fluid Manipulation** — Zhou Xian, Bo Zhu, Zhenjia Xu, Hsiao-Yu Tung, Antonio Torralba, Katerina Fragkiadaki, Chuang Gan. ICLR 2023 Spotlight. [官方项目页](https://fluidlab2023.github.io/), [arXiv:2303.02346](https://arxiv.org/abs/2303.02346) | 项目页介绍以可微流体环境、FluidEngine 及复杂流体操控任务为中心；FluidEngine 支持多材料物理。 | “其模拟数据不能直接充当本项目的 CFD 真值”是基于两者目标及模拟系统不同作出的**项目适用性推论**，并非来源的原文结论；该区分应保留。 | **UNVERIFIED** |

## 校验边界与后续动作

- `research-lit` 规范 helper `verify_papers.py` 在 `.aris/tools/`、`tools/` 和可用的 `ARIS_REPO` 位置均不存在。按照 fallback 规则，不能自行把手工核对结果升级为机器校验通过。
- 六项候选记录与 fallback 状态保存在同目录 `.aris/verify-papers/`：`candidate_papers.json` 保存标识与来源，`verified_papers.json` 明示 `verdict: WARN`、缺失原因及逐项 `status: unverified` / `method: none`。
- 后续若规范 helper 可用，应按候选清单重新运行，并将其结果与本报告的人工来源核对分开记录。特别是 FD-Bench 的会议状态，宜再核对 KDD 官方论文集记录。
- 本审计只处理 PLAN 的文献来源证据；它不改变实验资格、Core 完成矩阵或既有资源门槛。
