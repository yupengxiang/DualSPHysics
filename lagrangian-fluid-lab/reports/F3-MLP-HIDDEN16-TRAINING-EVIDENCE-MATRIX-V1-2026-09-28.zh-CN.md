# F3 MLP hidden16 三 seed training evidence matrix V1

- 状态：`training_evidence_bound_diagnostic_only`
- source-bound：`True`；fail-closed：`False`
- 范围：仅读取 bounded `core.training.v1` 与独立 MLP training-matrix JSON 的 schema/hash/小字段；不打开 manifest、checkpoint、case HDF5、trajectory 或 progress。
- 授权：diagnostic-only；formal/T1/T2/qualification 均为 false，credit 与 formal training counted 均为 0。

| seed | 状态 | model/hidden/updates | checkpoint | initialization | normalization |
|---:|---|---|---|---|---|
| 17 | `bound_complete` | `mlp/16/500` | `/tmp/f3-mlp500-hidden16-seed17-20260928-checkpoint.pt` / `8cd8304c2b8ebda145ec99b1faf1623a0fb222d582eaaabfa7cf00600fb9ceac` | `captured` / `ad6043377d15dcbd7d3d22c4f4c1a07549aa392db165dffca7039f9aee2f147c` | `16/16` |
| 29 | `bound_complete` | `mlp/16/500` | `/tmp/f3-mlp500-hidden16-seed29-20260928-checkpoint.pt` / `2be97da01924b0998b3605018da368cb9dca08b2dc0c638dfede77e329510e31` | `captured` / `45a5c8ee7bc4271ba4a9137f20800a34b63246855d5b704c7d6ef31b4af3b256` | `16/16` |
| 43 | `bound_complete` | `mlp/16/500` | `/tmp/f3-mlp500-hidden16-seed43-20260928-checkpoint.pt` / `68ba0d2c7966fa07bbd86106dceef7e1f5f00d7e4bca4aa5b1e42cb6133c0817` | `captured` / `b11c0467559a6065781a1876f79be96a9feb64023a98e107c17f919b03a4edb9` | `16/16` |

本报告是独立、只读、非授权的 MLP training evidence 绑定；即使三份 receipt 完整，也不计入 formal 9 runs，不产生 T1/T2 或 qualification credit。
