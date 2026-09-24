# Core 计划续推状态 UPDATE-75

日期：2026-09-25（Asia/Shanghai）

## 本次完成

在 `core_formal_admission_audit._evidence_rows()` 增加 global qualification schema discriminator：只有精确 builtin string `core.qualification.v1` 的 top-level evidence 才进入 global T1 evidence 集合。synthetic、未知及缺失 schema 不会以 top-level `family/scope_id/T1_numerical` 提升 family 计数；此更改不改变嵌套 case-level rows 路径。既有 F3/F4 qualification JSON 均使用该 schema，回归断言确认仍计为 2 个 T1 families。临时 fixture 同时验证 synthetic、unknown、missing 不计数，合法 schema 按现有语义计数。

## 复核与验证

- `pytest -q tests/test_core_formal_admission_audit.py tests/test_core_formal_readiness.py`：15 passed。
- `python3 -m py_compile scripts/core_formal_admission_audit.py tests/test_core_formal_admission_audit.py` 与 `git diff --check` 通过。
- 指定 Terra High/high 静态复核未发现本范围 P0/P1，确认现有 F3/F4 路径与负例行为；无独立身份/effort attestation，因此不作为可审计的 Terra 身份证明或资格证据。

## 未完成与状态边界

该项只是 schema 过滤，不是来源认证。带正确 `core.qualification.v1` 标签的伪造对象仍可能进入 global T1 通道；当前没有 strict raw-byte/duplicate-key decoder、受信根与 source-bound verifier/capability，也没有 producer/runtime identity attestation。非 qualification schema 下的 nested case-level rows 仍按旧逻辑提取，需单独盘点与加负测。故此改动只能防止跨 schema 的直接 global T1 污染，不代表 V8/V12 consumer gate 通过。

本次只读取仓库内 F3/F4 qualification JSON 的 schema/字段兼容信息，并对临时合成 manifest/evidence 执行定向单测；未读取 production bundle 或 solver frame，未运行 GenCase/native decoder/solver/worker/GPU/queue。F8 R008 gate、T1/credit、F3/F4 一次性授权状态均未改变。
