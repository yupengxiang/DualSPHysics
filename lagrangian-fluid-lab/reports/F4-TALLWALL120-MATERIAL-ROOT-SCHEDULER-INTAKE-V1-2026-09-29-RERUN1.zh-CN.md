# F4 Tallwall120 DEV_07 material root/scheduler admission intake V1

- 状态：`blocked_missing_fresh_root_scheduler_receipts`
- scope/case：`F4_resting_pool_laminar_tallwall120_x_v1` / `F4_resting_pool_laminar_tallwall120_x_v1_DEV_07`
- proposal/host/sidecar：`True` / `True` / `True`
- source identity：`False`；collection path exact=`False`；reader SHA exact=`False`
- current material/collector/runtime hashes：`True`
- normalized argv/cwd：`True`；fresh namespace：`True`
- root receipt：present=`False` valid=`False`
- scheduler receipt：present=`False` valid=`False`

## Fail-closed 边界

本 intake 只读取 bounded strict JSON 与小型源码文件。DEV_07 trajectory HDF5 只做 lstat 元数据检查，未打开、未读取、未重哈希；未启动/停止 solver、worker、native、GPU 或 queue。

`diagnostic_only=True`、`formal=False`、`T1=False`、`T2=False`、`credit=0`。

## 阻塞原因

- `reader_identity_bound_false`
- `source_identity_contract_valid_false`
- `root_scheduler_pair_cross_binding_invalid`
- `fresh_output_namespace_receipt_cross_binding_invalid`
- `scheduler_owned_host_io_reservation_missing_or_mismatched`
- `root_receipt:future F4 fresh root receipt is missing`
- `scheduler_receipt:future F4 scheduler host-I/O receipt is missing`
- `root_receipt:root_receipt.missing_or_not_object`
- `scheduler_receipt:scheduler_receipt.missing_or_not_object`

未写 registry、ledger、denominator、gate 或 PLAN；完整 receipt pair 也不会被本 intake 晋升为 launch capability。
