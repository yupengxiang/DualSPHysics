# F2 静态 full-cup H2 修复候选（2026-09-21）

这份记录是只读的路线提案，不是运行结果或资格结论。静态 full-cup 的 v4 输入矩阵已经完成 15 行 CPU GenCase/native decode 闭合，但 cell-0 的两个独立运行仍然在早期观察窗触发实体墙完整性失败：原生 DBC 首次失败约为 `0.02001944 s`，H1 mDBC 修复首次失败约为 `0.02001457 s`。两次失败都保留在同一个固定 15 行分母中，不能扩展剩余行、删掉失败或重试同一输入。

提案的 H2 假设是“初始液体支撑间隙不足”：保留连续杯体、重力、时间窗、原生质量策略和 H1 的 mDBC/显式法向设置，只生成一个全新液体初始晶格。对每个粒距定义 `c(dp)=3*hdp*dp`，其中 `hdp=1.3`；流体平面在杯体左右和底面距离至少为 `c(dp)`，液体高度由

\[
H(q,dp)=\frac{0.022950+0.001290q}
{(0.425-2c(dp))(0.30-2c(dp))}
\]

计算。静态连续几何筛查表明三个粒距和五个参数点都能在杯顶 `z=1.10 m` 以下容纳声明体积；离散粒子质量、ID、法向和端点门仍未验证。

新候选使用独立 case identity：`CORE_F2_static_full_cup_volume_supportclearance_h2`，revision 为 `F2_static_full_cup_support_clearance_h2_v1`。旧 Definition、旧轨迹和旧 anchor 均不复用为 H2 结果。

当前状态：

- `qualification_claim=none`，`T1_numerical=false`，`matrix_credit=0`；
- 固定分母为 15 行，当前 `executed=0`；
- 不允许 Definition 写入、GenCase、native decoder、solver、GPU、job、队列、ledger 或 registry；
- 后续只有在单独 root review 通过静态 fit 与质量检查后，才能授权一次新的 CPU/native canary；即使通过，也只产生零信用输入证据。

提案及哈希绑定见 [f2-static-full-cup-boundary-repair-h2-proposal-v1.json](../campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-proposal-v1.json)。
