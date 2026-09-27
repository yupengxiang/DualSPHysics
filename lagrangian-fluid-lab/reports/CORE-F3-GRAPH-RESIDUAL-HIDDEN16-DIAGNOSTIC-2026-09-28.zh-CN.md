# F3 graph_residual hidden16 独立真实数据诊断（2026-09-28）

本次运行已完成，但结论严格保持为 bounded diagnostic-only：没有 formal eligibility、T1/T2 qualification 或 qualification credit。训练使用 F3 v2 registered numerical data；evaluation 只使用同一 checkpoint 对 `F3_DEV_00_a0p903125` 做 autonomous 50-step 受限窗口，没有未来状态输入。

## 运行绑定

- 物理 GPU：GPU6；`CUDA_VISIBLE_DEVICES=6`，进程内设备 `cuda:0`。
- run-id：`f3-graph-residual500-hidden16-seed17-20260928`。
- 模型：`graph_residual`，seed=`17`，updates=`500/500`，centers/update=`256`，hidden=`16`，learning rate=`0.001`，normalization transitions=`16/16`，`max_neighbors=192`。
- 训练使用 train split 统计量；residual prior 证据为 finite，`execution_calls=500`，邻居截断比例最大值为 `0.0`。
- 训练 wall=`2226.560415918041 s`，峰值 GPU 显存=`2731527680 B`，峰值 RSS=`3003.5625 MiB`。
- 训练 checkpoint、training JSON、progress、evaluation JSON、evaluation progress 和 trajectory HDF5 的 SHA-256 见[同名 JSON receipt](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/CORE-F3-GRAPH-RESIDUAL-HIDDEN16-DIAGNOSTIC-2026-09-28.json)。

## coverage 与因果输入

evaluation 窗口完成 `50/50` 帧且全部有限；固定 registered 分母仍为 `835` transitions，因此 raw error coverage 为 `50/835 = 0.059880239520958084`。`failure_category=maximum_steps_limit` 只是窗口右删失：请求窗口完成，但完整 registered denominator 未完成，不能把本次结果当作 full-horizon pass。

`future_state_inputs=false` 同时由 evaluation receipt、progress 和 HDF5 属性证明；trajectory 使用 `core.state.native_velocity.v1`，位置/速度数组为 `[51, 34560, 3]`，包含初始帧，未读取未来 fluid state。

## mass / validity 核对

在已执行的 50 个 transitions 内：

- active particle count 始终为 `34560`，active mass 始终为 `14.580000378191471 kg`；`mass_error_abs_max_kg=0.0`。
- `changed_particle_mass_frames=0`，`validity_mismatch_frames=0`；HDF5 的 51 个状态帧全部 `valid=true`，全部位置/速度/时间/质量值有限。
- saved-chord wall diagnostic 报告累计 `760` 个 particle hits、`0.3206250083167106 kg`；其语义是有限保存步 chord 相交检查，不是连续路径或 qualification gate。

因此，这个 bounded 窗口没有质量漂移、validity mismatch 或非有限状态；这只说明执行/状态完整性在 50 steps 内成立，不等同于物理材料资格。

## position / velocity horizon metrics

以下数值直接来自 evaluation JSON 的有限前缀，单位分别为 m 和 m/s；ADE 为对应 horizon 的 absolute displacement/velocity error。

| step | position RMSE (m) | velocity RMSE (m/s) | position ADE (m) | velocity ADE (m/s) |
|---:|---:|---:|---:|---:|
| 1 | 0.000021445457 | 0.0015505842167 | 0.0000356898834 | 0.0019910189308 |
| 10 | 0.0004169994682 | 0.0072587685580 | 0.0006359960700 | 0.0107549918113 |
| 20 | 0.0015442696598 | 0.0151418304723 | 0.0023657580890 | 0.0228186839110 |
| 30 | 0.0034428930755 | 0.0222580021862 | 0.0052568152727 | 0.0330233873956 |
| 40 | 0.0058082220236 | 0.0289817784471 | 0.0086205789729 | 0.0422569130963 |
| 50 | 0.0086232514781 | 0.0423089802992 | 0.0124877273050 | 0.0635481739338 |

50-step finite-prefix frame mean 为 position RMSE=`0.003139114574614788 m`、velocity RMSE=`0.019193303511781955 m/s`；fixed-denominator selection score（包含未执行的后续 785 帧 penalty）为 `0.940417584783162`。step-50 FDE 分别为 `0.012487727304967998 m` 和 `0.06354817393378795 m/s`。

## 独立诊断结论

该 `graph_residual`, hidden=`16` 运行在 50-step bounded 窗口内可执行、有限、无未来状态输入，且 mass/validity 完整性检查为零 mismatch；位置和速度误差随 horizon 增长，完整 835-transition 分母未覆盖。结论因此是：保留为独立诊断证据，`formal_eligible=false`、`T1_numerical=false`、`T2_macro=false`、`qualification_credit=0`；不得据此更新 formal candidate、registry、ledger、denominator 或 gate。

原始临时产物均在 `/tmp/f3-graph-residual500-hidden16-seed17-20260928-*`；本报告及 receipt 是本任务唯一新增的仓库文件。
