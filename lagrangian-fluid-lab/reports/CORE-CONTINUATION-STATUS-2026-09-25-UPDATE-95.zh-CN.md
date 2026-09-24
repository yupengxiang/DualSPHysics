# Core continuation status — UPDATE-95

日期：2026-09-25

## 本轮推进

`core_formal_admission_audit._bound_adapter_cases()` 现在将 adapter schema 快照一次，并要求 exact builtin string 且属于注册 adapter schema 集合，之后才读取 manifest hash 或遍历 per-case rows。新增 synthetic Diagnostic read-probe，证明未注册 wrapper 在 case binding 前被忽略。

## 验证与边界

- `test_synthetic_adapter_rejected_before_case_binding`：1 passed。
- implementation/test `py_compile` 与 `git diff --check` 通过。
- 未运行全量 `audit_admission()`，未读取 F3/F4 manifest、真实结构回执、resource profile 或 graph probe；没有 planner/job spec/训练/worker/solver/GPU/queue 操作。
- 此 discriminator 只拒绝未注册 schema；注册 adapter Mapping/JSON 可伪造且缺 trusted source/root capability、duplicate-key/raw-byte/runtime identity。formal admission 仍 blocked。未获 Terra High/high 外部复核（agent thread limit），不记 PASS。
