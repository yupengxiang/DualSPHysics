# Core 计划续推状态 UPDATE-151

## F8 R008 solver-timestep audit v2 follow-up

按要求由 Terra High（gpt-5.6-terra/high）进行只读静态复核，结论为 **REVISE**。审查确认 v2 matrix adapter 虽然对 source file 做了 no-follow、single-link、大小与哈希约束，却没有解析该文件；`max_solver_dt_s` 仍完全来自 audit JSON 的 caller claim。测试夹具也使用任意 `synthetic.log`，所以这些约束不能证明时间步数字是从 DualSPHysics 输出计算出来的。

源码核对显示 `JSph::SaveRunPartsCsv` 写出 26 列 PART 记录，`DtMax [s]` 是每个 PART 间隔的记录值；`SaveRunPartsCsvFinal` 追加 footer，且 CPU/GPU `FinishRun(bool stop)` 路径会调用它。因而 footer 或单个 CSV 哈希本身不能证明运行达到冻结终点：源码还存在 `NstepsBreak`、`TERMINATE`、minimum-fluid stop 等提前终止路径；输出文件以 append 模式打开，复用目录可拼接运行。Symplectic 下记录的 `PartDtMax` 也不等同于实际推进的 `stepdt`，除非执行配置绑定并确认算法。

本轮本地补丁只收紧 v2 JSON 输入：`max_solver_dt_s` 必须是 JSON number（拒绝字符串和布尔值），`checks` 必须精确等于冻结键集 `{"finite_positive_max_step"}`。matrix v2 定向测试 **49 passed**，未改动的旧 v1 metric-adapter 测试 **18 passed**，`py_compile` 与 `git diff --check` 通过。这仅关闭输入类型/额外声明的窄缺口，**不**消除上述 P1 来源语义问题；Terra High 未给当前 v2 implementation PASS，因此没有生成新的 PASS review receipt。

后续应按新 schema 设计受限 RunPARTs parser/producer，并在同一安全打开的源文件上重新计算 `max(DtMax)`；同时必须把 CSV 与专属 attempt、冻结 Definition/control、solver argv/binary、成功退出及完整终止证据闭合。缺少这些执行闭环时，解析结果只能作为零信用诊断，不得宣称完整 solver maximum、正常完成、T1 或 readiness。**未**运行 GenCase、native decoder、solver、worker、GPU 或 queue；资格 credit 仍为 0。
