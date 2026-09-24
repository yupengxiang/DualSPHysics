# F8 R008 synthetic non-qualifying control harness v6（草案）

状态：V6 吸收 V5 的未认证技术审查 `REVISE` 和消费者首轮盘点。审查者要求把字段/异常/consumer/testing 契约写成可执行条件；未提供可验证 Terra High 身份或 effort attestation，故不记为 Terra High review/PASS。尚未实现或测试，不授权/启动 solver、native decoder、GenCase、worker、GPU、queue。

V4/V5 与其更新记录保持不变；在 v6 获得设计审查及实现前各项 release gate 之前，不实现 parser、不传递任何 synthetic 输出。

## 1. 类型隔离与 production consumer 契约

唯一入口只解析调用者交给它的合成 UTF-8 JSON bytes，验证精确形状，并比较两个彼此独立、不透明的 token。成功只表示两个字符串各自相等，不证明来源、原像、上下文、签名、scope、row、运行或文件真实。

V6 输入/输出类型固定为 `mode="synthetic_only"`、`evidence_class="synthetic_non_qualifying"`。Diagnostic 不是 receipt：不得写盘、转封装为 execution evidence、进入 registry 或成为资格聚合子证据。它不含 `gate_state`，输出资格/执行相关量恒定非授权、零信用、无 transition、无 registry write。任何 token match、shape-valid 或 diagnostic code 都不能改变这些常量。

所有 production ingress 必须先识别该入口的闭合、版本固定 schema allowlist，再检查禁止的 synthetic discriminator，之后才可读取 score/credit/status/gate 字段。缺失或未知 schema 一律 fail-closed；若输入格式定义 `mode`/`evidence_class`，缺失、未知或 synthetic 值均拒绝。旧 production schemas 不含这些 discriminator 时，只能按其各自的 exact schema/fields 解析，不能因缺字段而破坏既有 schema，也不能把任意 mapping 当作已验证对象。

Production gate 只接受由对应独立 verifier 完整验证、绑定原始证据 bytes/hash 和 verifier 版本的允许类型；不能接受调用者自行构造的裸 mapping。Harness Diagnostic 及任何复制字段、加/删字段、重命名 schema、重新序列化、包装/派生出来的对象，永远不能成为允许的 production 类型。到达 bytes 的 decoder 必须拒绝重复 key，禁止 key normalization/aliasing；后续适配器必须保留并验证同一来源绑定。若某现有 consumer 尚无法区分 verifier 产物与调用方伪造 mapping，则该 consumer 当前不具备接受资格证据的条件，状态保持 fail-closed。

V6 前置盘点及首轮发现见[消费者清单](F8-R008-SYNTHETIC-CONSUMER-INVENTORY-2026-09-25.zh-CN.md)：`core_formal_readiness._admission_observation` 没有先校验 admission schema，通用 admission evidence 也缺少统一 synthetic 拒绝层。修复和逐 consumer 负向回归必须在任何 harness 输出可被使用前完成；本设计没有授权当前改接或晋升任何 consumer。

## 2. API、调用端与失败闭合

唯一函数：

```text
diagnose_non_qualifying_synthetic_probe(
    raw_json_utf8: bytes,
    expected_scope_token: str,
    expected_qualification_row_token: str,
) -> Diagnostic
```

函数纯内存、不作 I/O，不调用 filesystem/FD/environment/network/log sink/callback/plugin/dynamic import/C-v1/registry/qualification API；静态 import allowlist 仅 `json`，无模块级可变结果、缓存或 service locator。期望 token 由调用者提供且不视为可信。

调用方每次调用前清空 result slot。仅当本次调用正常返回，且返回对象经唯一的 `validate_exact_v6_diagnostic` 检查通过，才能读取诊断。该 validator 必须检查完整 exact field set、每字段精确类型、v6 schema/mode/evidence class、允许的 diagnostic code，以及第 4 节所有常量和 code/布尔关系；拒绝额外字段、子类替代精确类型、`bool` 冒充整数。失败时 result slot 保持空，且不得把对象传给任何后续 consumer。异常、超时、取消、进程退出、缺失/截断/无法解析返回、类型不符或旧缓存值均统一拒绝；禁止默认补 `open` 或复用上一结果。

