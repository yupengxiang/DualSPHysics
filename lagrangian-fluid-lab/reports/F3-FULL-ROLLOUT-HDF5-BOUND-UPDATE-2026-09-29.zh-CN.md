# F3 full-rollout HDF5 validator 尺寸上限修复

本说明对应 `f3_full_rollout_receipt_hdf5_validator_v1.py` 的独立、只读边界修复，不改变 formal registry、ledger、gate 或 PLAN。

## 变更

将 `MAX_HDF5_BYTES` 从 `512 MiB` 提升为固定的 `1 GiB`（`1 * 1024 * 1024 * 1024`）。当前 current-manifest 的 835-step、34560-particle trajectory 观测大小为 `723,147,992` bytes，因此仍有约 29% 的文件预算余量，同时不会把读取变成无限制读取。

validator 仍然：

- 通过 `O_NOFOLLOW`、单 hard-link 和两次同一 descriptor 读取绑定稳定文件身份；
- 对每次原始 HDF5 snapshot 施加同一个 1-GiB 上限；
- 在解析前拒绝 soft/external link、virtual dataset 和超出 link 数上限的结构；
- 保留 identity、shape、time、finite-state、tail、mass 和 `future_state_inputs=false` 检查；
- 任一不一致继续 fail-closed、返回零 qualification credit，且不写入输入文件。

这个上限下两份返回的原始 snapshot 合计最多 2 GiB，读取时的 1-MiB 分块组装另有固定上界；整体仍是明确的有限预算，不是对 HDF5 逻辑 shape 或 tail 约束的放宽。

## 回归覆盖

专属测试覆盖：

1. 观测的 `723,147,992`-byte trajectory（大于旧 512-MiB 上限）可以通过完整只读验证；
2. `MAX_HDF5_BYTES + 1` 在打开/读取前 fail-closed；
3. 旧的小型 fixture 仍通过，原有身份、shape、tail、future-state 和 unsafe-link 回归保持不变。

本次不启动 solver、worker 或 GPU workload，也不触碰运行中的进程。
