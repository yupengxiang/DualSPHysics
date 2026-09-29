# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`completed_diagnostic_batch`；batch=`seed29-rerun3-c08C15-20260929`
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
| `F3_DEV_08_a0p953125` | `validation` | 899512487 | 0 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE08-SEED29-294bcfde0848cce70586616a30d444c9-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_09_a0p959375` | `train` | 899701103 | 1 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE09-SEED29-5f7db31216ee9cc3dcc694559e423e59-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_10_a0p965625` | `train` | 899786474 | 2 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE10-SEED29-d4a2d5e67f9eb8394797e70c0867ff8b-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_11_a0p971875` | `train` | 899739060 | 3 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE11-SEED29-11303164c73954240b52f6d0140aa4b7-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_12_a0p978125` | `train` | 899800349 | 4 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE12-SEED29-17dda17fdb2e97dc8b6e08b82170b38f-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_13_a0p984375` | `validation` | 899576772 | 5 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE13-SEED29-08c20a1d01608db77bb1322cc0ccdd0d-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_14_a0p990625` | `train` | 900082956 | 6 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE14-SEED29-c7409228b5aae5abb24f77b197ff6a17-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_15_a0p996875` | `train` | 900176936 | 7 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE15-SEED29-26ceaf8a7753a4c77a275db3f0486d2e-PROCESS-EXIT-PROOF-V1.json` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
