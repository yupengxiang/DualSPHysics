# Core continuation status — 2026-09-27 — UPDATE-256

## F3 500-update 续训与 50-step 配对评估

从 UPDATE-254 的 100-update checkpoint 恢复，在完全相同的真实 F3 数据、seed 17、`graph_raw`、hidden 8、center 256、`max_neighbors=192` 和 train-only normalization 下继续到 500 updates。`500/500` 完成，evidence complete，邻居截断始终为 0；续训 wall=`1888.7126551880501 s`，peak RSS=`2703.7109375 MiB`，peak GPU memory=`1566300160 bytes`。

对同一 test case、同一 chunk=34560、同一 GPU 配置做 50-step autonomous diagnostic：50/50 finite/executed，无 provenance、nonfinite 或 model execution failure。完整 835-transition 分母仍按 `maximum_steps_limit` 标记 `complete=false`，raw coverage=`0.059880239520958084`，selection score=`0.9405794502120072`。

训练量增加带来混合结果：step50 position RMSE 从 update100 的 `0.013675 m` 降至 `0.010809 m`，velocity RMSE 从 `0.100115` 降至 `0.050800 m/s`；但 position 全窗口均值从 `0.005367` 升至 `0.006482 m`，selection score 基本不变。因此不能据此宣称长时域质量已解决，下一步应比较模型/损失或训练采样策略，而非单纯继续堆 update。

完整 receipt 见 [`F3-REAL-GRAPH-TRAIN500-EVALUATION50-CANARY-2026-09-27.json`](F3-REAL-GRAPH-TRAIN500-EVALUATION50-CANARY-2026-09-27.json)。本次仍为 diagnostic-only，不计 formal training、T1/T2 或 credit；未修改生产 HDF5、registry、ledger 和分母，未启动 solver/worker/queue。
