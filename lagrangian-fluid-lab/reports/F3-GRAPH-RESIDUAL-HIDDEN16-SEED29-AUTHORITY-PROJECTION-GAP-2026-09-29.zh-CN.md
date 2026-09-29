# F3 graph_residual hidden16 seed29 authority projection gap

- 状态：`blocked_projection_gap`
- 范围：`graph_residual / hidden16 / seed29 / test / 500 updates / 835 transitions / 836 frames`
- source admission receipt：当前未发现
- external scheduler authority：未提供；Ed25519 验证未发生
- trusted scheduler root/key：`/var/lib/dual-sph/f3-seed29-scheduler` 与 `/etc/dual-sph/scheduler-ed25519-public.key` 当前均不可用
- adapter authority：即使生成也只是内存中的 non-authorizing envelope
- runner consumable：`false`
- Popen / solver / worker / GPU / queue：`0 / 0 / 0 / 0 / 0`
- registry / ledger / denominator / gate / completion / PLAN 写入：`0`
- formal / T1 / T2 / credit：`false / false / false / 0`

## Fail-closed gap

只有真实 external scheduler authority、部署拥有的 Ed25519 public key、nonce、namespace inode、plan、source descriptors、scheduler-owned resource snapshot、GPU identity 和独立 consume claim 全部交叉验证通过，才允许生成短暂的非授权 projection。当前缺少 receipt/authority，不能用 caller claim、local GPU probe 或复制 JSON 字段补齐。

本报告是 residual seed29 专属 gap artifact；不写回 admission receipt，不让 runner 消费，不修改历史 receipt、registry、ledger、denominator、gate、completion 或 PLAN，也未读取生产 checkpoint/HDF5/trajectory。
