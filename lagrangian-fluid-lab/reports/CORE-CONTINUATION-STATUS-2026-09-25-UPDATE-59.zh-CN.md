# UPDATE-59：F8 synthetic non-qualifying harness v4 修订

日期：2026-09-25（Asia/Shanghai）

按只读审查对 v3 的技术意见新增 [v4 草案](F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V4-DRAFT-2026-09-25.zh-CN.md)。修订内容为：

- 明确外层 `payload` 为 object，外层和 payload 内部各字段的精确类型。
- 在恒定 `gate_state="open"`、零信用之外，增加恒为 false 的 `qualification_authorized` 与 `execution_authorized`，并禁止下游从 diagnostic/token match 推导授权。
- 定义不能被 JSON array 伪造的私有 `ObjectPairs` 表示、递归重复键检测以及仅在全树无重复后转换为 dict/list。
- 规定专用 `NonStandardJsonConstant` 只映射到 `bad_json`，其他可恢复异常映射 `internal_error`；删除不可达的第二深度判定分支。

审查请求配置为 `gpt-5.6-terra` / high，但 reviewer 自述实际可见身份仅为 Codex/GPT-5，且无独立身份/推理等级 attestation。因此技术结论记为 `REVISE` 意见，不计作 Terra High 审查或 `PASS`。v1–v3 历史草案保留，不覆盖。

当前只有文档草案，无实现或测试；未接入 C-v1、未读取 production evidence，也未运行 GenCase/native decoder/solver/worker/GPU/queue。F8 R008 的 production execution gate 仍 open，`T1_numerical=false`、资格信用 0、无执行授权。下一步先取得符合 Terra High 要求的只读 v4 复核；通过后也只考虑纯合成 harness 实现。
