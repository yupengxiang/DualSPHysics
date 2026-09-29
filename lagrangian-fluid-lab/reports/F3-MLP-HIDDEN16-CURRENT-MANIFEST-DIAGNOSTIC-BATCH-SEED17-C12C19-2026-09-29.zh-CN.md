# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`blocked_diagnostic_batch`；batch=`seed17-c12c19-20260929`
- 覆盖：`8 real cases × seed 17`
- 终态回执：`0/8`；缺失 `8`
- 权限：所有结果 `diagnostic_only=true`、formal/T1/T2/qualification=`false`、credit=`0`
- 进程安全：只等待本批新建 worker/evaluator 自然退出；既有进程停止/重启均为 `0`

## Source binding

- manifest：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/f3-dataset-v2.json`
- manifest canonical SHA：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`
- training receipt：`/tmp/f3-mlp500-hidden16-currentmanifest-seed17-20260929-training.json`
- checkpoint：`/tmp/f3-mlp500-hidden16-currentmanifest-seed17-20260929-checkpoint.pt` (`c1e41d29900e02e50fcf0a0435f8c3427e41761d8114858235c82a8847cf8897`)

## Cases

| case | split | HDF5 bytes | GPU | status | proof |
|---|---|---:|---:|---|---|
| `F3_DEV_12_a0p978125` | `train` | 899800349 | 0 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_13_a0p984375` | `validation` | 899576772 | 1 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_14_a0p990625` | `train` | 900082956 | 2 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_15_a0p996875` | `train` | 900176936 | 3 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_16_a1p003125` | `train` | 899978242 | 4 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_17_a1p009375` | `train` | 900503563 | 5 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_18_a1p015625` | `validation` | 900394799 | 6 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_19_a1p021875` | `train` | 900242210 | 7 | `blocked_worker_fail_closed` | `—` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
