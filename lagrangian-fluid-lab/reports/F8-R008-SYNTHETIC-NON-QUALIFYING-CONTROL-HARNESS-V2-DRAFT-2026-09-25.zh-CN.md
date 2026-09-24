# F8 R008 synthetic non-qualifying control harness v2（草案）

状态：v1 收到未认证身份 reviewer 的 `REVISE` 技术意见后修订；该轮请求虽指定 Terra 配置，但回复自述为 GPT-5 基础配置，故不计作 Terra High 复核。本文待 Terra (`gpt-5.6-terra`, high) 只读审查。它不是 execution-evidence schema/verifier；不授权或启动 solver/native/GenCase/worker/GPU/queue。

## 1. 职责与信任边界

v2 仅定义纯内存 synthetic probe 的确定性形状/字符串比较诊断。合法 probe 的唯一成功代码为 `synthetic_bindings_match`，其含义仅为“两个不透明 ASCII 测试 token 分别与调用者传入的 token 相等”。它不验证 token 的摘要原像、生成过程、内容、相互对应关系或来源；两个 expected token 可以来自不同上下文。本接口不验证 scope、qualification row 或任何 execution evidence。

harness 不消费 C-v1、文件、FD、环境变量、日志、网络、registry 或 qualification API；不写文件、registry 或 receipt。它只能说明**harness 本身未执行外部 I/O**，不能说明调用者提供的内存字节最初来自 synthetic 还是 production。任何 `synthetic_bindings_match` 都仍然等价于 `gate_state=open`、零信用、无资格或执行授权。

## 2. API 与依赖约束

唯一公开入口：

```text
diagnose_non_qualifying_synthetic_probe(
    raw_json_utf8: bytes,
    expected_scope_token: str,
    expected_qualification_row_token: str,
) -> Diagnostic
```

实现为确定性纯函数，不设模块级可变状态、插件、日志/遥测 sink、回调、依赖注入或动态导入。导入 allowlist 仅为 Python 标准库 `json`；编码/类型/ASCII token 检查用语言内建操作。禁止 `os`, `pathlib`, `io`, `socket`, `subprocess`, `logging`, `importlib`、C-v1、registry、qualification 或 app-specific 模块。

无外部 I/O 是实现性质，不由输出布尔字段单独证明；实现审查必须核对 import allowlist，测试须加入模块依赖 AST 审计及对文件/环境/网络/registry 入口的无调用 spy。该约束不构成 Python 运行时或宿主机级隔离证明。函数不捕获/吞掉 `KeyboardInterrupt`、`SystemExit`、`GeneratorExit`；`MemoryError`、进程终止和解释器/宿主崩溃不保证返回诊断。任何**可恢复的普通 `Exception`** 均须由唯一异常边界转为 `internal_error` 安全输出，不得外抛或改变 gate 状态。

## 3. Input exact schema 和确定性解析顺序

1. `raw_json_utf8` 必须是精确 `bytes` 类型；expected token 必须是精确 `str` 类型且仅含 ASCII，并匹配 `[0-9a-f]{64}`。否则 `invalid_arguments`。不对 token 执行 hash、Unicode normalization 或大小写转换。
2. 在 UTF-8 解码/BOM 检查前，按原始 bytes 计算长度；大于 4096 bytes 返回 `too_large`。BOM 在此长度内计数，随后一律返回 `bad_encoding`。
3. 输入须为合法 UTF-8。
4. 在 JSON parse 前作深度预扫：容器深度从根对象计数，根 object 为 1、payload object 为 2；任意 object/array 深度超过 2 返回 `too_deep`。预扫只把 JSON 字符串外的 `{[ ]}` 识作容器符号，按 JSON 转义规则跳过字符串内容；此步骤先于 JSON grammar 校验，因此 over-depth 优先于后续 parse error。
5. 执行完整 JSON parse；语法非法或 `NaN`、`Infinity`、`-Infinity` 返回 `bad_json`。只有 parse 成功后才判定 object 重复键并返回 `duplicate_key`，因此语法错误优先于重复键错误。
6. 以上均通过后，执行 exact-field、类型、常量和 token 正则校验；失败为 `bad_shape`。

唯一合法结构：

```json
{
  "schema": "core.cfd.f8.r008.synthetic_non_qualifying_probe.v2",
  "payload": {
    "schema": "core.cfd.f8.r008.synthetic_non_qualifying_payload.v2",
    "mode": "synthetic_only",
    "probe_id": "fixture-001",
    "scope_token": "<64 个小写十六进制字符>",
    "qualification_row_token": "<64 个小写十六进制字符>"
  }
}
```

