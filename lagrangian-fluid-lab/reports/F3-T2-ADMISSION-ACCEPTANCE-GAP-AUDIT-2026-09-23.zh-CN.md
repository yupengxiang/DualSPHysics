# F3 宏观 T2 admission/acceptance gap audit v2（2026-09-23）

本版本保留 v1 历史审计，不覆盖旧 receipt；仅把新提交的 native-MLS JSON acceptance bridge 纳入静态软件闭环。没有打开 HDF5、启动 solver/GPU/queue，也没有修改 registry、ledger、matrix 或科学分母。

当前结论：`T2_macro=false`、`T2_path=false`、`qualification_credit=none`。

## 新增 bridge

- adapter：`scripts/f3_native_mls_acceptance_adapter_v1.py`
- SHA-256：`bbbfe1b334e4433fa5f749884a355878b8e0a6b7eeadb68ed184989ae7d63f1c`
- 静态 contract closure：`true`
- bridge 只消费 JSON evidence；仍保持 `qualification_claim=none` 和 zero credit。

## 仍未通过的科学门

- source unknown 最大值：`0.015625`；固定门为 `0.01`。
- CDF 最大差异：`0.06103515625`；固定门为 `0.02`。
- 33 行矩阵：`33` 行，formal acceptance receipts=`0`。
- bridge presence gate：`true`；它不替代 exact source 与逐行 acceptance。

## 边界

这一步完成的是 acceptance 入口的代码闭环，不是 T2 资格。right-censored canary、超限 unknown/CDF、缺失 exact CFD source 和未完成 33-row receipt 仍必须保留在分母中。
