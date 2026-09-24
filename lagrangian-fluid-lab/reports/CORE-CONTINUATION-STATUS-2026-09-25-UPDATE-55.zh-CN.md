# UPDATE-55：F8 synthetic harness v2 follow-up 技术意见

日期：2026-09-25（Asia/Shanghai）

## 审查身份与结论

审查请求指定 `gpt-5.6-terra` / high；回复自述实际可见模型为 Codex/GPT-5，且没有 Terra High 子代理接口或独立身份 attestation。因此**不计作 Terra High 复核**。技术结论 `REVISE`，仅作为草案修订意见；未改代码、测试、冻结输入或执行状态。

发现：

1. 重复 JSON key 要求“完整 parse 后检测”还不够，必须明确 `object_pairs_hook` 保留每个嵌套 object 的完整原始键值 pair，不能让普通 dict 静默覆盖；重复键错误只在合法 JSON 完整 parse 后触发。
2. 深度预扫在 malformed strings/escapes 上需精确定义 scanner 状态和 `too_deep`/`bad_json` 优先级。
3. `MemoryError` 虽是 `Exception` 子类，但应明确列为不可恢复例外，与普通可捕获 `Exception` 的返回保证区分。

## v3 修订

新增待审 [v3 草案](F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V3-DRAFT-2026-09-25.zh-CN.md)，给出三态词法扫描器、超深输入的固定优先级、pair-list JSON object 表示及迭代重复键检查，并明文排除 `MemoryError` 返回保证。该草案仍没有代码或测试，也未获得 Terra High `PASS`；实现继续冻结等待符合配置的复核。

R008 真实 execution gate 仍 `open`，`T1_numerical=false`，资格信用为零。没有读取 production evidence，没有启动 solver/worker/GPU/queue/native/GenCase。