不可恢复的 `MemoryError`、`KeyboardInterrupt`、`SystemExit`、`GeneratorExit`、进程终止和 interpreter/host 崩溃不承诺返回对象；调用边界仍按拒绝处理。任何未被下表明确定义的普通 `Exception` 只可映射到完整固定的 `internal_error`，不外带异常文本、路径或环境信息。

## 3. 输入字段与有界解析优先级

完成 UTF-8 严格解码后，depth scanner 按 Unicode code point 扫描。首个命中项唯一决定 code，顺序固定：

1. 参数必须为精确 `bytes`、精确 `str`；两个 expected token 均为 ASCII 且整串匹配 `[0-9a-f]{64}`。失败 `invalid_arguments`。
2. 原始 byte 长度 `>4096` 为 `too_large`（BOM 计入）。否则 UTF-8 BOM 或非法 UTF-8 为 `bad_encoding`。
3. 有界 lexical depth scan：`NORMAL/STRING/ESCAPE`，depth 初始 0。NORMAL 中 `{`/`[` 令 depth+1，刚到 3 即 `too_deep`；`]`/`}` 在 depth>0 时 depth-1，在 depth=0 时保持 0。扫描器不检查括号种类匹配、不校验 grammar，也不因 EOF 时 depth 非零而报错。STRING 中反斜线转 ESCAPE、未转义双引号回 NORMAL；ESCAPE 消耗下一个 code point 后回 STRING。EOF 状态留给 JSON parser。
4. 调用 `json.loads(text, strict=True, object_pairs_hook=ObjectPairs, parse_constant=reject_nonstandard_constant, parse_int=JsonNumber, parse_float=JsonNumber)`。`JSONDecodeError` 和专用 `NonstandardConstantError`（只由 `parse_constant` 抛出）映射为 `bad_json`；其他 decoder、hook、marker 构造异常均映射 `internal_error`。`NaN`/`Infinity`/`-Infinity` 不可进入 shape 检查。
5. `ObjectPairs` 为每个 JSON object 建立私有有序 key/value wrapper；数组始终使用 list。完整 parse 后递归查所有 object 的 duplicate key，任一重复映射 `duplicate_key`；仅在全树无重复后转为普通 dict/list。遍历意外异常映射 `internal_error`。
6. 在去重后的树上执行第 4 节 exact shape/type/value 检查，不符 `bad_shape`。unexpected validator exception 映射 `internal_error`。只有 shape 完全有效后才做 scope/row token equality 比较。

优先级冲突按上述顺序确定：`invalid_arguments` 优先于 size；`too_large` 优先于 BOM/encoding；`bad_encoding` 优先于 depth；`too_deep` 优先于 syntax；完整 parse 失败时 `bad_json` 先于 duplicate 检查；duplicate 先于 shape；shape 错误先于 binding mismatch。扫描不做额外 grammar 优先级。

输入精确 schema：

| 层级/字段 | 精确类型 | 要求值 |
|---|---|---|
| outer object | JSON object；仅 `schema,payload` | 无重复键、无其他字段 |
| outer `schema` | string | `core.cfd.f8.r008.synthetic_non_qualifying_probe.v6` |
| outer `payload` | JSON object | 仅下列六字段 |
| payload `schema` | string | `core.cfd.f8.r008.synthetic_non_qualifying_payload.v6` |
| payload `mode` | string | `synthetic_only` |
| payload `evidence_class` | string | `synthetic_non_qualifying` |
| payload `probe_id` | string | whole-string `[a-z0-9][a-z0-9._-]{0,63}` |
| payload `scope_token` | string | whole-string `[0-9a-f]{64}` |
| payload `qualification_row_token` | string | whole-string `[0-9a-f]{64}` |

实现需用 length + ASCII character validation，或等价的 whole-string fullmatch；禁止前缀匹配、Unicode normalization、大小写转换或自动 hash。schema sample 本身不能代替上表的逐字段检查。合法 shape 不含数字字段；`parse_int`/`parse_float` 返回保留原 token text 的私有 `JsonNumber` marker，不转换成 Python int/float，因此任意 JSON number 在 shape 阶段为 `bad_shape`，也避免大整数转换异常或 `1e999` infinity。

