# Core continuation status — 2026-09-27 — UPDATE-253

## F3 h2_k48 材料候选完整窗口诊断

在 baseline24 单例材料 smoke（UPDATE-239）之后，对真实 F3 `F3_DEV_00_a0p903125` 完整跑通预注册的 `h2_k48` 邻域候选：512 seeds、48 neighbors、substeps=2、836 frames、835 transitions。运行 wall=`283.35377051192336 s`，peak RSS=`635720 KiB`，最终 frame=`835`；HDF5 output SHA-256 为 `6d1cc29db627fff2909ac019b715db72fae52491ec6425b267006d54efac1897`，checkpoint SHA-256 为 `eee30e3b7eca8d48aa8c6ceb619566327a28ab2984134e67f1ec7153b760c9c8`。完整 receipt 见 [`F3-MATERIAL-H2-K48-REAL-SMOKE-2026-09-27.json`](F3-MATERIAL-H2-K48-REAL-SMOKE-2026-09-27.json)。

质量守恒和 unknown 单调性通过，但固定 `unknown <= 1%` gate 失败：source0/source1 final unknown=`0.0546875/0.03125`，common reliable path coverage=`0.95703125`。相较 baseline24 的 `0.0390625/0.03125` 与 `0.96484375`，候选没有改善，故判定 `candidate_rejected_for_no_improvement`，不进入后续资格选择。

该运行仍是 diagnostic-only：不授予材料可靠性、宏观 T2、T1 或 credit；未修改 production HDF5、registry、ledger 和分母，未启动 solver/worker/GPU/queue。F3 当前需要继续推进完整模型训练和正式 case-run 分母，不能把本候选结果解释为计划完成。
