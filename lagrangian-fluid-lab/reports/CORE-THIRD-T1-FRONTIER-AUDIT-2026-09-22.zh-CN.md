# Core 第三 T1 家族 Frontier 审计（2026-09-22）

本审计把当前第三家族候选路线放在同一条 hash-bound 证据链中，不新增资格、不修改 registry，也不运行求解器。

- **F1/F2**：当前 repair/topology 路线均为 `route_closed_no_new_hypothesis`，禁止同输入重试；重开必须有全新的可证伪物理机制和独立 root review。
- **F6 v10**：15 个 native preflight 通过，但已授权的 8-cell solver canary 只有 7/8 通过；`F6_OBS_V10_Q1P00_DP0P015_SPATIAL` 因 1 个流体粒子丢失失败，剩余 cell 明确未授权。
- **F7**：直接力矩方案的 root receipt 为 `NO-GO`；fresh Definition、native BI4 integrity receipt 和结果收据均不存在。
- **F8**：新提出振荡压力驱动通道，已完成官方语义的静态 hash-bound 检查，但仍是 `proposal_only_root_review_required`；没有 Definition、native preflight 或执行资格。

因此当前仍没有可登记的第三 T1 family。F8 只能等待 root 对 PLAN 的自由表面边界解释及独立 admission review。Core 必须保持未完成状态；不能用 F6 的 7/8 结果、F7 的 proposal、F8 的 proposal 或 F4 单家族 evaluator 绕过第三家族门槛。
