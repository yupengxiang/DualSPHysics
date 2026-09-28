# F1 formal-run readiness/evidence bridge V1

状态：`blocked_fail_closed`。

本 bridge 只读取固定 allow-list 的 bounded JSON，并把 F1 的 15 行 preparation、formal job metadata、qualification evaluation、source identity 元数据和历史 negative evidence 串成一个只读投影。不打开或统计生产 HDF5、BI4、trajectory，不跟随 JSON 内嵌 artifact path，不启动或停止 solver、worker、native、GPU、queue，也不修改 registry、ledger、denominator、gate、PLAN 或 completion。

## 当前已经绑定

- F1 H1 candidate/design/prepared matrix：`15/15` 行 preflight/static/mass preparation 通过；这仍然是 preparation-only，不是 formal runtime 或 T1。
- 固定 formal 分母：15 行；当前 formal runtime rows=`0`，missing=`15`，缺失行全部保留。
- source metadata：source Definition、design digest、matrix digest 已记录，但 Core manifest、known_inputs、每行 source hash 和 solver/runtime identity 尚未闭合（`closed=false`）。
- 历史 terminal/negative evidence：full-window canary 的 event window 完成但 hard-integrity 失败；G1 anchor 同样 event complete 但 hard-integrity 失败；两者都排除 numerator。

## 未闭合 blocker

- `fresh_f1_reopen_authorization_missing`：the current F1/F2 route is closed with no auditable new falsifiable F1 Definition; fresh root review is required before any formal run or GPU submission.
- `formal_runtime_products_missing`：the fixed F1 job manifest remains prepared_only and the qualification evaluation retains all 15 runtime rows as missing; preparation cannot substitute for result, audit, observations, or trajectory products.
- `source_identity_closure_missing`：source Definition, design digest, and matrix digest are metadata-only bindings; no Core manifest, known_inputs closure, per-cell source hash, or solver/runtime identity is bound for the formal products.
- `terminal_evidence_missing_or_failed`：no formal 15-cell terminal receipts exist; the retained full-window canary and G1 anchor complete their event windows but fail hard integrity, so neither is a terminal qualification pass.
- `fixed_15_row_denominator_incomplete`：the fixed 15-row denominator retains 15 missing formal runtime rows and zero formal runtime rows; all missing rows must remain visible.
- `qualification_gates_incomplete`：the current evaluation has canary, matrix, spatial, time/output, cadence, and independent checks closed; T1_numerical remains false and credit remains zero.
- `material_evidence_absent`：F1 has no independently bound material sidecar, training, or reproduction evidence; preparation and historical negative evidence are not T2 evidence.

因此：prepared=15/15，formal runtime=0/15，terminal rows=0；`formal_run_ready=false`、`T1=false`、`T2=false`、credit=0。不能把 preparation、observer calibration 或历史失败当成 formal/T1/T2 成功。

下一步必须先获得一个超出 H1/H2/H3/G1 已关闭谱系的新 F1 物理 Definition、独立 root review 和新 namespace；之后才能补齐 source-bound 15-cell runtime/terminal evidence，并重新运行本 bridge。

机器报告：`F1-FORMAL-RUN-READINESS-EVIDENCE-BRIDGE-V1-2026-09-28.json`。
