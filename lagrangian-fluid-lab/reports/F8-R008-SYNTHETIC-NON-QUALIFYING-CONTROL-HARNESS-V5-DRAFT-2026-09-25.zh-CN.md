# F8 R008 synthetic non-qualifying control harness v5（草案）

状态：吸收 v4 的未认证技术审查意见及 UPDATE-63 的 source call-graph 事实后的新草案。审查请求即使指定 `gpt-5.6-terra` / `high`，当前 subagent 结果仍未提供可验证身份 attestation，故 v5 尚无 Terra High review。它不是 C execution evidence schema/verifier，不授权或启动 solver/native/GenCase/worker/GPU/queue。

## 1. 唯一职责与隔离类型

该组件只解析调用者交给它的合成 UTF-8 JSON bytes，验证精确 JSON 形状，并比较两个彼此独立、不透明的 token 字符串。成功只表示两个字符串各自相等；不表示 token 的来源、原像、上下文、签名、scope、row、运行或文件真实。

输入和输出都用固定类型标为 `mode="synthetic_only"`、`evidence_class="synthetic_non_qualifying"`。Diagnostic 不是 receipt，不得写盘、转封装为 execution evidence、进入 gate registry 或作为资格聚合的子证据。输出不含 `gate_state` 字段；全部输出恒有 `diagnostic_outcome="non_qualifying"`、`qualification_eligible=false`、`qualification_authorized=false`、`execution_authorized=false`、`qualification_credit=0`、`gate_transition="none"`、`registry_write=false`。token match、shape-valid 和任何 diagnostic code 都不能改动这些常量。

生产资格入口的消费者合同：在解析 score、credit、status 或其他 gate 字段前，必须硬拒绝该 v5 schema、`mode="synthetic_only"` 或 `evidence_class="synthetic_non_qualifying"`；未知／缺失 schema、mode、evidence class 一律拒绝且不产生 gate transition。真实资格只能由独立、版本固定、经 out-of-band activation 的 production verifier 产生。实现前必须盘点并给所有现存 admission、C-v1/per-case、T1 reducer、registry 和 finalizer consumer 加拒绝回归测试；在该盘点/测试完成前不得把 harness 结果传入这些入口。

## 2. API 与失败闭合边界

唯一入口为纯内存函数：

```text
diagnose_non_qualifying_synthetic_probe(
    raw_json_utf8: bytes,
    expected_scope_token: str,
    expected_qualification_row_token: str,
) -> Diagnostic
```

函数本身不作 I/O，不调用 filesystem、FD、环境、网络、日志 sink、callback、plugin、动态导入、C-v1、registry 或资格 API。实现静态 import allowlist 仅 `json`；无模块级可变结果、缓存或 service locator。期望 token 由调用者提供，不视为可信数据。

调用方每次调用前必须清空本次 result slot；只有当该次调用正常返回、返回对象精确匹配本 v5 Diagnostic schema 且 `evidence_class`/`diagnostic_outcome`/资格与执行常量全部相符时，才可读取其诊断。异常、超时、取消、进程退出、缺失/截断/无法解析的返回、类型不符或上次缓存结果，统一记为调用失败并拒绝；禁止默认补 `open`、复用上一轮结果或将无返回解释为授权。

参数错误、JSON/shape 错误及其他可恢复普通 `Exception` 均映射为完整固定 Diagnostic；`MemoryError`、`KeyboardInterrupt`、`SystemExit`、`GeneratorExit`、进程终止和解释器/宿主崩溃不承诺返回任何对象，调用边界仍必须按拒绝处理。内部异常映射固定为 `diagnostic_code="internal_error"`，不得外带异常文本、路径或环境信息。

## 3. 输入字节与唯一解析优先级

验证顺序固定，首个命中项唯一决定 `diagnostic_code`：

1. 参数必须是精确 `bytes`、精确 `str` 类型；expected token 为 ASCII 且**全串**匹配 `[0-9a-f]{64}`。实现应使用长度和逐字符检验，或等价的 whole-string fullmatch；不得用前缀匹配、Unicode normalization、大小写转换或自动 hash。失败为 `invalid_arguments`。
2. 在解码前检查原始 byte 长度；`>4096` 为 `too_large`。BOM 计入上限。其余输入有 UTF-8 BOM 或非法 UTF-8 为 `bad_encoding`。
3. 完整 JSON parse 前做 bounded lexical depth scan。扫描器状态严格为 `NORMAL/STRING/ESCAPE`，初始 depth=0；在 `NORMAL` 中，字符串外 `{`/`[` 令 depth 加一，刚到 3 即返回 `too_deep`；字符串外 `}`/`]` 在 depth>0 时令 depth 减一，在 depth=0 时保持 0。它不核对括号种类是否匹配、不判 JSON grammar，也不因 EOF 时 depth 非零而自行报错；这些 grammar 错误交给 parser。`STRING` 遇 `\\` 转入 `ESCAPE`，遇未转义 `"` 回到 `NORMAL`；`ESCAPE` 消耗下一个字符后回 `STRING`。故 malformed input 若按此有限状态扫描先观察到第三层则固定优先 `too_deep`，否则由 parser 决定 `bad_json`。
4. JSON parser 调用参数固定为 `json.loads(text, strict=True, object_pairs_hook=ObjectPairs, parse_constant=reject_nonstandard_constant, parse_int=JsonNumber, parse_float=JsonNumber)`；`JsonNumber` 是 parser 内部私有 marker，保留原数字 token text，不转换为 Python int/float。由于合法 schema 完全没有数字字段，任何 `JsonNumber` 都在 shape 阶段成为 `bad_shape`，同时避免大 integer 转换异常和 `1e999` 变成 infinity。`parse_constant` 对 `NaN`/`Infinity`/`-Infinity` 抛出专用异常且只在该 parse 阶段映射 `bad_json`；普通 JSON grammar 错误同样映射 `bad_json`。
5. `object_pairs_hook` 对每个 nested JSON object 建立私有 `ObjectPairs` wrapper（有序 key/value pairs）；数组保留普通 `list` 类型，不能用 list 同时表示 object/array。完整 parse 后递归检查每个 wrapper 的重复键；任意重复键为 `duplicate_key`。确认全树无重复后才能转普通 dict/list。
6. 最后检查 exact fields、字段类型、固定常量和所有 token 的全串格式；不符为 `bad_shape`。

