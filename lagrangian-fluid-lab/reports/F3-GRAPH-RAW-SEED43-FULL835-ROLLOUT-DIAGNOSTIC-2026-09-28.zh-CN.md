# F3 graph_raw seed43 full835 长时域诊断报告

本报告记录独立重建的 graph_raw / seed43 / hidden=8 checkpoint 对
F3_DEV_00_a0p903125 执行完整 autonomous diagnostic rollout 的结果。
本报告明确为 diagnostic-only：不属于 formal release、T1/T2 qualification
或生产数据资产，也不产生 qualification credit。

## 结论摘要

- 训练严格完成 500/500 updates；checkpoint update 为 500，
  checkpoint_verified=true，evidence_status=complete，最大
  neighbor_truncation_fraction=0。
- rollout 完成完整注册分母：835/835 transitions、836/836 frames，
  full_registered_denominator_complete=true，raw_error_coverage=1.0。
- HDF5 validator：passed=true、complete=true、tail_frame_count=0，
  trajectory 为 [836, 34560, 3] 的 position/velocity。
- future_state_inputs=false；position、velocity、mass、time 均 finite，
  mass error 最大绝对值为 0 kg，validity mismatch 为 0。
- 误差从 step 50 到 step 835 明显累积；这是诊断观察，不是 formal
  qualification 判定。

## 执行边界与协议

- 模型：graph_raw，seed 43，hidden 8，centers/update 256，
  learning rate 0.001，normalization transitions 16，
  max neighbors 192。
- 训练：updates=500、checkpoint-every=500、validation-every=500。
- 评测：case F3_DEV_00_a0p903125，split test，maximum-steps=835，
  chunk-size=34560，device=cuda:0，diagnostic、autonomous。
- 设备：物理 GPU4（NVIDIA RTX 6000 Ada Generation），通过
  CUDA_VISIBLE_DEVICES=4 映射到进程 cuda:0。GPU1/GPU3 外部任务未触碰，
  既有进程未终止。
- 未修改 PLAN、源码、生产 HDF5、manifest、registry、ledger、denominator
  或 gate；rollout HDF5 和所有 receipt 均保留在 /tmp。

训练命令：

    PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES=4 .venv/bin/python scripts/core_learning.py train --manifest campaigns/core-v1/f3-dataset-v2.json --data-root . --model graph_raw --seed 43 --updates 500 --centers 256 --hidden 8 --learning-rate 0.001 --normalization-transitions 16 --max-neighbors 192 --device cuda:0 --run-id f3-graph-raw500-seed43-rebuild-20260928 --checkpoint /tmp/f3-graph-raw500-seed43-rebuild-20260928-checkpoint.pt --checkpoint-every 500 --log-every 100 --validation-every 500 --progress-output /tmp/f3-graph-raw500-seed43-rebuild-20260928-training-progress.json --output /tmp/f3-graph-raw500-seed43-rebuild-20260928-training.json

评测命令：

    PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES=4 .venv/bin/python scripts/core_learning.py evaluate --manifest campaigns/core-v1/f3-dataset-v2.json --data-root . --checkpoint /tmp/f3-graph-raw500-seed43-rebuild-20260928-checkpoint.pt --case-id F3_DEV_00_a0p903125 --split test --maximum-steps 835 --chunk-size 34560 --device cuda:0 --trajectory-output /tmp/f3-graph-raw500-seed43-full835-20260928-trajectory.h5 --progress-output /tmp/f3-graph-raw500-seed43-full835-20260928-evaluation-progress.json --progress-every 25 --diagnostic --output /tmp/f3-graph-raw500-seed43-full835-20260928-evaluation.json

HDF5 validator 命令：

    PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python scripts/f3_full_rollout_receipt_hdf5_validator_v1.py /tmp/f3-graph-raw500-seed43-full835-20260928-evaluation.json --trajectory /tmp/f3-graph-raw500-seed43-full835-20260928-trajectory.h5 --case-id F3_DEV_00_a0p903125 --expected-transitions 835

## 训练与 checkpoint 证据

