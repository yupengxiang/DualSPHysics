# F3 material coarse s4 terminal-result intake RERUN1

- 状态：`negative_diagnostic`（仅诊断；不授予 T1/T2/credit）。
- scheduler job：`core-f3-material-coarse-s4-rerun1`；attempt：`20260929T122756-ab18fca003d8`；worker pid：`1390695`；host：`ada`。
- execution receipt：`succeeded`，return code=`0`；GPU reservation=`0` MiB。
- 完整时域：`836` native frames / `835` transitions，committed frame=`835`。
- mass closure：`True`；unknown monotonicity：`True`。
- coverage：common reliable path=`0.947265625`；unknown max=`0.0625`，阈值=`0.01`；超过 1%，明确记录为 `negative diagnostic`。

该路径位于 git 忽略的 scheduler runtime 下；本报告只是 scheduler-owned runtime attempt 的只读引用，不是可携带的静态 formal receipt。
本 intake 只读绑定 result/spec/material JSON、worker/host identity 与 scheduler artifact hashes；未读取或重算 native source HDF5，未修改 runtime attempt、历史 receipts、registry、ledger、denominator、gate 或 completion。
