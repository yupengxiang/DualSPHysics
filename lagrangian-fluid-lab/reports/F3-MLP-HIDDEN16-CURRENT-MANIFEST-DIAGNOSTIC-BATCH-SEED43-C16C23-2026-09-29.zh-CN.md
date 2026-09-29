# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`completed_diagnostic_batch`；batch=`seed43-c16c23-20260929`
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
| `F3_DEV_16_a1p003125` | `train` | 899978242 | 0 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE16-SEED43-0489a2cfc082a2189db61852876259e8-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_17_a1p009375` | `train` | 900503563 | 1 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE17-SEED43-9ec375f60d5bf246acf4c7723401ed4c-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_18_a1p015625` | `validation` | 900394799 | 2 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE18-SEED43-5fc3325bb31d5f0135a8ee61f4642daf-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_19_a1p021875` | `train` | 900242210 | 3 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE19-SEED43-92196b46ad79f4db61bc709ab295d334-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_20_a1p028125` | `train` | 900624967 | 4 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE20-SEED43-1b6481635ec8bfcd3aa54e1a0935503f-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_21_a1p034375` | `train` | 901118248 | 5 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE21-SEED43-cabc1969dea8652101d05c52dd4a9db3-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_22_a1p040625` | `train` | 900796925 | 6 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE22-SEED43-906f21b1f5e513595fd380fb93b27cc8-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_23_a1p046875` | `validation` | 901226878 | 7 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE23-SEED43-9f0670be0032d36e7aebef7c6da5b61b-PROCESS-EXIT-PROOF-V1.json` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
