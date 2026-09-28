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
| 17 | 32 | `19cf88df48e369ce061a7dcd11b28d5e30864f30075deaa8d245ddc6184293ca` | `blocked_fail_closed` |
| 29 | 32 | `4cd9dc78230a11cd14354e48d073fb7cfd2f7dfd2515d57b7a65cfe5c1edf215` | `blocked_fail_closed` |
| 43 | 32 | `c979614f7ae8e5d6e8924a9624d023c1633eb88a9fd28e5c04ad8d20ccddf2db` | `blocked_fail_closed` |

This is a source-bound graph_raw hidden16 current-manifest dry-run identity matrix only. It is not terminal runtime evidence and cannot increase formal training, T1/T2, qualification, denominator, ledger, registry, gate, or completion counters.
