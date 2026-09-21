# F6 physical-anchor CPU/native preflight preliminary audit（2026-09-21）

本次 v1 只使用一个 hash-bound 的 F6 physical-anchor Definition，授权范围是一次 CPU GenCase/native preflight。`qualification_claim=none`、`qualification_credit=0`、`T1=false`。授权明确关闭 solver、GPU、queue、registry、ledger 和 matrix。

GenCase 实际返回 code `0`，并生成了 XML/BI4。生成 XML 的粒子摘要包含 `693` 个 `<floating mkbound="8">` 粒子、`16008` 个 fluid 粒子和 `11806` 个 fixed-boundary 粒子。初版 verifier 的 `_group_items` 只解析 `fixed`、`moving`、`fluid`，漏掉了合法的 `floating` 标签，因此 preliminary group gate 失败并在 native decoder 调用前停止。这是 verifier infrastructure failure，不能解释为 GenCase 或物理失败。

原始 receipt 保留为 `preflight.json`：`status=cpu_native_preflight_failed_hard`，GenCase `returncode=0`，`native_decoder_invoked=false`，`same_input_retry=false`。没有对相同 Definition 重跑 GenCase，也没有调用 native decoder、solver 或 GPU。后续 parser repair 必须使用新 amendment receipt 和同一已生成 BI4，并明确不增加 GenCase invocation；本报告不授权该 repair。

输出目录中的 `one-shot-lock.json` 将 Definition hash、GenCase/native invocation budget 和禁止的中央 mutation 固定为 zero。当前结果不构成 solver canary、物理资格、Core 第三 T1 family 或任何 credit。

产物包括 root authorization、one-shot lock、preflight receipt、GenCase log 和 generated XML；大型 BI4 不纳入本次 commit，但 receipt 保留其 hash-bound 路径与 SHA-256。
