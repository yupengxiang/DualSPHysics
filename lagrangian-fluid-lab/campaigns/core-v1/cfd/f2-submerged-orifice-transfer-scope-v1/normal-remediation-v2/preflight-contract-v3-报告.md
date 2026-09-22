# F2 submerged-orifice v3 proposal-only contract

本交付只建立静态 contract，不实现也不调用 CPU/native preflight runner。Verifier 重新校验现有 `root-review-receipt-v3`、fresh Definition、`fresh-definition-contract-v2` 和 fresh Definition proposal 的 SHA-256、case identity 与权限边界。

新输出前缀绑定为 proposal 中声明的 `fresh-definition-v2/generated/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2`。本次没有创建 XML、BI4、job 或任何运行产物。

contract 明确列出六组 hard gates：零 BoundNor、零 NormalSize、IDs 唯一且与 native XML 对齐、数组有限、native mass 相对误差不超过 2.5%、以及 outer-wall endpoint 和 gate endpoint penetration 均为零。由于 v3 root receipt 的 `authorized_for_one_fresh_cpu_native_preflight` 为 `false`，六组 gate 状态均为 `pending_fresh_cpu_native_preflight`，当前不产生通过结论或 qualification credit。

GenCase、native decoder、solver、GPU、job creation、queue、ledger、registry 和 matrix submission 全部保持关闭；zero-normal 阈值不放宽，不允许 same-input retry 或 survivor renormalization。
