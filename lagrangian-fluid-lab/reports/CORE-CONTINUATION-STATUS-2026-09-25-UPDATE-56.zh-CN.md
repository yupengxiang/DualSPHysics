# UPDATE-56：F3 row30 no-slip boundary/time refinement 离线 sweep

日期：2026-09-25（Asia/Shanghai）

针对既有 R003 的 40 个终态 `wall_occluded` seed，新增只读脚本和 helper tests。脚本核对 source、trace 与注册 MLS backend SHA-256，只回放各首失效 native interval 的剩余部分；测试时间细化因子 1/2/4/8/16，并在最近闭壁 0.25–1.9h 评估 constrained fit 与 unconstrained wall-foot 外推。40/40 seed 在所有时间细化下完成剩余 interval，factor1 到 factor16 的最大 endpoint 差 `6.8081e-11 m`，但每档均 16/40 seed 超出原 residual 门，最大 constrained residual 约 `0.2240 m/s`；外向法向求值比例保持约 29.3%。空间剖面各距离仍有 16–20/40 越残差门；unconstrained wall-foot 速度 median/max 为 `0.06252/1.11648 m/s`。

结果说明对该诊断 field 的继续时间细化不消除局部重建残差；当前 constrained MLS 候选不合格，不能用于 row30 重试。新增 tests 2 passed、py_compile 与 diff check 通过。未改变历史数据、后端、阈值、分母、root decision 或 T2 credit；未运行 worker/solver/GPU/queue/native 作业。详见 [F3 sweep report](F3-ROW30-R003-NOSLIP-REFINEMENT-SWEEP-2026-09-25.zh-CN.md)。
