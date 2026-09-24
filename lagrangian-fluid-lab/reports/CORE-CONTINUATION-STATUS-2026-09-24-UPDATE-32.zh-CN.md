# Core 接续状态 UPDATE-32：F8 R008 B/C/D native-fluid-table 集成

日期：2026-09-24

## 本轮推进

承接 [UPDATE-31](CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-31.zh-CN.md)，新增独立集成层，把已审查的 per-case B/C/D provenance verifier 与 native fluid-table v2 语义 verifier 串接。旧 verifier 源码和其已被 D 回执绑定的哈希未改写。

集成层在合成 fixture 中逐阶段验证 B/C/D，并要求 B 的 Definition/control 回执绑定与冻结 R008 pack 行完全一致；同时重读对应的冻结源文件字节并核验固定参数合同。它从 B 重新导出 fluid ID 与初始 MassFluid，从持有的文件描述符逐帧流式读取 C 原始 BI4，再验证 D 所绑定的 v2 HDF5 table。语义检查后重新闭合 B→C→D provenance，并再次核验冻结源；中途失败也会关闭源帧生成器及原始帧 fd。

Terra High（`gpt-5.6-terra`, high）对该集成实现的只读静态复核为 `PASS`。机器回执：[bundle review v1](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/bundle-review-v1/receipt.json)。回执固定了集成器、测试、v2 standalone verifier、既有 B/C/D verifier 与其审查回执、冻结 pack/scope 及参数合同的字节哈希。

## 验证结果与边界

- 跨模块回归 **119 passed**；独立审查归档完整性测试 **2 passed**。其中集成器 synthetic B/C/D suite 为 **10 passed**。`py_compile` 与 `git diff --check` 通过。
- 所有新集成测试仅使用临时合成 B/C/D receipts、BI4 与 HDF5；没有读取生产 bundle 或 solver frames，没有调用 GenCase、native decoder、solver、worker、GPU 或 queue，也没有修改 registry/ledger。
- 这是合成输入上的静态/软件集成结果，不是生产 B/C/D 产物验证。调用方 authorization authenticity、wrapper/module code identity 与 runtime assumption 仍是外部信任输入；该工具不做 native integrity、metrics、readiness 或 T1 adjudication。
- R008 v2 table producer/metric adapter 接入、完整几何/边界/法向审计、生产 solver frames 及登记的 15-case T1 尚未完成。F8 R008 仍 `readiness_pass=false`、`T1_numerical=false`、资格信用为 0；本轮不授予 solver/T1/worker/GPU/queue 执行权限。

## 下一步

完成冻结 Definition/control 对应几何、边界与法向的独立重算审计；随后补齐 v2 table producer/metric adapter 的合同与静态实现验证。生产帧读取、solver/T1 与其他运行时动作继续遵循各自的资源准入及明确执行门，不因本轮 PASS 自动开放。