## 4. Diagnostic exact schema 与诊断表

V6 Diagnostic exact fields：

```json
{
  "schema": "core.cfd.f8.r008.synthetic_non_qualifying_diagnostic.v6",
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

`validate_exact_v6_diagnostic` 必须逐字段验证，不可仅验证 marker 子集：string 字段为精确 `str`；所有 `*_matches`、`*_eligible`、`*_authorized`、`registry_write`、`harness_performed_external_io`、`payload_shape_valid` 为精确 `bool`；`qualification_credit` 为精确 `int` 且值 0（Python bool 不可通过）；schema/mode/class/outcome/transition 为固定常量；diagnostic code 在下表 allowlist 中。不得有额外、缺失或重复字段。

| Code | Shape | Scope | Row | 唯一条件 |
|---|---:|---:|---:|---|
| `invalid_arguments` | false | false | false | 精确参数类型/ASCII/full-token 失败 |
| `too_large` | false | false | false | raw bytes `>4096` |
| `bad_encoding` | false | false | false | BOM 或非法 UTF-8 |
| `too_deep` | false | false | false | depth scanner 观察到第三层 |
| `bad_json` | false | false | false | `JSONDecodeError` 或专用非标准常量异常 |
| `duplicate_key` | false | false | false | 完整 parse 后任一 object 有重复键 |
| `bad_shape` | false | false | false | exact fields/type/constants/token shape 不符 |
| `scope_mismatch` | true | false | true | 仅 scope 不匹配 |
| `qualification_row_mismatch` | true | true | false | 仅 row 不匹配 |
| `scope_and_row_mismatch` | true | false | false | 两者均不匹配 |
| `synthetic_bindings_match` | true | true | true | 两个不透明字符串分别相等 |
| `internal_error` | false | false | false | 上述明确定义以外的普通异常 |

除 `diagnostic_code`、`payload_shape_valid` 和两个 match booleans 外，所有返回字段每行恒定；每行布尔/整数/字符串之间必须符合上表，不可仅依据 diagnostic code 推断未验证字段。`synthetic_bindings_match` 不代表资格通过。

## 5. 可测试 release gate 与实现前置条件

技术 release gate 与 reviewer/模型身份等流程元数据分开记录。任何审查结论本身不替代下列机器测试；任何未经 attestation 的意见不称为 Terra High review。

实现前必须通过：

- 所有 code 的正/负 fixture 及 exact output field/type/constant/无额外键断言；包括 Python bool 不可冒充 int。
- 表驱动错误冲突矩阵：`too_large+bad_encoding`、BOM+malformed JSON、`too_deep+bad_json`、`duplicate_key+bad_shape`、非标准常量+shape 错误、错误 escape/引号/容器符号组合，以及各阶段 unexpected exception 映射。
- depth scanner 所有状态、unmatched close、EOF、size、BOM/UTF-8、duplicate nesting、object/array 区分和 token/probe_id full-string 行为。
- 调用端 result-slot 清空、异常/timeout/缺失/缓存旧结果拒绝；validator exact fields、类型和 code/布尔关系。
- 对消费者清单中的每个 admission、C-v1/per-case、T1 matrix/reducer、registry/readiness/release boundary 运行同一负向 corpus：V6 exact Diagnostic、synthetic marker 加 gate-shaped extra fields、重复 discriminator key、unknown/missing schema、production-schema 重标、复制/包装/重序列化后的 synthetic 对象，均须在 gate 值解析/聚合前拒绝。把 consumer 清单和实际 test node IDs 一起留存；发现新的消费者时扩充清单，不得跳过。
- 证明生产 evidence 入口的 strict decoder、无 key normalization、source/hash/verifier-version binding；证明纯 mapping 或 harness 派生对象不能构造 production accepted type。若目前架构不能证明此项，则不得把 synthetic/无可信来源输入用于资格入口。

目前上述测试没有实现/运行，消费者仍有盘点出的 schema gate 缺口。本草案不授予 consumer 改接权限；真实 F8 execution gate 仍为 `open`、`T1_numerical=false`、资格信用为零。即使 V6 后续实现通过 synthetic tests，也不构成 C-v1、native integrity、T1、readiness 或任何资格信用。
