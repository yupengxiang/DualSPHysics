# Core 独立复现证据 Assembly Envelope v1

日期：2026-09-28

本报告记录一个 additive、synthetic-only 的独立复现证据 assembly verifier。它处于既有两个合同之间：

- UPDATE-300 `core_independent_reproduction_preflight.py` 负责路径型 typed-evidence preflight；
- UPDATE-311 `core_independent_reproduction_root_review_adapter_v1.py` 负责把 synthetic typed evidence 绑定到既有 diagnostic root-review decision。

本 verifier 不消费上述任一结果，也不重新读取或解析 raw artifact。它只接受 bounded in-memory projection，检查五类 typed evidence、六个 artifact role、source/reproduction host、两个 distinct data roots，以及 reader → prediction → scoring 的 SHA-256 binding，并从规范化 envelope 重新计算唯一 digest。

## 机器结果

- verifier schema：`core.reproduction.independent_evidence_assembly_envelope.v1`
- report schema：`core.reproduction.independent_evidence_assembly_report.v1`
- 状态：`synthetic_only_non_authorizing_independent_reproduction_assembly`
- envelope SHA-256：`6d9529e82bc3681f7524939902758f7b561a50b0f8d130a2c1caf4c308b36446`
- `envelope_hash_recomputed=true`
- typed evidence categories：`host_pair`、`data_roots`、`reader`、`prediction`、`scoring`
- artifact roles：`source_host`、`reproduction_host`、`data_roots`、`reader`、`prediction`、`scoring`
- `diagnostic_only=true`、`capability_minted=false`、`full_product_reproduction=false`
- `credit=0`、`qualification_credit=0`、`formal_training_count=0`

envelope 中同时保留了两个 manifest descriptor、三项 component output descriptor、六项 role descriptor、host/root projection 和完整的 reader→prediction→scoring hash chain。规范化 JSON 使用 UTF-8、`sort_keys=true`、紧凑 separators、`allow_nan=false`；digest 由 verifier 派生，不接受调用方提供的 digest。

## 安全边界

本次仅使用脚本内部 synthetic projection；没有读取 production bundle 或 raw artifact bytes，没有启动 workload、solver、worker、GPU、queue，也没有写入 registry、ledger、denominator、gate、completion。输出文件采用新路径并拒绝覆盖已有 receipt。

该层只验证 assembly 关系，不能把 projection 中的 host、data-root、artifact hash 或 component 断言升级为可信来源、真实异机执行或正式产品复现。物理 host 身份、生产 artifact 内容、root review、执行来源和最终 Core gate 仍需由各自的可信合同闭合。

## 验证与未解决阻塞

- focused pytest：`10 passed`
- `py_compile`：脚本与测试通过
- `git diff --check`：通过
- 当前 Core `independent_reproduction` gate 不因该 diagnostic envelope 改变；仍不能授予 formal admission、full-product reproduction 或 qualification credit。
- 本 verifier 特意不重新验证 raw artifact bytes；下游若需要可信 hash/path 证明，必须消费 UPDATE-300/311 或另行认证的上游 receipt，而不能把本 envelope digest 当作 trust root。
