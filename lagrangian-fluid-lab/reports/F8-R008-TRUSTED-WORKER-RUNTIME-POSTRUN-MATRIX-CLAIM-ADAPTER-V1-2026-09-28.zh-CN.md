# F8/R008 UPDATE-310：trusted worker/runtime → postrun matrix claim adapter

本报告记录一个新增的、仅 synthetic-only 的 fail-closed 静态 adapter。它把已由 UPDATE-308/309 验证的 handoff 与 replay-ledger transition 投影绑定到冻结的 15 个 R008 matrix case-level claims；它不是 postrun worker，也不产生执行权限或资格信用。

## 输入与边界

- 输入仅为内存中的 canonical fixture bytes，以及冻结 R008 matrix-v5 提供的 15 个 case IDs。
- 每个 case 必须存在且只能出现一次；adapter 拒绝缺行、额外行、claim case ID 不一致和跨 case 重用。
- UPDATE-309 verifier 是唯一负责 handoff/witness canonicality、签名、scope、nonce、issuer/subject、consumed transition 与 generation+1 校验的层；本 adapter 只在 verifier 成功后提取投影并做等值绑定。
- 由于 UPDATE-308 的 synthetic attempt case ID 既有格式要求，冻结真实 case ID `X` 映射为确定性的 `synthetic-matrix-X`；任何不同映射都会 fail closed。
- 每 case 绑定独立 handoff SHA-256、attempt ID、synthetic attempt-case ID、nonce、ledger/entry、generation transition 和 replay consumption ID；15 行共享同一 R008 scope 及可信 issuer/worker/runtime subject projection。

## 拒绝条件

adapter 拒绝缺失或重复的冻结 case、跨 case handoff digest/attempt/nonce/consumption ID/ledger-entry/generation transition reuse、scope/issuer/subject projection 不一致、claim 与已验证 projection 的 digest/nonce/generation 不一致，以及任何非 synthetic 或带有授权/资格语义的 UPDATE-308/309 结果。

## 非授权结果

成功输出固定为 diagnostic-only：`capability_minted=false`、`execution_authority=false`、`readiness_pass=false`、`T1_numerical=false`、`formal=false`、`qualification_credit=0`、`real_ledger_mutation=0`、`registry_mutation=0`、`gate_mutation=0`。adapter 不调用 `f8_r008_postrun_case_worker_v1.py` 或 `f8_r008_postrun_matrix_worker_v1.py`，不读生产 bundle/ledger，不运行 worker、solver、native、GPU 或 queue。

机器可读的固定契约见同名 JSON；实现和专项测试见：

- `scripts/f8_r008_trusted_worker_runtime_postrun_matrix_claim_adapter_v1.py`
- `tests/test_f8_r008_trusted_worker_runtime_postrun_matrix_claim_adapter_v1.py`
