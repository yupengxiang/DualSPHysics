# Core continuation status — 2026-09-27 — UPDATE-252

## F3 coarse graph training improves short-window rollout

在 UPDATE-251 的 1-update graph_raw 发散 canary 后，使用真实 F3 train split 做 bounded `graph_raw` training：20 updates、256 centers/update、hidden 8、normalization transitions 16、seed 17、cap 192、CPU。训练 wall=`109.36784281488508 s`、peak RSS=`2927.78125 MiB`、evidence complete；16 个 train case 的均匀 transition 绑定均被采样，20 次记录的 `neighbor_truncation_fraction` 全为 0。

使用该 checkpoint 对同一 test case 做 10-step diagnostic evaluate：仍按完整 835 transitions 标记 `maximum_steps_limit`、complete=false、raw coverage=`0.011976047904191617`，但短窗误差明显优于 1-update canary：position RMSE `0.00021036337262399346→0.0021323269126876953 m`，velocity RMSE `0.002254926015778417→0.017265891565776067 m/s`，selection score=`0.9880511211531582`。这是 coarse training effect 的诊断观察，不是完整案例质量或正式模型选择结论；receipt 见 [`F3-REAL-GRAPH-TRAIN20-EVALUATION-CANARY-2026-09-27.json`](F3-REAL-GRAPH-TRAIN20-EVALUATION-CANARY-2026-09-27.json)。

仍未进入 32k formal training、完整 test denominator、T1/T2 或 credit；checkpoint/evaluation 都位于 `/tmp`，没有修改生产 HDF5、registry、ledger、分母或 gate，未启动 solver/worker/GPU/queue。
