# Core continuation status — 2026-09-27 — UPDATE-249

## F3 real graph training canary with bound cap 192

在 UPDATE-248 的 checkpoint cap binding 完成后，按真实 `campaigns/core-v1/f3-dataset-v2.json` 做了一个受界限的 F3 `graph_raw` training canary：seed `17`、hidden `8`、1 update、每次 1 center、normalization transitions=`1`、CPU、显式 `max_neighbors=192`，不做 milestone evaluation。该 canary 完成，wall=`5.0246339871082455 s`、peak RSS=`1261.703125 MiB`，checkpoint `97,547` bytes；实际采样 `F3_DEV_20_a1p028125` frame `714`，`neighbor_truncation_fraction=0.0`，evidence status=`complete`。receipt、checkpoint 和 reader manifest identity 见 [`F3-REAL-GRAPH-TRAIN-CANARY-CAP192-2026-09-27.json`](F3-REAL-GRAPH-TRAIN-CANARY-CAP192-2026-09-27.json)。

这是第一次走通真实 F3 reader → train-only normalization → full-field graph input → backward/update → bound checkpoint 的粗粒度链路，但 manifest `formal_release=false`、validation formal eligibility=false，因此不能计入 9 个正式 training runs、T1 或 credit。所有输出留在 `/tmp`；未修改生产 HDF5、registry、ledger、分母或 gate，未启动 solver/worker/GPU/queue。
