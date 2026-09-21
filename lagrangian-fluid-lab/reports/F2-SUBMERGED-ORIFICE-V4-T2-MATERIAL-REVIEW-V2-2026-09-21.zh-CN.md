# F2 submerged-orifice v4 材料/T2 边界复核

本报告只读复核现有 root-review receipt、v4 static candidate、exact-one CPU/native preflight 与父 scope；没有启动任何新 executable，也没有修改 solver、GPU、job、queue、ledger、registry 或 matrix。

复核结论：现有 v4 CPU/native preflight 为硬失败，`zero_boundnor=29484`、`zero_normal_size=29484`；finite、ID、端点和 2.5% 质量门通过，但整体 `preflight_pass=false`。因此该结果保持 `qualification_claim=none`、`qualification_credit=0`、`matrix_credit=0`。

父 F2 scope 仍是固定 15 行，当前 `executed=0`、`passed=0`、`failed=0`、`unattempted=15`、`credit=0`，所有 matrix row 仍为 `not_started`。CPU/native preflight 没有提交 matrix。

root-review receipt 原先记录 output prefix 未物化；本复核发现其后已有 preflight JSON、XML 与 BI4，因此把该静态 freshness 字段标记为历史快照过期，不覆盖旧回执，也不重跑同一输入。

T2 边界明确关闭：`T2_macro=false`、`T2_path=false`、`t2_status=not_established`。即使 CPU/native integrity 假设通过，也不能解释为 material T2、T1 或 matrix credit；同一 hard-failed input 禁止重试，不能放宽 zero-normal、finite/ID、端点或质量门。

材料边界 review receipt SHA-256：`a27eda0ba6abbf58c0977018148cbac07b531d073f74fe86eec955913db0813d`。
现有 preflight SHA-256：`db18863a97cb0a6d17a2cbb877e7b3df94368c96be4176728bd7b15b8a698685`。
