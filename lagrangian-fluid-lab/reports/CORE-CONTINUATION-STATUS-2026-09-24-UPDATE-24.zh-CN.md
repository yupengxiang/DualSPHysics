# Core 续做状态（2026-09-24，UPDATE-24）

## 本轮推进

F8 R008 per-case provenance 的 Terra High v2 静态设计审查 PASS 后，完成 BI4/`bi4_dump` 静态格式审计 v1。审计交叉核验官方 DualSPHysics v5.4 writer、JBinaryData 类型与 byte-order 实现、`bi4_dump.cpp` 的递归输出代码，以及既有 R008 GenCase initial XML、decoder stdout、五个 decoded arrays 与 Q1 PartVTK 对照记录。

静态证据支持：评分所需每帧数组为 `Idp:uint32`、`Vel:float32[3]`、`Rhop:float32` 与按有效 solver 保存配置确定的 `Pos:float32[3]` 或 `Posd:float64[3]`。既有初态还含 `BoundNor:float32[3]`。所有 XML 声明的扩展数组需逐项纳入精确递归 manifest，不能静默忽略。`JBinaryData` 以 host byte order 加载并校验 BI4；decoder 把原生数组内存直接写出，故目标消费器需明确 `<` little-endian dtypes。decoder 不清理目标目录且不核验写流错误，后续实现需 fresh namespace 与 XML/file 精确闭合、no-follow、regular-file、`st_nlink==1` 检查。

边界仍明确：当前只有 GenCase 初始帧格式锚点，没有 R008 solver 输出帧，因而完整 solver 输出集合/cadence 尚未观察。历史 `bi4_dump` 是 ignored/untracked ELF；仓库未找到 build command。Q1 回执绑定 decoder 源码与外部 `JBinaryData.cpp`，但没绑定 header 或 binary；R008 preflight 也没记调用时 binary SHA。因此旧初态产物只作格式锚点，不能回填成 per-case decoder provenance。新 decoder receipt 必须绑定 executable SHA/build identity、argv、host byte order 与调用前后文件身份。

静态审计脚本与回执位于 `scripts/f8_r008_bi4_format_static_audit_v1.py` 和 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/bi4-format-static-audit-v1/receipt.json`；目标测试 3 项通过。已经向此前 Terra High reviewer 提交只读 follow-up，尚未收到结论。review 前不把审计状态记为独立审查通过。

## 权限与状态

本轮只读检查既有文件并生成静态审计文档/回执；没有运行 decoder、GenCase、solver、worker、GPU 或 queue。R008 仍 `readiness_pass=false`、零资格信用、无 solver 执行授权；F8 的 per-case provenance verifier 和正式 15-case T1 结果仍未完成。
