# F8 R008 C-execution synthetic open-only control harness v1（草案）

状态：回应 v3 Terra 配置复审 `REVISE` 后的**范围收敛候选**，待 Terra High 只读复核。它不是 execution-evidence schema 或 verifier。旧 C-v1、v1/v2/v3 草案和冻结 R008 输入均不改写；未授权或启动 solver/native/GenCase/worker/GPU/queue。

## 1. 唯一职责与非目标

本 harness 只证明一个接口性质：对合法、非法、摘要不匹配或解析异常的 synthetic probe，诊断接口没有产生资格判定的能力。它不打开证据文件、不解析日志、不检查签名或信任包、不验证运行事件，也不消费任何 C-v1 receipt。

production execution evidence 暂不在本文件冻结。supervisor/event-source 信任、文件对象解析、builder/source-to-binary、完整 solver call graph、accinput/time horizon、termination、资源/cgroup 等必须在独立生产合同中逐项完成；不得从本 harness 的通过/有效形状推断任何一项成立。

## 2. 纯内存 API

唯一入口候选：

```text
diagnose_synthetic_probe(
    raw_json_utf8: bytes,
    expected_scope_sha256: str,
    expected_qualification_row_sha256: str,
) -> Diagnostic
```

没有 path、directory/file descriptor、callback、registry、network client 或 C-v1 verifier 参数。实现不得导入、调用或持有能写 gate registry/qualification receipt 的接口；不得自行读取磁盘或环境变量。调用者传入的两个 expected digest 是测试上下文，不是 production trust root，也不由 probe 自我声明为真。

## 3. Input schema：exact fields 与边界

输入只接受 UTF-8 JSON bytes，最多 4096 bytes；拒绝 UTF-8 BOM、非法 UTF-8、重复 object key、NaN/Infinity、超过 3 层嵌套、任何 JSON number、未知字段和缺字段。唯一合法的 JSON 结构为：

```json
{
  "schema": "core.cfd.f8.r008.synthetic_open_only_probe.v1",
  "payload": {
    "schema": "core.cfd.f8.r008.synthetic_open_only_payload.v1",
    "mode": "synthetic_only",
    "probe_id": "fixture-001",
    "scope_sha256": "<64 个小写十六进制字符>",
    "qualification_row_sha256": "<64 个小写十六进制字符>"
  }
}
```

外层 exact fields 为 `schema`, `payload`。payload exact fields 为 `schema`, `mode`, `probe_id`, `scope_sha256`, `qualification_row_sha256`，均必需且 `additionalProperties=false`。常量必须逐字匹配上例。`probe_id` 匹配 `[a-z0-9][a-z0-9._-]{0,63}`；两个摘要均匹配 `[0-9a-f]{64}`。不要求签名或 JCS：本格式不是有权威性的签名 payload。

expected digest 参数也必须匹配 `[0-9a-f]{64}`；payload 摘要与对应 expected 值分别作字节级字符串相等比较。形状有效不代表 digest 匹配，更不代表输入证据存在或可信。

## 4. Output schema 与永久 open 不变量

返回值 exact fields：

```json
{
  "schema": "core.cfd.f8.r008.synthetic_open_only_diagnostic.v1",
  "mode": "synthetic_only",
  "payload_shape_valid": false,
  "scope_binding_matches": false,
  "qualification_row_binding_matches": false,
  "diagnostic_code": "invalid_input",
  "gate_state": "open",
  "qualification_credit": 0,
  "registry_write": false,
  "production_input_consumed": false
}
```

三个 boolean 的 JSON 类型必须固定；`qualification_credit` 整数恒为 0。`diagnostic_code` 仅可为 `ok`, `invalid_input`, `bad_encoding`, `bad_json`, `duplicate_key`, `too_large`, `bad_shape`, `scope_mismatch`, `qualification_row_mismatch`, `internal_error`。任何 malformed input、摘要不符或捕获到的解析异常均返回上述固定安全值：`gate_state=open`、零信用、无 registry write、无 production input consumed。成功解析时只可把 `payload_shape_valid` 与两个摘要比较结果置为 true；输出 schema 中不存在 `pass`、`defined_pass` 或数值资格字段。

这个性质应由结构保证，而非调用者约定：返回对象由单一构造器生成；公开 API 不暴露 gate 状态 setter；无 registry 写接口；任何异常边界只能构造 `internal_error` 安全返回，不能把部分验证结果映射为关闭 gate。

## 5. 负例和性质测试要求

实现前仍须 Terra High 复核本合同。获准实现后，仅可增加纯内存合成测试，至少覆盖：合法 probe；未知/缺失字段；重复 key；非法 UTF-8/BOM；NaN/Infinity；深度/字节超限；畸形摘要；scope 和 row 各自不匹配；每个 diagnostic code 的输出恒量；解析异常注入后仍 open；无路径/文件/registry 参数且无 side effect。测试不得读取真实 attempt 或生产数据。

## 6. C-v1 与生产 activation 边界

本 harness 不调用 C-v1 verifier、不消费 `solver_execution`、不改 C-v1 schema，不创建 stage object ref，因此 C-v1 的 `status=passed` 或 `solver_execution={}` 均与它无关。未来 production gate 必须使用独立、执行前固定且外部信任根授权的 activation/consumer；不得把本 harness 或 C-v1 structural pass 迁移为 execution pass。

当前生产合同仍需独立冻结：

- 固定 `(stage, role, object_id)` 到受信目录内单一对象的 allowlist、root identity、FD-relative no-follow resolver、mount/文件身份与跨阶段角色配对；receipt 内路径只能作既有一致性数据，不能作为打开目标。
- 精确的无环证据 DAG、对象唯一性、supervisor 与 builder 的签名 envelope/trust bundle/revocation 语义、事件源认证及所有嵌套字段/界限。
- source/config/build/features/dynamic load 与完整 CPU/GPU control-query call graph 的闭合。
- 每个 runtime `accinput` 的顺序、XML identity、MK-range expansion、有限 `TimeIni/TimeEnd`、表绑定与查询域包含关系。
- termination/`TERMINATE`/全部子进程 reaping 及 solver-supervisor 分离 cgroup 的连续成员、mount/root/parent 和丢事件语义。
- 独立 C-v1 到 production execution-gate 的前置 activation、版本/hash pin 与失败行为。

以上任一项缺失时，真实 R008 execution gate 继续为 `open`。本草案没有实现、测试、生产验证或执行授权。
