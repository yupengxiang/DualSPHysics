# Core 计划续推状态 UPDATE-147

## 对齐 F4 历史收据测试与既有 schema 安全门

UPDATE-146 暂将 `test_real_first_eight_is_reader_hold_with_fixed_denominator` 排除；追溯 UPDATE-87 后确认，collector 明确要求 qualification receipt 在最外层带精确 legacy schema，旧 `qualification-tick.json` 的无 wrapper 形状必须 fail closed。为避免日后误把旧收据兼容重新引入，本轮将该过时成功断言替换为拒绝断言；不改生产代码、历史收据或 V13/formal gate。合成 diagnostic 成功路径仍由现有测试覆盖。

F4 collector、connector、V3 codec 与 formal-admission-readiness 定向测试现为 **61 passed**（不再 deselect 测试）；仅读取既有 design/batch/prepared/旧 tick JSON，未读取 HDF5、未启动 worker/solver/GPU/queue。此项是回归测试与既有安全合同对齐，不代表历史收据迁移完成或资格状态变化。
