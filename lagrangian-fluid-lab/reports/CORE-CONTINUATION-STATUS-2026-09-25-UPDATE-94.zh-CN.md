# Core continuation status — UPDATE-94

日期：2026-09-25

## 本轮推进

为 F4 registry writer 的两个现有前置输入验证器增加 synthetic read-probe：`_validate_range_qualification()` 与 `_validate_collection()` 在读取 scope/family/T1/formal/evidence/case markers 前拒绝 `core.f8.synthetic_diagnostic.v1`。测试 monkeypatch `_load` 返回只允许读取 schema 的 probe，因此不访问固定数据或文件系统 registry。

## 验证与边界

- `test_synthetic_t1_inputs_rejected_before_registry_evidence_fields`：2 passed，分别覆盖 range qualification 与 formal collection。
- 测试文件 `py_compile`、`git diff --check` 通过。
- 未调用 `register_f4()`，未生成 qualification/case records、未写临时或正式 registry；无生产 evidence/HDF5 读取。
- 这只验证既有 JSON schema-first 顺序；`_load` 仍为普通 JSON，未解决 duplicate-key/raw-byte/source/root/runtime capability，也未通过 public writer 的隔离测试。正式 registry admission 仍 BLOCKED。未获 Terra High/high 外部复核（agent thread limit），不记 PASS。
