# Core continuation status — 2026-09-24 UPDATE-36

## Outcome

新增 [F8 R008 D artifact producer v2](../scripts/f8_r008_d_artifact_producer_v2.py)，把先前独立的 safe-BI4 decode、metadata binding 与 native-fluid-table v2 producer 接入已冻结的 D-stage v1 receipt / manifest 结构；没有改动 D v1 schema。

生产器要求 B/C 已由既有 verifier 通过，并复核 C→B receipt 绑定；对调用方准备的 D authorization 与 one-shot lock 逐项执行 v1 字段、时间、哈希、owner、单链接和权限约束。D 输出在发布 receipt 前进行候选闭合：精确检查 manifests、outputs 清单和权限，按冻结帧轴重开并 hash-check C 原始帧，校验安全解码与 metadata 证据，并再次运行独立 table-v2 FD verifier，把 table 全量重算结果与 B 物料语义、冻结属性、帧轴和源帧比较。

`receipt.json` 是提交记录：先写入并 fsync 临时文件，再用 Linux `renameat2(RENAME_NOREPLACE)` 原子发布。最终目录 fsync 或文件关闭异常以明确布尔状态返回，不会在已发布 receipt 后再抛出普通清理异常；平台不支持 no-replace rename 时 fail-closed。任何发布前错误都不回滚已经生成的 D 证据，one-shot 目录必须保留且不得重试。

## 独立审查与验证

Terra High（`gpt-5.6-terra`, high；agent `01a0d33f-d33b-7552-a92a-22d96ca4d329`）对修订后的当前代码作只读复审，结论 `PASS`。首轮指出的 v1 authorization 校验、receipt 前 table 语义重验、发布后 fsync/close 错误处理及输出文件权限四项均已处理；复审未运行测试，也未改动文件。残余权限说明：规则禁止 group/world 写入但允许读取；若未来要求保密性，应再收紧为目录 `0700`、文件 `0600`。

新增 D producer 合成测试 20 passed。联合回归命令：

```text
.venv/bin/python -m pytest -q \
  tests/test_f8_r008_d_artifact_producer_v2.py \
  tests/test_f8_r008_per_case_bundle_verifier_v1.py \
  tests/test_f8_r008_native_fluid_table_bundle_verifier_v1.py \
  tests/test_f8_r008_native_fluid_table_metric_bundle_verifier_v2.py \
  tests/test_f8_r008_native_fluid_table_producer_v2.py \
  tests/test_f8_r008_native_fluid_table_schema_v2.py
```

联合结果 96 passed；覆盖表语义预提交失败不发布 receipt、v1 authorization 越界拒绝、prelude/output 权限拒绝，以及 receipt 原子发布后的 fsync/close 故障状态。测试只使用临时合成 B/C/D、BI4 与 HDF5 文件。

## 边界与未完成项

本次没有读取 production B/C/D bundles 或 solver frames；没有运行 GenCase、native decoder、solver、worker、GPU 或 queue。D receipt 明确记录零资格信用；`native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false`。

生产器自身不调用 receipt 发布后的 v1 stage/provenance/table-chain verifier；合成集成测试在 receipt 发布后分别调用这些独立消费者并通过，真实调用方仍须执行同样的事后验证。授权/审查回执真实性、当前运行时与 loaded-module identity 仍由调用方提供，且新 D orchestrator 的自身代码身份尚未纳入冻结 v1 receipt；不能把此次静态实现或合成回归解释为可信生产链或 R008 数值资格。详见 [PLAN.md F8 状态](../../PLAN.md)。
