# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`completed_diagnostic_batch`；batch=`seed43-c24c31-20260929`
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
| `F3_DEV_24_a1p053125` | `train` | 900920008 | 0 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE24-SEED43-c5c3598eb7da5066a1833bfb24bac565-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_25_a1p059375` | `train` | 901319562 | 1 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE25-SEED43-26f6395a8040334889fac206fe644eb2-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_26_a1p065625` | `test` | 901286606 | 2 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE26-SEED43-54e9e646c253fc3f2db1cbe18ab9afa5-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_27_a1p071875` | `test` | 901823189 | 3 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE27-SEED43-8dd831f72ed3c4b3c69082879a7bcf5a-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_28_a1p078125` | `test` | 901640992 | 4 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE28-SEED43-e04cb984e6f813abee73809328d33654-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_29_a1p084375` | `test` | 901526081 | 5 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE29-SEED43-7844a8a5af89cd6558cb9c24ea2df946-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_30_a1p090625` | `test` | 901574649 | 6 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE30-SEED43-10864a492aa9b1c1f23b3db1a5868ce1-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_31_a1p096875` | `test` | 901526961 | 7 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE31-SEED43-d468aa61c08d63d2b01830f047b463c7-PROCESS-EXIT-PROOF-V1.json` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
