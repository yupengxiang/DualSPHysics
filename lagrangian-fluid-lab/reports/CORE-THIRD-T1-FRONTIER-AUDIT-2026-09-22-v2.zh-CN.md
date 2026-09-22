# Core 第三个 T1 frontier audit v2（2026-09-22）

本版本保留 v1 的不可变历史决定，并补入当前 F8 Womersley 解析参考
oracle 的 hash-closed static contract。F8 仍只是候选：没有 Definition、
GenCase、native decode、solver、GPU、queue、registry、ledger 或分母变更，
`qualification_credit=0`。

当前 Core 仍为 `F3/F4`，第三 T1 family 未建立。F8 的参考 oracle 只验证
连续体解析接口、壁面无滑移、中心线对称、低频 Poiseuille 极限和零均值周期
通量；它不能替代 root 对非自由表面 F8 是否属于 Core 的解释，也不能替代
native preflight、受保护 anchor 或 13+2 资格矩阵。

本 receipt 是只读 frontier 状态更新，不覆盖 v1 审计，也不授权任何计算。
