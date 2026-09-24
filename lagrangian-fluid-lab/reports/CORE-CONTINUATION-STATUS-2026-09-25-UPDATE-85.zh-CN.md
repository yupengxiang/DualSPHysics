# Core continuation status — UPDATE-85

日期：2026-09-25

## 本轮推进

为 F4 `verify_qualification_receipt()` 调整校验顺序：读入 JSON 后先快照并要求 exact builtin `core.qualification.v1` schema，再检查 family，之后才读取 scope 并进入范围/hash/evidence 校验。新增 synthetic/missing-schema 回执负测，以不匹配的 family/scope 和空 matrix 验证 schema 错误优先发生。

兼容性检查发现 `core_production.next_batch()` 的 UPDATE-84 discriminator 会拒绝 F4 tall-wall connector 从 evaluator summary 构造、但原本没有顶层 schema 的 qualification。故 `_receipt_summary()` 现在输出既有的 `core.qualification.v1` 标签；更新 8→24 合成决策 fixture，确认 connector 的 bound-audit 路径仍兼容。

## 验证

- `test_core_production.py`：3 passed。
- F4 runner synthetic schema、hash-verified 合成回执和纯决策分母测试：4 passed。
- tall-wall connector 合成 bound-audit 8→24 测试：1 passed。
- 合并定向回归：8 passed；相关文件 `py_compile` 与 `git diff --check` 通过。
- 测试只使用仓库静态设计/矩阵和临时合成回执/审计；没有读取已消耗的一次性授权回执，没有运行 connector proposal/prepare、GenCase、worker、solver、GPU 或 queue。
- Terra High/high reviewer 因 agent thread limit 未能启动；本轮无外部复核结论。

## 边界与未完成项

schema discriminator 只防 unknown/missing/synthetic schema 跨消费者传播；普通 JSON parser 仍未拒绝 duplicate keys，正确 schema 可由伪造文件标注，source-bound capability、trusted producer/root 与 runtime identity 仍缺。F4 runner 的 hash/evidence verifier 和 tall-wall connector 的 binding 校验各自保留，但尚不能替代这些信任根。不得据此视为 F4 production authorization、T1 资格或 V9/V12 consumer gate 完成；F8 R008 仍 `T1_numerical=false`、零资格信用。
