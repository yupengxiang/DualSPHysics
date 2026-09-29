# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`completed_diagnostic_batch`；batch=`seed43-c00c07-20260929`
- 覆盖：`8 real cases × seed 43`
- 终态回执：`8/8`；缺失 `0`
- 权限：所有结果 `diagnostic_only=true`、formal/T1/T2/qualification=`false`、credit=`0`
- 进程安全：只等待本批新建 worker/evaluator 自然退出；既有进程停止/重启均为 `0`

## Source binding

- manifest：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/f3-dataset-v2.json`
- manifest canonical SHA：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`
- training receipt：`/tmp/f3-mlp500-hidden16-currentmanifest-seed43-20260929-training.json`
- checkpoint：`/tmp/f3-mlp500-hidden16-currentmanifest-seed43-20260929-checkpoint.pt` (`8916c6a710f0e567767df986ed9e810d6df8503e4a46b8a1970ea1fcadb202ac`)

## Cases

| case | split | HDF5 bytes | GPU | status | proof |
|---|---|---:|---:|---|---|
| `F3_DEV_00_a0p903125` | `test` | 899562494 | 0 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE00-SEED43-75a91827ac9b68a4219aeb482f4bc3be-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_01_a0p909375` | `test` | 899502944 | 1 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE01-SEED43-e6dafedad81d674dc999bf5054db25ec-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_02_a0p915625` | `test` | 899257415 | 2 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE02-SEED43-b3255017cb9434861f883dcbde1aaaf9-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_03_a0p921875` | `test` | 899285381 | 3 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE03-SEED43-883d9a04c5bf82535a6ee7af82264e72-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_04_a0p928125` | `test` | 899600874 | 4 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE04-SEED43-be6291c0cfa1aa2baddb15928ad0aee6-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_05_a0p934375` | `test` | 899139420 | 5 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE05-SEED43-5abc90f989542f6637b4f7c6562fd05c-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_06_a0p940625` | `train` | 899634806 | 6 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE06-SEED43-88c86bc3283424609141c51e29d64363-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_07_a0p946875` | `train` | 899585032 | 7 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE07-SEED43-e37fea9f3d4d8e77b5ca41ad78187fb8-PROCESS-EXIT-PROOF-V1.json` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
