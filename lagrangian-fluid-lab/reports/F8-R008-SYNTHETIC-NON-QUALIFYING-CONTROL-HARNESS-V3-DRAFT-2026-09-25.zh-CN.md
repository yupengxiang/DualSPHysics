# F8 R008 synthetic non-qualifying control harness v3（草案）

状态：v2 收到未认证 reviewer `REVISE` 技术意见后修订；审查请求虽指定 Terra (`gpt-5.6-terra`, high)，回复自述为 Codex/GPT-5 且当前无 Terra High 子代理接口，故不计 Terra High 审查。本文仍待符合用户指定配置的独立只读复核。它不是 execution-evidence schema/verifier，不授权或启动 solver/native/GenCase/worker/GPU/queue。

## 1. 职责与信任边界

本文件只定义纯内存 synthetic probe 的确定性 JSON 形状检查与两个不透明 token 的独立字符串比较。唯一成功诊断码为 `synthetic_bindings_match`，只表示两个 ASCII 测试字符串分别相等；不验证其原像、生成过程、相互关系、上下文、内容或来源。两个 expected token 可以来自不同上下文。

harness 不消费 C-v1、execution evidence、文件、FD、环境变量、日志、网络、registry 或 qualification API；不写文件、registry 或 receipt。`harness_performed_external_io=false` 只描述 harness 自身，不判断调用者传入内存 bytes 的来源。所有返回结果（包括 `synthetic_bindings_match`）都恒为 `gate_state=open`、资格信用 0、无资格或执行授权。

## 2. 纯函数 API、依赖和异常边界

唯一入口：

```text
diagnose_non_qualifying_synthetic_probe(
    raw_json_utf8: bytes,
    expected_scope_token: str,
    expected_qualification_row_token: str,
) -> Diagnostic
```

模块为确定性纯函数：无模块级可变状态、插件、动态导入、日志/遥测 sink、回调、全局 service locator 或依赖注入。静态 import allowlist 仅 `json`；其余操作使用语言内建，不导入文件、环境、网络、C-v1、registry 或资格模块。无 I/O 是实现属性，须以 AST import allowlist、依赖审计和文件/环境/网络/registry 无调用 spy 测试；本约束不是 Python 解释器或宿主机沙箱证明。

唯一异常边界覆盖参数处理、扫描、JSON parse、重复键/深度/shape 检查、比较和成功结果构造。任意可恢复普通 `Exception`（`MemoryError` 除外）映射至固定 `internal_error` 安全输出，不得外抛。`MemoryError` 明确视为不可恢复，即使其继承 `Exception`；`KeyboardInterrupt`、`SystemExit`、`GeneratorExit`、进程终止、解释器/宿主崩溃也不承诺返回值。上述不可恢复故障不能由本纯函数写 gate 或生成资格信用。

## 3. 输入约束与唯一解析优先级

按下列顺序执行，首个命中项唯一决定诊断码：

1. 输入参数类型：raw 必须为精确 `bytes` 类型；expected token 必须为精确 `str`、仅 ASCII 且匹配 `[0-9a-f]{64}`。不做 Unicode normalization、解码替换、大小写转换或 hash 运算。违反为 `invalid_arguments`。
2. 在解码和 BOM 检查前计算原始 byte 长度；大于 4096 为 `too_large`。BOM 计入此上限；长度合格但有 UTF-8 BOM 或非法 UTF-8 时为 `bad_encoding`。
3. 在完整 JSON parse 前运行下述 bounded lexical depth scan。其扫描状态机只有 `NORMAL`, `STRING`, `ESCAPE`：NORMAL 遇 `"` 转 STRING，遇 `{`/`[` 增加容器深度，深度首次大于 2 即返回 `too_deep`，遇 `}`/`]` 则在深度大于 0 时减 1；STRING 遇反斜线转 ESCAPE、遇未转义 `"` 返回 NORMAL；ESCAPE 消耗一个字符后返回 STRING。其他字符不影响深度；扫描不判定 JSON grammar、括号类型匹配、转义合法性或字符串闭合，交由 JSON parse。深度检查只计 JSON 双引号字符串以外的 ASCII 容器符号。若 malformed input 在 parser 发现语法错误前已观察到第三层开括号，固定优先 `too_deep`；否则后续 parse 决定 `bad_json`。
4. `json.loads` 完整解析 JSON，使用 `parse_constant` 明确拒绝 `NaN`, `Infinity`, `-Infinity`；语法错误、非法常量为 `bad_json`。传入 `object_pairs_hook`，将**每个嵌套 object 的全部键值对原序**保留为 pair-list wrapper，不构造会覆盖重复键的普通 dict。
5. 仅在完整语法 parse 成功后，迭代遍历所有 wrapper；任意 object 内键名重复即 `duplicate_key`。深度限制已在第3步按其固定优先级处理；若扫描没有观察到第三层容器，parse 成功的 JSON 必在深度限制内。
6. 转成无重复键的 object 后，执行 exact-field、类型、常量和 token pattern 检查；失败为 `bad_shape`。

