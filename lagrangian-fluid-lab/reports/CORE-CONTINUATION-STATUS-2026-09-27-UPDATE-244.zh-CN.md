# Core continuation status — 2026-09-27 — UPDATE-244

## F3 real-case graph profile with cap 192

在 UPDATE-243 的 bounded profile 参数补丁之后，对真实 `F3_DEV_00_a0p903125` 做了显式 `max_neighbors=192` 的 `graph_raw` 单步 profile：seed `17`、hidden `16`、chunk `256`、CPU、`steps=1`。该次 profile 成功完成，`steps_completed=1`，step wall `335.07701214100234 s`，CPU `715.619268 s`，peak RSS `1127.66015625 MiB`；原始 CLI 输出 SHA 与配置保存在 [`F3-MODEL-PROFILE-CAP192-2026-09-27.json`](F3-MODEL-PROFILE-CAP192-2026-09-27.json)。

这证明在当前真实 frame 0 上，恢复足够的 neighbor capacity 后，reader → formal provenance → graph_raw inference 的单步接口可以走通；它不证明后续 autonomous frame、全 32-case、训练或物理质量。当前 profile 仍是 diagnostic-only，未创建 checkpoint，不读取未来 reference state，也未修改生产 HDF5、registry、ledger、分母、gate 或资格信用；solver/worker/GPU/queue 均未启动。当前 chunking 成本较高，下一步先做更大 center chunk 的效率探测，再决定是否有条件扩大 profile 窗口。
