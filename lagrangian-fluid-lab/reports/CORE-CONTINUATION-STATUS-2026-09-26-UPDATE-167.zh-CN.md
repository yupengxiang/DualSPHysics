# UPDATE-167：PartOut Idp 与 CaseNp 范围一致性

时间：2026-09-26（Asia/Shanghai）

## 实现与独立复核

在 UPDATE-165 的合成 PartOut/RunPARTs 诊断解析器中，补充核验 PartOut 根项的原生 `uint64 CaseNp`：要求其存在且为正；要求每条排除记录 `Nout <= CaseNp`，并要求每个 `Idp < CaseNp`。所有 PartOut block 的根元数据（包含 `CaseNp`）必须一致。此前解析器只验证 ID 唯一，没有验证 ID 是否落在该案例声明的粒子身份域内。

该范围规则仅适用于冻结 F8 R008 15 项 qualification 定义；这些定义不启用 InOut/VRes 动态增粒。DualSPHysics 的 `JPartOutBi4Save::ConfigParticles()` 将总案例粒子数写入 `CaseNp`，`JSph.cpp` 以 `CaseNp-1` 初始化最大原生粒子 ID。此规则不得无条件复用于允许运行中动态增粒的其他 case family。

GPT-6 Luna Max 独立只读复核结论 **PASS（仅限冻结 R008）**：检查不会误拒上述 15 行，且 `Idp == CaseNp` 会被拒绝；审查指出动态 InOut/VRes 算例可能在初始 CaseNp 后创建更大的 ID，因此实现已明确标注不得跨该边界泛化。

## 验证与边界

- PartOut/RunPARTs 专项：**18 passed**，含等于 CaseNp 的越界 ID 与非正 CaseNp 负测。
- SAFE BI4、RunPARTs、native-state finite、native-fluid-table bundle 相邻回归：**75 passed**。
- `py_compile` 与 `git diff --check` 通过。
- 只使用测试现场合成 BI4/CSV；未读取生产 bundle/frame，未运行 GenCase、native decoder、solver、worker、GPU 或 queue；未改 registry、ledger、分母、F8 readiness 或资格信用。

所有输入仍属未认证诊断材料：一致时 exclusion gate 仍为 `open`，不一致时为 `missing`；没有 pass/fail、T1/readiness 或资格信用路径。Core 的总体完成状态不变。
