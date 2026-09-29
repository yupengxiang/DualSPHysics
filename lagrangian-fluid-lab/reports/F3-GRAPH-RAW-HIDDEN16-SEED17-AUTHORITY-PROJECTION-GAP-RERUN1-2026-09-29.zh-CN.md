# F3 graph_raw hidden16 seed17 authority projection gap

本次只修复 receipt schema projection/adapter 接口，不把本地字段提升为 authority，也没有改写历史 receipt。

## 结论

- 旧 receipt：`9d905d62efe69d9b131031fa35b6892b65dc1e1d498d0fb79b5926858df795be`
- 可投影字段：只有 top-level `authority` 非授权 envelope。
- 不可本地重建：`identity.external_authority`、签名关联的 `plan_sha256`、namespace descriptor、source/resource bindings，以及当前 consumption state 字段。
- 生产 scheduler root `/var/lib/dual-sph/f3-seed17-scheduler` 不存在；没有真实 seed17 signed authority document。
- 因此结果是 `blocked_projection_gap`，不是成功 admission，也不是 rollout result。

## 安全边界

adapter 只有在真实 external scheduler authority 通过 trusted Ed25519 key 验证，并同时绑定 nonce、namespace inode、source descriptors 和 resource snapshot 后，才会在内存中生成 non-authorizing `authority` envelope。该 projection 不写 durable receipt，不能直接消费 runner capability；必须由 producer 重新签发 current-schema receipt。

`Popen/solver/worker/GPU/queue` 均未启动；registry、ledger、denominator、gate、completion 和 PLAN 均未写入；diagnostic-only、formal=false、credit=0。

详细 JSON：[authority projection gap](F3-GRAPH-RAW-HIDDEN16-SEED17-AUTHORITY-PROJECTION-GAP-RERUN1-2026-09-29.json)。
