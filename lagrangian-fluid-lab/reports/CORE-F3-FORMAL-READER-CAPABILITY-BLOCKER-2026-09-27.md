# F3/Core formal-reader admission blocker — 2026-09-27

本报告只记录 F3 当前 reader/admission capability contract 的边界。新增的
`f3_formal_reader_capability_contract_v1.py` 是独立的 bounded validator；它不
导入或修改 `core_dataset.py`、`core_learning.py`，不打开 HDF5/FD，不验证真实
fs-verity，不认证进程身份，也没有 formal admission 权限。

## 当前已有与缺失

| 能力 | 当前状态 | 结论 |
| --- | --- | --- |
| held-FD/source snapshot | `CoreDataset` 支持严格模式下的 read-only FD、FD identity，以及可选的 fs-verity measurement；但调用方提供的 measurement 不是已认证 capability，且没有 producer/broker/worker 绑定。 | 局部能力已有，formal source trust 缺失 |
| geometry/control descriptor | F3 v2 manifest 的 32 个 case 都有 content-addressed geometry/control path + SHA-256 metadata。descriptor-only reader 会拒绝重新打开 path-backed asset。 | 静态 metadata 已有；同一 snapshot 的 descriptor bundle/rebind contract 缺失 |
| particle identity | manifest semantics 声明 `particle_zone,particle_id`，reader 也检查 identity/mass 轴。 | 这是粒子轴身份，不是 producer/broker/worker 进程身份 |
| producer/broker/worker identity + nonce | manifest、reader 和 learning admission 中没有 capability session、三方 identity、nonce 链。 | 缺失 |
| formal reader capability contract | `CoreDataset.formal_eligible` 固定为 `False`；`core_learning._manifest_formal_release()` 固定返回 `False`。 | 缺失，必须保持 fail-closed |
| manifest release | `campaigns/core-v1/f3-dataset-v2.json` 为 `formal_release=false`，schema 为 `core.dataset.v2`，32 cases。 | formal admission 必须拒绝 |

代码证据：[`CoreDataset` 的诊断/FD 边界](../scripts/core_dataset.py#L554-L566)、[`CoreDataset` 的 snapshot 初始化](../scripts/core_dataset.py#L624-L654)、[`descriptor-only` 对 path-backed 输入的拒绝](../scripts/core_dataset.py#L795-L802)、[`formal_eligible` 固定关闭](../scripts/core_dataset.py#L602-L606)、[`core_learning` 的 V13 fail-closed gate](../scripts/core_learning.py#L358-L366)。

当前 manifest 只读 inventory 的机器回执是
[`F3-FORMAL-READER-CAPABILITY-BLOCKER-2026-09-27.json`](F3-FORMAL-READER-CAPABILITY-BLOCKER-2026-09-27.json)，manifest raw SHA-256 为
`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`。

## 新增的隔离 contract validator

[`f3_formal_reader_capability_contract_v1.py`](../scripts/f3_formal_reader_capability_contract_v1.py) 只验证未来 envelope 的内部结构和绑定关系：

- source snapshot 必须声明 held-FD/fs-verity、same-FD、snapshot nonce、每 case 的 bytes/FD identity/measurement；
- geometry/control descriptor 必须有相对路径、版本和 SHA-256；每个 case binding 必须与 descriptor/source snapshot 一致；
- producer、broker、worker 必须各有不同 identity/nonce，并绑定 session nonce；
- `formal_release=false`、缺 source trust、descriptor rebind、缺失/重复 identity nonce 都产生确定 blocker code；
- 完整 synthetic envelope 可以证明“contract shape valid”，但该模块的 `authorizes_formal`、`formal_eligible` 永远为 `false`，`qualification_credit` 永远为 `0`。

这层 validator 不把任意 JSON 字段升级为信任证据，因而不能单独 closure 当前 formal-reader blocker。真实 closure 仍需要后续实现一个能由 broker 产生、由 reader 消费、并由 worker 校验的 capability；该实现必须把 held FD/source snapshot、geometry/control descriptor bundle、producer/broker/worker identity 和 nonce 绑定到同一 session。

## Synthetic negative tests

新增 [`test_f3_formal_reader_capability_contract_v1.py`](../tests/test_f3_formal_reader_capability_contract_v1.py)，共 **10 passed**，覆盖：

- 完整 envelope 只通过结构检查，不产生 formal authorization；
- `formal_release=false` fail-closed；
- 缺 source trust fail-closed；
- source snapshot rebind fail-closed；
- geometry descriptor rebind fail-closed；
- 缺失或重复 identity/nonce fail-closed；
- 当前真实 F3 manifest 的 metadata 不得晋升为 capability；
- validator 不修改输入 contract。

本轮没有修改历史 receipt、manifest、registry、ledger、denominator 或 gate；没有启动 GPU、solver、worker、queue 或 formal training。该任务的安全结论是：**可以新增隔离的 contract shape validator 和负测，但不能安全地宣称 V13 formal-reader admission 已 closure。**
