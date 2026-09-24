# Core continuation status — UPDATE-91

日期：2026-09-25

## 本轮推进

F3/F4 T2 admission contract 分别加载两份 T1 receipt 后，现在先调用 `_require_qualification_schema()` 检查 exact builtin `core.qualification.v1`，之后才读取 T1/T2/matrix markers。新增参数化 synthetic read-probe 覆盖 F3 与 F4 两分支。

## 验证与边界

- `test_synthetic_qualification_rejected_before_t2_admission_markers`：1 passed（覆盖 F3、F4 两个 helper 调用）。
- `py_compile` 与 `git diff --check` 通过。
- 未调用 `build_contract()`/`verify()`，未读取固定 F3/F4 qualification、材料历史审计或 HDF5；无 solver、worker、GPU、queue、registry/ledger 写入。
- 普通 JSON 与 schema 标签仍不认证原始来源、duplicate keys、scope-bound producer/runtime capability；T2 保持 false、zero credit。Terra High/high reviewer 因 agent thread limit 未启动，不记 PASS。