外层 exact fields 为 `schema`, `payload`；payload exact fields 为 `schema`, `mode`, `probe_id`, `scope_token`, `qualification_row_token`。不得有缺失或额外字段。所有值均为 JSON string；不允许 JSON number、boolean、null 或数组。`probe_id` 匹配 `[a-z0-9][a-z0-9._-]{0,63}`。本格式不签名，不使用 JCS；它没有权威性。

## 4. Output schema、状态决策表

返回值 exact fields 为：

```json
{
  "schema": "core.cfd.f8.r008.synthetic_non_qualifying_diagnostic.v2",
  "mode": "synthetic_only",
  "payload_shape_valid": false,
  "scope_binding_matches": false,
  "qualification_row_binding_matches": false,
  "diagnostic_code": "invalid_arguments",
  "gate_state": "open",
  "qualification_credit": 0,
  "registry_write": false,
  "harness_performed_external_io": false
}
```

恰有五个 boolean：`payload_shape_valid`, `scope_binding_matches`, `qualification_row_binding_matches`, `registry_write`, `harness_performed_external_io`。`qualification_credit` 是 JSON integer 恒为 0；其他常量字段也必须逐字固定。布尔值按下表唯一确定：

| `diagnostic_code` | shape valid | scope match | row match | 条件 |
|---|---:|---:|---:|---|
| `invalid_arguments` | false | false | false | 参数类型或 expected token 不合法 |
| `too_large` | false | false | false | 原始输入超过 4096 bytes |
| `bad_encoding` | false | false | false | UTF-8 BOM 或非法 UTF-8 |
| `bad_json` | false | false | false | JSON 语法非法或出现非标准常量 |
| `duplicate_key` | false | false | false | JSON 语法有效但 object key 重复 |
| `too_deep` | false | false | false | JSON 容器嵌套深度大于 2 |
| `bad_shape` | false | false | false | 字段、类型、常量或 token 形状不符 |
| `scope_mismatch` | true | false | true | 只有 scope token 不相等 |
| `qualification_row_mismatch` | true | true | false | 只有 row token 不相等 |
| `scope_and_row_mismatch` | true | false | false | 两个 token 均不相等 |
| `synthetic_bindings_match` | true | true | true | 两个独立字符串分别相等 |
| `internal_error` | false | false | false | 参数校验至结果构造范围内的可恢复普通异常 |

解析失败时两个 match 值恒为 false。形状有效时，分别比较两个 token，所以一项不匹配不掩盖另一项的真实比较结果。所有行的 `gate_state`, `qualification_credit`, `registry_write`, `harness_performed_external_io`, `mode`, `schema` 完全相同，分别恒为 `open`, `0`, `false`, `false`, `synthetic_only` 和上列 output schema 常量。没有 `ok`、`pass`、`defined_pass` 输出。

唯一异常边界覆盖参数检查、输入预扫、JSON 解析、形状验证、两个字符串比较与正常结果构造；捕获到可恢复普通异常时，返回 `internal_error` 对应的全 false 安全行。`MemoryError` 及进程/解释器失效属于不可恢复故障，不承诺能返回对象；由于纯函数没有 I/O 能力，它们仍不能写 gate 或生成资格信用。

## 5. 测试要求与 production 边界

实现前须经 Terra High 只读复核。之后只可实现该纯内存诊断与合成测试，覆盖决策表全部行、UTF-8/BOM/长度/深度 precedence、重复 key、非标准常量、所有 shape 变异、单项/双项 token mismatch、异常注入、output exact schema、import allowlist、无 I/O/registry 调用。测试断言成功代码也恒定 open/零信用；不得读取真实 attempt 或生产数据。

本草案不改变 C-v1 compatibility/activation，不打开任何 C-v1 receipt，不把任何结构性 `passed` 迁移为 execution gate。独立生产合同仍须解决 supervisor/event-source trust root、stage-role object allowlist/resolver、exact execution journal 与无环 DAG、builder/source-to-binary、完整 CPU/GPU control-query call graph、逐 entry accinput 查询域、termination/子进程回收、cgroup membership、C-v1 activation。上述未闭合前，R008 真实 execution gate 继续 `open`，`T1_numerical=false`、资格信用为零。
