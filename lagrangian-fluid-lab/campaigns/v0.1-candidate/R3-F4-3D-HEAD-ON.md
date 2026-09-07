# R3 F4 3-D head-on liquid-column observation probe

状态：**candidate-only；不授权正式数据发布**。

本探针从 `cases/F4/F4_head_on_columns/F4_head_on_columns_Def.xml` 复制隔离定义，
使用显式 `tmax=0.55 s`、
`tout=0.01 s`，并验证
三档 `dp=0.04/0.03/0.02 m` 的 3-D 双液柱正碰路径。固定点 `MeasureTool` 同时记录
pressure、velocity、rhop 和 Kcorr；`ComputeForces` 按契约先执行 `mk=10`。

当前 solver 完成 3/3 个运行，
其中 3 个完成固定点观测，
0 个真正完成 requested Mk=10，
3 个只完成了 effective-Mk fallback；
跨分辨率比较形成 3 对，全部仅为 diagnostic。

一个关键可复现问题已经暴露：该 XML 的 `mkbound=0` 在 GenCase v5.4 中映射为
物理 `Mk=17`，因此 `ComputeForces -onlymk:10` 没有边界粒子。报告保留原始
Mk=10 请求，并把 Mk=17 结果标为 fallback，不能把 fallback 改写成 Mk=10 或
当作外部物理验证。

本轮只证明“隔离复制、三档求解、固定点观测和力后处理链路可执行/可追溯”。
原始 solver BI4、CSV 和运行日志留在 campaign 的 ignored 运行目录；提交内容只保留
定义/GenCase provenance、结构化摘要和 candidate-only 结论。
没有外部参考、没有收敛阈值，也没有材料谱系/混合界面真值；因此 F4 仍不能
进入正式数据发布或 family admission。

机器可读详情见 `r3-f4-3d-head-on.json`。
