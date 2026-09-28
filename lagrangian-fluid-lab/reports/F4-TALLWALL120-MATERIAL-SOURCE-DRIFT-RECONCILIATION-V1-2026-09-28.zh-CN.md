# F4 Tallwall120 DEV_07 material source-drift reconciliation v1

- 状态：`blocked_fail_closed`
- 结论：只读诊断；actual material sidecar 未执行，formal/T1/T2/credit 均关闭。
- source reconciliation ready：`False`
- fresh root receipt：`False`
- scheduler-owned host-I/O receipt：`False`

## 已确认的 drift / diagnostic 边界

- collection row exact path：`False`；当前 row 与 proposal target 的 archives-v1/v2 差异被显式保留。
- reader manifest SHA exact：`False`；stale reader SHA 不得被 manifest formal 声明覆盖。
- source SHA 一致（未重哈希 HDF5）：`True`。
- DEV_07 参数绑定：`False`；现有 diagnostic q=0.5，不可作为 q=0.234375 sidecar。
- full event window / unknown gate / reliable coverage：`False` / `False` / `False`。

## 取得 authority receipt 的最小外部输入

1. collection authority 提供 DEV_07 archives-v2 row，并给出当前 manifest 的精确 SHA256。
2. reader authority 提供绑定该 manifest path + SHA 的 reader receipt；reader smoke 不自授 formal/T1/T2/credit。
3. root owner 提供非 synthetic、single-use、未消费、fresh namespace + 64-hex nonce 的 root receipt，并绑定当前全部 hashes、normalized argv/cwd 和 scheduler counterparty。
4. scheduler 提供同 pair_id 的 scheduler-owned host-I/O receipt，绑定同一 hashes/argv/namespace、resource request、filesystem/snapshot/capacity 和 root counterparty。

## 当前 blockers

- `collection_manifest_archives_v1_vs_target_archives_v2_mismatch`
- `reader_smoke_manifest_sha_stale`
- `fresh_root_and_scheduler_authority_missing`

## 边界

- trajectory HDF5 仅做 `lstat`；未打开、未读取、未重哈希。
- 未写 authority receipt、material sidecar、registry、ledger、denominator、gate、completion 或 PLAN。
- 未启动/停止/重启 solver、worker、native、GPU、queue 或 scheduler。

下一安全动作：由 collection/reader authority 先提供修正后的 archives-v2 collection row 与绑定当前 manifest SHA 的 reader receipt；再由 root owner 和 scheduler 分别提供严格 cross-bind 的 fresh root receipt 与 scheduler-owned host-I/O receipt。在这些外部 authority receipt 全部存在且校验通过前，不得执行 actual material sidecar；当前 DEV_07 diagnostic 只能保留为 diagnostic-only。
