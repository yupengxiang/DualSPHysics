# F3 graph_raw hidden16 三 seed training evidence matrix V1

- 状态：`training_evidence_bound_diagnostic_only`
- source-bound：`True`；fail-closed：`False`
- 范围：仅读取 bounded `core.training.v1` 与既有 training-matrix JSON 的 schema/hash/小字段；不打开 manifest、checkpoint、case HDF5、trajectory 或 progress。
- 授权：diagnostic-only；formal/T1/T2/qualification 均为 false，credit 与 formal training counted 均为 0。

| seed | 状态 | evidence_status | checkpoint path+SHA | initialization | normalization |
|---:|---|---|---|---|---|
| 17 | `bound_complete` | `complete` | `/tmp/f3-graph-raw500-hidden16-seed17-20260928-checkpoint.pt` / `19cf88df48e369ce061a7dcd11b28d5e30864f30075deaa8d245ddc6184293ca` | `captured` | `16/16` |
| 29 | `bound_complete` | `complete` | `/tmp/f3-graph-raw500-hidden16-seed29-20260928-checkpoint.pt` / `4cd9dc78230a11cd14354e48d073fb7cfd2f7dfd2515d57b7a65cfe5c1edf215` | `captured` | `16/16` |
| 43 | `bound_complete` | `complete` | `/tmp/f3-graph-raw500-hidden16-seed43-20260928-checkpoint.pt` / `c979614f7ae8e5d6e8924a9624d023c1633eb88a9fd28e5c04ad8d20ccddf2db` | `captured` | `16/16` |

本报告是独立、只读、非授权的 training evidence 绑定；即使三份 receipt 完整，也不计入 formal 9 runs，不产生 T1/T2 或 qualification credit。
