# F4 Tallwall120 archives/reader reconciliation v1

- status：`blocked_fail_closed`；source reconciliation ready：`False`
- archives-v1/v2 artifact identity exact：`True`；collection path exact：`False`
- reader manifest path exact：`True`；reader manifest SHA exact：`False`
- fresh root receipt present：`False`；scheduler host-I/O reservation present：`False`
- authority：`launch_allowed=false`、`formal=false`、`T1=false`、`T2=false`、`credit=0`。
- 本 intake 只读取有界 JSON metadata；不打开、读取或重哈希 trajectory HDF5，不启动 solver/worker/GPU/queue，不伪造 receipt。

## Blockers

- `collection_manifest_archives_v1_vs_archives_v2_path_drift`
- `reader_manifest_sha_stale`
- `fresh_root_receipt_missing`
- `scheduler_host_io_reservation_missing`

## Next safe action

由 collection authority 以不可变新回执把 DEV_07 collection row 重绑定到 archives-v2，由 reader authority 以同一 collection manifest 原始字节重做 smoke receipt；之后仍须由 root owner 与 scheduler 分别提供真实且 cross-bound 的 fresh root receipt 和 scheduler-owned host-I/O reservation。在全部条件满足前，不得启动 material sidecar、solver、worker、GPU 或 queue。
