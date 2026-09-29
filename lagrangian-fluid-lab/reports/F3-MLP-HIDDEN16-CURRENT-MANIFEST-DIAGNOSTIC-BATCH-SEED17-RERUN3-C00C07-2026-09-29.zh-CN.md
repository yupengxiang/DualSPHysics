# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`completed_diagnostic_batch`；batch=`seed17-rerun3-c00C07-20260929`
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
| `F3_DEV_00_a0p903125` | `test` | 899562494 | 0 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE00-SEED17-574b73c162623e1f01287159bb79ba10-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_01_a0p909375` | `test` | 899502944 | 1 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE01-SEED17-951f96247e6ebd5a60dccc80c5b2908e-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_02_a0p915625` | `test` | 899257415 | 2 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE02-SEED17-d967ba62fe2a904a7cdb3a10e22673f7-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_03_a0p921875` | `test` | 899285381 | 3 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE03-SEED17-205189e92b3c487594ae132b18e98d05-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_04_a0p928125` | `test` | 899600874 | 4 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE04-SEED17-8f69b5e40e93aac4acdbf425e797db9a-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_05_a0p934375` | `test` | 899139420 | 5 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE05-SEED17-2463649b7389f155f21262e6f2dfee8e-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_06_a0p940625` | `train` | 899634806 | 6 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE06-SEED17-80c8747819aef2879db96e2d914ef871-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_07_a0p946875` | `train` | 899585032 | 7 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE07-SEED17-3cd1fdb7c287a3d872e0098133c86375-PROCESS-EXIT-PROOF-V1.json` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
