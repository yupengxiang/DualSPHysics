# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`completed_diagnostic_batch`；batch=`seed17-rerun3-c24C31-20260929`
- 覆盖：`8 real cases × seed 17`
- 终态回执：`8/8`；缺失 `0`
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
| `F3_DEV_24_a1p053125` | `train` | 900920008 | 0 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE24-SEED17-ecf82fcfcdc73e494d3e71ef01fee039-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_25_a1p059375` | `train` | 901319562 | 1 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE25-SEED17-54fd487e6190287e34389c338d783e27-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_26_a1p065625` | `test` | 901286606 | 2 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE26-SEED17-ace23d08f64cb524e02fa066c32e9f44-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_27_a1p071875` | `test` | 901823189 | 3 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE27-SEED17-d0fdf734e5aa189e38f83faaf1339af0-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_28_a1p078125` | `test` | 901640992 | 4 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE28-SEED17-cd17ee6c31d514f97405771a6b009bf0-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_29_a1p084375` | `test` | 901526081 | 5 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE29-SEED17-9e986202d8a086cf4c0f8ac88e669a4e-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_30_a1p090625` | `test` | 901574649 | 6 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE30-SEED17-3bc2b3048356e207511a6bdad96a42bd-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_31_a1p096875` | `test` | 901526961 | 7 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE31-SEED17-58b44e1a6e532b30494e21931eff18f4-PROCESS-EXIT-PROOF-V1.json` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
