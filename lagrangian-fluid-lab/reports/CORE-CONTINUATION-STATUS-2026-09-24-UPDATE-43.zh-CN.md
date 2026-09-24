# Core continuation status — 2026-09-24 UPDATE-43

## F8 R008 native-integrity v3 语义提案

Terra High 对 v2 给出 `REVISE`：有限性候选未覆盖 scope 字面要求的全部 state/control values；保存帧 ID 检查不能证明保存间隔内没有排除事件；`control_no_extrapolation` 必须明确到 `0..T_end`。

本轮只读核对 DualSPHysics 源码后新增 v3 提案。源码显示 CPU/GPU 每步采集 fluid exclusions，经 `JDsPartsOut` 累积到后续 `SaveData()`；非零记录写入 `PartOut`，逐 PART 计数写入 `RunPARTs.csv`。但零事件不会产生 `PartOut` item，`RunPARTs.csv` 依赖 Info 输出，现有 R008 C/D 证据链未绑定这些输出或完整结束证明。因此 v3 将 `excluded_fluid_particles_zero` 明确保留为 `open`，提出“逐段 RunPARTs 计数 + 非零 PartOut 记录 + 成功运行到冻结 T_end 的 receipt”作为未来候选合同，而不宣称现有证据足以判零。

`native_state_finite` 同样保持 `open`，要求先冻结覆盖 state、数值 metadata 与七个 control 列的机读 inventory；当前 `Pos[d]/Vel/Rhop` finite 扫描不得冒充完整 scope gate。控制 no-extrapolation 候选精确定义到闭区间 `[0,T_end]`，并与控制值 finite 检查分开。八 gate registry、15×8 分母、mass provenance、BoundNor 非 gate、wall/overlap open 均不变。

v3 提案： [F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V3-2026-09-24.zh-CN.md](F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V3-2026-09-24.zh-CN.md)。当前等待 Terra High（high）只读设计审查；无测试/生产 bundle/frame/native/GenCase/solver/worker/GPU/queue 访问或执行。R008 `native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false`、qualification credit=0。
