# Core 计划续推状态 UPDATE-140

## F8 attempt-result observation time axis 与 B/C/D 冻结时间轴对照

在 UPDATE-139 的逐 attempt B/C/D 内容绑定上补充有限的 attempt-result 时间轴一致性检查。冻结合同有两个不同长度：完整 native C/D 轴为 321 帧；资格 observation window 是 full-axis inclusive indices `[128,320]`，共 193 帧。V2 `actual_frame_ordinals` 是 observation-window 内从零开始的连续前缀，因此本地 ordinal `j` 映射到 full native ordinal `128+j`，不能把 193 与 321 直接比较，也不能把 projection 的时间值与 full-axis 从 0 开始的前缀比较。

wrapper 从 pinned scope row 取得窗口索引、从已审查 verifier 的 frozen pack 构造 full axis，并要求 B/C/D verified chain 覆盖该完整轴；随后把 caller-supplied `actual_time_axis_ieee754_hex` 前缀与 full axis 的冻结 observation-window 前缀逐位比较。输出记录 ordinal origin 与 schedule-consistency 结果。此处只证明投影数值与冻结 observation schedule 一致，不证明这些值由实际执行产生；`attempt_result_frame_projection_crosschecked=false`、来源认证 false、attempt unresolved、T1 false、qualification credit 为零。

8 个跨模块测试文件 **312 passed**；新增合成测试覆盖完整 193 点 observation projection、错误时间前缀拒绝，以及原有 retry 分批、跨 attempt 换包、open attempt 与 byte/batch 限制。`py_compile` 和 `git diff --check` 通过。只使用临时合成 ledger/B/C/D/HDF5；未访问生产 bundle/frame，也未运行 GenCase/native decoder、worker、solver、GPU 或 queue。

仍缺 actual attempt-result producer/provenance、trusted worker/supervisor/runtime/loaded-module identity，以及完整来源验证的真实 15 行结果；本项不改变资源准入或正式执行门，Core 仍不可 finalize。
