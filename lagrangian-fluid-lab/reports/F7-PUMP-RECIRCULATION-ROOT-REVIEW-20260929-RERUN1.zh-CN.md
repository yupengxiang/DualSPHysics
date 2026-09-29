# F7 预设旋转内泵循环路线根审查材料（2026-09-29 RERUN1）

这是对当前小型 F7 static root-review receipt 的 hash 刷新。历史
`F7-PUMP-RECIRCULATION-ROOT-REVIEW-2026-09-22.zh-CN.md`、v1 candidate/source/interface/
receipt 均保留，不覆盖。

## 当前失败分类

旧 v1 candidate 的 `current_core_snapshot.completion` 绑定为 `2359` bytes、
`c081c4e1f75fe2c04b2261ac8c07f1ab2a6d4ca4b2ef749578594117d88c5aa9`；当前
`campaigns/core-v1/completion.json` 已更新为 `3959` bytes、
`51aa36d360f7f9a6c8387726ad9bf124fee87bc9c5b34a2c8081e82b4e515647`。
这是 stale checked-in receipt 的来源绑定漂移，不是 F7 Pump geometry/observer 代码失败，
也不是资格结果变化。

## RERUN1 输出

当前脚本常量切换到新的不可覆盖命名空间：

- `campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260929-RERUN1/candidate-card-v1.json`
- `campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260929-RERUN1/source-audit-v1.json`
- `campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260929-RERUN1/interface-review-v1.json`
- `campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260929-RERUN1/root-review-receipt-v1.json`

RERUN1 的 candidate/source/interface/receipt SHA-256 分别为：

```text
9c56712ff9e8c75b2ae31b08f2413100830fd208e1d741b693fb3b12d63857ea
7401601725fc6ffcfc18b89d1fb1c95b225eb2915f074d87e3844d7ceb20f4c8
4fab2e4e2809630acaf10ff13b2de360171f71cbe521ba18776fc5dcf9beb200
a4951aa48c4ad4bc1b9b08a92a0fb80ab6019669a1948135d32c6dd9a8cd3dd9
```

结果仍为 `root_review_only_blocked`、`admission_granted=false`、
`qualification_claim=none`、credit=`0`；Definition writer、Core preflight、GPU、queue、
registry、ledger、T1/T2 denominator mutation 全部保持关闭/零。版本化 writer 现在对已存在
artifact fail-closed，不能覆盖 RERUN 或历史文件。

## 验证

```text
lagrangian-fluid-lab/.venv/bin/pytest -q lagrangian-fluid-lab/tests/test_f7*.py
68 passed in 14.31s
py_compile: passed
git diff --check: passed
```

实现脚本 SHA-256：
`fe61c2d3c29613f4777c6c599f8f9d07e9f30c4bbaf6435ac10f506772003ea7`。

本次没有启动 solver、GPU、queue，也没有读取大型生产 artifact；仅保留既有隔离 canary 的
小型静态/运行证据绑定，F7 仍不具备 Core admission。
