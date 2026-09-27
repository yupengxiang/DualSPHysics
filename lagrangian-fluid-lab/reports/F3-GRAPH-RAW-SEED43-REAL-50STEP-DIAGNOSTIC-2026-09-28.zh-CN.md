# F3 `graph_raw` seed43 真实 50-step 独立诊断

结论：本次固定协议训练成功完成 `500/500`，evidence 为 `complete`，并生成已验证的 update-500 checkpoint。对 `F3_DEV_00_a0p903125` 的 autonomous diagnostic 完成 `50/50` 个 bounded 预测步且观测误差 finite；但完整注册分母仍是 `835 transitions / 836 frames`，本次只覆盖 `50/835 = 0.059880239520958084`。因此本记录明确为 `diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`credit=0`，不得把 50-step 窗口当作完整分母或 formal 资格。

## 固定协议

- manifest：`campaigns/core-v1/f3-dataset-v2.json`，`data-root=.`；文件 SHA-256：`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`。
- case：`F3_DEV_00_a0p903125`；源 HDF5 SHA-256：`8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`。
- 模型/随机性：`graph_raw`、seed `43`、hidden `8`、learning rate `0.001`。
- 训练：`500` updates、`256` centers/update、train-only normalization `16` transitions、`max_neighbors=192`。
- 评测：full chunk `34560`、`maximum-steps=50`、物理 GPU4（`CUDA_VISIBLE_DEVICES=4`），进程内 `cuda:0`。
- reader 的 canonical manifest binding SHA 为 `5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`；这是 reader 规范化后的绑定值，和原始 manifest 文件 SHA 分开记录。

## 训练校验

| 项目 | 结果 |
|---|---:|
| completed updates | `500/500` |
| evidence status | `complete` |
| checkpoint | `update=500`，verified |
| max neighbor truncation fraction | `0.0` |
| training wall（receipt） | `2220.8169346349314 s` |
| outer wall | `2260.69 s` |
| peak RSS | `3006.7890625 MiB` |
| peak GPU allocation | `1584764928 B` |
| checkpoint SHA-256 | `8c05ea0580af4f22622a095019a4c424a70b9e61259bdbf4e7244bc668d4ba29` |

## 评测分母与完成语义

| 项目 | 结果 |
|---|---:|
| bounded requested window | `50/50` steps，complete |
| finite observed prefix | `50/50` |
| registered transition denominator | `835` |
| registered frame denominator | `836`（含初始 frame） |
| evaluated transitions | `50` |
| raw error coverage | `0.059880239520958084` |
| full registered denominator complete | `false` |
| trajectory HDF5 | `51` frames（初始 frame + 50 个预测 frame） |
| future state inputs | `false` |
| failure category | `maximum_steps_limit`，first missing frame=`51` |

`maximum_steps_limit` 是本次有意设置的 bounded horizon 右删失，不是 model execution failure，也不是科学负结果。evaluate JSON 中的后续 `785` 个误差位置保持为缺失值；没有用零、最后状态或任何未来真实状态补齐分母。

## 原始指标表

| model | seed | updates | bounded steps | selection score | position RMSE step (m) | position RMSE frame mean (m) | velocity RMSE step (m/s) | velocity RMSE frame mean (m/s) | raw coverage |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `graph_raw` | 43 | 500 | 50 | `0.9403748199692692` | `0.006271187203975505` | `0.003812338938588208` | `0.03558410184597668` | `0.01272651200333618` | `50/835` |

补充指标：position overall executed-components RMSE=`0.004295971384298318 m`、ADE step=`0.005757743826224702 m`、FDE=`0.00981469653291758 m`；velocity overall executed-components RMSE=`0.015878290117600866 m/s`、ADE step=`0.020925575096921226 m/s`、FDE=`0.0576069431414888 m/s`。

## finite / mass / validity

- trajectory position 与 velocity 全部 finite；误差数组各有 `50` 个 finite 前缀和 `785` 个缺失尾部。
- `mass_error_abs_max_kg=0.0`，`changed_particle_mass_frames=0`。
- `validity_mismatch_frames=0`；初始和最后观测 frame 均为 `34560` 个 valid 粒子。
- physics diagnostic 完成 `50` 个观测 frame；wall chord 状态为 `checked_static_saved_chords`。这些检查只描述已观测 bounded 窗口，不提升 formal 资格。

## 失败分类、资格与分析结论

本次 contract failures 为空，训练和评测 launcher exit code 均为 `0`，并按 fail-closed 规则保留完整注册分母。唯一 failure category 是 `maximum_steps_limit`，对应 bounded 窗口的右删失。因没有完整 835-transition 评测，本结果不用于 formal model selection、qualification 或 credit。

关键发现：

1. 真实 F3 seed43 的 500-update `graph_raw` 训练和 checkpoint 证据链完整。
2. 50-step 观察窗内预测 finite，mass 与 validity 检查通过。
3. `50/835` 覆盖率不足以支持完整时域结论；不能将 `0.9403748199692692` 解释成完整分母 selection score。

若另行获得 gate 授权，下一实验应沿用同一 checkpoint、同一 835-transition/836-frame 注册分母完成 full-horizon evaluate；在此之前不应据本 bounded 诊断进行 formal 选择或积分 credit。本报告是单 seed 独立诊断，不计算跨 seed mean/std。

## 证据 SHA-256

- training JSON：`/tmp/f3-graph-raw500-seed43-20260928-gpu4-training.json` — `9e6adb62b7769a5ce0cce99892cb3a869c38d11218f42841e4df2f52cc56ac51`
- checkpoint：`/tmp/f3-graph-raw500-seed43-20260928-gpu4-checkpoint.pt` — `8c05ea0580af4f22622a095019a4c424a70b9e61259bdbf4e7244bc668d4ba29`
- evaluation JSON：`/tmp/f3-graph-raw500-seed43-20260928-gpu4-evaluation.json` — `ab6f198a432a08e6c71d3455885058f03ee79951e5747c1775247d70359f26f3`
- trajectory HDF5：`/tmp/f3-graph-raw500-seed43-20260928-gpu4-trajectory.h5` — `b277bc2b60c7532372651eb3a2f62be0c29997e4b26d25e02fd47ecb5e122d9d`
- training progress：`/tmp/f3-graph-raw500-seed43-20260928-gpu4-training-progress.json` — `fdca3c142269b8cd5356b870075bdbb9933ab9ef8713599e4736eac1449916e0`
- evaluation progress：`/tmp/f3-graph-raw500-seed43-20260928-gpu4-evaluation-progress.json` — `ffc779cdeaa52fa469d21700a131664348223659e582d5727f4b92305e26c846`
- training stdout：`/tmp/f3-graph-raw500-seed43-20260928-gpu4-training-stdout.log` — `f91b9b01cf5b0211b2549451c39228d69652873a89de4088334975a790e97d3f`
- evaluation stdout：`/tmp/f3-graph-raw500-seed43-20260928-gpu4-evaluation-stdout.log` — `47d633f86f7a3b5c6c18b4067390a08f5ef96cf48127b43cb7ef8a0d38b4c0bd`
- training resource log：`/tmp/f3-graph-raw500-seed43-20260928-gpu4-training-time.txt` — `ac04c72e2191606288d8fe3c1a0f7a5af0cd9d77fa3e2eef9b3c25764921208e`
- evaluation resource log：`/tmp/f3-graph-raw500-seed43-20260928-gpu4-evaluation-time.txt` — `f4d5febecf7dbb091f70d3f42b8ff7669f5d9f5effb6277b92b4b8f167f24102`

初次遗漏 `--device cuda:0` 的 CPU 启动在产生 training JSON/checkpoint 前已停止，不计入科学结果；修正后的训练与评测均为 exit `0`。生产算法、生产 HDF5、manifest、registry、ledger、denominator、gate 和 PLAN.md 均未修改。
