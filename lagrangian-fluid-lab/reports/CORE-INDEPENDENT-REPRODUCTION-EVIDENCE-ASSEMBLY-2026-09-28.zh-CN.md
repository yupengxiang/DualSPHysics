# Core 独立复现 typed-evidence 装配合同（2026-09-28）

本提交新增 `core.reproduction.independent_evidence_assembly_envelope.v1`，作为既有 UPDATE-300 typed-evidence preflight 与 UPDATE-311 root-review adapter 之间的纯结构装配层。它只接受有界 synthetic in-memory canonical JSON，不调用上游 verifier，也不读取生产 bundle 或历史 receipt。

装配结果覆盖五类证据和六个 role：

- source/reproduction host pair；
- source/reproduction distinct data roots 及 package manifests；
- reader、autonomous prediction、scoring 三个组件输出；
- reader → prediction → scoring 的 SHA-256 lineage；
- portable path、byte count、canonical JSON 和 artifact hash 的精确闭环。

缺 role/category、同 host、规范化后相同 data root、artifact/hash/bytes 漂移、chain hash rebind、非 canonical JSON 或 diagnostic 冒充 formal/product 均 fail-closed。成功结果仍固定 `diagnostic_only=true`、`capability_minted=false`、`full_product_reproduction=false`、`credit=0`，不铸造 trusted root 或执行权限。

机器回执的 envelope SHA-256 为 `9d2f234ad67c3732a434456f73255a3c9cbc5daa66bfdde2bc8cc877ae7a6314`。专项测试 `9 passed`，`py_compile`、JSON parse 与 `git diff --check` 通过；未启动 workload、solver、worker、GPU 或 queue，未修改 registry、ledger、denominator、gate、completion。该合同只推进证据结构，不能替代真实异机运行和可信 root review。
