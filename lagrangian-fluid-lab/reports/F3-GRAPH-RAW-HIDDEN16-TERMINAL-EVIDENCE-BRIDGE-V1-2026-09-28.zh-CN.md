# F3 `graph_raw` hidden16 terminal-evidence bridge V1

机器报告：`F3-GRAPH-RAW-HIDDEN16-TERMINAL-EVIDENCE-BRIDGE-V1-2026-09-28.json`

- 状态：`bound_terminal_diagnostic`；source_bound=`True`。
- 终态合同：model=`graph_raw`、hidden=`16`、updates=`500`、`835` transitions / `836` frames。
- 已绑定真实 seed：`17`；缺失 seed：`29, 43`。
- seed17 的 evaluation JSON 只做流式字节/SHA 核对；checkpoint 与 trajectory 只做 stat，不打开内容。
- progress、trajectory/HDF5、manifest、solver、worker、GPU、queue 均未被读取或启动；已有 live job 未停止、未重启。
- 所有结果保持 diagnostic-only；formal/T1/T2/qualification=false，credit=0，所有 mutation=0。

## Seed 状态

- seed `17`：`bound_terminal_diagnostic`；无
- seed `29`：`missing`；missing terminal summary for seed 29
- seed `43`：`missing`；missing terminal summary for seed 43

## 审计解释

seed17 的 receipt 证明现有真实 diagnostic rollout 已完成固定 835-transition 窗口，并将 training/checkpoint、evaluation、validator 与 trajectory 元数据绑定到同一案例；它不等同于正式资格结果。seed29/43 若缺少同样闭合的输入，继续保持 fail-closed。
