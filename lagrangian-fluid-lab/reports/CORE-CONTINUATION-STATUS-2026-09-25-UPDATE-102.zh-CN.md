# Core 计划续推状态 UPDATE-102

日期：2026-09-25（Asia/Shanghai）

## 本次推进：V3 admission reference-graph consistency

在 UPDATE-101 的纯内存 codec 上新增 `inspect_untrusted_admission_envelope()`。它接受调用方提供的 bytes，不读文件或 descriptor，只用于检查 V12/V13 admission metadata 的内部一致性：

- 对 outer envelope、binding admission wrapper/projection、evaluation admission projection 和 refs 执行 exact-key/schema/type 检查，并限制 object id 格式及 ref 声明长度。
- 对三个角色对象验证实际 byte length、raw SHA-256、canonical JSON SHA-256 与目标 schema；计算包含 envelope 和三角色对象的 V13 domain-separated bundle digest。
- 闭合 outer/binding/evaluation/source ref 关系，检查 binding 与 evaluation projection 的字段及集合一致，验证 cell index 集合的完整互斥 partition，并验证 `matrix_complete`、`T1_numerical` 与 promotion status 的确定性派生。
- 所有成功结果仍显式标为 `metadata_ref_graph_consistent_untrusted`；qualification admission、capability、source semantics、object allowlist、descriptor-root 和 producer identity 均为 false。

仓库 `.venv` 下 `tests/test_core_f4_qualification_bundle_v3_codec.py` 为纯内存合成测试，18 passed。Terra High/high 只读审查未发现可复现的 serialization/ref-consistency 接受绕过，并发现原 raw-hash 回归会因 byte-length 先失败而形成假阳性；测试已改为等长、canonical digest 相同而 raw digest 不同的序列化顺序变体，明确断言命中 raw SHA-256 错误。`py_compile` 与 `git diff --check` 通过。

## 安全边界与未完成项

这不是可信 admission verifier。codec 不判断 source evaluation 的真实语义，不校验固定对象白名单或 descriptor root，不建立 producer/runtime 身份，不读取受信 snapshot、不验证 FD/fs-verity，也不 mint capability、不开放 F4 batch、不贡献 T1/T2 或正式资格信用。未读生产 campaign、HDF5、archive 或 F3/F4 one-shot；未运行 planner、tick、canary、preparation、GenCase/native、solver、worker、GPU 或 queue。

仍需实现并独立审查 trusted root reader/supervisor、source-bound capability、broker 与 same-FD worker/fixed runtime closure，才能替换 legacy fail-closed ingress。UPDATE-98/99/100 的 fail-closed 仍有效；F4 正式 admission 继续零信用。
