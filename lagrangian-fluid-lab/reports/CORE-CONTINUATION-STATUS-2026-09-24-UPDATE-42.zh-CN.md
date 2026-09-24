# Core continuation status — 2026-09-24 UPDATE-42

## F8 R008 native-integrity 门禁盘点

Terra High（`gpt-5.6-terra`, high）只读对照 PLAN、冻结 R008 scope、当前 table/matrix/finite 实现及 CPU/native preflight 后，结论是：现有合同足够生成完整 raw-state finite 子证据，但不足以裁决完整 native-integrity，更不能形成 T1。它确认单次 q=.5 初态 preflight 不能推广到 15-case solver-state；当前 metric matrix 已固定 15-case 分母，却没有 native-integrity per-case result schema/aggregate。

关键状态：

- density `[950,1050] kg/m³` 与 Mach `<=0.0010125` 的数值界已冻结；fluid/non-fluid population、密度闭区间与时序窗口、post-run Mach reducer 尚未冻结。现有 table 的 fluid-only projection 与 finite evidence 的全 raw finite 是不同职责。
- `MassFluid` 已由 B/C/D 逐帧精确绑定；T1 scope 并无独立总质量 gate。不能将单次初态预检中的 `MassFluid×Nfluid` 与容差升格为新 gate。
- wall penetration threshold 已登记，但 physical signed-distance 对象、法向/墙面位置、粒子 population 与比较窗口未冻结；overlap 的距离阈值/周期最小像规则也未定义，二者应继续 open。
- `BoundNor` 当前仅有单个 baseline 初始几何预检，不是可推广的 15-case solver-frame gate；若做 execution-admission 检查，仍需逐例身份映射和覆盖证明。
- aggregate 需要固定 gate ID registry、逐例状态及 `open/missing/failed/passed` 语义；不能依赖动态“所有必需 gate”列表。

据此形成 native-integrity semantics proposal v1；Terra High 给出 `REVISE`，指出全保存轴扩张、`±H` 直接当物理墙面、质量升格为 T1 gate、以及聚合 gate registry 不可机器判定。v1 保留为审查历史；additive v2 已按上述边界修订并正在 Terra High 只读复审。两个 proposal 均不改变冻结 R008 scope、阈值、15-case 分母、执行许可或资格信用。

本轮只读运行 `core_campaign.py status` 的总览见 [UPDATE-41](CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-41.zh-CN.md)。未读取 production bundle/solver frame，未执行测试或 native/GenCase/solver/worker/GPU/queue。R008 readiness/T1/qualification credit 仍 false/false/0。
