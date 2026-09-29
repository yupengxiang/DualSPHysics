# F6 observation-axis v4 route closure（2026-09-29 RERUN1）

这是对当前小型静态 route card 的 hash 绑定刷新。历史 `2026-09-21` 报告以及 v1 card/receipt
均保留，不覆盖；本次没有重新读取生产轨迹，也没有运行 Definition、GenCase、native decoder、
solver、GPU 或 queue。

## 当前失败的分类

旧 v1 receipt 的 `core_completion` 绑定仍是 `2359` bytes、
`c081c4e1f75fe2c04b2261ac8c07f1ab2a6d4ca4b2ef749578594117d88c5aa9`。当前
`campaigns/core-v1/completion.json` 已由后续 Core gate 更新为 `3959` bytes、
`51aa36d360f7f9a6c8387726ad9bf124fee87bc9c5b34a2c8081e82b4e515647`。
这属于 stale checked-in receipt，而不是 F6 科学代码失败；F6 的 route decision、失败 cell-08、
分母和 zero-credit 语义没有改变。

## RERUN1

当前脚本常量已切换到新的不可覆盖输出：

- card：`campaigns/core-v1/cfd/f6-observation-axis-v4-third-t1-route-closed-20260929-RERUN1.json`
- receipt：`campaigns/core-v1/evidence/f6-observation-axis-v4-third-t1-route-decision-20260929-RERUN1.json`

RERUN1 当前 card SHA-256 为
`a26fd85bfd80f3884baa5460dabbc9c6b9fe1c3f915c160ea967a064868dc5f5`，receipt SHA-256 为
`f4ff360e0ac1231a7902648ebf50fcebd83e14672901b658bfbd6a7cedfb63f0`。两者均保持
`route_closed_no_new_hypothesis`、`T1=false`、`qualification_credit=0`、
`solver_authorized=false`、`gpu_authorized=false`、queue/registry/ledger/matrix mutation 为 `0`。

旧 v1 card、receipt 和历史报告未被改写。

## 验证

```text
lagrangian-fluid-lab/.venv/bin/pytest -q lagrangian-fluid-lab/tests/test_f6*.py
49 passed in 1.60s
py_compile: passed
git diff --check: passed
```

实现脚本 SHA-256：
`6954d6a72512d2a3bb13ba5a06100ab767748b9e27bcdecc9beb4d033d3c9715`。
