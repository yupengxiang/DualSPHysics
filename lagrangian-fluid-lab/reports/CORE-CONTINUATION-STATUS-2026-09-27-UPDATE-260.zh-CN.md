# Core continuation status — 2026-09-27 — UPDATE-260

## F3 graph_raw seed 与 hidden 宽度并行粗筛

利用空闲 GPU1/2，在 GPU0 full rollout 并行运行期间完成两条独立诊断。两条都使用真实 F3 manifest、同一 test case、100 updates、256 centers、`max_neighbors=192`、full chunk `34560`、50-step autonomous evaluate；均 `100/100` training、evidence complete、邻居截断 `0.0`、`50/50` requested steps finite/executed。固定 registered denominator 仍为 835 transitions，因此两条都保持 `maximum_steps_limit` incomplete，不计 formal training/T1/T2/credit。

| 配置 | step50 position RMSE (m) | step50 velocity RMSE (m/s) | position RMSE 均值 (m) | velocity RMSE 均值 (m/s) | selection score |
|---|---:|---:|---:|---:|---:|
| 既有 `graph_raw`, seed17, hidden8, update500 | 0.010809 | 0.050800 | 0.006482 | 0.024222 | 0.940579 |
| 新 `graph_raw`, seed18, hidden8, update100 | 0.012922 | 0.043598 | 0.005016 | 0.028150 | 0.940570 |
| 新 `graph_raw`, seed17, hidden16, update100 | 0.017573 | 0.066463 | 0.007421 | 0.024931 | 0.940618 |

结果是 mixed：seed18 hidden8 给出较好的 position frame mean 和两个新诊断中的 endpoint velocity；hidden16 给出较好的 velocity frame mean，但 position 变差。两条都没有在 50-step 窗口上同时胜过 raw500，因此继续保留 raw500 checkpoint 作为当前 GPU0 full-rollout 对象，不把 seed/width 诊断升级为 formal 选择。

GPU1 seed18 训练 wall=`444.4755237370264 s`、peak GPU=`1584575488 bytes`；GPU2 hidden16 训练 wall=`442.9830682859756 s`、peak GPU=`2731527680 bytes`。两条 50-step 评估分别耗时 `962.0430630361661/915.1072924260516 s`。完整哈希和 per-step 曲线见 [`F3-REAL-GRAPH-RAW-SEED-CAPACITY-MATRIX-50STEP-2026-09-27.json`](F3-REAL-GRAPH-RAW-SEED-CAPACITY-MATRIX-50STEP-2026-09-27.json)。本次未修改生产 HDF5、registry、ledger 或分母，未启动 solver/worker/queue。
