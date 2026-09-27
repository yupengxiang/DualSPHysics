# F3 MLP seed43 full835 长时域诊断报告

本报告记录 `F3_DEV_00_a0p903125` 在已验证的 MLP seed43 / hidden8 checkpoint 上进行的完整 autonomous diagnostic rollout。该结果仅用于诊断，不是 formal release、T1/T2 qualification 或生产数据资产。

## 执行闭合

- GPU：物理 GPU0，进程设备 `cuda:0`，`CUDA_VISIBLE_DEVICES=0`。
- checkpoint：`/tmp/f3-mlp500-seed43-20260928-checkpoint.pt`，SHA-256 `c2aab25a554c460dfccce9440298a27e7f1f31f4e4d43e5909761f0ede5a5dbb`；与既有 seed43 50-step 报告一致。
- rollout：835/835 transitions，836/836 frames，完整注册分母闭合，`future_state_inputs=false`。
- evaluation：`failure_category=null`，`finite_rollout_complete=true`，scientific status 为 `not_assessed`。
- HDF5 validator：`passed=true`、`complete=true`、`tail_frame_count=0`；trajectory 形状为 `[836, 34560, 3]`（position/velocity）。
- active position、velocity、mass、time 全部 finite；mass error 最大绝对值为 `0 kg`，validity mismatch 为 `0`。

执行命令：

```text
PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES=0 ./.venv/bin/python scripts/core_learning.py evaluate --manifest campaigns/core-v1/f3-dataset-v2.json --data-root . --checkpoint /tmp/f3-mlp500-seed43-20260928-checkpoint.pt --case-id F3_DEV_00_a0p903125 --split test --maximum-steps 835 --chunk-size 34560 --device cuda:0 --progress-every 25 --trajectory-output /tmp/f3-mlp500-seed43-full835-20260928-trajectory.h5 --progress-output /tmp/f3-mlp500-seed43-full835-20260928-evaluation-progress.json --output /tmp/f3-mlp500-seed43-full835-20260928-evaluation.json --diagnostic
```

## 指标

| 指标 | 数值 |
|---|---:|
| selection score | `0.28860515014452587` |
| raw frame mean position RMSE | `1.0476556152184564 m` |
| raw frame mean velocity RMSE | `2.0132262678916883 m/s` |
| step 50 position / velocity RMSE | `0.010629219363048927 m` / `0.026684503887126836 m/s` |
| step 835 position / velocity RMSE | `17.64862820431942 m` / `36.52892656032414 m/s` |
| maximum kinetic-energy error | `29180.381209075953 J` |
| raw error coverage | `1.0` |

完整长时域结果显示误差随 rollout 明显累积；这是诊断结论，不构成资格通过。

## Receipt 索引

- progress：`/tmp/f3-mlp500-seed43-full835-20260928-evaluation-progress.json`，SHA-256 `87475129dad0acd0c5d84890e46011bd30672810207203a64aaded72af569a12`。
- evaluation：`/tmp/f3-mlp500-seed43-full835-20260928-evaluation.json`，SHA-256 `cfac9c57991c63827cdc3f2d0f39fa1d96639029b836c198ef1237c667650a48`。
- trajectory HDF5：`/tmp/f3-mlp500-seed43-full835-20260928-trajectory.h5`，SHA-256 `238c0d937d4985fdc99688d3122a2fcb2ddf6b83ea9e490450b5534ecfffa06a`。
- HDF5 validation：`/tmp/f3-mlp500-seed43-full835-20260928-hdf5-validation.json`，SHA-256 `77966034113395a89e45d63c50487ba4dd644de38793fa57fa3046f6636e4472`。

## 资格状态

`diagnostic_only=true`、`formal_eligible=false`、`T1_numerical=false`、`T2_macro=false`、`qualification=false`、`credit=0`。本报告没有修改 PLAN、源码、生产 HDF5、manifest、registry、ledger、denominator 或 gate。
