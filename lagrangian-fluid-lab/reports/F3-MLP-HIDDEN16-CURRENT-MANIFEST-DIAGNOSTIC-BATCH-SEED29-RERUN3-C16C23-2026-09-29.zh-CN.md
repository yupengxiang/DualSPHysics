# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`completed_diagnostic_batch`；batch=`seed29-rerun3-c16C23-20260929`
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
| `F3_DEV_16_a1p003125` | `train` | 899978242 | 0 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE16-SEED29-ff4f9fa27cb288efafb5ba4bde05fb08-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_17_a1p009375` | `train` | 900503563 | 1 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE17-SEED29-4bd81175e9884ebea7274ee9031e11b4-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_18_a1p015625` | `validation` | 900394799 | 2 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE18-SEED29-7e71a6a3b35443ad988d85e95e9dc527-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_19_a1p021875` | `train` | 900242210 | 3 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE19-SEED29-d57ccf144a92a8786384a28336046241-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_20_a1p028125` | `train` | 900624967 | 4 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE20-SEED29-a1138b7969fd986a28b6e2ae2d0de4cb-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_21_a1p034375` | `train` | 901118248 | 5 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE21-SEED29-8f938fe5f9eebe5b2529013d6111d8e8-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_22_a1p040625` | `train` | 900796925 | 6 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE22-SEED29-82176e92ec0db58af12a6673394f61ff-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_23_a1p046875` | `validation` | 901226878 | 7 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE23-SEED29-fa31863c61e5c143c4b10eb882210c86-PROCESS-EXIT-PROOF-V1.json` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
