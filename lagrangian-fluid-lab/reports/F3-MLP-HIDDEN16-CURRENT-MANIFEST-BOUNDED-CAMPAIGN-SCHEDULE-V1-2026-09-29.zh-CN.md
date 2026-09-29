# F3 MLP hidden16 current-manifest bounded campaign schedule

- 状态：`dry_run_schedule_ready`；campaign=`f3-mlp-hidden16-currentmanifest-bounded-20260929`
- 覆盖：`32` cases × seeds `17,29,43` = `96` jobs
- 批次：`12` 个；每批最多 `8` 个 case；seed 隔离=`True`
- 预计输出空间：约 `96.0 GiB`（固定规划包络，不读取 HDF5/checkpoint 内容）

## Source identity

- manifest：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/f3-dataset-v2.json`
- manifest raw SHA-256：`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`
- manifest canonical SHA-256：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`
- training identity：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-2026-09-29-RERUN1.json`
- training identity SHA-256：`aa5561dc69148a38a14d6b21c501d9214aba242707be782eeb512ba45e6300ef`

## Batch schedule

| batch | seed | cases | GPU slots | output report |
|---|---:|---:|---|---|
| `f3-mlp-hidden16-currentmanifest-bounded-20260929-seed17-batch00` | 17 | 8 | `0,1,2,3,4,5,6,7` | `/tmp/f3-mlp-hidden16-currentmanifest-bounded-campaign-20260929-v1/batch-reports/f3-mlp-hidden16-currentmanifest-bounded-20260929-seed17-batch00.json` |
| `f3-mlp-hidden16-currentmanifest-bounded-20260929-seed17-batch01` | 17 | 8 | `0,1,2,3,4,5,6,7` | `/tmp/f3-mlp-hidden16-currentmanifest-bounded-campaign-20260929-v1/batch-reports/f3-mlp-hidden16-currentmanifest-bounded-20260929-seed17-batch01.json` |
| `f3-mlp-hidden16-currentmanifest-bounded-20260929-seed17-batch02` | 17 | 8 | `0,1,2,3,4,5,6,7` | `/tmp/f3-mlp-hidden16-currentmanifest-bounded-campaign-20260929-v1/batch-reports/f3-mlp-hidden16-currentmanifest-bounded-20260929-seed17-batch02.json` |
| `f3-mlp-hidden16-currentmanifest-bounded-20260929-seed17-batch03` | 17 | 8 | `0,1,2,3,4,5,6,7` | `/tmp/f3-mlp-hidden16-currentmanifest-bounded-campaign-20260929-v1/batch-reports/f3-mlp-hidden16-currentmanifest-bounded-20260929-seed17-batch03.json` |
| `f3-mlp-hidden16-currentmanifest-bounded-20260929-seed29-batch00` | 29 | 8 | `0,1,2,3,4,5,6,7` | `/tmp/f3-mlp-hidden16-currentmanifest-bounded-campaign-20260929-v1/batch-reports/f3-mlp-hidden16-currentmanifest-bounded-20260929-seed29-batch00.json` |
| `f3-mlp-hidden16-currentmanifest-bounded-20260929-seed29-batch01` | 29 | 8 | `0,1,2,3,4,5,6,7` | `/tmp/f3-mlp-hidden16-currentmanifest-bounded-campaign-20260929-v1/batch-reports/f3-mlp-hidden16-currentmanifest-bounded-20260929-seed29-batch01.json` |
| `f3-mlp-hidden16-currentmanifest-bounded-20260929-seed29-batch02` | 29 | 8 | `0,1,2,3,4,5,6,7` | `/tmp/f3-mlp-hidden16-currentmanifest-bounded-campaign-20260929-v1/batch-reports/f3-mlp-hidden16-currentmanifest-bounded-20260929-seed29-batch02.json` |
| `f3-mlp-hidden16-currentmanifest-bounded-20260929-seed29-batch03` | 29 | 8 | `0,1,2,3,4,5,6,7` | `/tmp/f3-mlp-hidden16-currentmanifest-bounded-campaign-20260929-v1/batch-reports/f3-mlp-hidden16-currentmanifest-bounded-20260929-seed29-batch03.json` |
| `f3-mlp-hidden16-currentmanifest-bounded-20260929-seed43-batch00` | 43 | 8 | `0,1,2,3,4,5,6,7` | `/tmp/f3-mlp-hidden16-currentmanifest-bounded-campaign-20260929-v1/batch-reports/f3-mlp-hidden16-currentmanifest-bounded-20260929-seed43-batch00.json` |
| `f3-mlp-hidden16-currentmanifest-bounded-20260929-seed43-batch01` | 43 | 8 | `0,1,2,3,4,5,6,7` | `/tmp/f3-mlp-hidden16-currentmanifest-bounded-campaign-20260929-v1/batch-reports/f3-mlp-hidden16-currentmanifest-bounded-20260929-seed43-batch01.json` |
| `f3-mlp-hidden16-currentmanifest-bounded-20260929-seed43-batch02` | 43 | 8 | `0,1,2,3,4,5,6,7` | `/tmp/f3-mlp-hidden16-currentmanifest-bounded-campaign-20260929-v1/batch-reports/f3-mlp-hidden16-currentmanifest-bounded-20260929-seed43-batch02.json` |
| `f3-mlp-hidden16-currentmanifest-bounded-20260929-seed43-batch03` | 43 | 8 | `0,1,2,3,4,5,6,7` | `/tmp/f3-mlp-hidden16-currentmanifest-bounded-campaign-20260929-v1/batch-reports/f3-mlp-hidden16-currentmanifest-bounded-20260929-seed43-batch03.json` |

## Fail-closed boundary

- 计划器只打开显式 manifest/training identity JSON；不打开 HDF5 或 checkpoint 内容。
- 不启动 GPU、solver、worker，不停止或重启既有进程。
- 所有 job 都是 `schedule_only`、`diagnostic_only=true`、`formal=false`、`credit=0`；本报告不是 terminal receipt。
- 不读取或写入 formal registry、ledger、gate 或 PLAN；后续 executor 必须重新进行显存、namespace、新鲜性和终态回执检查。
