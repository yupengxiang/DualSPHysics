# Core continuation status — 2026-09-27 — UPDATE-261

## F3 `h1_affine_bound` 材料候选完整窗口诊断

### 候选与科学理由

在 UPDATE-239 的 baseline24 和 UPDATE-253 的 `h2_k48` 之后，本轮选择已登记的 `h1_affine_bound`。它保持 k=24、visible-Shepard 权重、substeps=2、regularization、support distance 和 unknown≤1% 固定 gate 不变，只把已有的 `local_affine_query_bias` 加入重建误差估计。这样可以独立检验：真实 unknown 是否主要来自移动 tracer 查询点的局部重建偏差，而不是单纯来自邻域数量不足。该控制与 UPDATE-253 的 h2_k48 正交：h2 只改变邻域 cap，本候选只改变误差估计器。

候选运行前没有修改生产算法。现有 synthetic/contract 定向回归为 **62 passed**；CLI synthetic harness 保持 source path 不可用、全分母、固定 gate、失效 support fail-closed 和零资格信用。额外 quadratic probe 中，baseline residual 最大值为 `3.5288183843696714e-05 m/s`，h1 affine query bias 最大值为 `8.287120632502247e-06 m/s`，h1 estimated error 最大值为 `4.357530447619896e-05 m/s`；估计误差只增加、不放宽 gate。

### 真实 F3 单 case 结果

真实 `F3_DEV_00_a0p903125` 使用 512 个独立 seed，完整读取 836 个 native frame（835 transitions）至 `8.350012828223477 s`。运行 `completed`，HDF5 `committed_frame=835`，临时输出和 checkpoint 的 SHA-256 已写入机器回执 [`F3-MATERIAL-H1-AFFINE-BOUND-REAL-FULL-2026-09-27.json`](F3-MATERIAL-H1-AFFINE-BOUND-REAL-FULL-2026-09-27.json)。

| 配置 | source0 final unknown | source1 final unknown | common reliable coverage | fixed unknown gate |
|---|---:|---:|---:|---|
| baseline24（UPDATE-239） | 0.0390625 | 0.03125 | 0.96484375 | fail |
| h2_k48（UPDATE-253） | 0.0546875 | 0.03125 | 0.95703125 | fail |
| h1_affine_bound（本轮） | 0.0859375 | 0.09375 | 0.91015625 | fail |

h1 的 source0/source1 首次不可靠 frame 分别为 `244`（`2.440000728246361 s`）和 `321`（`3.210003315394127 s`）。质量守恒 `mass_closed=true`、unknown 单调性 `true`，但两个 source 的 unknown 都比 baseline24 和 h2_k48 更差；common reliable coverage 比 baseline24 低 `0.0546875`，比 h2_k48 低 `0.046875`。

### 结论与边界

判定：**拒绝 `h1_affine_bound`，不接受后续 F3 材料路径**。这只说明该保守 affine query-bias 估计器在当前固定 gate 和真实 F3 case 上没有改善可靠窗口；不能把它解释为 baseline 已获得材料资格，也不能由此放宽 gate 或删除 unknown。

本轮仍为 diagnostic-only：`T2_macro=false`、`T2_path=false`、`T1_numerical=false`、`qualification_credit=0`。未改 registry、ledger、denominator、gate、production HDF5 或生产算法；未启动 solver、worker、GPU 或 queue。写集仅为本报告和对应 JSON receipt；没有新增测试文件。
