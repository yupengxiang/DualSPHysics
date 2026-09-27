# F3 graph_raw seed29 真实 50-step 独立诊断

本次独立 F3 诊断已完成：`graph_raw`、seed `29` 从零训练 `500/500` updates，并在真实案例 `F3_DEV_00_a0p903125` 上以 `maximum-steps=50` 完成 bounded autonomous evaluate `50/50`。结果仅属于 diagnostic evidence：`diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`qualification_credit=0`；不产生 T1/T2 或 formal credit。

## 固定协议

- manifest：`campaigns/core-v1/f3-dataset-v2.json`，`data-root=.`，案例 `F3_DEV_00_a0p903125`。
- 模型：`graph_raw`，seed `29`，updates `500`，centers/update `256`，hidden `8`，learning rate `0.001`。
- normalization transitions `16`，`max-neighbors=192`，full chunk `34560`。
- 物理 GPU：`CUDA_VISIBLE_DEVICES=5`，进程内设备 `cuda:0`，型号 NVIDIA RTX 6000 Ada Generation。
- 评测：test split、`maximum-steps=50`、`--diagnostic`、autonomous、`future_state_inputs=false`。
- 训练、评测、checkpoint、progress、log、trajectory 均使用唯一前缀 `/tmp/f3-graph-raw500-seed29-20260928-*`。

## 完成状态与完整分母

训练 receipt 报告 `completed_updates=500`、`evidence_status=complete`、`checkpoint_verified=true`，checkpoint update=`500`；独立 SHA 校验通过。训练 wall 为 `2197.0679090509657 s`，精确 peak RSS 为 `3009.578125 MiB`，PyTorch allocator peak GPU memory 为 `1599798272 B`（`1525.6865234375 MiB`）。

评测 progress 报告 bounded 请求窗口 `50/50`、`execution_complete=true`、`finite_rollout_complete=true`，wall 为 `952.6699718039017 s`。但登记的完整分母仍固定为 **835 transitions / 836 trajectory frames**：evaluation receipt 的 `full_registered_denominator_complete=false`、`full_registered_finite_rollout_complete=false`，raw error coverage 只有 `50/835=0.059880239520958084`。因此 `failure_category=maximum_steps_limit`、`first_failure_frame=51` 只表示 bounded 窗口的正常右删失，不是模型执行错误，也没有缩小、改写或替代完整分母。

trajectory HDF5 按 bounded 协议仅含初始状态在内的 `51` 帧，形状为 position/velocity `[51, 34560, 3]`、valid `[51, 34560]`、time `[51]`；这不是登记的 `[836, 34560, ...]` 完整轨迹。已执行前缀的 position、velocity、time 全部 finite，`valid_true_count=1762560`，`future_state_inputs=false`。

## 原始指标表

| step | position RMSE (m) | velocity RMSE (m/s) |
|---:|---:|---:|
| 1 | 0.00013167273554621684 | 0.0012660324566573442 |
| 10 | 0.0014673441792391433 | 0.0025437760277958656 |
| 20 | 0.0035649070125166075 | 0.003948135082537215 |
| 30 | 0.005695038178226528 | 0.007620330373120689 |
| 40 | 0.006398257962484392 | 0.019190777218135894 |
| 50 | 0.006190025948475731 | 0.035656176158284106 |

selection score 为 `0.9403616578271421`。执行帧平均 position/velocity RMSE 分别为 `0.004094388887656441 m` 与 `0.010489062408158958 m/s`；执行帧 scalar RMSE 分别为 `0.004637182907221926 m` 与 `0.014504640925943115 m/s`。step 50 的 position/velocity ADE（也是最后执行帧 FDE）分别为 `0.008657046060485306 m` 与 `0.054067072515159825 m/s`。

已执行的 50 frames 上，physics 诊断为 `mass_error_abs_max_kg=0.0`、`validity_mismatch_frames=0`、`changed_particle_mass_frames=0`；kinetic-energy error absolute max 为 `0.03804619808080111 J`。wall chord 状态为 `checked_static_saved_chords`，涉及 `1008` 个粒子、质量 `0.4252500110305846 kg`。这些是 bounded prefix 的完整性结果，不构成 full-horizon scientific qualification；`scientific_status=not_assessed`。

## 分析结论

1. 训练链路完整：`500/500`、`evidence complete`、checkpoint update=`500` 且 SHA 已重新校验；训练没有 resume，也没有邻居截断。
2. bounded 50-step 窗口执行完整且 finite，但完整登记分母未完成；短窗指标不能外推为 835-transition 的长时域质量。
3. position RMSE 在 step 50 为 `0.006190025948475731 m`，velocity RMSE 在 step 50 为 `0.035656176158284106 m/s`；这些只作为本次 diagnostic 的 bounded 指标保留。
4. bounded prefix 的 mass/validity 检查通过，但 scientific status 仍为 `not_assessed`；这不改变 formal 或 qualification 判定。
5. 本报告明确 `qualification=false`、`formal_eligible=false`、`qualification_credit=0`，不启动任何 gate、registry、ledger 或 denominator 变更。

没有自动 follow-up 或 gate action。如需解释长时域稳定性，必须另行授权并执行保持 `835-transition/836-frame` 分母的 full-horizon 评测；本报告不提供该授权。

## 资源与 side effects

训练 receipt 的精确 peak GPU allocator 为 `1599798272 B`，peak RSS 为 `3009.578125 MiB`。评测 CLI 会写出 wall progress，但不输出进程 peak RSS/GPU allocator 字段；运行期间 live sample 的 GPU5 `memory.used` 最大观测为 `3049 MiB`，`ps` RSS 最大观测为 `3399168 KiB`（`3319.5 MiB`），这些采样值不冒充进程报告的 peak。评测结束后 GPU5 为 `18 MiB`。

两次训练前 shell wrapper 错误的原始文本已保留在 machine JSON：`zsh:31: command not found: tee` 与 `zsh:12: command not found: env`。两次均在 Python 实验进程启动前发生，分类为 launcher-only；最终运行改用可解析的 `/usr/bin/tee` 与 shell 变量赋值，没有绕过任何 gate，也没有覆盖科学产物。

本次没有修改 production algorithm、production HDF5、manifest、registry、ledger、denominator、gate 或 `PLAN.md`；side effects 中对应 mutation 均为 `false/0`。

## SHA-256

- source verify：`e0d91dae287e0e43bb11fa1a6726da98ef4e729f79e7f6944b42ece417fffc18`
- manifest 文件：`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`
- manifest 声明的 source manifest：`86e27740d764f9769e3255a82a599013a282f1bc4385ad3c29a657a56d9c5bea`
- reader manifest：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`
- case HDF5：`8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`
- known inputs：`089573de6d2c7633b5192bf626fa98eb941f79500f1c1a04b632af68b6ca3bc9`
- control input：`f6852502c7ae5ad7da14faa2dddf3da04e5f02757528e38f3e8c140c00f6389e`
- geometry input：`d7ccdc43108fde81c71f1ef6483258e6b0fa2a3bc9561df063b87a580bc55d70`
- training receipt：`6ff3e753baf3163cfabe1cde49e0c8e06182b5aa861f45b2ec289f5a1bdfc2da`
- checkpoint：`c675c1915f05a18df3752b2320c076404015e916dc860f76de1e4d20479dabe5`
- training progress：`7f77360e51c022214bbe09915e04a3fe38830175077a3ddb58e88280444b1097`
- evaluation receipt：`d8faa87981def753b113432c4ee1d6b25722ac323cab0228ff9a41f40111ffe3`
- evaluation progress：`f3808242be02d538032db3bcd8b4daee058851e931ca26ebf92673bd124218b3`
- trajectory：`80fa5c9a86fa9bae514ffc77f57b137502b61f8d22783366111f29cb888b528c`
- run log：`5b654cc363d38d473aab5cbe672cec66324245e93698b33c30a00a53a0370259`

machine summary：[F3-GRAPH-RAW-SEED29-REAL-50STEP-DIAGNOSTIC-2026-09-28.json](F3-GRAPH-RAW-SEED29-REAL-50STEP-DIAGNOSTIC-2026-09-28.json)。
