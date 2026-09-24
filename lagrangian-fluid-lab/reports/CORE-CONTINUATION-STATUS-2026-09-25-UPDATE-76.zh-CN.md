# Core 计划续推状态 UPDATE-76

日期：2026-09-25（Asia/Shanghai）

## 本次完成

为 V8 consumer 清单中的 Core release-candidate 边界新增 `test_synthetic_admission_receipt_cannot_release`。测试先构造并验证一份除 schema 外完全满足 release-candidate admission validator 的内存 admission fixture，再只把 schema 改成 exact F8 synthetic Diagnostic schema；断言 validator 唯一错误为 unsupported schema，public `build_candidate()` 输出 blocked、`formal_release=false`、零 formal job，并确认 mocked campaign completion 本身有效且可 finalize。该测试只验证 release-candidate 消费端的 schema 隔离，不调用 `generate()` 或文件 materializer。

## 复核与验证

- `pytest -q tests/test_core_formal_release_candidate.py`：5 passed。
- Terra High/high 静态复核通过，确认修订后拒绝原因已被隔离到 schema；无独立身份/effort attestation，故不作为可审计的身份或资格证明。

## 边界与剩余工作

测试使用 monkeypatch 的 admission/campaign producer 和内存 fixture；它不证明真实 producer→consumer raw-byte 传递，也不覆盖 `generate()` 输出文件路径。release candidate 现有校验仍接受带正确 `core.formal_admission_audit.v1` schema 的伪造对象；duplicate-key/非有限数解析、raw-byte/source binding、可信根、capability 与 runtime identity 仍未闭合。故 V8/V12 consumer gate 仍为 FAIL，R008 gate open、`T1_numerical=false`、零资格信用。未访问 production bundle/solver frame，也未运行 GenCase/native/solver/worker/GPU/queue。
