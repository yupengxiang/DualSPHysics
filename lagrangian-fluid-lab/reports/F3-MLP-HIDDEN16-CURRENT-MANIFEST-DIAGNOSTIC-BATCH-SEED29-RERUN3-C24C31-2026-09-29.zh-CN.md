# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`completed_diagnostic_batch`；batch=`seed29-rerun3-c24C31-20260929`
- 覆盖：`8 real cases × seed 29`
- 终态回执：`8/8`；缺失 `0`
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
| `F3_DEV_24_a1p053125` | `train` | 900920008 | 0 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE24-SEED29-bad753269de5e7eb79c04665c8ec4efd-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_25_a1p059375` | `train` | 901319562 | 1 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE25-SEED29-57ef26fa31aad841493f38cb2664853f-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_26_a1p065625` | `test` | 901286606 | 2 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE26-SEED29-dc70256192eca10ea1e177a243abd34f-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_27_a1p071875` | `test` | 901823189 | 3 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE27-SEED29-17d9c8641490cedff11b2c7f670f3257-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_28_a1p078125` | `test` | 901640992 | 4 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE28-SEED29-d42277056f17e32c82c4410c37d2873c-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_29_a1p084375` | `test` | 901526081 | 5 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE29-SEED29-e5eb4febc079471adb3227b9abada345-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_30_a1p090625` | `test` | 901574649 | 6 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE30-SEED29-dd8135c05b15d3a7fcb52410fac62905-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_31_a1p096875` | `test` | 901526961 | 7 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE31-SEED29-1ea53397ddb878b27cfc888b7542895c-PROCESS-EXIT-PROOF-V1.json` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
