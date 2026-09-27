# Core continuation status — 2026-09-27 — UPDATE-241

## F3 real-case neighbor-cap sweep

为定位 UPDATE-240 的 two-hop provenance blocker，对真实 `F3_DEV_00_a0p903125` 的 frame 0 做了只读 cap sweep；源 HDF5、manifest SHA、粒子轴和 smoothing length 固定在 [`F3-REAL-NEIGHBOR-CAP-DIAGNOSTIC-2026-09-27.json`](F3-REAL-NEIGHBOR-CAP-DIAGNOSTIC-2026-09-27.json)。默认 cap=`64` 时全场有 `13,544` 个截断行，center 0 的 35 个 required rows 中有 8 个截断；cap=`128` 时 center 0 的 required rows 完整，但全场仍有 `6,764` 个截断；cap=`192` 和 `256` 时该 frame 全场均无截断，实测最大邻居数为 `146`。

这只是一个 frame-local、单案例的容量诊断：它说明默认 cap 是真实 profile 的直接接口阻塞来源之一，但不能把 `192` 推断为所有 frame、所有 F3 case 或正式训练策略的全局值。没有修改 `core_models.py`、没有放宽 formal provenance validator、没有创建训练 checkpoint，也未改变 T1/T2、gate、credit、registry、ledger 或分母；生产 HDF5 与 solver/worker/GPU/queue 均未触碰。下一步仍需 synthetic cap/provenance 负例、可审计参数传递和更广的真实输入验证后，才可考虑模型 profile 修复。
