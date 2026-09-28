# F3 MLP hidden16 current-manifest training evidence RERUN1

- 状态：`diagnostic_bound`；`source_bound=true`；`fail_closed=false`
- 范围：current-manifest 下的 MLP/hidden16、seed 17/29/43、每路 500 updates；仅消费 bounded `core.training.v1` receipt 与显式 manifest JSON。
- 授权：仍为 diagnostic-only；`formal=false`、`formal_training_runs_counted=0`、T1/T2/qualification 均为 false，`credit=0`。

| seed | run | training receipt SHA-256 | checkpoint SHA-256 | updates |
|---:|---|---|---|---:|
| 17 | `f3-mlp500-hidden16-currentmanifest-seed17-20260929` | `e5a90ab6784e57dcc4d573ba5e3608ed81c6f67d77fc3d39e285b201c63352a3` | `c1e41d29900e02e50fcf0a0435f8c3427e41761d8114858235c82a8847cf8897` | 500 |
| 29 | `f3-mlp500-hidden16-currentmanifest-seed29-20260929` | `1f112bbfb52f7649417f749a5216c5ad57c386f2f7506c3d08a0a5cc14122b3a` | `be4a789a3d769f97fb6fb535afa09c5d3df545ee5ffde6d533732008caf93a04` | 500 |
| 43 | `f3-mlp500-hidden16-currentmanifest-seed43-20260929` | `758a56942b57ddcb6dd23f44b586f6c5d7f5afc61b97c5b94bb75f9a534aa4c3` | `8916c6a710f0e567767df986ed9e810d6df8503e4a46b8a1970ea1fcadb202ac` | 500 |

Manifest identity is recorded without conflating two contracts:

- raw manifest-file SHA-256: `8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`;
- canonical payload SHA-256 used by `CoreDataset.manifest_sha256` and receipt `config.manifest_sha256`: `5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`.

The intake opened only bounded JSON/manifest metadata. It did not open checkpoint or HDF5 content, start a solver/GPU, read the historical matrix/registry/ledger, or mutate any formal gate. This report is not a promotion into the historical training matrix; the next independent step is current-manifest rollout evidence through the newly added parameterized launcher.
