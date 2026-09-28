# F3 graph_raw hidden16 terminal runtime verifier V1

- 状态：`blocked_fail_closed`；source-bound：`False`；fail-closed：`True`。
- 输入：仅读取 bounded JSON receipt；不打开 manifest、checkpoint、evaluation、progress、trajectory/HDF5，也不启动、停止或重启 evaluator。
- Contract：三 seed training matrix + terminal completion matrix + full835 rollout identity + evaluator/launcher exit proof + independent HDF5 validator receipt。
- 绑定：graph_raw / hidden16 / 500 updates / F3_DEV_00_a0p903125 / test / 835 transitions / 836 frames / fresh 32-hex nonce；formal、T1、T2、qualification、credit 均为零授权。

| seed | 状态 | blocker |
|---:|---|---|
| 17 | `missing` | full835 terminal completion matrix is not bound for this seed |
| 29 | `missing` | full835 terminal completion matrix is not bound for this seed |
| 43 | `missing` | full835 terminal completion matrix is not bound for this seed |

该报告是独立 runtime evidence verifier 的诊断性结果，不改变任何 registry、ledger、分母、gate 或 PLAN 状态。
