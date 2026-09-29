# F3 MLP hidden16 current-manifest diagnostic batch

- 状态：`completed_diagnostic_batch`；batch=`seed17-rerun3-c08C15-20260929`
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
| `F3_DEV_08_a0p953125` | `validation` | 899512487 | 0 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE08-SEED17-a5c93263a789a16d2d894c3ce0ad9994-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_09_a0p959375` | `train` | 899701103 | 1 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE09-SEED17-1759b56368dbda3ffa83ff7c35af0910-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_10_a0p965625` | `train` | 899786474 | 2 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE10-SEED17-71c6d2a450295f43cbfe960babf45855-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_11_a0p971875` | `train` | 899739060 | 3 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE11-SEED17-2fc14dda768695868e32095b1c8012f3-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_12_a0p978125` | `train` | 899800349 | 4 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE12-SEED17-c001ce3cb88ab9cadfa262f179ee7a30-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_13_a0p984375` | `validation` | 899576772 | 5 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE13-SEED17-fc484fa535c922cd31ba6f8381f0323a-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_14_a0p990625` | `train` | 900082956 | 6 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE14-SEED17-4482661dcc1c8cc5c220fdc51adaa2c3-PROCESS-EXIT-PROOF-V1.json` |
| `F3_DEV_15_a0p996875` | `train` | 900176936 | 7 | `exited_successfully` | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-CASE15-SEED17-67d6327bfed2fa133400ab82842ae33c-PROCESS-EXIT-PROOF-V1.json` |

该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。
