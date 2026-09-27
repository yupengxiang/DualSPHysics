# Core continuation status — 2026-09-27 — UPDATE-245

## F3 real-case full-field chunk efficiency and two-step profile

保持真实案例、`graph_raw`、seed `17`、hidden `16`、CPU 和 `max_neighbors=192` 不变，仅将 center chunk 从 `256` 调为全场 `34,560`。一阶 profile 从 chunk=256 的 `335.07701214100234 s` 降至 `20.67582248011604 s`，peak RSS 为 `4318.84765625 MiB`。随后相同配置运行 2-step autonomous profile，两步分别为 `20.45677742990665 s` 与 `20.22977391211316 s`，mean=`20.343275671009906 s`，peak RSS=`4352.16015625 MiB`；两次输出均标记 `autonomous_state_feedback=true`、`max_neighbors=192` 且完整完成。

这表明当前 graph 实现的主要成本来自对每个 center chunk 重复构造全场 two-hop graph；大 chunk 可以把短窗口诊断压到可执行范围，但内存代价约 4.35 GiB，不能直接推断正式训练的资源预算。结果仍是 diagnostic-only，不创建 checkpoint、不计算资格指标、不读取未来 reference state；未修改生产 HDF5、registry、ledger、分母、gate，也未启动 solver/worker/GPU/queue。
