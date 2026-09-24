# Core 计划续推状态 UPDATE-74

日期：2026-09-25（Asia/Shanghai）

## 本次完成

修复 `core_formal_readiness._admission_observation()` 对 admission schema 的缺少前置检查：仅在 `schema` 是精确 builtin string 且等于 `core.formal_admission_audit.v1` 时继续读取 `family_summary`、validation 分母和 protocol。缺失、未知及 F8 synthetic Diagnostic schema 返回中性空 observation，并在 readiness 汇总中产生 `ADMISSION_SCHEMA` contract blocker。对应测试覆盖 exact synthetic Diagnostic、带伪造 gate 字段的包装对象、unknown/missing schema，并用读取探针断言拒绝路径只访问 `schema`；集成测试确认输出保持 `blocked`、不计入伪造 T1 family 或 validation cases。

## 复核与验证

- `pytest -q tests/test_core_formal_readiness.py`：6 passed。
- `python3 -m py_compile scripts/core_formal_readiness.py tests/test_core_formal_readiness.py` 与 `git diff --check` 通过。
- 按用户指定配置的 Terra High/high 静态复核认为本次 fail-closed 行为成立、未见有效 schema 路径回归、无 P0；该意见没有独立身份/effort attestation，故不记作可审计的 Terra PASS。

## 明确未完成与状态边界

这只是 schema discriminator，不是 producer/source authentication。`_load_json()` 仍以普通 JSON parser 先解析完整对象；尚无 duplicate-key strict decoder、受信根/FD-relative raw-byte reader、schema allowlist verifier、capability 或 loaded-runtime identity。自造对象若贴上正确的 production schema，仍可能进入既有字段解析；本修复不得用于声称 V8/V12 consumer gate 通过。

F8 R008 execution gate 仍 open，`T1_numerical=false`、资格信用为零。未读取 production bundle/solver frame，未执行 GenCase/native decoder/solver/worker/GPU/queue；未改写或重试 F3 row30、F4 supportcap 的一次性授权/回执。V12 admission producer/可信 ingress、其他 consumer 的 negative corpus、C V4 extractor/trusted producer/build-runtime closure 与正式 15-case T1 仍未完成。
