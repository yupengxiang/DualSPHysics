# Core continuation status — 2026-09-27 — UPDATE-258

## F3 三模型同协议粗筛完成

在同一真实 F3 输入和同一 test case 上，完成 `graph_raw`、`graph_residual`、`mlp` 的可比短长窗矩阵：seed 17、100 updates、256 centers、hidden 8、train-only normalization、`max_neighbors=192`、full chunk `34560`、GPU、50-step autonomous evaluate。三条 rollout 均执行到请求上限；完整注册分母仍为 835 transitions，所以都不是 complete case。

| 模型 / 训练量 | step 50 position RMSE (m) | step 50 velocity RMSE (m/s) | position RMSE 均值 (m) | velocity RMSE 均值 (m/s) | selection score |
|---|---:|---:|---:|---:|---:|
| `graph_raw` / 100 | 0.013675 | 0.100115 | 0.005367 | 0.042248 | 0.940724 |
| `graph_raw` / 500 | 0.010809 | 0.050800 | 0.006482 | 0.024222 | 0.940579 |
| `graph_residual` / 100 | 0.658410 | 2.647096 | 0.226518 | 1.327444 | 0.961031 |
| `mlp` / 100 | 0.014581 | 0.101352 | 0.005855 | 0.042813 | 0.940746 |

MLP 训练 `100/100` 完成，evidence complete，wall=`194.1937219509855 s`，peak RSS=`2545.984375 MiB`；50-step evaluate `50/50` finite/executed，无 execution/provenance/nonfinite failure，wall=`96.0019589799922 s`。它与 graph_raw train100 接近，但 step50 position/velocity 和 velocity 均值均略差，未提供替换 graph_raw 的证据。结合 residual 的显著失败，当前粗筛选择 `graph_raw` 作为主方向，MLP 保留为 compact control；selection score 的约 `0.9406` 级别差异不覆盖 RMSE/ADE 曲线。

下一步继续围绕 F3 `graph_raw` 做长时域/训练策略验证，再决定是否值得承担完整 835-transition 窗口成本；当前仍不把任何短窗诊断计入 formal training、T1/T2 或 credit。

完整矩阵 receipt 见 [`F3-REAL-MODEL-MATRIX-RAW-RESIDUAL-MLP-50STEP-2026-09-27.json`](F3-REAL-MODEL-MATRIX-RAW-RESIDUAL-MLP-50STEP-2026-09-27.json)。本次未修改生产 HDF5、registry、ledger 或分母，未启动 solver/worker/queue。
