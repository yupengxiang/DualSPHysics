# Core 计划续推状态 UPDATE-83

日期：2026-09-25（Asia/Shanghai）

## 本次完成

`core_campaign.completion()` 中从 qualification evidence 派生 scope T1 的两条路径（`scope_studies` 与 registered `scopes`）现在先调用 `_require_qualification_schema()`，只接受精确 builtin string `core.qualification.v1`；之后才检查 diagnostic/formal/root admission、scope/family identity、T1、extent、matrix 与独立性标记。

新增参数化 read-probe 测试，把两个入口分别注入 exact F8 V8 synthetic Diagnostic schema。probe 断言调用只读取 `schema`，然后拒绝；未接触任何 gate field。已有合成 negative qualification 与 scope/family 回归确认合法 schema 后的既有语义保持。

## 复核与验证

- `tests/test_core_campaign.py` 8 个纯合成定向节点：8 passed。
- `py_compile` 与 `git diff --check` 通过。
- 指定 Terra High/high 静态复核范围内通过；无独立 model/effort identity attestation，不作为审计身份或资格证明。

## 明确未完成与状态边界

此 schema discriminator 只是内容分类；`load_evidence()` 对路径与 registry 声明的 SHA-256 进行比较，但同一不可信来源仍可能共同伪造 registry ref 与 `core.qualification.v1` JSON。普通 JSON parse 仍不拒绝 duplicate key，也没有 root-bound raw reader、发布者签名、loaded-runtime identity 或可信 supervisor。Core campaign source-verification consumer gate 仍 BLOCKED。

本轮只使用 `tmp_path` synthetic qualification receipts；未读生产 campaign receipt，未执行 campaign 命令或生成 job，未运行训练、solver、worker、GPU、queue、native 或 GenCase。R008 T1 与资格信用状态未变；F3/F4 已消费的一次性授权和历史回执未修改或重试。
