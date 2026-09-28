# F2 resting-fill formal-run readiness/evidence bridge V1

状态：`blocked_fail_closed`。

本 bridge 只读取固定 allow-list 的 bounded JSON，并把 F2 static full-cup resting-fill 的 preparation、历史 runtime receipt、admission 和 Core interface metadata 串成一个 15 行证据投影。它不打开或统计生产 HDF5/BI4/trajectory，不启动 solver、worker、native、GPU、queue，也不修改 registry、ledger、denominator、gate 或 PLAN。

## 当前已经绑定

- v4 CPU/native preparation：15/15 输入行完成 hash/preflight closure；这仍是 preparation-only，不是 T1/T2。
- 固定失败分母：15 行保持不变；cell 0 是历史 `failed_static_gate`，其余 14 行是 `missing_runtime_product`。
- 静态 nominal anchor：历史 hard-integrity/event/static-settled 事实仅作为 anchor，明确排除 numerator。
- Core interface：现有接口只有 1 个 case 且 `formal_release=false`。

## 未闭合 blocker

- `static_scope_not_core_third_family`：scope review keeps fixed zero-motion resting-fill as prerequisite_only; it is not admitted as the Core third T1 family.
- `future_formal_runtime_admission_missing`：the qualification admission and root review allow preparation/decode only; the historical runtime review is smoke-only for cell 0 and does not authorize a 15-cell formal run.
- `cell_00_historical_hard_failure`：cell 0 is retained as failed_static_gate with cup closed-face endpoint, saved-chord, open-cup escape, and spatial-comparison failures.
- `fourteen_runtime_rows_missing`：the fixed 15-row denominator retains 14 missing runtime products; prepared inputs do not fill those rows.
- `core_formal_interface_not_released`：the existing Core interface is a one-case formal_release=false metadata interface, not a formal 15-cell F2 release.
- `t1_runtime_evidence_incomplete`：no complete 15-cell runtime/observer/temporal/held-out evidence chain is bound; T1 remains false and credit remains zero.
- `t2_material_evidence_absent`：no independent F2 material-sidecar/training/reproduction evidence is bound; preparation and historical failure are not T2 evidence.

因此：prepared=15/15，historical failed=1，missing runtime=14；`formal_run_ready=false`、`T1=false`、`T2=false`、credit=0。不能把 preparation 或 historical hard failure 当成成功。

下一步必须先获得新的物理 scope/独立 root review 与 fresh 15-cell runtime admission，再为每个 cell 绑定 prepared hash、case_id、native identity、trajectory/observer/temporal evidence，随后重新运行 bridge。

机器报告：`F2-RESTING-FILL-FORMAL-RUN-READINESS-BRIDGE-V1-2026-09-28.json`。
