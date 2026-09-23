# F3 material row30 R003 首次 RK stage 离线回放（2026-09-24）

## 结论

对 R003 的 43 个最终 unknown seed，按原始 trace 状态、绑定的 CFD source frame 和执行代码逐个回放其首次失效 interval。结果为：40 个首个不可靠 stage 是 `wall_occluded`，另 3 个是 `low_effective_sample_size`。40 个墙遮挡 query 全部越过至少一个登记的封闭面，向外距离为 0.001655–0.347031 mm；相应邻域候选粒子仍在容器范围内，全部被有限墙可见性检查拒绝。这是 RK4 中间 stage 查询越界的证据，不支持“墙可见性误判”的解释。

R003 的固定科学门仍失败：来源 0/1 的 unknown 分别为 22/2048（1.0742%）和 21/2048（1.0254%），均超过 1% 上限；512-vs-4096 独立 CDF 对照也仍未绑定。因此本回放不接受 row30、不增加 T2 credit，也不改变失败分母或阈值。

## 证据绑定与范围

- [R003 terminal receipt](../campaigns/core-v1/material/evidence/f3-material-row30-r003-terminal-audit-v1/receipt.json)：SHA-256 `5f629213e01109849b08b6422d6da441966f25a5f4e53a4ec061cf6673fada3f`。
- [trace summary](../campaigns/core-v1/runtime/attempts/f3-material-30-canonical-s4-r003/20260923T105621-d33cb17f4735/trace.summary.json)：SHA-256 `6e310de7c343d8e67da7611870f54336a5585ed16f06296d2996e4d7704b457d`；其中 `code_sha256=e1c5fc39e73781d386c7da2874c1749b5223c8209e8af8f25bb4453346df51ff9`。
- [source preflight](../campaigns/core-v1/runtime/attempts/f3-material-30-canonical-s4-r003/20260923T105621-d33cb17f4735/source-preflight.json)：SHA-256 `d52857120d91e855c1e33089d63ce990cb00f817b8a1b73e9ea6fa32eb7bfc12`；CFD source SHA-256 `fb304e0bc8e5d7f51eaab0af0d8dba8c928b8146e0bf5776002f83012e4480c4`。
- [trace HDF5](../campaigns/core-v1/runtime/attempts/f3-material-30-canonical-s4-r003/20260923T105621-d33cb17f4735/trace.h5)：515,193,688 bytes，SHA-256 `10e5219d6821d8963a82e068135f078a696a5a111fbd79f598408508c3799366`，与此前独立流式核验及 terminal receipt 一致。
- 原始执行快照中的 [`f3_native_volume_mls.py`](../campaigns/core-v1/runtime/snapshots/b1f86844ad94d18d47e841756d4530dcce1d7e03e5c4ba67981bd6933db95de5/lagrangian-fluid-lab/scripts/f3_native_volume_mls.py) 与当前文件 SHA 相同；墙几何与 `segment_visibility` 所在 [`passive_tracers.py`](../campaigns/core-v1/runtime/snapshots/b1f86844ad94d18d47e841756d4530dcce1d7e03e5c4ba67981bd6933db95de5/lagrangian-fluid-lab/scripts/passive_tracers.py) 也与当前文件逐字节一致。回放没有误用后来的 temporal-v3 backend。

只读读取了 trace 的 unknown/frame/seed 状态与首失效前一输出帧位置；对 CFD source 做了一次完整顺序 SHA-256 校验，随后仅从 HDF5 数据集读取 37 个对应 native frame payload（每帧 34,560 个流体行）。每个 seed 最多回放该 interval 的 4 个 RK 子步及 k1–k4。source hash 与 preflight 和 trace binding 一致。未遍历重算全轨迹，未运行 tracer worker、solver、GPU 或 queue，未修改 queue、registry、ledger、阈值、矩阵或既有产物。

trace 没有逐 seed 保存首个失败的 RK 子步、stage query 和该 stage 的支持诊断，所以这是受原始代码、state、source hash 约束的离线重放，不是历史 stage log。receipt 未保存原始 Python/NumPy/SciPy/BLAS 运行时指纹，故不声称跨运行环境 bitwise-identical；本次运行环境为 Python 3.10.12、NumPy 2.2.6。

## 首个失败 stage 结果

| 首个 stage 原因 | Seed 数 | 来源分布 | 首个 stage | 关键诊断 |
|---|---:|---|---|---|
| `wall_occluded` | 40 | source 0：19；source 1：21 | k2：17；k4：23 | 40/40 的候选均被拒绝，support=0；query 越过最近封闭面 0.001655–0.347031 mm；40/40 邻域候选都在登记容器范围内 |
| `low_effective_sample_size` | 3 | source 0：3；source 1：0 | k2：1；k4：2 | 无 wall rejection；support 分别为 9、12、6，ESS 分别为 3.76345、3.60767、2.40041，均低于 4 |

source 1 最早在输出 frame 237（2.3700045 s）失效；source 0 最早在 frame 422（4.2200150 s）失效。43 个首次失效分布在 37 个 native interval。3 个低 ESS 案例为 seed 247/frame 756/k2、seed 55/frame 592/k4、seed 143/frame 756/k4。

40 个越界 stage 的上一 RK stage 重建速度均指向最近封闭面外侧，法向分量为 0.004629–0.320658 m/s（中位数 0.029798 m/s）。按 k2 的 `q + 0.5 dt k1` 与 k4 的 `q + dt k3` 计算，法向位移预测的越界深度与回放 query 几何一致，最大绝对残差 `2.8e-14 mm`。这进一步确认越界来自当前 RK stage 公式及其重建外向速度，而非 trace 行与 seed 的错位。

另做了只读的“坐标投影到最近闭壁”反事实：对原 40 个失败 stage query 投影到墙面并用同一 source frame 重建，40/40 都恢复为 reliable；但投影点的外向法向速度仍 40/40 为正，范围 0.004623–0.346446 m/s（中位数 0.029917 m/s）。因此坐标钳位本身没有建立无穿透的后续轨迹；如果下一 stage 仍使用该外向分量，仍会请求域外 query。此反事实只用于排除“单纯钳位已足够”的解释，不是被推荐或接受的边界处理方案。

墙遮挡 query 的坐标落在封闭容器外侧，候选流体粒子仍在容器内；连接 query 与内部候选粒子的线段因此穿过封闭面。当前有限墙 visibility 的全候选拒绝与几何关系一致。保存的上一输出帧 tracer 位置仍在域内，而首个不可靠点出现在 k2 或 k4，说明应调查 RK stage 的越界机制；仅凭本证据还不能裁定应采用边界事件定位、法向约束或其他离散策略。

## 下一步边界

可以继续做不启动作业的数值设计审查：比较候选 stage-boundary 处理在 manufactured/解析流场上的守恒、收敛与边界行为，并保持当前门槛和 unknown 记账不变。不得仅为通过门而钳位 query、删除 failed seed 或重归一化 survivors。任何新 row30 attempt 仍需先有新的 root decision、fresh resource/scheduler preflight、独立输出命名空间和恢复契约；本回放不授予 worker、solver、GPU、queue 或 T2 执行权。
