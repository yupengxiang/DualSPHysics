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
- 双轴/相位与偏心挡板 parent 的 GenCase 实际粒子数、actual 3D、横向层、控制覆盖、有限壁面、初始质量及输入 hash 已由 shared runner receipt 审计；完整 3 分辨率 solver 矩阵、native dt、事件标签和 full-window HDF5 仍待后续 runner 产出。
- 积分步研究与保存频率研究尚未执行；降采样不能替代积分步对照。真实预览和可移动 HDF5 包在标签/Q-I 后生成。

## 最短执行链与 runner 请求

1. 两个新机制 parent bounded CPU GenCase 已完成并通过结构审计；下一步按 `qualification_requests/` 提交首批完整 0–10 s solver qualification，由 shared runner 绑定 GPU lease、启动 commit 和 parent receipt。
2. shared DS-DATA-02 runner 串行执行两个机制×三分辨率；每次先写入 runner 分配的唯一外部 `{attempt_root}`，通过标签/Q-I 后再移动复用到 `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/case/attempt`，启动时绑定 activity commit、generator hash、输入哈希、UUID lease 和 attempt_id。
3. 对中分辨率做 actual-dt 与 output-cadence 对照；之后生成原生事件标签、Q-I/Q-N scope receipt、预览和 portable manifest。

当前 runner 请求见 `execution_queue.json`；历史 `training_launch_allowed` 不是 DS-DATA-02 活动授权。

## 后续任务

两个 parent 已冻结且通过 bounded CPU GenCase 结构审计；下一任务是提交 `qualification_requests/` 中的完整窗口 solver 请求，再由 shared runner 串行推进 2×3 矩阵、积分步/保存采样对照和原生事件标签，不把旧 plain gate 当作新机制数值参考。

## Actual parent evidence

- 双轴/相位 parent GenCase：attempt `_02`，total=132522、fluid=34320、actual 3D、横向层=26、初始质量=14.47875 kg；控制覆盖 0–10 s/2001 行，有限壁面和输入 hash 均通过。
- 偏心挡板 parent GenCase：attempt `_03`，total=130768、fluid=36736、actual 3D、横向层=22、初始质量=18.808832 kg；移动槽世界坐标控制覆盖 0–10 s/2001 行，有限外壁/挡板 shell 和输入 hash 均通过。
- 根因修复证据保留在 audit：双轴第一次 seed 位于底边界后修为内部高度；挡板先移除造成全域 bound 的 void-shell 操作，再把落在挡板厚度内的 origin seed 移到开放通道；每个机制均在两次以内收敛到非零 fluid。
- parent 只通过 GenCase/Q-I 结构审计；qualification request 已生成但 solver/GPU 尚未启动：`qualification_requests/dual_axis_phase.json`, `qualification_requests/eccentric_baffle_exchange.json`.
- 旧 32 例及原 split 仍只在 legacy plain fixed-acceleration 等价范围复用；新 parent 不改变旧 split，也没有 Q-N 资格。
