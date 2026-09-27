# Core continuation status — 2026-09-27 — UPDATE-250

## F3 three-model real canary coverage

在 cap=192 checkpoint binding 和 graph_raw canary 之后，对同一真实 F3 manifest、seed `17`、hidden `8`、1 update/1 center/normalization 1/CPU 运行三条模型分支：`graph_raw` wall=`5.0246339871082455 s`、`graph_residual` wall=`5.36543723102659 s`、`mlp` wall=`2.6338432179763913 s`。三次均完成 checkpoint 写入，evidence status=`complete`，实际采样相同的 `F3_DEV_20_a1p028125` frame `714`，`neighbor_truncation_fraction=0.0`；绑定回执与 checkpoint digest 汇总在 [`F3-REAL-MODEL-CANARIES-CAP192-2026-09-27.json`](F3-REAL-MODEL-CANARIES-CAP192-2026-09-27.json)。

这完成了 F3 方向 reader → normalization → 三类 model update → bound checkpoint 的粗粒度覆盖，但不是 9 个正式 model/seed runs：manifest `formal_release=false`，没有正式 validation/test rollout 或可信 reader admission。三次输出均在 `/tmp`，未改生产 HDF5、registry、ledger、分母或 gate，未启动 solver/worker/GPU/queue，credit=0。
