# R3 当前交接：固定体力计与 mDBC 有界校准

日期：2026-09-07  
分支：`codex/lagrangian-fluid-exploration`  
交接内容编制时的已同步基线提交：`14036245179b6914f3fb295dcb99709cb31bb666`  
本交接文件随后作为独立文档提交；以远端分支最新 HEAD 为准。DualSPHysics 上游目录没有修改。

## 本轮范围

本轮按云端审阅意见，先完成一个独立的固定浸没体闭环：矩形水箱、固定的 `0.2 m` 立方体、压力力计，以及 DBC 控制和两档 mDBC 校准。没有扩大六族工况、没有做半径扫描，也没有生成任何 development tranche。

解析压力合力只作为预注册参考：

\[
F_z=\rho gV=1000\times9.81\times0.2^3=78.48\ \mathrm{N}.
\]

DualSPHysics force gauge 的含义是选定 `mkbound` 固定边界粒子上的压力相互作用；不包含重力、支撑反力或黏性项。因此 78.48 N 不能单独构成物理验收。

## 资源与可复现性

- 你已明确授权 GPU `0--7` 可使用；本轮实际选择空闲 GPU 4（UUID `GPU-74ce8a29-c3cd-1e50-a9b4-a2293f2335c9`）。
- GPU 0--3 在各次 preflight 时有既有负载，全部保持原样，没有中断；空闲优先级仍为 4--7。
- canonical 与 fine 的 preflight、solver 日志、法向/ghost VTK、力轨迹和统计摘要均在 mDBC 结果目录；大体积逐粒子 CSV 保留在本机的可恢复临时归档中，没有推入远程仓库。
- 全量回归：`cd lagrangian-fluid-lab && PYTHONPATH=. .venv/bin/pytest -q` → **196 passed**。

## 方向状态

| 方向 | `execution_status` | `acceptance_status` | 已验证范围 | 仍阻塞的事项 |
|---|---|---|---|---|
| E0 规范壁面/ghost 几何（`a7e3cad`） | 已完成 CPU/几何审计 | candidate geometry pass；physical mDBC 未接受 | `x_b,n_b,n_g,x_\gamma` 重构、`n_g=2n_b`、矩形/圆柱几何残差 | 求解器运行时仍出现零法向；尚无压力/力闭合 |
| 固定体 DBC 重力控制（`f831fb1`,`d04be60`） | GPU4 完成 | candidate not accepted | 固定身份、质量、无穿透、压力场和 force CSV | 末 0.20 s `Fz=124.777 N`、标准差 `36.634 N`，相对参考误差 58.99%；稳定门失败 |
| 固定体 DBC 零压控制 | GPU4 完成 | control pass；不是物理参考接受 | 初始/末态压力和力窗口均为 0，固定体不动 | 仍需修复历史 solver-log excluded 字段为 null 的报告缺口 |
| C1/C2 tracer/G4 几何契约（`d160d8b`） | 已完成，生产路径测试纳入 | candidate-only | 刚体 pose/Slerp、swept-wall、sidecar、ESS/geometry guard、失败分母 | 尚无外部物理锚点；不等于材料示踪物理验收 |
| mDBC canonical-2（`b438655`） | 最终定义 GPU4 完成 | candidate not accepted | `dp=0.025 m`；固定映射、力计、法向/ghost、初末场审计 | 运行时零法向 `63/22515`；末帧流体穿透 `27`；末 0.20 s `Fz=93.397±52.379 N` |
| mDBC fine-3（`b438655`） | 最终定义 GPU4 完成 | candidate not accepted | 同一物理几何，`dp=0.0125 m`；固定映射、力计、法向/ghost、初末场审计 | 运行时零法向 `240/87979`；排除粒子 `20`；末帧穿透 `197`；末 0.20 s `Fz=80.789±28.919 N` |

canonical 和 fine 的 force 均没有通过稳定性门（以 5% 参考力作为诊断限值，不是自动接受条件）。fine 的均值接近 78.48 N 不能抵消穿透、排除和零法向失败。

详细机器报告：[mdbc-fixed-box-force-gauge-report.json](cases/r3-fixed-box-force-gauge/mdbc-fixed-box-force-gauge-report.json)；复现实验和契约测试：[run_mdbc_fixed_box_force_gauge.py](cases/r3-fixed-box-force-gauge/run_mdbc_fixed_box_force_gauge.py)、[test_mdbc_fixed_box_force_gauge.py](cases/r3-fixed-box-force-gauge/test_mdbc_fixed_box_force_gauge.py)。

## 当前结论

这轮成功证明了“最终几何定义 → GenCase → GPU 求解 → force gauge → PartVTK 初末场 → 法向/ghost 与穿透审计”的闭环，也证明了一个容易被忽略的负事实：GenCase 的 `Final zero normals=0` 不能替代求解器运行时法向完整性。canonical/fine 的运行时法向和场完整性均未达标，因此不能把 mDBC 宣称为 Test 14 或固定浮体的物理参考实现。

工具链、身份/生命周期语义、材料示踪候选接口、lineage 划分和评测契约仍可作为开发版快照；正式 v0.1 物理设计、F6 参考场景和排行榜均不冻结。

## 下一步 acceptance gate

1. 定位 mDBC 运行时零法向：按面、边、角和 `Mk` 分区，明确是 normal construction、粒子层、还是 solver 读取/边界距离问题；不得用改变物理壁面尺寸来“清零”。
2. 在同一固定体上修复并重跑 canonical/fine 的短时静水力；必须同时满足运行时法向完整、无排除粒子、无流体穿透、固定体不动、质量守恒和多窗口 force 稳定。
3. 对时间输出 cadence 与 `dp` 做受控收敛，并寻找可兼容的外部压力/排水观测锚点。
4. 只有某个家族通过上述门禁，才允许为该家族生成 20--30 例 development tranche；随后重新训练真实 baseline，再决定正式规模。

请云端审阅者重点确认：下一轮是否优先对 canonical/fine 的 63/240 个运行时零法向做面级诊断，还是先调整 mDBC 的规范壁面/粒子层构造；在这两个门禁通过前，不应扩大生产矩阵。
