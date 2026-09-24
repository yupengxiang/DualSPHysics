# Core continuation status — 2026-09-24 UPDATE-49

## F8 R008 control-no-extrapolation 源码语义补充

对 DualSPHysics 控制输入和主循环做只读源码追踪后，确认静态 CSV 端点并不会自动阻止运行越过控制时间域：`JLinearValue::GetValue3d3d()` 在查询晚于最后采样点时返回最后一行；`JDsAccInput` 的 `time` 默认窗是 `[0, DBL_MAX]`。`TimeMax` 可被 CLI `TMAX` 覆盖，CPU path 还可被输出目录 `TERMINATE` 文件动态改写；`TOUT`/`TOUTX` 会改输出 cadence，`NSTEPS` 可提前结束，minimum-fluid 条件也会缩短运行时限。`-OPT <file>` 可递归加载最多 10 层配置，因此必须连同顶层 argv 一起闭合。CPU/GPU 主循环与 finish path 对这些情况的日志/退出语义并不完全相同。

此外，现有 B generated-XML cohort parser 只检查 `<particles>` 与 BI4 粒子身份，不检查 GenCase 输出 XML 中 solver 实际使用的 `TimeMax`、`TimeOut` 和 control-file reference；只绑定 GenCase 前的 Definition/control 源字节仍不足以证明 solver 输入。

因此 control gate 需要证明实际 solver 输入、运行 horizon 和正常完成状态均绑定到 frozen B Definition/control；完整 C/D 输出轴、receipt 的 `passed` 或进程零退出码单独都不充分。新增 [C 阶段执行证据合同草案](F8-R008-C-SOLVER-EXECUTION-EVIDENCE-CONTRACT-V1-DRAFT-2026-09-24.zh-CN.md)，枚举 argv/递归 OPT、GenCase 输出 XML、运行终态与资源证据的必要候选条件及未冻结边界，待 Terra High 只读设计复核。草案不是已冻结合同或执行授权。

本次仅读取仓库内 DualSPHysics 源码与已有静态合同；未运行测试、未读生产 solver 数据/帧、未运行任何 native/solver/worker/GPU/queue，也未更改 scope、阈值、分母、registry 或资源账本。所有 gate 与资格信用保持原状。
