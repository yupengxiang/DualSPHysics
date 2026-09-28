# F4 Tallwall120 material case sidecar intake V1

- status: `blocked_fail_closed`
- case: `F4_resting_pool_laminar_tallwall120_x_v1_DEV_07`
- q: `0.23437500000000008`
- sidecar status: `missing`; present=`False`
- blockers: collection_dev07_source_identity, reader_identity_and_non_t2, sidecar_terminal_intake, missing_material_case_sidecar, archives_v1_v2_path_drift, reader_manifest_sha_drift

## 边界

本 intake 只消费 bounded JSON 与文件系统元数据；trajectory HDF5 只允许 stat，未打开、未重哈希。未启动 solver、worker、GPU 或 queue。

## 单案例契约

DEV_07 必须绑定 proposal、archives-v2 manifest、collection/reader identity、q、fresh output namespace、event-window terminal marker、mass closure、unknown fraction、reliable coverage 与 right-censor status。sidecar 缺失、部分终态或删失窗口均 fail-closed。

## 资格边界

diagnostic_only=`True`，formal=`False`，formal_eligible=`False`，T1=`False`，T2=`False`，credit=`0`。reader smoke 与 proposal 均不被提升为 T2。

## Mutation / execution

registry/ledger/denominator/gate/completion mutation 均为 `0`；HDF5 content read=`False`，HDF5 hash recomputed=`False`，solver/worker/GPU/queue started 均为 `False`。

机器报告由 `build_report()` 精确绑定；本文件只是其中文 companion。
