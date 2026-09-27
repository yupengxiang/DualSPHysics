# Core continuation status — 2026-09-27 — UPDATE-255

## F3 100-update checkpoint 的 50-step 长窗诊断

继续使用 UPDATE-254 的真实 F3 `graph_raw` checkpoint（seed 17、100 updates、hidden 8、center 256、`max_neighbors=192`），在固定 test case `F3_DEV_00_a0p903125` 上用 full-chunk `34560` 做 50-step GPU autonomous evaluate。50/50 个请求步均 finite/executed，未出现 provenance、nonfinite 或 model execution failure；wall=`952.831371658016 s`，trajectory 为 51 帧（含初始帧）。

不过完整注册分母仍是 835 transitions，receipt 必须标记 `maximum_steps_limit`、`complete=false`，raw coverage=`0.059880239520958084`。误差随 rollout 增长：position RMSE 从 `0.000164 m`（step 1）升至 `0.013675 m`（step 50），velocity RMSE 从 `0.001830 m/s` 升至 `0.100115 m/s`，selection score=`0.9407240030483476`。因此结论是“50 步内数值有限，但长时域误差明显增长”，不能外推为完整 case 质量或 T1。

receipt 见 [`F3-REAL-GRAPH-TRAIN100-EVALUATION50-CANARY-2026-09-27.json`](F3-REAL-GRAPH-TRAIN100-EVALUATION50-CANARY-2026-09-27.json)。本次仍为 diagnostic-only，不计 formal training、T1/T2 或 credit；未修改生产 HDF5、registry、ledger 和分母，未启动 solver/worker/queue。下一步应优先改善训练/模型的长时域误差，再考虑昂贵的 835-transition 全窗口。
