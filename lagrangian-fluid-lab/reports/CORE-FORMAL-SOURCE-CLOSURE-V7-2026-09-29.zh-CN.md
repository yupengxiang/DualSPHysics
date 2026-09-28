# Core formal source closure V7（2026-09-29）

本收据记录 WP-CF-01 的当前代码源闭包。它是 planning-only 的新命名空间，不覆盖或改写历史 V6 收据；也不授予 Core formal root admission。

## 机器收据

- 命名空间：`core-formal-source-closure-v7-20260929`
- source closure：`campaigns/core-v1/learning/formal-source-closure-v7-20260929/source-closure.json`
- source audit：`campaigns/core-v1/learning/formal-source-closure-v7-20260929/source-audit.json`
- admission receipt：`campaigns/core-v1/learning/formal-source-closure-v7-20260929/receipt.json`
- source closure SHA-256：`4a9a966c071752683c334974d2a91b2cd67dc968d9d761905d4f4d16b5c28751`
- source-closure JSON SHA-256：`fe1e03d0c459f3a410440757755059f2f7049d49edb349a6fe7f54896dc429e5`
- source-audit JSON SHA-256：`3891e751659c6d808e8962a4423ae6c6b8c5a2b7ca44c20fbf2d50552f34608b`
- receipt JSON SHA-256：`65c6c682dca9af3e3caa40f87140fa1c92b8c589b0ef2e8550b3ef135c3e9c36`

V7 当前 canonical runtime closure 为 13 个脚本，包含本轮 WP-CF-01 补齐的 lazy/runtime dependencies：`core_fsverity.py`、`f3_control.py`、`passive_tracers.py` 和 `f7_pump_geometry_adapter_v1.py`。审计以 live workspace 重新计算全部文件 SHA-256；`--verify` 返回 `ok=true`，所有 closure、receipt、输入绑定与 closed-gate checks 均通过。

## Admission 结论

以下字段是明确的 fail-closed 结果：

```text
closure_verification=true
formal_release=false
formal_training_allowed=false
formal_job_count=0
launch_allowed=false
root_admission.granted=false
```

当前仍有 9 个 admission blockers：第三个 T1 family、12-case validation denominator、9 个 formal training runs、288 个 material case-runs、32000-update resource frontier、formal release、formal readiness、launch contract 和 root admission。历史 V4 source snapshot 与当前 V7 的差异只作为 `historical_baseline_only` 记录，不替代当前 V7 hash，也不作为升级 formal 的理由。

## 执行边界

本次只生成并验证 bounded JSON/sha256 收据；没有启动 optimizer、GPU、solver 或 formal job，没有写 registry/ledger，也没有改变 Core 分母、T1/T2、credit 或 completion gate。后续只有在上游正式门禁独立闭合、重新绑定 readiness/launch contract，并取得单独 root decision 后，才可讨论 formal execution。
