# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`blocked_diagnostic_batch`；batch=`seed29-c00c07-20260929`
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
| `F3_DEV_00_a0p903125` | `test` | 899562494 | 0 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_01_a0p909375` | `test` | 899502944 | 1 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_02_a0p915625` | `test` | 899257415 | 2 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_03_a0p921875` | `test` | 899285381 | 3 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_04_a0p928125` | `test` | 899600874 | 4 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_05_a0p934375` | `test` | 899139420 | 5 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_06_a0p940625` | `train` | 899634806 | 6 | `blocked_worker_fail_closed` | `—` |
| `F3_DEV_07_a0p946875` | `train` | 899585032 | 7 | `blocked_worker_fail_closed` | `—` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
