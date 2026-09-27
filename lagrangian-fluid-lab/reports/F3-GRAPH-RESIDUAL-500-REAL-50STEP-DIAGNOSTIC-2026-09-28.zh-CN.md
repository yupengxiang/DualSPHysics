# F3 graph_residual 500-update 真实 50-step 独立诊断

本次独立诊断严格使用 `CUDA_VISIBLE_DEVICES=4`，进程内设备为 `cuda:0`。训练完成 `500/500` updates，评测完成请求窗口 `50/50` 帧；完整登记分母为 `835` transitions，因此 `maximum_steps_limit` 是有意的 bounded 右删失，不是运行错误，也不构成完整 case qualification。

结论保持 diagnostic-only：`future_state_inputs=false`，`qualification=false`，`T1_numerical=false`、`T2_macro=false`、`formal_eligible=false`、`qualification_credit=0`。没有修改源码、manifest、registry、ledger、denominator、gate 或 `PLAN.md`。

## 协议与完成证据

- manifest：`campaigns/core-v1/f3-dataset-v2.json`，SHA-256=`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`；reader manifest SHA=`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`。
- case：`F3_DEV_00_a0p903125`，test split，34560 粒子，835 transitions；case HDF5 SHA-256=`8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`。
- 模型协议：`graph_residual`、seed `17`、500 updates、256 centers/update、hidden `8`、lr `0.001`、normalization transitions `16`、`max_neighbors=192`、`cuda:0`。
- 训练：`evidence_status=complete`，wall=`2251.8673923660535 s`，checkpoint `update=500`，progress `status=completed`。
- 评测：`--maximum-steps 50 --diagnostic`，最终采用全场 `chunk_size=34560`；50 帧均执行且 finite，trajectory 含初始帧共 51 帧。

## 指标

| 指标 | 结果 |
|---|---:|
| selection score | 0.9404577573694052 |
| position RMSE（step 50） | 0.010426218230156332 m |
| position RMSE（50 帧 frame mean） | 0.00336599805328606 m |
| velocity RMSE（step 50） | 0.0529934419010521 m/s |
| velocity RMSE（50 帧 frame mean） | 0.022431113817225744 m/s |
| position ADE（50 帧） | 0.005026568070279438 m |
| velocity ADE（50 帧） | 0.0343493933094577 m/s |
| raw error coverage | 0.059880239520958084 |
| physics mass error max | 0.0 kg |
| physics kinetic-energy error max | 0.09097669418640647 J |

训练 residual prior 执行 `500` 次、共 `17280000` rows，finite 且 history complete；邻居截断比例为 `0.0`。训练 receipt 给出的峰值显存为 `1567362048 B`（1494.7529296875 MiB，PyTorch allocator），峰值 RSS=`3013.0234375 MiB`；外部 `nvidia-smi` 采样最大显存为 `4763 MiB`。

评测 wall=`1042.9566028309055 s`。评测 CLI 不输出 allocator/RSS 峰值；外部采样最大值为显存 `3049 MiB`、RSS `3087.72265625 MiB`，已明确标注为 sampled 而非 receipt-native peak。

trajectory 完整性核验通过：position `(51,34560,3)`、velocity `(51,34560,3)`、valid `(51,34560)`、time `(51,)`；位置、速度、mass 全 finite，valid 全为 true，粒子 ID 唯一，HDF5 attribute `future_state_inputs=false`。

## SHA-256 证据索引

所有运行产物均使用唯一前缀 `/tmp/f3-graph-residual500-seed17-20260928-`：

- training JSON：`b723653b5e9fafb0847064363eb11685141c2d24ef696dfff8df22bebf13bfc2`
- checkpoint：`1f64ebd53eb794d87562a87c43a37db4ac8b8f7e2f3b1cc994a6a7baf448eb96`
- training progress：`8ecc00de68109ec02731275411ad04969c5787c53aa32d5b99b61865eba5902f`
- train log：`711851ffdba14a56d459412afbae0f4771d38c3b64eaf5b7fad2d8b70357a18d`
- evaluation JSON：`fe9cd31863a4cf532edad6a7b19f1d8e49abd16c9bd07bcf5ee804836c39e865`
- trajectory HDF5：`d0c24031082399d9e02fb2b06b27a2ae7cbf8130b0996ab299f7f83e98ed3815`
- evaluation progress：`8b976cebe55e6d6136264f2906bdd93cd3672104b4343c250d5855d223850728`
- evaluate log：`d98bdaa17df599345c887536aec9914a7ac0e4ccbe9386ed9585459ec882126e`

machine summary：[F3-GRAPH-RESIDUAL-500-REAL-50STEP-DIAGNOSTIC-2026-09-28.json](F3-GRAPH-RESIDUAL-500-REAL-50STEP-DIAGNOSTIC-2026-09-28.json)。本报告仅记录独立诊断证据，不授予 qualification，不追加 `PLAN.md` 索引。
