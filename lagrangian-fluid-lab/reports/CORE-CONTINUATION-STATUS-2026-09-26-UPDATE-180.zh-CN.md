# UPDATE-180：F4 supportcap 新候选证据与预检适用性审查

时间：2026-09-26（Asia/Shanghai）

## 比较数据

| 证据 | 冻结观测 | 对候选的含义 |
|---|---|---|
| R001 原生 trace / 失败归因 | 512 个 t=0 几何种子被直接用于 t=0.160014986 s 的 native frame 40；frame 40→41 两帧可靠计数均为 0/512，512/512 unknown。支持距离门限为 0.03 m，观测最小/中位数/p95/最大值为 0.07814/0.13944/0.20067/0.20071 m。 | 明确存在时间原点错配；但不能证明它是唯一失败原因，也不能推出正确推进后的种子会通过其余 gate。归因脚本未重跑 canary。 |
| R002 static design v3 | 同一个 `f4_supportcap_affine_query_bound_v3`；规定从 native row 0 对原始 512 个种子起步，依次推进 0→1 至 40→41，以 row 40 推进后的状态评估末区间；`q=0.5`、`dp=0.0075 m`、2 substeps；固定 gate、分母、事件及 censoring 不变。 | 时间对齐修正是既有 v3 的 trace/setup 修正，不是已证明的新重建算法。静态回执明确 zero execution。 |
| R002 CPU/native preflight | 既有 attempt 仍绑定同一 v3，状态 `preflight_passed_runtime_not_authorized`，`same_scope_retry_allowed=false`；已核验 42 行输入窗及 10,326,356,548-byte source HDF5 摘要；tracer/canary 未启动。 | 旧 v3 预检 one-shot 已消耗，不能改名或复用；预检通过不证明候选通过，也不授权 runtime。 |
| v3 held-out synthetic calibration | 两种解析制造场、`q=0.375/0.875`；合成回执报告 mass closure 全通过及 source unknown budget 通过。 | 仅是原 v3 组合在合成条件下的校准，不含 native R002 轨迹结果，不能为另一个算法变体提供实证选择依据。 |

## 判断与边界

本轮判定：目前没有证据足以冻结一个与 v3 实质不同、且适合绑定用户所授权“新 F4 候选 CPU-native canary 预检”的算法候选。R001 的强归因指向输入状态时间错配；R002 已在 v3 内修正该对齐，但其相同 scope 的预检 one-shot 已消耗，且没有运行 tracer 或 canary。因此不能把改 candidate ID、重述 R002 时间推进、增加 support cap 或放宽 0.03 m / 其他固定 gate 当作证据支持的新候选。

本轮未创建候选、未运行预检或任何 tracer/native/solver/worker/GPU/queue；未访问新的 HDF5、未改 registry/ledger/qualification。用户对真正新候选的一次 CPU-native canary **预检**授权仍未消费；它不等于 canary/runtime 授权。T1/T2=false，资格 credit=0。

## 下一步实验建议

保留该 one-shot，直到出现独立于 R001 时间错配、可由既有源数据或先验分析检验的具体算法假设，并在不改固定阈值、512 分母、事件定义或 censoring 的前提下完成静态候选契约与测试。之后该预检只核输入与环境；是否运行 canary 仍须另有明确授权。若唯一假设仍是“正确 advect 后 v3 会怎样”，那是既有 R002 的未执行问题，不构成新候选。

## 依据

- [R001 failure attribution](../campaigns/core-v1/material/evidence/f4-supportcap-affine-query-bound-v3-cpu-native-canary-r001-failure-attribution-v1.json)
- [R002 static design recipe v3](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/r002-static-design-v3/recipe.json) 与 [review v1](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/r002-static-design-v3/review-v1.json)
- [R002 CPU/native preflight receipt](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/cpu-native-canary-preflight-r002-v1/preflight-receipt.json)
- [v3 held-out synthetic calibration](../campaigns/core-v1/material/evidence/f4-reconstruction-calibration-v3-20260922-result.json)
- [v3 candidate card](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/candidate-card-v3.json) 与 [Terra High static root review v4](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/terra-high-root-review-v4.json)
