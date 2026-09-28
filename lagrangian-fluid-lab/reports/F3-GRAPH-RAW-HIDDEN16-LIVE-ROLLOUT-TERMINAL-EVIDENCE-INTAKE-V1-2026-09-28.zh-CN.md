# F3 `graph_raw` hidden16 live rollout terminal-evidence intake V1

机器报告：`F3-GRAPH-RAW-HIDDEN16-LIVE-ROLLOUT-TERMINAL-EVIDENCE-INTAKE-V1-2026-09-28.json`

- 状态：`blocked_missing_terminal_evidence`；这不是资格结论。
- 目标：model=`graph_raw`、hidden=`16`、updates=`500`、seed=`17/29/43`。
- 固定分母：`835` transitions / `836` frames；progress/PID 不被视为完成。
- 边界：只读取有界 terminal JSON；不打开 manifest、HDF5、checkpoint、trajectory 或 progress。
- 结果：diagnostic-only，formal/T1/T2/qualification=false，credit=0，所有 mutation=0。

## Seed 状态

- seed `17`：`missing`；阻塞：missing terminal evidence for seed 17
- seed `29`：`missing`；阻塞：missing terminal evidence for seed 29
- seed `43`：`missing`；阻塞：missing terminal evidence for seed 43

## 后续

只有严格终态、hidden16、同配置、835/836 且零信用的 fresh terminal summary 才能重新 intake；当前缺失或非终态输入不会被提升为 T1/T2/qualification。
