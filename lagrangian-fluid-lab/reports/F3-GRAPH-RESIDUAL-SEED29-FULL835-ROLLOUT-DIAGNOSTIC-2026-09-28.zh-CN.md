# F3 graph_residual seed29 full835 rollout diagnostic（2026-09-28）

本报告记录 seed29、graph_residual、hidden=8、max_neighbors=192 checkpoint 在 F3_DEV_00_a0p903125 上的独立 autonomous full-horizon 诊断。结果明确为 diagnostic-only，不产生正式资格、T1/T2 或 gate credit。

## 执行与证据

- GPU：CUDA_VISIBLE_DEVICES=7，物理 GPU7，进程内 device=cuda:0；显存峰值未超过约 3 GiB，未发生 OOM。
- checkpoint：/tmp/f3-graph-residual500-seed29-20260928-checkpoint.pt。
- checkpoint SHA256：c037455244ac1ffdd6908908eaf76b3b66e3ec5baaa63d8b9107641248e10287；101,613 bytes。
- checkpoint 与既有 seed29 bounded diagnostic 报告一致；既有训练证据为 500/500 updates、evidence complete、checkpoint verified。
- graph residual prior：17,280,000 rows，finite=true，history complete=true，neighbor truncation fraction=0。
- rollout elapsed：7266.3929549369495 s；source time 从 0.0 s 到 8.350012828223477 s。

执行命令使用项目锁定环境中的 scripts/core_learning.py evaluate，maximum-steps=835、chunk-size=34560、diagnostic、autonomous。完整命令和所有 receipt 的 SHA256 记录在同名机器 JSON 报告中。

## 完整分母与 HDF5 validator

- 注册分母：835 transitions / 836 trajectory frames。
- 实际执行：835 transitions / 836 frames；full registered denominator complete=true；raw error coverage=1.0。
- HDF5 validator：passed=true、complete=true、fail_closed=false、synthetic_only=false。
- validator 检查：case binding、completion semantics、shape、time、valid 均通过；tail_frame_count=0。
- 实际 future_state_inputs=false；validator 的 future-state 检查也通过。
- finite_rollout_complete=true，evaluation execution_complete=true，failure_category=null。

## 关键数值

| 指标 | 数值 |
| --- | ---: |
| selection score | 0.8109931765474838 |
| raw position RMSE frame mean | 267123337.05506775 m |
| raw velocity RMSE frame mean | 922219095.7834071 m/s |
| step 50 position RMSE | 0.011656636805092279 m |
| step 50 velocity RMSE | 0.06257107137184988 m/s |
| step 835 position RMSE | 7493844929.4207 m |
| step 835 velocity RMSE | 25504582423.440575 m/s |
| position ADE / FDE | 155111783.85571146 m / 4351486800.072421 m |
| velocity ADE / FDE | 535509375.920749 m/s / 14809867948.895292 m/s |
| maximum kinetic-energy error | 1.422607942588272e+22 J |
| maximum absolute mass error | 0.0 kg |
| changed-particle-mass frames | 0 |
| validity-mismatch frames | 0 |

轨迹在数值上保持 finite，质量守恒和 valid closure 通过；但从 step 50 到 step 835 发生显著长时域发散。因此不能把 bounded 的短时误差外推为 full-horizon 可靠性。

## 正式状态与副作用边界

- formal_eligible=false
- T1_numerical=false
- T2_macro=false
- qualification=false
- qualification_credit=0
- credit=0
- diagnostic_only=true

本次只读生产数据和 checkpoint，未修改 production HDF5、源码、manifest、registry、ledger、denominator 或 gate；没有产生任何正式资格 credit。

报告 receipt：

- 机器报告：F3-GRAPH-RESIDUAL-SEED29-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json
- evaluation：/tmp/f3-graph-residual500-seed29-full835-20260928-evaluation.json
- progress：/tmp/f3-graph-residual500-seed29-full835-20260928-evaluation-progress.json
- trajectory：/tmp/f3-graph-residual500-seed29-full835-20260928-trajectory.h5
- HDF5 validation：/tmp/f3-graph-residual500-seed29-full835-20260928-hdf5-validation.json
