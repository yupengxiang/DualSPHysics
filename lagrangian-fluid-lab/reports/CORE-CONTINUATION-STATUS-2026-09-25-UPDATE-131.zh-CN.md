# Core 计划续推状态 UPDATE-131

## 本次推进：descriptor-only reader 不再重开 compact 输入资产

此前 `CoreDataset(snapshot_fds=...)` 已通过 held HDF5 FD 读取轨迹，但 descriptor-only 的 `known_inputs()` 路径仍会按 pathname 打开 compact geometry/control NPZ。现在：

- `known_inputs()` 对带 `known_inputs_ref` 的 descriptor-only row 在 source binding / pathname 访问前拒绝，直到存在 descriptor-backed input bundle。
- `_bind_sources()` 的 descriptor-only HDF5 读取和哈希路径不再打开或哈希 geometry/control pathname。
- `verify_sources()` 若所选 rows 有 compact path-backed inputs，则在任何 source hashing 前整体拒绝，避免把只验证 HDF5 误报成完整 source verification。
- `times()` / `read_state()` 仍可经 held HDF5 FD 工作；`formal_eligible` 继续固定为 `false`。

新增合成测试以 `_asset` 拒绝 sentinel 覆盖 `verify_sources()`、`known_inputs()` 的早期拒绝，以及 `times()`、`read_state()` 的 held-HDF5-FD 读取；断言没有 geometry/control pathname 调用。Terra High/high 只读 follow-up 对修订后的 descriptor-only 公共路径检查未发现 P1/P2。

## 验证与环境盘点

- `tests/test_core_dataset_compact.py` 与 `tests/test_core_contract.py -k 'not registered_f3_real_complete_axis_and_actual_updater'`：**40 passed，1 deselected**。
- `py_compile` 和 `git diff --check` 通过。
- 本会话较早的一次未过滤 reader suite 为 **41 passed**；其中既有 `test_registered_f3_real_complete_axis_and_actual_updater` 读取了本机 F3 注册 HDF5 作只读集成验证。该既有测试无写入；最终 scoped run 已排除此生产资产用例。
- 只读挂载盘点显示本地可写 ext4 为 `/` 与 `/home`；这两处临时文件的 fs-verity enable 已在 UPDATE-120 返回 `EOPNOTSUPP`。其他相关挂载包括 NFS `/data/nas` 与 tmpfs `/dev/shm`，没有发现新的本地 fs-verity positive candidate。未调用 sudo、未建挂载或改变系统状态。

## 边界与未完成

此项只消除 descriptor-only reader 对 compact geometry/control 路径的 pathname 依赖；它不创建输入 FD bundle、descriptor-root、可信 producer/supervisor/runtime 身份、active-key registry 或 capability，不改变 `CoreDataset.formal_eligible=false`，也不解锁 F8/Core T1/T2 或任何资格信用。fs-verity positive backend 和 trusted snapshot supervisor 仍需要合适的本地文件系统与后续系统级实现；F8 真实 provenance、15-case solver/T1、Core 正式训练/评测/异机复现仍未完成。
