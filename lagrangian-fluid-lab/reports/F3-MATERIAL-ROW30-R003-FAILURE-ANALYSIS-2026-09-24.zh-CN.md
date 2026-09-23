# F3 material row 30 R003：只读失败归因

本记录只综合 R003 的 terminal audit、该 audit 绑定的 JSON 汇总和冻结 MLS 实现；本次归因未直接打开或哈希生产 trace HDF5／checkpoint NPZ，也未启动 worker、solver、GPU、队列或修改账本。核心执行及资格边界见 [`terminal audit`](../campaigns/core-v1/material/evidence/f3-material-row30-r003-terminal-audit-v1/receipt.json)。

归因所用汇总是 `campaigns/core-v1/runtime/attempts/f3-material-30-canonical-s4-r003/20260923T105621-d33cb17f4735/trace.summary.json`（SHA-256 `6e310de7c343d8e67da7611870f54336a5585ed16f06296d2996e4d7704b457d`）；R003 授权绑定的 MLS 源码 SHA-256 为 `e1c5fc39e73781d386c7da2874c1749b5223c8209eaf8f25bb4453346df51ff9`。

## 结果

R003 成功完成全部 835 个原生间隔（836 帧，0–8.35 s），质量闭合，但没有通过固定材料可靠性门：每个来源 2048 个独立几何 seed，source 0 有 22 个永久未知（1.0742%），source 1 有 21 个（1.0254%），均超过每来源 1.0% 上限。独立匹配的 512／4096 seed CDF 比较也没有绑定到该 attempt，因此不得认定 T2。

| 来源 | 首次永久失效 | 终点未知数 | 终点失败原因 |
|---|---:|---:|---|
| 0 | frame 422，4.2200 s | 22/2048（1.0742%） | 19 `wall_occluded`，3 `low_effective_sample_size` |
| 1 | frame 237，2.3700 s | 21/2048（1.0254%） | 21 `wall_occluded` |

失败不是只出现在最终帧：两个来源的首次失效分别在 2.37 s 与 4.22 s，未知质量随后累积并保留到全窗终点。主导诊断标签是墙体可见性筛选造成的支持不足；source 0 另有少量有效样本量不足。执行窗完整、质量闭合，因此本次负结果不能归因于未跑满窗口或质量缺口。该分类不证明墙体筛选算法错误：跨实体壁拒绝邻居可能正是保持物理隔离所必需。

## 后续边界

不应通过放宽 1% 门槛或取消墙体可见性来“修复”该结果。若继续设计候选，应先在静态方案中区分几何遮挡与局部采样不足，并保持跨实体壁不泄漏；任何新 seed／后端／重建变体都需要独立的固定门验证和 CDF 对照。已批准的 row-30 资源／调度预检是一次性且结果为 blocked-no-worker，不构成新的 worker、solver、GPU 或队列授权；本记录不触发重试。