| 项目 | 结果 |
|---|---:|
| completed updates | 500/500 |
| checkpoint | update 500，checkpoint_verified=true |
| evidence | complete |
| neighbor truncation 最大比例 | 0.0 |
| normalization selected transitions | 16，source split train |
| validation | update 500，MSE 0.8696202337741852，RMSE 0.9325343070226345 |
| checkpoint SHA-256 | 4c421ac596dc2e597c14d06cdd8b1f0b28c9ddb645c29fd0d050e2fa0c10ed4b |

训练 receipt：

    /tmp/f3-graph-raw500-seed43-rebuild-20260928-training.json

训练 progress：

    /tmp/f3-graph-raw500-seed43-rebuild-20260928-training-progress.json

## rollout 闭合与 HDF5 validator

| 项目 | 结果 |
|---|---:|
| registered denominator | 835 transitions / 836 source frames |
| executed | 835/835 transitions，轨迹 836/836 frames |
| finite rollout | true |
| failure category | null |
| first failure frame | null |
| scientific status | not_assessed |
| raw error coverage | 1.0 |
| future_state_inputs | false |
| HDF5 validator | passed=true，complete=true |
| validator trajectory | 836 frames / 835 transitions |
| validator tail frames | 0 |
| production artifacts touched | false |

trajectory HDF5 的 position/velocity shape 均为 [836, 34560, 3]，valid
shape 为 [836, 34560]，valid_false_count=0；position、velocity、mass、
time 全部 finite，mass 为正且静态，总质量为 14.580000378191471 kg。

## 关键指标

| 指标 | 数值 |
|---|---:|
| selection score | 0.2817127004975565 |
| raw frame mean position RMSE | 0.5724223823442722 m |
| raw frame mean velocity RMSE | 0.5584473221960782 m/s |
| step 50 position / velocity RMSE | 0.006271187203975505 m / 0.03558410184597668 m/s |
| step 835 position / velocity RMSE | 3.61500033969847 m / 3.256576790802283 m/s |
| maximum kinetic-energy error | 236.74228197132754 J |
| mass error 最大绝对值 | 0 kg |
| changed particle-mass frames | 0 |
| validity mismatch frames | 0 |

selection score 是 registered selection penalty（越低越好），不是
qualification decision。step 835 的误差增长说明该 checkpoint 在完整长时域
diagnostic 中出现明显误差累积；本次 rollout 仍保持 finite 且没有被标记为
scientific failure。

## Formal / T1 / T2 / qualification 状态

| 状态 | 结果 | 含义 |
|---|---:|---|
| formal eligible | false | diagnostic-only，manifest 不是 formal release |
| T1 numerical | false / not_assessed_diagnostic_only | 未进入资格评定 |
| T2 macro | false / not_assessed_diagnostic_only | 未进入资格评定 |
| qualification | false / not_eligible_diagnostic_only | 不产生 qualification credit |
| qualification credit | 0 | 本次仅为诊断 |

这里的 false 表示本次运行没有资格评定权限，不应解读为一次 formal
pass/fail 结论。结果不会被保留为当前 formal candidate，也不会被接受用于
formal training。

## Receipt 与 artifact 索引

- checkpoint：/tmp/f3-graph-raw500-seed43-rebuild-20260928-checkpoint.pt
- training receipt SHA-256：
  1672f7d397304064d1c0a562a224cd6265f7cb38f86c4fdcf1eb77ede906cd47
- training progress SHA-256：
  8e41290fc03515de02273666a086ecac75fb1376a1c0d204816f9d20241b0103
- evaluation receipt：
  /tmp/f3-graph-raw500-seed43-full835-20260928-evaluation.json
- evaluation receipt SHA-256：
  26bf246e141d08e86156ef72d48b3279060ff9bd6cdd4db13a9c7ae429622f86
- evaluation progress SHA-256：
  58d4b57c3746e3edb94e2d2bc76cadc409e60f51b9189a70c6029b38bb7c3b1e
- trajectory HDF5 SHA-256：
  d7b58aac520466f33a336bc4cb5e67d0edda6f9119e91fd0d3bc8c8bf591dc8b
- HDF5 validation SHA-256：
  33f56ac9c2fb0666f6ace8ec917e983ff9ba99174728ee543f45e5f3c86cff06

完整机器可读字段、源数据哈希、checkpoint/evidence、finite/mass/validity、
selection、资格状态和 side-effect 声明见同名 .json 报告。
