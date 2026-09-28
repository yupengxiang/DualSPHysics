# F3 graph_raw hidden16 current-manifest case matrix

- 状态：`dry_run_matrix_ready`；source-bound：`True`；launch_allowed：`False`
- 当前 canonical manifest SHA：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`
- 覆盖：`32` cases × seeds `17,29,43` = `96` plans
- 唯一性：namespace `96`、nonce `96`、command identity `96`
- 真实 terminal receipts：`0/96`；`missing_real_terminal_receipts_fail_closed`
- 边界：只打开 bounded manifest/training-evidence JSON；不打开 checkpoint、case HDF5、evaluation、trajectory 或 progress，不启动 GPU/runtime/queue。
- 授权：diagnostic-only；formal/T1/T2/qualification 均为 false，credit=0；不写 registry/ledger/denominator/gate/completion。

| seed | plans | checkpoints | launch |
|---:|---:|---:|---|
| 17 | 32 | `1e191bf26505db380c05712b00c099c0ff6f303954065dc02d5da7a13b9ace6b` | `blocked_fail_closed` |
| 29 | 32 | `d7014bb654f43a2e8a0a82dcd1ac2602aaf4d8e334fbbdbd34f725d4efd480dc` | `blocked_fail_closed` |
| 43 | 32 | `d9b7ff43433ff8732e551a0eacf75f7d862a5c267c3ce0f01ee52efafec69386` | `blocked_fail_closed` |

This is a source-bound graph_raw hidden16 current-manifest dry-run identity matrix only. It is not terminal runtime evidence and cannot increase formal training, T1/T2, qualification, denominator, ledger, registry, gate, or completion counters.
