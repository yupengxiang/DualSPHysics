# Core 异机复现 typed-evidence/root-review adapter（UPDATE-311）

本 sidecar 是针对 UPDATE-298 缺口、建立在 UPDATE-300 typed-evidence preflight 之上的独立只读合同。它只消费确定性的 synthetic in-memory canonical JSON bytes，不调用或修改 `core_cross_host_root_review.py`、`core_independent_reproduction_preflight.py`，也不读取生产 bundle、历史 receipt、registry、ledger、gate 或 completion。

## 绑定内容

- 精确要求五类 typed evidence：`host_pair`、`data_roots`、`reader`、`prediction`、`scoring`；六个 role 必须完整且无重复：`source_host`、`reproduction_host`、`data_roots`、`reader`、`prediction`、`scoring`。
- 每个 role、两个 package manifest、三个 component output、UPDATE-300 preflight、既有 cross-host root-review decision 与 binding claim 均以 portable path、byte count、SHA-256 和 exact canonical JSON 绑定。
- source/reproduction hostname 与 physical host identity 必须不同；source/reproduction data-root 必须 canonical 后不同。
- reader → autonomous prediction → scoring 的输出 hash 链必须逐项相等；future-state 输入、formal 标记和 full-product 标记均 fail-closed。
- root review 必须符合既有 `core.reproduction.root_review.v1` 的 diagnostic decision：三个验证标记为真、`diagnostic_only=true`、`formal_training_count=0`、`full_core_reproduction_proven=false`，且 scope 与既有 F3 validation decision 精确一致。
- `trusted_root`、`root_trusted`、`root_authority` 等 caller self-asserted trust 字段直接拒绝；本 sidecar 不认证 trust root，也不铸造 capability。

## 结果与边界

synthetic fixture 成功绑定，结果固定为：

`diagnostic_only=true`、`capability_minted=false`、`formal_training_count=0`、`full_product_reproduction=false`、`credit=0`、`qualification_credit=0`。

这不是对真实跨主机执行、full-product reproduction、formal admission 或 scientific qualification 的声明。所有 workload、solver、worker、GPU/queue、registry/ledger/gate mutation 均为零。

专项回归为 **10 passed**；`py_compile` 与 `git diff --check` 通过。机器报告见 [JSON report](CORE-INDEPENDENT-REPRODUCTION-ROOT-REVIEW-ADAPTER-V1-2026-09-28.json)，实现见 [`core_independent_reproduction_root_review_adapter_v1.py`](../scripts/core_independent_reproduction_root_review_adapter_v1.py)，测试见 [`test_core_independent_reproduction_root_review_adapter_v1.py`](../tests/test_core_independent_reproduction_root_review_adapter_v1.py)。
