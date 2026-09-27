# Core continuation status — 2026-09-28 — UPDATE-263

## F3 formal/source admission closure audit v2

本轮新增独立只读、synthetic-only 的
[`f3_formal_admission_closure_audit_v2.py`](../scripts/f3_formal_admission_closure_audit_v2.py)。它阅读当前 F3 manifest、`CoreDataset`/fs-verity/source reader、`core_learning` fail-closed gate、`core_campaign` gate，以及已提交的 v1 capability validator 和 strict held-FD verifier；不打开 HDF5/FD，不调用 fs-verity，不导入生产 reader，不启动 worker/GPU/solver/queue，也不写既有生产状态。

机器收据为
[`F3-FORMAL-ADMISSION-CLOSURE-AUDIT-V2-2026-09-28.json`](F3-FORMAL-ADMISSION-CLOSURE-AUDIT-V2-2026-09-28.json)，schema 为 `core.f3.formal_admission_closure_audit.v2`。当前 manifest SHA-256 为
`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`。

结论固定为：`formal_eligible=false`、`qualification_credit=0`、`authorizes_formal=false`。

## 合同存在与可信运行时证据分离

| 项目 | 代码／synthetic 合同 | 当前可信 runtime evidence | 结论 |
|---|---:|---:|---|
| v1 capability envelope shape | 存在，且已有负测 | 不存在；validator 本身不授权 | `contract_only_non_authorizing` |
| strict held-FD bundle/session/attempt/replay shape | 存在，且已有负测 | 不存在；JSON sidecar 不持有或认证 FD | `contract_only_non_authorizing` |
| manifest source/hash/geometry/control metadata | 存在，32 case metadata 完整 | 不存在；这些是 content-addressed metadata，不是 source authority | `metadata_only` |
| reader/fs-verity measurement primitive | 存在，`CoreDataset` 与 `core_fsverity` 有局部原语 | 不存在；measurement 由 caller 提供，未绑定可信 producer/runtime authority | `primitive_only_no_authority` |
| producer/broker/worker identity | 仅 v1 synthetic envelope 可表达 | 不存在；生产 reader/learning path 未消费 identity/nonce chain | `synthetic_shape_only` |
| formal capability release | v1/strict 要求 release，`core_learning` 保持 fail-closed | 不存在；当前 manifest 为 `formal_release=false`，无绑定 capability release | `fail_closed_no_release` |
| production reader integration | v1/strict sidecar 文件存在 | 不存在；`CoreDataset`、learning/evaluation admission 未接入 sidecar | `isolated_sidecars_not_consumed` |
| `core_campaign` formal gate | 存在，拒绝 diagnostic/non-formal evidence | 当前不满足；registry 中 formal training/evaluation receipt 均为 0 | `gate_present_but_unsatisfied` |

这意味着 v2 没有重复实现 v1/strict 的 envelope 结构验证；新增闭合的是“合同是否接入生产 admission、是否有可信 authority、是否被正式 gate 消费”这一层。

## 当前 blockers

1. `F3_MANIFEST_FORMAL_RELEASE_FALSE`：manifest 明确声明 `formal_release=false`。
2. `FORMAL_CAPABILITY_RELEASE_UNBOUND`：manifest 没有绑定 capability contract、source authority、identity chain 或 release reference。
3. `SOURCE_MEASUREMENT_RUNTIME_AUTHORITY_MISSING`：held-FD/fs-verity 只是调用方提供的代码原语，没有可信 producer measurement/runtime authority。
4. `PRODUCER_IDENTITY_RUNTIME_AUTHORITY_MISSING`：没有可信 producer identity、nonce/session binding 或 runtime attestation。
5. `BROKER_IDENTITY_RUNTIME_AUTHORITY_MISSING`：没有可信 broker identity、nonce/session binding 或 runtime attestation。
6. `WORKER_IDENTITY_RUNTIME_AUTHORITY_MISSING`：没有可信 worker identity、nonce/session binding 或 runtime attestation。
7. `READER_CAPABILITY_INTEGRATION_MISSING`：v1/strict validator 是隔离 sidecar，未被 `CoreDataset` 与 formal learning/evaluation admission 消费。
8. `CORE_CAMPAIGN_FORMAL_GATE_UNSATISFIED`：`core_campaign` 只接受 formal/root-admitted evidence；当前 manifest、reader 和 registry 不能满足该门。

`core_campaign` 的现有拒绝条件保持有效：它会拒绝 `formal_eligible=false`、diagnostic/non-formal 或缺 root admission 的 receipt；formal training 还要求 `manifest_formal_release=true` 与 `validation_formal_eligible=true`。本轮没有修改这些 gate。

## 安全边界与验证

- 新增脚本、新测试和本 JSON/report 是本轮唯一写集；没有修改 manifest、reader、registry、ledger、denominator 或 gate。
- v2 + v1 + strict targeted suite：**29 passed**。
- `py_compile`：通过。
- `git diff --check`：待提交前再次执行。
- 没有伪造 authority，也没有启动 GPU、worker、solver、queue 或任何生产执行链。
