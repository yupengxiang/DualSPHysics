# F4 Tallwall120 material external receipt intake v1

- 状态：`blocked_missing_external_receipts`
- 诊断性、非授权；`launch_allowed=false`、`solver_authorized=false`、`gpu_authorized=false`、`credit=0`。
- 本 intake 只验证外部 producer 签名、单次 replay guard、root fresh namespace、scheduler host-I/O reservation 及 host/resource snapshot；不创建或消费任何资源。

## 当前 blocker

- `root.missing_or_not_object`
- `scheduler.missing_or_not_object`
- `pair.pair_id_equal`
- `pair.attempt_id_equal`
- `pair.nonce_equal`
- `pair.binding_sha_equal`
- `pair.pair_commitment_equal`
- `pair.counterparty_cross_bound`
- `pair.pair_commitment_recomputed`
- `root_receipt:missing`
- `scheduler_receipt:missing`

## 安全边界

- 当前没有真实 external receipt、trusted producer public key 或 replay guard，因此保持 fail-closed。
- 不启动 solver、worker、native、GPU 或 queue；不修改 registry、ledger、denominator、gate、completion、PLAN 或历史 receipt。

## 下一步

请由真实 root namespace producer 与 scheduler producer 写出带签名、一次性 replay guard 和 host/resource snapshot 的 receipt；禁止手工编辑、复用或合成 receipt，然后重新运行只读 intake。
