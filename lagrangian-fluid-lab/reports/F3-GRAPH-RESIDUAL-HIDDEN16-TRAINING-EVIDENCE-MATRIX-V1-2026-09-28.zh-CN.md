# F3 graph_residual hidden16 三 seed training evidence matrix V1

- 状态：`training_evidence_bound_diagnostic_only`
- source-bound：`True`；fail-closed：`False`
- 范围：仅读取 bounded `core.training.v1` 与独立 training-matrix JSON 的 schema/hash/小字段；不打开 checkpoint、case HDF5、trajectory、progress、manifest，也不启动 GPU/solver。
- 授权：diagnostic-only；formal/T1/T2/qualification 均为 false，credit 与 formal training counted 均为 0。

| seed | 状态 | checkpoint SHA | init digest | normalization identity | residual prior |
|---:|---|---|---|---|---|
| 17 | `bound_complete` | `21dc97a619aa03f6ed9ea203a3d1a47e49c074bb65c5ae12ded66d0a022e16ac` | `ce74cb93b1144cf872fce13810c07e9cb14101ca1fe807b458ee1317bca53e89` | `4c7a988bbda1eb9f0597808c879ddf986446b461ecc653d1ac884aa8891cec1d` | `True/500` |
| 29 | `bound_complete` | `c5bc04436f12f5cba0de7ca3332e61634bfe87f2e78ac348516f8b6c4277731f` | `4f4f2555e47bd7b61843d4925eba9853c2f5c667c76f56846247c378d42830e3` | `4f2234df32a1670c8b1683704cff72bcc038bf3878bb73b2b5349bb1f1de7a34` | `True/500` |
| 43 | `bound_complete` | `81d51fd5a5c590fa84f02e20b7f9cffb31fc381453ddfd55e8632dbe108a108e` | `8bc6b9b9b11df237be1fb8c203941d659ced805a30fd0dd1c6eb81258c8e5368` | `7b3fdc679418cf3cd1e39615665fe349306152f3aad4ce7f2fb2d2bbb3cf0213` | `True/500` |

本报告是独立、只读、非授权的 graph_residual training evidence 绑定；即使三份 receipt 完整，也不计入 formal 9 runs，不产生 T1/T2 或 qualification credit。
