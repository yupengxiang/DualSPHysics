# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`completed_diagnostic_batch`；batch=`seed43-c08c15-20260929`
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
| `F3_DEV_08_a0p953125` | `validation` | 899512487 | 0 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE08-SEED43-f3f23757d3590e3b25f145558fb0cbb0-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_09_a0p959375` | `train` | 899701103 | 1 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE09-SEED43-058560a225dfea4158d5172959700cab-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_10_a0p965625` | `train` | 899786474 | 2 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE10-SEED43-bc84acfc24e5c3ba0f3060817861c54f-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_11_a0p971875` | `train` | 899739060 | 3 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE11-SEED43-f2664c1d7a0cf6f4e5ab4fad06759ff9-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_12_a0p978125` | `train` | 899800349 | 4 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE12-SEED43-2dd4c0e5b08e6005457fd3fd2b2a38aa-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_13_a0p984375` | `validation` | 899576772 | 5 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE13-SEED43-9e0c76a7d8535b7131fb700b947044be-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_14_a0p990625` | `train` | 900082956 | 6 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE14-SEED43-59feab7a07d30d6ce138f57ea5304f21-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_15_a0p996875` | `train` | 900176936 | 7 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE15-SEED43-6ca1e9d76d4e8bd26b193f6acd5e6cc8-PROCESS-EXIT-PROOF-V1.json` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
