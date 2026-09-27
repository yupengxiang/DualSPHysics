# Core continuation status — 2026-09-28 — UPDATE-262

## F3 `graph_raw` train500 完整 835-transition rollout

本轮沿用当前 graph_raw 主方向、seed17/hidden8、center256、max_neighbors=192、full chunk=34560、GPU0 checkpoint，完成了真实 F3 test case 的完整 autonomous rollout。训练 `500/500`、evidence complete；评测执行 `835/835` transitions、836 frames，未发生 execution/nonfinite/reference/physics failure，`future_state_inputs=false`。

验收结果：

- HDF5 validator `passed=true`、`complete=true`、trajectory `836` frames / `835` transitions、`tail_frame_count=0`；
- metric summary `raw_error_coverage=1.0`、`selection_score=0.5127170375307817`；
- canonical evidence pack `passed=true`，但始终 `diagnostic_only=true`、`qualification_credit=0`。

| horizon | position RMSE | velocity RMSE |
|---:|---:|---:|
| step 50 | 0.010809 m | 0.050800 m/s |
| step 200 | 0.103640 m | 0.124895 m/s |
| step 400 | 0.502160 m | 0.853872 m/s |
| step 600 | 1.448731 m | 2.799018 m/s |
| step 835 | 7.024502 m | 14.443016 m/s |
| frame mean | 1.237837 m | 2.453439 m/s |

结论：这是“执行完整但科学质量不通过”的负结果。误差在长时域显著增长，50-step 的短窗结果不能外推为完整窗口质量；当前 graph_raw train500 checkpoint 不升级为 formal candidate，不计 F3 T1/T2 或 9-run formal training credit。保留完整失败/失稳证据，不放宽 gate、不修改 registry/ledger/denominator。

本轮没有修改生产算法、生产 HDF5、registry、ledger、denominator 或 gate，也没有启动 solver/worker/queue。机器回执见 [full rollout receipt](F3-REAL-GRAPH-RAW-TRAIN500-FULL-ROLLOUT-2026-09-28.json)。
