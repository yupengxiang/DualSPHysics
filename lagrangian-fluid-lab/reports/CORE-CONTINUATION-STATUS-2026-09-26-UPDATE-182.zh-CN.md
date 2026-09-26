# UPDATE-182：F4R 完整 Definition 的 GenCase 相位矩阵

时间：2026-09-26（Asia/Shanghai）

完成 UPDATE-181 建议的 F4R center/offset × 三档分辨率 GenCase-only 静态矩阵。六例原始 Definition 的基线输出 `.bi4` 均与仓库现存旧矩阵逐字节一致，确认了旧初始人口可复现。

按每档分辨率选择全局 `<pointref>` 后，池体 MK1 的所有粒子中心都进入连续池盒；但该相位同时移动液滴质心与改变液滴/壁面粒数。候选的中档 fluid 质量比基线低约 6.4%；细档 center/offset 液滴数量差方向翻转。跨分辨率质量 spread 有所下降，不能据此声称守恒或因果修复。因此只保留为 GenCase 设计诊断，不冻结候选、不启动 solver。

详细原始对照、位置/人口/质量分项、输入转换脚本和逐文件哈希见[本轮 campaign 报告及回执](../campaigns/core-v1/cfd/f4r-pointref-phase-matrix-v1/report.zh-CN.md)。本轮未打开 production HDF5，未运行 solver/worker/GPU/队列，未改 registry/ledger；`T1/T2=false`，credit=0。

PLAN 的 F4 工作仍未完成：池体离散包络与旧轨迹穿墙之间的因果未证实；完整 `T₀=4.34 s` 事件窗未运行。下一静态设计须隔离全局 phase 对液滴初态的影响，再判断是否构成可审计的新 F4 scope。
