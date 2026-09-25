# UPDATE-164：F8 R008 exclusion-event 终端证据合同 v4

时间：2026-09-26（Asia/Shanghai）

## 设计审查

复核确认 PLAN UPDATE-44 已将 native-integrity semantics proposal v3 记为 Terra High PASS；v3 文件首页“待复核”是旧状态文字。本轮没有改写 v3，而新增 additive [proposal v4](F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V4-2026-09-26.zh-CN.md)，专门落实后续 review 提出的两项非阻塞 P3：精确说明排除事件采集调用条件，并冻结逐 PART event/RunPARTs 对账及 terminal flush 候选条件。

v4 明确：CPU/GPU cell-division 代码只在 `GetNpfOut()!=0` 时调用 `SaveFluidOut()`，不是每个 integration step 的无条件事件日志；未来证据要逐 PART 对齐 `RunPARTs.NpOut`、三原因计数、`PartOut.Nout`、`Idp`/`Motive` 数量、数组长度和 motive histogram；零事件时缺少 `PartOut` item 不能证明零排除。终止证据还需证明覆盖冻结 `T_end`、最后事件完成 flush 且无 pending `PartsOut`，否则 gate 保持 `open/missing`。

Terra High（`gpt-5.6-terra`, high）对 v4 只读设计审查为 **PASS**，无 P0–P3。审查核对了 CPU/GPU cell-division 调用点、`SaveData()` 原因计数、BI4 Motive 1/2/3 编码、`PartOut` 的零事件不写 item，以及 `FinishRun()` 不自动保证最终 `SaveData()`。审查指出未来 GPU 证据需独立闭合 GPU build/runtime identity；PART 序列还须绑定冻结输出调度、起点与非 restart/append 状态。v4 将这些作为实现前置条件，而非当前已验证证据。

## 边界与后续

v4 不改八 gate、阈值/单位、窗口、15×8 分母或资格边界。`native_state_finite`、`excluded_fluid_particles_zero`、wall、overlap 仍保持 open；没有生产 attempt、完整终止、可信 worker/source/build/runtime identity 或 native-integrity evidence。因此不能推出 F8 T1、readiness、solver 授权或资格信用。未读取生产 bundle/HDF5/frame，未运行测试、GenCase、native decoder、solver、worker、GPU 或 queue。

下一步可在这些约束下做 PartOut/RunPARTs 的纯合成结构解析与负测；该实现仍只能报告诊断或 `open/missing`，不能将未认证调用方数据升级为 gate pass。
