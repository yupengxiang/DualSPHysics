# Core continuation status — 2026-09-27 — UPDATE-236

## F8 R008 bounded attempt/output binding diagnostic v1

针对 GPT-5.6 Luna Max 对 native-integrity proposal v6 的 P2 意见，新增 [`f8_r008_attempt_output_binding_diagnostic_v1.py`](../scripts/f8_r008_attempt_output_binding_diagnostic_v1.py) 及对应合成测试。该层要求 canonical exact JSON manifest，绑定 attempt ID/nonce、process-generation 字段、solver/config/Definition/control/initial-state SHA-256、fresh output-root dev/inode、writer identity 和逐文件 dev/inode/长度/SHA-256；使用 no-follow directory/file descriptor、稳定 stat/hash 复核，并拒绝 preexisting root、restart/append 声明、未列出的文件、符号链接、重复 identity、字节漂移及跨 attempt writer/file 拼接。

验证结果：binder 专项 **9 passed**；与现有 F8 fanotify parser、final-fput reducer v1/v2/v3、PartOut/RunPARTs diagnostic、registry 和 readiness v8 联合回归 **143 passed**；`py_compile` 与 `git diff --check` 通过。

该实现的成功结果是 `synthetic_structural_binding_verified`，只表示 caller-supplied manifest 与临时合成目录在读取时结构/字节一致。它明确输出 `source_authenticated=false`、`runtime_authenticated=false`、`native_integrity_evaluated=false`、`T1_numerical=false`、`gate_decision_eligible=false`、`qualification_credit=0`，没有接入 gate/registry，也没有认证 producer、supervisor、进程身份、fresh-root 历史或 native semantics。因此它不能把跨 attempt 反例升级为可信 T1 证据；生产路径、真实 writer inventory、terminal flush、raw PART/`RealStr`/OutputTime 仍未闭合。

本轮只使用 pytest 临时目录和 synthetic bytes；未打开生产 bundle/frame，未运行 GenCase/native decoder/solver/worker/GPU/queue。下一步是为 v7 合同实现 raw RunPARTs token/`RealStr`/stateful cadence 与 writer inventory 的 bounded diagnostic，并保持所有未认证结果为 `open`/`missing`。
