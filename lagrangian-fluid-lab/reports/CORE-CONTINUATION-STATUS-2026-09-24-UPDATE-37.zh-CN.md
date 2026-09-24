# Core continuation status — 2026-09-24 UPDATE-37

## Outcome

新增 [F8 R008 native-state finite evidence contract v1](F8-R008-NATIVE-STATE-FINITE-EVIDENCE-CONTRACT-V1-2026-09-24.zh-CN.md)，冻结下一阶段的 evidence-only 设计：对完整原始 BI4 帧逐帧、逐标量流式统计 `Pos`/`Posd`、`Vel`、`Rhop` 的 finite/NaN/±Inf 数量，并记录保留原生精度的极值位模式；non-fluid 粒子也纳入。raw-array 描述符和 SHA 必须重新与 C manifest、D safe-decode receipt/output manifest 对齐，不能只依赖调用方传入的成功布尔值。

单次输出绑定冻结 15 个 `qualification_only` 案例中的一个案例，但保留完整 15-case 分母含义；C/D 必须覆盖该 case 的完整冻结原生时间轴。JSON exact field-set、canonical UTF-8 格式、native dtype/type/shape 映射、位级 TimeStep 检查、extrema 并列规则及计数/字节上限均已规定。必须在同一组 held B/C/D roots/output FDs 下前后重验，要求 B/C/D receipt 均为 `passed`，表语义复核成功；任一身份或哈希变化即不发布。

## 静态审查与验证

Terra High（`gpt-5.6-terra`, high；agent `01a0d376-e477-7ab0-be6e-55325dc9de10`）对当前文档作最终只读复审，结论 `PASS`。复审没有编辑文件、运行测试或访问 production bundle/solver frame。

本次仅新增设计文档，没有实现 verifier，因此没有运行 pytest。对新增文档执行 whitespace/diff 检查通过；仅做了只读代码与冻结合同核对。

## 边界与后续

本次未读取 production B/C/D bundles 或 solver frames；未运行 GenCase、native decoder、solver、worker、GPU 或 queue。即使后续有限值 evidence 成功，也固定为 `native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false`、资格信用 0；不裁决 density、Mach、wall penetration、overlap、质量容差、BoundNor 或最终 15-case native-integrity 聚合规则。该扫描沿用同一 safe BI4 scanner，不是 decoder-diverse 复核，也不认证 solver/build/runtime/module 身份。

下一步是在 synthetic-only 路径实现 FD-preserving provenance/table 复核与分块 finite evidence producer，并用临时合成 BI4 覆盖 float32/float64、non-fluid NaN/Inf、D-manifest 篡改、源 FD 变化、拒绝状态及 canonical 序列化。该实现和测试不得读取 production frames 或启动 GenCase/native decoder/solver/worker/GPU/queue。详见 [PLAN.md F8 状态](../../PLAN.md)。
