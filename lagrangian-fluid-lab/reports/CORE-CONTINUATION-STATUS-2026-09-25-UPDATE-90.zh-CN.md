# Core continuation status — UPDATE-90

日期：2026-09-25

## 本轮推进

F3 row30 root-decision packet 的 `build_packet()` 现在在读取 candidate/status 或 T1/T2 标记之前，分别验证 readiness 和 qualification 的 exact builtin schema。新增参数化 helper read-probe，synthetic Diagnostic 对两个入口都只触碰 `schema` 并被拒绝。

## 验证与边界

- `test_synthetic_gate_schema_rejected_before_root_packet_markers`：2 passed。
- 脚本/测试 `py_compile` 与 `git diff --check` 通过。
- 未调用 `build_packet()` / `write_packet()`，未读取 row30 readiness/qualification 固定文件或 one-shot 回执；无输出覆盖、预检、调度或 worker。
- schema 标签仍不是 trusted raw-byte/source/runtime capability；当前普通 JSON parser、路径绑定和 capability 入口未闭合，row30 执行授权状态不变。未获 Terra High/high 外部复核（agent thread limit），不记 reviewer PASS。
