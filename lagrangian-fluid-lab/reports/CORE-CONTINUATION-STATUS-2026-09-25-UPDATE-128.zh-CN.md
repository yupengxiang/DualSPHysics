# Core 计划续推状态 UPDATE-128

## 本次推进：F8 R008 attempt-ledger attestation 的非授权验证器

按 remediation draft 固定的合同新增 `f8_r008_attempt_ledger_attestation_v1.py`：

- 对 attestation 原始字节执行 bounded strict JSON 解析，拒绝重复键、额外/缺失字段、非 V12 canonical 编码、非 builtin 数值类型、非规范 Base64 与非 64-byte Ed25519 signature。
- 使用固定 domain separator 和去除 `signature_base64` 后的 V12 canonical JSON bytes 验签；同时先结构检查 caller 提供的 matrix/ledger，并逐字段核对 scope、matrix/ledger 原始 SHA-256、supervisor source、coverage 区间、event count、overflow 与 lost count。
- 公钥明确命名为 caller-supplied candidate key；即使签名和所有绑定都通过，也固定返回 `candidate_key_is_active=false`、`active_key_registry_verified=false`、`supervisor_identity_authenticated=false`、`descriptor_root_authenticated=false`、`attempt_ledger_complete=false`、`capability_minted=false`、`T1_numerical=false`、`qualification_credit=0`。临时测试密钥的自签名不建立 supervisor trust。
- 将 pinned `cryptography==50.0.1` 加入 `requirements.txt`，不在项目代码中自行实现 Ed25519。

## 验证与边界

- attestation、ledger、V2 attempt projection 与 V5 journal 四个定向测试文件合计 **173 passed**；其中 attestation + ledger 两个文件为 **85 passed**。
- 新增/修改 Python 文件 `py_compile` 通过，`git diff --check` 通过。
- GPT-6 Luna Max 独立只读安全复核为 **PASS，无 P1/P2**：确认签名消息正好是固定 domain separator 加去除签名字段后的 V12 canonical JSON，所有声称的 ledger/matrix 绑定均重核，且未发现将非授权诊断晋升为资格的 consumer。
- 测试只使用冻结静态 scope receipt、合成 ledger 和进程内生成的临时 Ed25519 keypair；未读取生产 bundle/HDF5/BI4/solver frame，也未执行 B/C/D、native decoder、GenCase、solver、worker、GPU 或 queue，未提权。

attestation 的 active/revocation registry、固定 descriptor-root reader、supervisor/launcher/runtime 身份闭环和真实 append-only 事件源仍未实现。因此本提交只提供密码学签名与输入字段一致性的诊断结果，不能验证 ledger coverage 完整性，不能使 F8 获得 readiness/T1 或任何资格信用。
