# Core 独立复现 Assembly V1 ↔ UPDATE-311 Root-review 一致性桥接（V1）

本报告记录一个 additive、synthetic-only 的跨合同一致性桥接器。它只接受两个既有 verifier 已产生的 bounded canonical in-memory result projection：

- `core.reproduction.independent_evidence_assembly_envelope.v1`（Assembly V1）；
- `core.reproduction.typed_evidence_root_review_adapter.v1`（UPDATE-311）。

桥接器不读取两份报告文件，不读取 production artifact/raw artifact，也不重新实现 Assembly V1 或 UPDATE-311 的底层语义校验。它只重算 Assembly envelope digest、Root-review decision digest，并对两个结果投影做精确的跨合同等值检查。

## 交叉绑定内容

- source/reproduction host 与 physical host identity；
- source/reproduction data-root、package hash 和两个 manifest descriptor；
- 五类 typed evidence、六个 role artifact；
- 三个 component output artifact 与 component descriptor；
- reader → prediction → scoring 的完整 SHA-256 chain；
- UPDATE-311 root-review artifact、decision 及其 decision SHA-256。

所有投影必须是 canonical JSON、字段集合精确且不超过固定内存上限；缺字段、多字段、digest drift、host/root/manifest/output/chain/root-review drift 均 fail-closed。

## 机器结果

- report schema：`core.reproduction.independent_assembly_root_review_consistency_report.v1`
- status：`synthetic_only_non_authorizing_assembly_root_review_consistency`
- cross-binding SHA-256：`0939b2b7d47a74be3be20512c4539ee9d85d6be2856b9cf2a271ddb87626d5c0`
- Assembly envelope SHA-256：`7030b31ee54134b6c253a2711975b7e2ad0831b399e62e46d711ca81eafc086e`
- UPDATE-311 root-review decision SHA-256：`688e71e8dca1d8572595ef6b2da186453d51752838ff2ae1db822949089eadea`
- `diagnostic_only=true`
- `capability_minted=false`
- `full_product_reproduction=false`
- `credit=0`、`qualification_credit=0`

> 注：机器 JSON 中保存了完整的 root-review decision digest；本段只作人类摘要，不改变机器回执。

## 非授权边界

本桥接器不认证 trusted root，不把 diagnostic root-review decision 升格为真实异机复现，不产生执行 capability，不改变 Core `independent_reproduction` gate。`registry_mutation`、`ledger_mutation`、`denominator_mutation`、`gate_mutation` 和 `completion_mutation` 均固定为 `0`；没有启动 workload、solver、worker、GPU 或 queue，也没有接触正在运行的 F3 GPU rollout。

## 验证

- 专项测试：`13 passed`；
- Assembly/root-review/F8/preflight 相邻回归：合计 `52 passed`；
- 脚本与测试通过语法检查，JSON report 与 `build_report()` 精确相等；
- `git diff --check` 通过。

该桥接只证明两个 synthetic result projection 的结构和 lineage 一致，不能替代 production artifact 内容校验、真实异机执行、trusted root review 或正式 qualification evidence。
