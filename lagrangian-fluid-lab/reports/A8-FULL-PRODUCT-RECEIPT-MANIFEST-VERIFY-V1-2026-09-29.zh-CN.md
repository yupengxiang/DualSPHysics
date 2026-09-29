# A8 full-product receipt / manifest verify boundary（2026-09-29）

本闭环补齐了 A8 package-level 的真实缺口：现有 bridge 与 independent-reproduction preflight 分别提供 projection 和 typed-chain preflight，但没有统一验证 full-product receipt 是否与 package manifest 以及 reader、prediction、scoring 三类 artifact 做 exact binding。

新增 verifier 只接受 bounded synthetic JSON，并逐层绑定：

- `package_id / case_id / attempt_id / nonce / package_sha256`；
- source/reproduction 的 `host_id / physical_host_id / data_root`，且拒绝重复 host、physical host、data root；
- 三类 artifact 的 role、portable path、raw SHA-256、byte count、schema、run identity、reproduction identity；
- reader → prediction → scoring 的上游 digest chain；
- receipt 的 manifest ref 与 artifact map 必须分别等于实际 manifest 和 manifest artifact map。

未知字段直接拒绝，因此 caller self-claim、authority mutation、正向 full-product/independent/credit/checkpoint 字段都不能穿透。所有成功结果仍明确是 `verified_diagnostic_only`：`diagnostic_only=true`、`full_product_reproduction=false`、`independent_reproduction=false`、`checkpoint=0`、`credit=0`。

验证结果：专项 `14 passed`；`py_compile`、JSON 校验、`git diff --check` 通过。测试只在 pytest 临时目录生成 synthetic fixture，没有读取生产 bundle、HDF5/NPZ/checkpoint，没有启动 workload、solver、worker、GPU、queue 或 root，也没有修改 registry、ledger、denominator、gate、completion、PLAN 或历史 receipt。

剩余外部 blocker：trusted-root attestation、独立外部 host attestation、真实 full-product terminal receipt，以及 formal checkpoint provenance/qualification evidence 仍缺失；本闭环不授予任何 Core credit。
