# F3 DS-DATA-02 checkpoint / F3 交接

本 checkpoint 完成只读历史审计、可移动复用清单、两个新机制定义、完整事件语义、数值观测及 2×3/积分/采样计划。没有启动 solver/GPU，也没有加载模型或权重。

## 已确认历史资产

- 历史 canonical manifest 的 32 个 physical case 均可轻量打开；可复用 native 核心轨迹数：**32**。实际 solver 维度均为 3（generated XML `data2d=false` 与 HDF5 `position[...,3]` 互证）。
- 每个轨迹为 836 帧、34560 个流体身份、0–8.350012828 s、初末有效、初始质量约 14.58 kg；旧 split 保留为 train=16、validation=4、test=12。
- gate 只覆盖 CELL3 plain、单轴固定槽加速度和旧 recipe `F3_CELL3_NS_visco1_native_nopen_revision075_ref0081818`；它不授予双轴相位或偏心挡板/分舱交换资格。
- material archive 的 aligned.h5 候选数为 2，按 SHA-256 去重后为 1 个；aligned.h5 重复组：1（archive 全部文件重复组：2）。这些文件不计入 native F3 core case，也不计为材料标签通过。
- 共享 runner 已完成历史 CELL3 母例 CPU GenCase：status=completed，total=108000、fluid=34560、solver_dimension=3；receipt 位于 `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_HISTORY_CELL3_PARENT/F3_HISTORY_CELL3_PARENT_GENCAS_01/execution-receipt.json`。

## 实际缺口

- 32 个历史 HDF5 尚未写入 DS-DATA-02 原生 source/destination/first-passage/net-flux/residence 标签；标签生成必须保留 unknown 与合法开放顶部离域的分桶。
- 双轴/相位控制和偏心挡板/分舱横向交换各缺一套完整 3 分辨率参考矩阵；新矩阵的 solver_dimension、GenCase 实际粒子数、输入/控制/geometry 哈希和 full-window 证据均待 runner 产出。
- 积分步研究与保存频率研究尚未执行；降采样不能替代积分步对照。真实预览和可移动 HDF5 包在标签/Q-I 后生成。

## 最短执行链与 runner 请求

1. 历史 CELL3 母例已完成 bounded CPU GenCase receipt；下一步对每个新机制做一个有资源预约的 bounded CPU GenCase parent preflight，记录真实粒子数、横向层数和 geometry/control hash。
2. shared DS-DATA-02 runner 串行执行两个机制×三分辨率；每次先写入 runner 分配的唯一外部 `{attempt_root}`，通过标签/Q-I 后再移动复用到 `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/case/attempt`，启动时绑定 activity commit、generator hash、输入哈希、UUID lease 和 attempt_id。
3. 对中分辨率做 actual-dt 与 output-cadence 对照；之后生成原生事件标签、Q-I/Q-N scope receipt、预览和 portable manifest。

当前 runner 请求见 `execution_queue.json`；历史 `training_launch_allowed` 不是 DS-DATA-02 活动授权。

## 后续任务

共享预约入口已提供；下一任务是为双轴/相位与偏心挡板各冻结一个 parent Definition 并执行 bounded CPU GenCase preflight，其余工作按 `execution_queue.json` 继续，不把 canary 或旧 plain gate 当作新机制数值参考。
