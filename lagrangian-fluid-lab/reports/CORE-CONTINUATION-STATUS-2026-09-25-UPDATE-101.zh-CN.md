# Core 计划续推状态 UPDATE-101

日期：2026-09-25（Asia/Shanghai）

## 本次推进：V13 qualification bundle serialization codec

新增 `core_f4_qualification_bundle_v3_codec.py`，只负责 raw JSON serialization 与 digest primitive：

- 要求 exact `bytes` 与 strict UTF-8；完整拒绝嵌套 duplicate keys、`NaN`/`Infinity` 等非标准常量、解析后溢出的非有限 float、非法 JSON 与非 object 顶层。
- canonical bytes 沿用 V12 固定规则：UTF-8 编码 `json.dumps(sort_keys=True, separators=(",",":"), allow_nan=False)`，默认 ASCII escaping、无结尾换行；分别计算原始 bytes 与 canonical object 的 SHA-256。
- 按固定三角色顺序及 U64/U16 big-endian 长度前缀实现 domain-separated V3 bundle digest；role digest 以 32-byte 解码值拼接。V13 golden vector 精确得到 `10c3a2d73f51262f595de744f111580157c4d37521c650a530cebe6e4142137e`，并固定 domain separator 只含一个末尾 LF (`0x0a`)。
- `positive_builtin_int()` 提供 exact positive builtin-int 检查并拒绝 bool，供未来 `hdf5_size_bytes` verifier 使用。

仓库 `.venv` 下 `tests/test_core_f4_qualification_bundle_v3_codec.py` 为纯内存合成测试：13 passed，覆盖 golden vector、canonical digest 与 duplicate/nonfinite/type/role/int 边界；py_compile/diff check 通过。未读/写生产文件、HDF5、F3/F4 固定材料；未调用 planner、tick、canary、collector、preparation、GenCase/native、solver、worker、GPU 或 queue。

## 安全边界

该模块只验证编码与摘要，不读 descriptor/path、不确认引用语义或 producer/root/runtime 身份、不验证 fs-verity、不 mint `VerifiedF4QualificationBundleV3`，更不授权 F4/Core batch。它是 V13 实现的一小段，不解除 UPDATE-99/100 的 fail-closed 状态，也不贡献 T1/T2/资格信用。后续仍需 exact schemas/ref cross-binding、trusted root reader、snapshot supervisor/broker、same-FD HDF5 worker 与 fixed launcher/runtime closure，并接受独立审查。
