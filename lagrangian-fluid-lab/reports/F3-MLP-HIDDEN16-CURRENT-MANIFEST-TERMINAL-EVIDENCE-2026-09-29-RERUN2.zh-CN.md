# F3 MLP hidden16 current-manifest terminal evidence RERUN2

- 状态：`terminal_diagnostic_verified`；`source_bound=true`；`terminal_evidence_verified=true`
- 范围：current-manifest 下的 MLP/hidden16、seed 17/29/43、每路 500 updates；case `F3_DEV_00_a0p903125`、split `test`、835 transitions / 836 frames。
- 结论：三路 terminal projection、process proof、evaluation identity、trajectory metadata、HDF5 validator、artifact identity 均完成交叉绑定；每路自然退出且 evaluator/launcher return code 为 0。
- 授权：永久 diagnostic-only；`formal=false`、`formal_eligible=false`、T1/T2/qualification 均为 false，`credit=0`、`qualification_credit=0`。本报告不进入 formal matrix、ledger、denominator 或 gate。

## Manifest 与 intake 边界

- raw manifest-file SHA-256：`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`，93710 bytes。
- canonical `CoreDataset.manifest_sha256`：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`。
- terminal intake 只读取 bounded projection JSON，并对外部 checkpoint、evaluation、trajectory、validator 做 lstat/声明身份检查；不打开 checkpoint/evaluation/HDF5 内容，不启动、停止或重启进程，不读写 formal registry、matrix、ledger、denominator、gate。

## 三路终态

| seed | run | namespace nonce | checkpoint SHA-256 | evaluation SHA-256 | trajectory SHA-256 |
|---:|---|---|---|---|---|
| 17 | `f3-mlp500-hidden16-currentmanifest-seed17-20260929` | `f17a9c4e2d6b8f1035c7e1a9d4b6c802` | `c1e41d29900e02e50fcf0a0435f8c3427e41761d8114858235c82a8847cf8897` | `48845d428c9d2c681a926cf2948c19a89b701dd5b37b3d410f56254ba268e204` | `9426b3eee4b9707def437f5befe5bf78d90a683d67bd2033ba62e6f78f669dcb` |
| 29 | `f3-mlp500-hidden16-currentmanifest-seed29-20260929` | `a29d6f3c8e1b5a7042c9f6d1b8e3a507` | `be4a789a3d769f97fb6fb535afa09c5d3df545ee5ffde6d533732008caf93a04` | `bf5e4d644f192be4313280689f2f20e12a58a1853cd88f85d0e541ad88ada8b4` | `4ee1bcd68a882cfce4fda93b3bc7c1b8497d1c299df89f41ecff00947c1c3d5c` |
| 43 | `f3-mlp500-hidden16-currentmanifest-seed43-20260929` | `c43e7a1d9b6f2c8054a8e3d7b1f9062c` | `8916c6a710f0e567767df986ed9e810d6df8503e4a46b8a1970ea1fcadb202ac` | `e1e9c5a02b127176e9d91b8ae51b00454f56f6d8946fe23c2d40d04b9cb7944d` | `4d17530ecaa7e8badd6670901db145572f9f8af0c44e54cf793fc814b7578bbe` |

对应 HDF5 validator SHA-256 依次为：

- seed17：`b552a9e4bd781ebde215d4fab29703dd40d06f697e51c5557436de57a67eba21`
- seed29：`7cdb88c38963a63210b3991e2f655ea6571ae0d581f63f8c7e62cdaa59d4b34c`
- seed43：`3081b3c494f41902a6895a01b51926061cae4e6bcbef5f4634ed90ba395b4b31`

正式 Core gate 仍未满足；下一步应继续处理 F3 material coarse admission、A8 独立复现 preflight 与 F8/R008 静态 readiness，而不是把本次 diagnostic evidence 提升为正式 credit。