唯一合法 JSON 结构：

```json
{
  "schema": "core.cfd.f8.r008.synthetic_non_qualifying_probe.v3",
  "payload": {
    "schema": "core.cfd.f8.r008.synthetic_non_qualifying_payload.v3",
    "mode": "synthetic_only",
    "probe_id": "fixture-001",
    "scope_token": "<64 个小写十六进制字符>",
    "qualification_row_token": "<64 个小写十六进制字符>"
  }
}
```

外层 exact fields 为 `schema`, `payload`；payload exact fields 为 `schema`, `mode`, `probe_id`, `scope_token`, `qualification_row_token`。所有值须为 JSON string；禁止 number、boolean、null、array 或额外/缺少字段。`probe_id` 匹配 `[a-z0-9][a-z0-9._-]{0,63}`。不签名、不使用 JCS；该文档不具权威性。

## 4. Output exact schema 与总决策表

输出 exact fields：

```json
{
  "schema": "core.cfd.f8.r008.synthetic_non_qualifying_diagnostic.v3",
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

五个布尔字段仅为 `payload_shape_valid`, `scope_binding_matches`, `qualification_row_binding_matches`, `registry_write`, `harness_performed_external_io`。`qualification_credit` 是 JSON integer 且恒为 0。所有行的 `schema`, `mode`, `gate_state`, `qualification_credit`, `registry_write`, `harness_performed_external_io` 分别恒为上例常量。其余结果严格如下：

| `diagnostic_code` | shape | scope | row | 唯一条件 |
|---|---:|---:|---:|---|
| `invalid_arguments` | false | false | false | 参数类型/expected token 不合规 |
| `too_large` | false | false | false | 原始 bytes >4096 |
| `bad_encoding` | false | false | false | BOM 或非法 UTF-8 |
| `too_deep` | false | false | false | 第3步观察到 >2 层；或第5步验证 >2 层 |
| `bad_json` | false | false | false | 深度检查后 JSON 语法非法或出现非标准常量 |
| `duplicate_key` | false | false | false | 未先触发 over-depth 的完整 parse 后，任意 object 的 pair-list 有重复 key |
| `bad_shape` | false | false | false | exact fields、类型、常量或 token 格式不符 |
| `scope_mismatch` | true | false | true | 仅 scope token 不等 |
| `qualification_row_mismatch` | true | true | false | 仅 row token 不等 |
| `scope_and_row_mismatch` | true | false | false | 两个 token 都不等 |
| `synthetic_bindings_match` | true | true | true | 两对 token 分别相等 |
| `internal_error` | false | false | false | 可恢复普通异常，除 MemoryError |

shape 有效时 scope 与 row 独立比较，因此单项失配时保留另一项真实比较值。任何解析/形状错误都令两个比较值 false。无 `ok`, `pass`, `defined_pass` 输出；成功码也不能改变 open/零信用。

## 5. 复核与实现边界

实现前待 Terra High 只读复核。未来仅可实现该纯内存诊断和纯合成测试，至少覆盖决策表每一行、键值对保留及任意嵌套 object 重复键、深度 scanner 状态转移/precedence、大小/BOM/UTF-8、非标准 JSON 常量、shape 变异、单/双 token mismatch、可恢复异常注入、output exact schema、import allowlist 和无 I/O/registry 调用。任何成功结果仍必须恒为 open 和零信用。

该 harness 不读取 C-v1，也不验证 invocation、input、horizon、process、termination、resource、build、trust 或 cgroup。独立 production execution contract 尚需逐项冻结 supervisor/event-source trust root、stage-role allowlist/resolver、execution journal 与 DAG、builder/source-to-binary、完整 solver call graph、逐 entry accinput 查询域、termination/reaping、cgroup membership 和 C-v1 activation。未完成前，R008 execution gate 仍为 `open`、`T1_numerical=false`、资格信用 0。
