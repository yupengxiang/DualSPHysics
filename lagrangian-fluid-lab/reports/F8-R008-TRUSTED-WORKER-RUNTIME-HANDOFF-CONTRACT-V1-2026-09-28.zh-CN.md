# F8/R008 trusted worker/runtime handoff contract v1

本轮针对 readiness v8 的剩余 high blocker
`trusted_worker_execution_source_and_runtime_identity_missing`，新增一个与
UPDATE-304 trusted identity contract 分离的 attempt-scoped handoff contract。UPDATE-304
只验证显式 trust-root 到 authority、worker、runtime 的身份链；本 contract 不重复该链，
而是复用它的 synthetic verifier，把一份有界 handoff claim 绑定到单次 synthetic attempt。

## Contract boundary

`f8_r008_trusted_worker_runtime_handoff_v1.py` 只接受两份 bounded canonical JSON bytes：
UPDATE-304 的 synthetic identity bundle，以及由 active key 签署的 synthetic handoff。它
fail-closed 校验：

1. identity bundle 的精确 SHA-256、active-key ID 和 authority binding；
2. worker/runtime principal、parent binding、host identity 与 code identity claim；
3. R008 scope、synthetic attempt/case/nonce、有限 epoch window 和 `single_use=true`；
4. worker source、runtime entrypoint、source/runtime manifest、Definition/control/initial
   state/configuration hash，以及声明的 output-manifest schema/artifact names；
5. 固定 handoff Ed25519 domain、拒绝默认信任、拒绝 production identity claim，并验证
   active key 对完整 handoff payload 的签名。

`single_use_claim_only_no_consumer` 只是一项静态 handoff 约束；本轮没有消费 replay
ledger，也没有观测进程启动、runtime module、文件输出或真实 worker。因此它不能把
caller-supplied claims 升格为生产来源认证或 runtime conformance。

## Non-authorizing boundary

机器报告为
[`F8-R008-TRUSTED-WORKER-RUNTIME-HANDOFF-CONTRACT-V1.json`](F8-R008-TRUSTED-WORKER-RUNTIME-HANDOFF-CONTRACT-V1.json)。验证成功仍固定为
`diagnostic_only=true`、`capability_minted=false`、`execution_authority=false`、
`readiness_pass=false`、`formal_eligible=false`、`T1_numerical=false`、
`qualification_credit=0`，并保持 registry/ledger/denominator/gate mutation 为 0。
实现不读取或修改 readiness v8、supervisor-session、attempt ledger/attestation、
15-case matrix、final-fput 或任何 reducer；不执行 root/sudo、ptrace/seccomp、fanotify、
kernel probe、native/solver/worker/GPU/queue。

## Verification

专项 handoff pytest 共 13 项通过，覆盖 identity-chain reuse、explicit trust anchor、
scope/lifetime/single-use、subject/source rebinding、signature、canonical JSON、synthetic
origin 和 report boundary；`py_compile` 与 `git diff --check` 通过。没有读取 production
bundle/frame，没有启动 solver/worker/runtime，也没有修改历史 receipt、registry、ledger、
denominator 或 gate。readiness v8、T1、formal 和 credit 仍为 `false/0`。
