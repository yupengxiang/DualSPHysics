# F3 `graph_raw` hidden16 独立 50-step 诊断

本次独立诊断已完成：`graph_raw` 在 GPU7（进程内 `cuda:0`）完成 `500/500` 更新训练，并从最终 checkpoint 对 canonical F3 test case `F3_DEV_00_a0p903125` 完成 `50/50` 帧的 bounded autonomous evaluation。结果严格属于 diagnostic-only 证据，不是 formal、T1/T2 或 qualification 结果。

## 结论

- 完整登记分母保持为 `835` transitions（`836` 状态帧）；本次只请求并执行前 `50` transitions，未缩小分母。
- raw error coverage 为 `50/835 = 0.059880239520958084`；`finite_prefix_frames=50`，剩余 `785` transitions 明确保留为缺失/未执行。`failure_category=maximum_steps_limit`、`first_failure_frame=51` 表示受限窗口右删失，不是模型执行错误。
- 受限窗口内 position、velocity、mass 均 finite；`future_state_inputs=false`。trajectory 的 `valid` 为 `1,762,560/1,762,560` 全 true；physics audit 的 `mass_error_abs_max_kg=0.0`、`changed_particle_mass_frames=0`、`validity_mismatch_frames=0`。
- 短窗口 horizon 指标随步数增长：step 50 position RMSE=`0.011604879613374489 m`，velocity RMSE=`0.051947402727045934 m/s`；这不能外推为完整 835-transition 质量。
- `qualification=false`、`formal_eligible=false`、`qualification_credit=0`；没有修改源码、PLAN.md、正式 manifest、registry、ledger、denominator 或 gate。

## 冻结协议

- manifest：`campaigns/core-v1/f3-dataset-v2.json`；`data-root=.`；case：`F3_DEV_00_a0p903125`（F3、test、34,560 particles）。本次采用该 canonical test case，使 `835-transition` 固定分母与诊断一一对应，未将其余 test case 混入本 receipt。
- 模型：`graph_raw`，seed `17`，updates `500`，centers/update `256`，hidden `16`，learning rate `0.001`，normalization transitions `16`，`max-neighbors=192`。
- 训练：`CUDA_VISIBLE_DEVICES=7`，进程内 device `cuda:0`；训练 receipt `evidence_status=complete`、checkpoint `checkpoint_verified=true`。
- 评测：`split=test`、`chunk-size=34560`、`maximum-steps=50`、`--diagnostic`；autonomous rollout 使用公开 known inputs，禁止未来 reference state 输入。
- 所有运行产物使用唯一前缀：`/tmp/f3-graph-raw500-hidden16-seed17-20260928-*`。

## 训练结果

训练完成 `500/500`，wall=`2226.891103646951 s`，参数量 `6086`，peak GPU allocator=`2731527680 B`，peak RSS=`2696.68359375 MiB`。最终 progress 的 loss MSE 为 `0.07728372514247894`，neighbor truncation fraction 为 `0.0`。归一化证据确认仅从 train split 的 16 个 evenly-spaced transitions 计算；未使用 validation/test state 做 normalization。

最终 checkpoint：`151761` bytes，SHA-256=`27664b90e7cd272e584badbdecf782a015974ef1c2306c7b62ae137e2e613009`。

## 完整 835-transition 分母与完整性核对

| 项目 | 结果 |
|---|---:|
| 固定登记分母 | 835 transitions / 836 frames |
| bounded 执行帧 | 50 / 835 |
| finite prefix | 50 / 835 |
| raw error coverage | 0.059880239520958084 |
| 未执行/显式缺失 transitions | 785 |
| full-denominator complete | `false`（受限窗口预期） |
| requested 50-step window | `50/50` executed 且 finite |
| future state inputs | `false` |
| selection score（固定分母、缺失帧 penalty） | 0.9405503692824372 |

`core.evaluation.v1` 的 `finite_summary.all_registered_rollouts_finite=false` 是因为完整 835 分母中的后 785 帧被本次 `maximum_steps=50` 有意保留为 null；它不否定已执行 50 帧的 finite completion。

## finite / mass / validity

