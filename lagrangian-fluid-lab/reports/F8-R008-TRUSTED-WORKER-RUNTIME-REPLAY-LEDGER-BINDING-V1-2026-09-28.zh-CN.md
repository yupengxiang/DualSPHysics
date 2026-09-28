# F8/R008 trusted worker/runtime replay-ledger binding v1

本 sidecar 是 UPDATE-308 handoff contract 的最小 disjoint 补充。UPDATE-308 已经委托
trusted identity / worker-runtime handoff verifier 校验 authority、worker、runtime、
issuer、subject、attempt 和输入输出 claim；本轮不重新实现这些字段语义，只把已验证的
handoff 原始 canonical bytes 投影成 replay ledger 必须精确签名的 binding。

## Single-use transition

新脚本
[`f8_r008_trusted_worker_runtime_replay_ledger_binding_v1.py`](../scripts/f8_r008_trusted_worker_runtime_replay_ledger_binding_v1.py)
要求两个独立的 bounded canonical synthetic witness：

1. pre-state 必须是 `consumed=false`、generation=`n`；
2. post-state 必须是 `consumed=true`、generation=`n+1`；
3. 两个 witness 必须使用同一 ledger/entry identity、ledger issuer 和显式 trusted
   ledger public-key anchor；
4. 两个 witness 的 handoff digest、R008 scope、attempt、case、nonce、issued/expiry
   epoch、handoff issuer projection 以及 worker/runtime subject projection 必须与已验证
   handoff 逐字段相等；
5. `consumption_id_sha256` 由完整 binding、ledger/entry identity、前后 generation 和
   consumed epoch 的 canonical bytes 精确派生。

因此已 consumed 的 state 不能再次作为 pre-state；跨 scope/case/nonce、handoff digest、
issuer/subject、generation rollback/skip、过期消费、caller self-claim 或缺少显式 trusted
ledger witness 均 fail closed。trusted ledger key 不能复用 handoff active identity key。

## Non-authorizing boundary

验证器只接收内存中的 synthetic JSON bytes 和调用方显式提供的 raw public keys；不读取
生产 bundle、真实 ledger、registry、gate、kernel、solver、worker、GPU 或 queue，也不修改
任何输入 snapshot。成功结果固定为
`diagnostic_only=true`、`capability_minted=false`、`execution_authority=false`、
`readiness_pass=false`、`formal_eligible=false`、`T1_numerical=false`、`credit=0`，并固定
`registry_mutation=0`、`ledger_mutation=0`、`real_ledger_mutation=0`、`gate_mutation=0`。

机器报告见
[`F8-R008-TRUSTED-WORKER-RUNTIME-REPLAY-LEDGER-BINDING-V1.json`](F8-R008-TRUSTED-WORKER-RUNTIME-REPLAY-LEDGER-BINDING-V1.json)。

## Verification

专项 replay-ledger pytest 在加入报告前已通过 `17 passed`；加入 checked-in JSON 后应为
`18 passed`。测试覆盖 valid transition、缺失/错误 trusted anchor、consumed replay、
scope/case/nonce/digest rebinding、issuer/subject rebinding、generation rollback/skip、
epoch bounds、consumption-id binding、caller self-claim、active-key reuse、canonical
duplicate rejection、ledger identity stability 和报告边界。随后还会运行 py_compile 与
`git diff --check`；本项不触碰任何 F3 rollout 或 `/tmp` artifact。
