# F7 泵力计能力审计（2026-09-22）

本审计只读取官方 DualSPHysics v5.4 源码和当前 F7 root receipt，没有修改 Definition、启动 GenCase/native solver/GPU/queue，也没有修改 Core registry、ledger 或分母。

审计结果：官方 `JGaugeForce` 支持对 moving `mkbound=2` 的边界粒子计算聚合合力，并可写出 force magnitude 与 xyz 分量。但其当前实现：

- CSV 只保存聚合合力；
- VTK 只保存初始中心点和聚合合力；
- 不保存逐边界粒子力分布；
- 不计算或输出 `r × F` 力矩。

因此现有 F7 canary 的流体角动量有限差分只能作为响应代理，不能升级为直接壁面反作用扭矩，也不能证明泵循环相对于 F6 的独立性。

当前结论：`root_review_only_instrumentation_gap`，`qualification_credit=0`，所有受保护状态变更均为零。

若继续 F7，必须先取得新的 root review，并采用新的 scope/revision 与输出命名空间，至少满足以下一种方案：

1. 在 moving-boundary interaction 中增加 provenance 绑定的逐粒子力和 `r × F` 扭矩输出；或
2. 将 moving pump 边界分成独立、可哈希的扇区，证明各扇区合力及扭矩重建。

不能把角动量差分改名为扭矩，也不能复用现有 coarse canary 作为直接扭矩证据。
