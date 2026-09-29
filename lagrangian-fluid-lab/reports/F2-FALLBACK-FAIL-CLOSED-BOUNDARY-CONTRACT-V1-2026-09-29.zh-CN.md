# F2 fallback fail-closed boundary contract v1（2026-09-29）

这是一个只读 bounded contract validator 的独立闭环。它把当前 F2 static/full-cup、dynamic DBC/open-top 与 pour/catch root-review 状态绑定起来，但不把任何准备、历史失败或 canary 变成 formal/T1/credit。

## 结论

- 状态：`blocked_fail_closed`；所有 13 个契约检查通过。
- static/full-cup：固定 15 行，cell-00 保留 `failed_static_gate`，missing runtime `14` 行。
- dynamic DBC：分母/分子 `15/0`；Boundary=1，几何保留 open top；mDBC contact 与 open-tray position-loss 负证据继续阻塞。
- pour/catch：route=`root_review_only_conditional_route`，gap=`blocked_before_new_definition`，`worth_preflight_now=false`，proposal credit=`0`。
- formal/T1/T2/qualification 均为 `false`，credit 为 `0`；没有 solver、worker、native、GPU、queue 或中央状态写入。

## 保留的硬边界

- cell-00 hard failure、14 个 missing runtime、dynamic boundary/open-mouth（open-tray）负证据以及 catch event ownership 未审查均不可被该 contract 绕过。
- 不读取依赖 JSON 中记录的 trajectory/HDF5/BI4 路径；只读取固定 allow-list 内的有限 JSON。
- 不修改 PLAN、registry、ledger、denominator、gate、completion；不启动任何 native/solver/worker/GPU/queue。

## 依赖

| key | path | bytes | sha256 |
|---|---|---:|---|
| `static_full_cup_bridge` | `reports/F2-RESTING-FILL-FORMAL-RUN-READINESS-BRIDGE-V1-2026-09-28.json` | 22423 | `38c18f1f827098cdf245b770e655a89242dea902f514b00c2d3075d9963d4948` |
| `dynamic_matrix` | `campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-matrix-v1.json` | 8559 | `cf356f1cf7d0b02474ce7e6d215a9ff07eea0d6293aca5c87799014367c5dcf1` |
| `dynamic_failure_denominator` | `campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-failure-denominator-v1.json` | 6526 | `037b22e8148c3c0f8f72f1b47550fd808072a5e3ce9810fadd0fda9fd04eda1b` |
| `pour_catch_route` | `campaigns/core-v1/cfd/f2-pour-catch-route-audit-2026-09-29-RERUN1.json` | 5817 | `911a45df79e87e56f6edf90eb4a8478b91fd4f089fc2130ffbe7dbfcf5f6807c` |
| `pour_catch_gap_audit` | `campaigns/core-v1/cfd/f2-pour-catch-root-review-gap-audit-v1-2026-09-29-RERUN1.json` | 4502 | `f3a500028727e205f4a6073f5958518ae8048d9a895a35396923b3029e91aa84` |
| `pour_catch_candidate` | `campaigns/core-v1/cfd/f2-pour-catch-candidate-card-v2-2026-09-29-RERUN1.json` | 8939 | `45af80f942c2b75bba62b3aa8278dcc26eca1e2f8cc776fd73c13f2f01021d37` |

契约文件：`campaigns/core-v1/cfd/f2-fallback-fail-closed-boundary-contract-v1.json`。
