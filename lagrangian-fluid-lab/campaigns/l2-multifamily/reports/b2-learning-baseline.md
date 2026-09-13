# B2 学习基线登记

结论：登记了两个三种子开发轨道，但没有模型资格化或数据发布声明。

| 轨道 | 路线 | seeds | 测试 rollout | 跨 seed 宏平均 RMSE/dp |
|---|---|---:|---:|---:|
| raw learned dynamics | `local_interaction` | 3 | 9/9 | 43.3271 ± 3.7149 |
| constrained/hybrid | `physics_residual` | 3 | 9/9 | 10.4168 ± 1.5263 |

- 输入因果审计通过：只允许当前预测状态、当前控制、当前边界摘要和初始属性；不读未来流体/刚体状态。
- A1 的 96 case-run 失败曲线、oracle 误差和有限/穿墙分类被原样保留。
- 这些结果仍是 development/candidate-only；没有墙面物理通过、T2/T3/T4 或正式模型资格结论。
