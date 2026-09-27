# Core continuation status — 2026-09-27 — UPDATE-254

## F3 100-update 粗训练与 10-step GPU 诊断

沿 F3 方向继续采用由粗到细策略：在相同真实 manifest、`graph_raw`、seed 17、hidden 8、center 256、normalization transitions 16、`max_neighbors=192` 绑定下，将 bounded diagnostic training 从 20 updates 推到 100 updates。训练 `100/100` 完成，evidence complete，`neighbor_truncation_fraction=0.0`；GPU wall=`457.5900733030867 s`，peak RSS=`2692.5078125 MiB`，peak GPU memory=`1567362048 bytes`。

随后对固定 test case `F3_DEV_00_a0p903125` 做 10-step GPU autonomous diagnostic：请求窗口内 `10/10` finite/executed，未发生数值失败；position RMSE `0.000164→0.001665 m`，velocity RMSE `0.001830→0.012789 m/s`，相较 UPDATE-252 的 20-update 短窗误差有所改善。但注册分母仍是完整 `835` transitions，因此 receipt 按 `maximum_steps_limit` 标为 `complete=false`，raw coverage=`0.011976047904191617`，不能解释为完整 case 质量或 T1。

完整 receipt 见 [`F3-REAL-GRAPH-TRAIN100-EVALUATION10-CANARY-2026-09-27.json`](F3-REAL-GRAPH-TRAIN100-EVALUATION10-CANARY-2026-09-27.json)。本次仍是 diagnostic-only：manifest `formal_release=false`，不计 9-run formal training、T1/T2 或 credit；未修改生产 HDF5、registry、ledger 和分母，未启动 solver/worker/queue。下一步应先用更长但仍有界的 rollout 验证误差是否持续增长，再决定是否投入完整 835-transition 计算。
