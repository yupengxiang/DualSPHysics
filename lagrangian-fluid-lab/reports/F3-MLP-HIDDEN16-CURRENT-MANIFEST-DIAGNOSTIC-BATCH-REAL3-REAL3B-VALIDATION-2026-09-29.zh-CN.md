# F3 MLP hidden16 current-manifest REAL3/REAL3B 验证整理

本文件与同目录的 JSON 汇总共同记录 REAL3/REAL3B。原始 REAL3 与 REAL3B 报告保持不改，fail-closed 证据保持不改；本文件只增加独立的只读验证结论。全部结果仍为 diagnostic-only、zero-credit，不构成 formal、T1、T2 或 qualification 证据。

## 结论

| 批次 | 原始报告状态 | 原始 fail-closed 证据 | 只读验证结果 |
|---|---|---|---|
| REAL3 | `blocked_diagnostic_batch` | 3 个 worker 均因 `_revalidate_input_snapshot` 缺失而未启动 evaluator；terminal receipt `0/3` | 无可验证 evaluator 输出 |
| REAL3B | `blocked_diagnostic_batch` | 3 个 case 均记录 `terminal_validator failed closed`；terminal receipt `0/3`、proof/sidecar 均为 0 | 3/3 个真实 evaluator 输出完成 835 transitions；当前只读 validator 对 3/3 返回 `passed=true` |

REAL3B 的历史阻塞与只读复核并不矛盾：启动时 validator 上限是 512 MiB，而每个 trajectory 为 `723147992` bytes，超过 `536870912` bytes，因此原批次 fail-closed；完成后以当前源码只读复核时上限为 1 GiB，三份输出均通过。只读复核没有补铸 terminal receipt、process proof 或 artifact sidecar。

## 真实身份绑定

- Manifest：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/f3-dataset-v2.json`；file SHA-256 `8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`，canonical SHA-256 `5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`。
- Checkpoint：`/tmp/f3-mlp500-hidden16-currentmanifest-seed17-20260929-checkpoint.pt`；64380 bytes；SHA-256 `c1e41d29900e02e50fcf0a0435f8c3427e41761d8114858235c82a8847cf8897`。
- Training receipt：`/tmp/f3-mlp500-hidden16-currentmanifest-seed17-20260929-training.json`；SHA-256 `e5a90ab6784e57dcc4d573ba5e3608ed81c6f67d77fc3d39e285b201c63352a3`。
- 选择的真实 case 为 `F3_DEV_01_a0p909375`、`F3_DEV_02_a0p915625`、`F3_DEV_03_a0p921875`，model 为 MLP hidden16，seed17，500 updates，test split。

## REAL3B 只读验证结果

| case | evaluation bytes / SHA-256 | trajectory bytes / SHA-256 | validator |
|---|---|---|---|
| `F3_DEV_01_a0p909375` | 6405269 / `f09e05e36cc0aa967242fc538b8903b8064d8e6d7eb50013d05c7b1e8ac7ece4` | 723147992 / `9551d25db7f7f7a95bb1335519f914d16aa834a3ecda057ae4be842762dce68f` | passed; complete; 835 frames; 7 HDF5 links |
| `F3_DEV_02_a0p915625` | 6404802 / `309b4d3e0697300ffa4f8d05c782023948793fd8d2ff8662d1cb8ad307474634` | 723147992 / `bbde9767a6a2c6348756d4bfad07810a5d27629b28143d62042251d4f2ecfa5b` | passed; complete; 835 frames; 7 HDF5 links |
| `F3_DEV_03_a0p921875` | 6405257 / `5e3e0d807119ce2e05103995ef51a2a3b9267cd8f7e49c79883c6d25a6be7911` | 723147992 / `fb176188dc84cea2a86ed036068a12973496738a96eeb6fda23d15b951599466` | passed; complete; 835 frames; 7 HDF5 links |

验证使用的 output namespace、完整路径和身份哈希详见同名 JSON。验证结果是内存中的只读结果，不是 terminal receipt，也没有写入任何正式 registry、ledger、denominator、gate 或 PLAN。

## 边界

本独立整理没有触碰、等待或发送信号给正在运行的 `c04c11/c12+` batch；没有重启或停止任何既有进程。REAL3/REAL3B 相关原始 JSON/Markdown 与本汇总均保持 diagnostic-only、zero-credit。