超过两个层级的 scanner 错误先于 parse 错误；其他优先级严格按 1→6，不实现未列出的优先规则。不得让通用 int/float 转换在形状检查前接受、溢出或拒绝 numeric token。

唯一合法输入对象：

```json
{
  "schema": "core.cfd.f8.r008.synthetic_non_qualifying_probe.v5",
  "payload": {
    "schema": "core.cfd.f8.r008.synthetic_non_qualifying_payload.v5",
    "mode": "synthetic_only",
    "evidence_class": "synthetic_non_qualifying",
    "probe_id": "fixture-001",
    "scope_token": "<64 lowercase hex chars>",
    "qualification_row_token": "<64 lowercase hex chars>"
  }
}
```

外层 exact fields 为 `schema,payload`；`payload` 必须是 JSON object。payload exact fields 为 `schema,mode,evidence_class,probe_id,scope_token,qualification_row_token`，六个值必须全为 string。`probe_id` 必须整串匹配 `[a-z0-9][a-z0-9._-]{0,63}`。禁止额外／缺少字段、数组代替对象或 number/boolean/null。该文档无签名、无文件引用、无生产 evidence bytes。

## 4. Output exact schema 与唯一诊断表

所有返回对象 exact fields 为：

```json
{
  "schema": "core.cfd.f8.r008.synthetic_non_qualifying_diagnostic.v5",
  "mode": "synthetic_only",
  "evidence_class": "synthetic_non_qualifying",
  "diagnostic_outcome": "non_qualifying",
  "diagnostic_code": "invalid_arguments",
  "payload_shape_valid": false,
  "scope_binding_matches": false,
  "qualification_row_binding_matches": false,
  "qualification_eligible": false,
  "qualification_authorized": false,
  "execution_authorized": false,
  "qualification_credit": 0,
  "gate_transition": "none",
  "registry_write": false,
  "harness_performed_external_io": false
}
```

`diagnostic_code` 仅可为：

| Code | Shape | Scope | Row | 唯一条件 |
|---|---:|---:|---:|---|
| `invalid_arguments` | false | false | false | 精确参数类型/ASCII/full-token 检查失败 |
| `too_large` | false | false | false | raw bytes `>4096` |
| `bad_encoding` | false | false | false | BOM 或非法 UTF-8 |
| `too_deep` | false | false | false | 词法扫描先观察到第三层容器 |
| `bad_json` | false | false | false | 深度扫描后 grammar 非法或出现非标准常量 |
| `duplicate_key` | false | false | false | 完整 parse 后任一 object 有重复 key |
| `bad_shape` | false | false | false | exact fields/type/constants/whole-token shape 不符 |
| `scope_mismatch` | true | false | true | 仅 scope token 不等 |
| `qualification_row_mismatch` | true | true | false | 仅 row token 不等 |
| `scope_and_row_mismatch` | true | false | false | 两 token 均不等 |
| `synthetic_bindings_match` | true | true | true | 两个独立字符串比较均相等 |
| `internal_error` | false | false | false | 除不可恢复故障外的普通异常 |

上述表中除 `diagnostic_code`、`payload_shape_valid` 与两个 match booleans 外，字段常量在每一行均不可变；所有 parse/shape/internal error 的 match booleans 都为 false。`synthetic_bindings_match` 仍不表示资格通过。

## 5. 测试门与实现前置条件

本 v5 在实现前仍需要审查，审查人须给出可验证的 Terra High 身份与 high effort attestation；未经 attestation 的技术意见只能作为普通建议。审查后也最多只解锁纯内存 parser 和 synthetic negative tests。测试必须覆盖：表中每个 code、嵌套重复键、object/array 区分、depth scanner 状态与错误优先级、BOM/UTF-8/size、`strict=True` 和 `parse_constant`、token/probe_id 全串匹配、所有恒 false/no-transition 输出、MemoryError 与普通异常边界、调用端 result-slot 清空，以及逐个现有 production consumer 拒绝 v5 schema/mode/evidence class。

当前没有实现、没有 production consumer 拒绝测试或 parser tests；v4 与旧稿保留不变。未通过审查前不实现。即使 v5 日后通过，其任何结果也不能用于 R008 readiness、C-v1、native integrity、T1 或资格信用；真实 execution gate 仍为 `open`，`T1_numerical=false`。
