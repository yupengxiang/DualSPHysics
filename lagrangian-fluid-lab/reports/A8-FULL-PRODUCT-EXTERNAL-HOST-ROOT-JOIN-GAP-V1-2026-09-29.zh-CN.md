# A8 full-product / external-host / trusted-root join gap（2026-09-29）

本增量边界补齐了现有 A8 合同之间的真实缺口：

- `a8_full_product_receipt_manifest_verify_v1.py` 已经绑定 reader、autonomous prediction、scoring 以及 reader→prediction→scoring digest chain，但它只验证 package 中声明的 source/reproduction identity；
- `a8_trusted_root_external_host_attestation_contract_v1.py` 已经绑定 distinct data-root、trusted-root placeholder 与 external-host placeholder，但没有绑定 full-product package 的 run identity、manifest/receipt digest 和三类 artifact-chain digest。

新增 join verifier 只接受 bounded synthetic projection，并要求以下五类投影共享同一个 canonical cross-binding identity：

1. package-level manifest/receipt 与 reader、prediction、scoring chain；
2. source/reproduction host、physical-host、data-root 及各自 manifest identity；
3. trusted-root review placeholder；
4. external-host attestation placeholder；
5. full-product join receipt placeholder。

合成突变测试覆盖 package run identity、artifact chain、trusted-root source manifest、external-host reproduction identity、重复 physical host/data-root、未知 caller authority 字段、cross-binding digest、terminal receipt 和 symlink 输入。专项测试结果为 `16 passed`；`py_compile`、JSON/report validator、`git diff --check` 均通过。

该结果仍是结构性 gap 证据：`trusted_root_authenticated=false`、`external_host_attested=false`、`full_product_terminal_receipt=false`、`independent_reproduction=false`、`credit=0`。没有读取生产 HDF5/checkpoint/trajectory，没有启动 Popen、solver、worker、queue、GPU 或 native workload，也没有修改 registry、ledger、denominator、gate、completion、PLAN 或历史 receipt。

剩余 blocker：真实可信 root review receipt、真实 external-host attestation、绑定同一 package join 的 terminal full-product receipt，以及 Core independent-reproduction gate 所需的正式证据仍未提供。
