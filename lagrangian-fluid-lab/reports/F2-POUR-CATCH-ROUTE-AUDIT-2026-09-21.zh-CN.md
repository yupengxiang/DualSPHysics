# F2 倾倒/接液替补路线只读审计（2026-09-21）

F6 v4 的 8 格 canary 为 7/8，cell-08 保留科学硬失败；本审计只读复核现有 F2 资格、registry 和报告，未启动任何 GenCase、native decoder、solver、GPU 或 queue。

结论是保留一条新的固定接收盆+自由落体液块路线作为有条件候选：`F2_receiver_ballistic_catch_release010_v2`。它没有 submerged aperture、crest 或 moving cup，与已关闭的 submerged-slot 负例在拓扑上独立。候选只停留在 root-review-only；当前不写 Definition、不做 preflight。

## 失败证据与分母

- submerged-slot v2 已有 `76095` 个 zero BoundNor/NormalSize，route 明确关闭且禁止同输入 retry；保留 `matrix_credit=0`。
- receiver/weir 的固定 15 行保留 `executed=1`、`failed=1`、`event_censored=1`、`unattempted=14`，不重跑。
- 静态接收盆 v1 q=.5 anchor 的第一次 loader attempt 返回 127；随后唯一允许的基础设施修复重试完成 301 帧，但排除 `64` 个粒子（其中 density 排除 `44`），所以 hard integrity=false。两次失败均保留，v1 输入、XML/BI4、trajectory 和 output stem 均关闭。
- v2 仅提出新的 `-0.10 m/s` release-speed 假设；建议的 15 行仍是 proposal-only，`executed=0`、`credit=0`，不改已有 T1/T2 分母。

## Root-review gap

当前阻塞项是：没有 v2 literal Definition/hash closure；v1 CPU/native pass 不能继承；v1 科学硬失败禁止 same-input retry；receiver contact、retained/spill ownership 和 q endpoint observer 尚未 root 冻结；还需要一次新的 root review，再考虑恰好一次 v2 CPU/native preflight。

是否值得进入新 Definition/preflight：**条件性值得保留，但当前不值得执行 preflight**。固定 receiver/free-fall 机制有独立问题和有限的历史 ballistic/plumbing 依据；只有先补齐上述 root-review gap，且新 Definition 明确改变 release-speed、case identity 和 output namespace 后，才进入一次零 credit CPU/native preflight。

## Gate 与执行控制

Core 仍为 `t1_families=['F3', 'F4']`、`missing_t1_case_runs=288`、`qualification_credit_added=0`。本次 `registry_mutation=0`、`ledger_mutation=0`、`T1_denominator_mutation=0`、`T2_denominator_mutation=0`；没有 solver/GPU/queue。

定向回归：`pytest -q tests/test_f2_pour_catch_route_audit_v1.py`。
