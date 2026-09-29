# F3 MLP hidden16 current-manifest diagnostic rollup audit

- 状态：`incomplete_diagnostic_rollup`
- 固定计划：`32 cases × seeds 17, 29, 43` = `96` pairs
- JSON/Markdown batch 对：`14`；pair failures：`0`
- 计划覆盖：`95/96`；结果覆盖：`95/96`
- fully auditable rows：`0`；row failures：`98`
- 所有聚合结果固定 `diagnostic_only=true`、formal/T1/T2/qualification=`false`、`credit=0`

## Uniqueness and gaps

- duplicate batch IDs：`0`
- duplicate planned case/seed：`3`
- duplicate result case/seed：`3`
- missing planned：`F3_DEV_00_a0p903125/seed17`
- missing result：`F3_DEV_00_a0p903125/seed17`
- unexpected planned：`—`
- unexpected result：`—`

## Batch reports

| JSON | Markdown | batch | status | rows | issues |
|---|---|---|---|---:|---:|
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-REAL3-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-REAL3-2026-09-29.zh-CN.md` | `real3-20260929` | `blocked_diagnostic_batch` | 3 | 15 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-REAL3B-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-REAL3B-2026-09-29.zh-CN.md` | `real3b-20260929` | `blocked_diagnostic_batch` | 3 | 15 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED17-C04C11-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED17-C04C11-2026-09-29.zh-CN.md` | `seed17-c04c11-20260929` | `blocked_diagnostic_batch` | 8 | 40 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED17-C12C19-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED17-C12C19-2026-09-29.zh-CN.md` | `seed17-c12c19-20260929` | `blocked_diagnostic_batch` | 8 | 40 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED17-C20C27-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED17-C20C27-2026-09-29.zh-CN.md` | `seed17-c20c27-20260929` | `blocked_diagnostic_batch` | 8 | 40 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED17-C28C31-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED17-C28C31-2026-09-29.zh-CN.md` | `seed17-c28c31-20260929` | `blocked_diagnostic_batch` | 4 | 20 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED29-C00C07-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED29-C00C07-2026-09-29.zh-CN.md` | `seed29-c00c07-20260929` | `blocked_diagnostic_batch` | 8 | 40 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED29-C08C15-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED29-C08C15-2026-09-29.zh-CN.md` | `seed29-c08c15-20260929` | `blocked_diagnostic_batch` | 8 | 40 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED29-C16C23-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED29-C16C23-2026-09-29.zh-CN.md` | `seed29-c16c23-20260929` | `blocked_diagnostic_batch` | 8 | 40 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED29-C24C31-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED29-C24C31-2026-09-29.zh-CN.md` | `seed29-c24c31-20260929` | `blocked_diagnostic_batch` | 8 | 40 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED43-C00C07-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED43-C00C07-2026-09-29.zh-CN.md` | `seed43-c00c07-20260929` | `completed_diagnostic_batch` | 8 | 24 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED43-C08C15-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED43-C08C15-2026-09-29.zh-CN.md` | `seed43-c08c15-20260929` | `completed_diagnostic_batch` | 8 | 24 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED43-C16C23-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED43-C16C23-2026-09-29.zh-CN.md` | `seed43-c16c23-20260929` | `completed_diagnostic_batch` | 8 | 24 |
| `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED43-C24C31-2026-09-29.json` | `F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-SEED43-C24C31-2026-09-29.zh-CN.md` | `seed43-c24c31-20260929` | `completed_diagnostic_batch` | 8 | 24 |

## Boundary

本审计器只读取目标 batch JSON/Markdown 报告；不打开 HDF5、checkpoint、嵌入式 receipt，不接触进程，不修改 formal registry、ledger、denominator、gate 或 PLAN。缺失 process/terminal receipt 的行保持 diagnostic zero-credit，不能被聚合器晋级为 formal evidence。