trajectory HDF5 含初始帧共 `51` 帧，position/velocity shape 均为 `(51, 34560, 3)`，valid shape 为 `(51, 34560)`，mass shape 为 `(34560,)`。检查结果如下：

- position finite：`true`；velocity finite：`true`；mass finite：`true`。
- valid true：`1,762,560/1,762,560`，全 true；trajectory 属性 `future_state_inputs=false`、`autonomous_prediction=true`。
- physics completed frames：`50/835`。
- `mass_error_abs_max_kg=0.0`；`changed_particle_mass_frames=0`。
- `validity_mismatch_frames=0`。
- wall chord 仅报告为 `checked_static_saved_chords`，不构成物理有效性/qualification 结论。

## position / velocity horizon

| horizon | position RMSE (m) | velocity RMSE (m/s) | position ADE (m) | velocity ADE (m/s) |
|---:|---:|---:|---:|---:|
| 1 | 0.00023158026137009321 | 0.0013297703906640834 | 0.0003424582581001611 | 0.0017556166154571663 |
| 10 | 0.0021386975604253794 | 0.006339813839870371 | 0.0030667119824534924 | 0.010190714830966114 |
| 20 | 0.004718027282869291 | 0.014350590917892944 | 0.006763293422278177 | 0.023165795765621264 |
| 30 | 0.00733903669851623 | 0.02586125509669936 | 0.010656971042070376 | 0.04229129826661949 |
| 40 | 0.00946752958718625 | 0.039117717169527465 | 0.014189144208917941 | 0.06404273735676645 |
| 50 | 0.011604879613374489 | 0.051947402727045934 | 0.0179227267060898 | 0.08367056074295147 |

已执行窗口的 aggregate scalars：position RMSE=`0.00693668239432838 m`、velocity RMSE=`0.027747110513398583 m/s`；frame-mean position/velocity RMSE 分别为 `0.006010279237741596 m` 与 `0.022892113973957358 m/s`；末帧 FDE/ADE 记录分别为 position=`0.0179227267060898 m`、velocity=`0.08367056074295147 m/s`。这些均是 50-step bounded diagnostic 指标。

## 完整性与副作用

运行前后保持生产输入与治理文件只读：未修改 `scripts/`、`PLAN.md`、`campaigns/core-v1/f3-dataset-v2.json`、registry、ledger、denominator、production HDF5 或 gate；未终止其他进程。该 receipt 不授予任何 qualification credit，也不启动 full-horizon 或 formal follow-up。

machine receipt：[CORE-F3-GRAPH-RAW-HIDDEN16-DIAGNOSTIC-2026-09-28.json](CORE-F3-GRAPH-RAW-HIDDEN16-DIAGNOSTIC-2026-09-28.json)。

## SHA-256

- manifest 文件：`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`
- reader manifest：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`
- manifest 声明 source manifest：`86e27740d764f9769e3255a82a599013a282f1bc4385ad3c29a657a56d9c5bea`
- case HDF5：`8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`
- known inputs：`089573de6d2c7633b5192bf626fa98eb941f79500f1c1a04b632af68b6ca3bc9`
- training receipt：`fc57ee863e86f8c88a0503ddf1149db973a236cd147f38a84ee68b20240020e7`
- training progress：`a4e830756ea77adff7e8743f0e89165d88d8f854dbd6cf849359169cdf7bdc81`
- checkpoint：`27664b90e7cd272e584badbdecf782a015974ef1c2306c7b62ae137e2e613009`
- evaluation receipt：`887b0b587e757ff5c45a2b93d8ad1744f3cbbd4e3a842c9cd6c923b5650cab27`
- evaluation progress：`381034b07c16aa8f30f139c6329ab823912e824c90a48e95bb7bd5236dc168f6`
- trajectory HDF5：`4f6032935ea10330aafdefa6e90c134394d4dd1406c35088ad47a183f9e2eeae`
- train log：`b3afb582f1fc50bdf9770e5f14cb8384da967b2d95954ad986bb1650398032ff`
- evaluate log：`5f5aba83c76be08795fb81dc9731c2dd9810e2bcd733affa445730c50db2597c`

> 注：known inputs 的完整 SHA-256、control/geometry SHA-256、source audit/prepared SHA-256 保存在同名 JSON receipt；receipt 是机器校验的权威记录。
