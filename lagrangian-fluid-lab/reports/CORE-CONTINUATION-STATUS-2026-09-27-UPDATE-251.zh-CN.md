# Core continuation status — 2026-09-27 — UPDATE-251

## F3 real graph checkpoint → rollout → unified scoring canary

使用 UPDATE-249 的真实 F3 `graph_raw`/seed 17/cap 192 checkpoint，在 `F3_DEV_00_a0p903125` test case 上完成 10-step autonomous rollout：10/10 帧执行、finite、无未来 reference state 输入；trajectory HDF5 与 rollout receipt 均已绑定哈希。随后通过统一 `evaluate --diagnostic --maximum-steps 10` 接入评分，checkpoint cap 自动从绑定 config 恢复为 192，未允许 caller 覆写。

评分明确标记为短窗 incomplete：完整 case 有 835 transitions，本次只执行 10，failure category=`maximum_steps_limit`，finite prefix=`10`、raw error coverage=`0.011976047904191617`、complete=`false`。模型误差是明显的有效负结果：position RMSE 从 `5.557858646830076e-06 m` 增长到 `4926.302828693858 m`，velocity RMSE 从 `0.0011530185610307535 m/s` 增长到 `1586745.7896445652 m/s`；短窗 selection score=`0.9944103861222086` 不能被解释为完整案例质量或资格通过。详见 [`F3-REAL-GRAPH-ROLLOUT-EVALUATION-CANARY-2026-09-27.json`](F3-REAL-GRAPH-ROLLOUT-EVALUATION-CANARY-2026-09-27.json)。

该结果闭合了真实 F3 的 checkpoint→autonomous rollout→scoring 粗链路，并保留模型发散这一 benchmark 负结果；没有写入正式 registry/ledger/分母、没有 T1/T2/credit，生产 HDF5 与 solver/worker/GPU/queue 未触碰。
