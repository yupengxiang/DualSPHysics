# F4 Tallwall120 material T2 sidecar aggregate join gap

本报告是一次只读审计，不是 receipt、admission 或 launch contract。审计范围仅为 F4 Tallwall120 material T2 的 32-case sidecar 路径；没有打开、读取或重新哈希生产 trajectory HDF5，也没有启动 solver、worker、GPU 或 queue。

## 结论

仓库已有的 `f4_tallwall120_material_sidecar_matrix_contract_v1.py` 已经实现了所需的 bounded source-bound aggregate join：以 `case_id` 连接固定 32-case denominator，逐案检查 sidecar 的 source path/SHA、split、完整 event window、material markers 和 zero-credit 约束。因此本次不新增重复矩阵或 external-receipt adapter。

当前 join 仍 fail-closed：

- denominator 是完整的 32/32，但 material sidecar 是 0/32，complete sidecar 也是 0/32；
- collection 仍为 `archives-v1`（32 cases），而 sidecar contract 要求 `archives-v2`；source drift 为 32 cases；
- reader manifest SHA 和 receipt path consistency 尚未通过；
- fresh root/scheduler authority、scheduler-owned host-I/O reservation 和 terminal evidence 尚未出现；
- T1/T2/formal/qualification 均为 false，credit 为 0。

因此本次只记录 gap，不声称产生了新的数据集、sidecar、receipt 或资格进展。下一步需要真实 producer-issued、cross-bound、one-use authority receipts，完成 archives-v2 collection/reader refresh，再为 32 个固定 case 分别取得 fresh source-bound terminal material sidecar，最后重新运行已有 matrix contract。

审计输入、精确 SHA-256、边界和机器可读结果见同名 JSON 报告。历史 receipt、PLAN、registry、ledger、denominator 和 gate 均未修改。
