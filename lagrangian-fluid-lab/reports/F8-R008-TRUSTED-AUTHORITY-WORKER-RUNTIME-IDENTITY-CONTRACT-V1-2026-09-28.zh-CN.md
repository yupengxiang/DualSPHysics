# F8/R008 trusted authority/worker/runtime identity contract v1

本轮新增的是 readiness v8 的纯静态、additive 缺口收敛，不是执行授权器。现有
`f8_r008_supervisor_session_claims_v1` 能把 candidate key 签名与 attempt ledger、C
execution journal 的字段绑定起来，但它明确不验证 active-key registry、revocation、
trusted root、supervisor identity 或 runtime completeness；attempt ledger/attestation
同样只证明 caller-supplied candidate key 下的签名与内容一致性。execution readiness v8
和 syscall policy contract 也没有 authority/worker/runtime identity chain，因此本轮不
重复这些功能，也不改写历史 receipt。

## Contract boundary

`scripts/f8_r008_trusted_authority_worker_runtime_identity_v1.py` 只接受有界的内存
`bytes` synthetic JSON bundle，并要求调用者显式提供 32-byte synthetic trust-root
public key。它按以下链路 fail-closed 校验：

1. trust-root 用固定 Ed25519 domain 对 active key 授权；root key 必须与显式参数相同，
   不存在默认 root。
2. active key 必须是不同于 root 的 `authority_issuer` key，并用另一个固定 domain
   签署 authority、worker、runtime identity assertion。
3. 三个 role record 必须显式绑定 role、host identity、runtime/code identity、epoch、
   revocation、issuer 和 SHA-256 parent binding；worker→runtime 还要求 host 与 runtime
   identity 一致。
4. epoch window、全部五个 revocation 状态、algorithm/domain、`default_trust=deny`
   和 `candidate_key_self_attestation=reject` 都是 exact constraints。root 与 active
   key 复用、缺 root signature、非 synthetic origin、篡改 parent/host binding 均拒绝。

这是“由显式 synthetic root 证明结构一致性”的 diagnostic verifier，不是对生产
authority 的认证。candidate key 不能自证为 active key，bundle 内的 root 字段也不能
替代显式 root argument。

## Non-authorizing result

成功结果固定包含 `diagnostic_only=true`、`capability_minted=false`、
`execution_authority=false`、`readiness_pass=false`、`T1_numerical=false`、
`qualification_credit=0`，并把 registry/ledger/gate mutation 置零。实现不读取或写入
registry、attempt ledger、attestation、readiness receipt 或 syscall policy；不执行
root/sudo、ptrace/seccomp、fanotify/kernel probe、native/solver/worker/GPU/queue。

机器报告见
[`F8-R008-TRUSTED-AUTHORITY-WORKER-RUNTIME-IDENTITY-CONTRACT-V1.json`](F8-R008-TRUSTED-AUTHORITY-WORKER-RUNTIME-IDENTITY-CONTRACT-V1.json)。
该报告只记录 schema、约束和禁止操作，没有生产身份或运行时证据。

## Verification

专项测试覆盖有效链、显式 root anchor、root 签名和 root/active key 不复用、epoch/
revocation/algorithm/domain/trust constraints、worker/runtime parent 与 host 绑定、
synthetic-only 输入、canonical JSON/重复键以及 non-authorizing report，共 `15 passed`。
本轮不改变 F8 readiness v8 的 `readiness_pass=false`、`T1_numerical=false` 或 credit=0。
