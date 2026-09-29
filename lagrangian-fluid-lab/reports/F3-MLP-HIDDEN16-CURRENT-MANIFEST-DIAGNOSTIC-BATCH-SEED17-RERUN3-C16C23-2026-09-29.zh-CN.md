# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`completed_diagnostic_batch`；batch=`seed17-rerun3-c16C23-20260929`
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
| `F3_DEV_16_a1p003125` | `train` | 899978242 | 0 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE16-SEED17-7ea63b49b749f88eec88614cbfebaf1f-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_17_a1p009375` | `train` | 900503563 | 1 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE17-SEED17-9ae467df648f78681a3d09d79447048f-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_18_a1p015625` | `validation` | 900394799 | 2 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE18-SEED17-6768bb51749a2989aef619c9b781fd71-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_19_a1p021875` | `train` | 900242210 | 3 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE19-SEED17-db951528f7f4c9db29e635abde664f20-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_20_a1p028125` | `train` | 900624967 | 4 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE20-SEED17-626f917c9bbba0b6b0030a75f6041892-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_21_a1p034375` | `train` | 901118248 | 5 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE21-SEED17-91df205befe2e08565352570ac47435e-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_22_a1p040625` | `train` | 900796925 | 6 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE22-SEED17-2aa691d0b8a4284a35af88519a1bd941-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_23_a1p046875` | `validation` | 901226878 | 7 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE23-SEED17-3aa662de56edcdc7de736a7cb928d2ab-PROCESS-EXIT-PROOF-V1.json` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
