# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`blocked_diagnostic_batch`；batch=`seed29-c24c31-20260929`
- 覆盖：`8 real cases × seed 29`
- 终态回执：`0/8`；缺失 `8`
- 权限：所有结果 `diagnostic_only=true`、formal/T1/T2/qualification=`false`、credit=`0`
- 进程安全：只等待本批新建 worker/evaluator 自然退出；既有进程停止/重启均为 `0`

## Source binding

- manifest：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/f3-dataset-v2.json`
- manifest canonical SHA：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`
- training receipt：`/tmp/f3-mlp500-hidden16-currentmanifest-seed29-20260929-training.json`
- checkpoint：`/tmp/f3-mlp500-hidden16-currentmanifest-seed29-20260929-checkpoint.pt` (`be4a789a3d769f97fb6fb535afa09c5d3df545ee5ffde6d533732008caf93a04`)

## Cases

| case | split | HDF5 bytes | GPU | status | proof |
|---|---|---:|---:|---|---|
| `F3_DEV_24_a1p053125` | `train` | 900920008 | 0 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_25_a1p059375` | `train` | 901319562 | 1 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_26_a1p065625` | `test` | 901286606 | 2 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_27_a1p071875` | `test` | 901823189 | 3 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_28_a1p078125` | `test` | 901640992 | 4 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_29_a1p084375` | `test` | 901526081 | 5 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_30_a1p090625` | `test` | 901574649 | 6 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_31_a1p096875` | `test` | 901526961 | 7 | `blocked_worker_fail_closed` | `—` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
