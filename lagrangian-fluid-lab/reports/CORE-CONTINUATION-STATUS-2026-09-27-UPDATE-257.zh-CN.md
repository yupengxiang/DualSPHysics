# Core continuation status — 2026-09-27 — UPDATE-257

## F3 graph residual 与 graph raw 的同协议粗筛

在与 UPDATE-254/255/256 相同的真实 F3 输入、test case、seed 17、hidden 8、center 256、train normalization、`max_neighbors=192`、full chunk `34560` 和 GPU 配置下，完成 `graph_residual` 100-update 诊断训练：`100/100`，evidence complete，residual prior 100 次调用、3,456,000 行均 finite，邻居截断比例为 `0.0`。训练 wall=`437.8605285859667 s`，peak RSS=`2691.96484375 MiB`，peak GPU=`1567362048 bytes`。

同一 test case 做 50-step autonomous diagnostic：`50/50` finite/executed，无 provenance、nonfinite 或 model execution failure。完整注册分母仍为 835 transitions，因此 receipt 保持 `maximum_steps_limit`、`complete=false`，raw coverage=`0.059880239520958084`。

| 模型 | 训练量 | step 50 position RMSE (m) | step 50 velocity RMSE (m/s) | 全窗口 position RMSE 均值 (m) | 全窗口 velocity RMSE 均值 (m/s) | selection score |
|---|---:|---:|---:|---:|---:|---:|
| `graph_raw` | 100 | 0.013675 | 0.100115 | 0.005367 | 0.042248 | 0.940724 |
| `graph_raw` | 500 | 0.010809 | 0.050800 | 0.006482 | 0.024222 | 0.940579 |
| `graph_residual` | 100 | 0.658410 | 2.647096 | 0.226518 | 1.327444 | 0.961031 |

结论：残差分支的“能完整执行 50 步”已证明，但物理误差显著差于两个 `graph_raw` checkpoint；更高的 selection score 与 RMSE 曲线不一致，不能据此选择残差模型。下一步按由粗到细原则，在同一协议下完成 `mlp` 100-update/50-step 粗筛，再决定是否值得进入更长窗口或 formal 训练。当前不启动 835-transition 全窗口，也不把任何一条诊断计入 formal training/T1/T2/credit。

完整对比 receipt 见 [`F3-REAL-MODEL-COMPARISON-RAW-RESIDUAL-50STEP-2026-09-27.json`](F3-REAL-MODEL-COMPARISON-RAW-RESIDUAL-50STEP-2026-09-27.json)。本次未修改生产 HDF5、registry、ledger 或分母，未启动 solver/worker/queue。
