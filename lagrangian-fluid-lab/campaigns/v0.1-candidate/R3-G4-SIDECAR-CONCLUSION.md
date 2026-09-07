# R3 G4 结论：因果输入与多路线学习基线

状态：**development-only；已执行 sidecar-aware 边界输入，但这仍不是正式学习排行榜或物理验收。**

## 路线与统一口径

| 路线 | runs | seeds | case-macro position RMSE/dp | case bootstrap 95% |
|---|---:|---|---:|---:|
| particle_mlp | 3 | [17, 29, 43] | 12.570788436465792 | 2.8298986752827964–31.07366879781087 |
| deepset_context | 3 | [17, 29, 43] | 9.504613041877747 | 1.3171005646387737–23.559518814086914 |
| local_interaction | 3 | [17, 29, 43] | 18.092622571521336 | 3.0960376262664795–47.31836128234863 |
| physics_residual | 3 | [17, 29, 43] | 11.061574432584974 | 2.731117089589437–27.19192059834798 |

所有学习路线都使用初始质量加权 COM、统一的 solver velocity 状态（训练使用当前帧速度，rollout 从帧 0 速度开始并只消费自己的下一帧速度）、不依赖文件终点的 elapsed time，以及相同的 `8*tanh(raw/8)` 平滑输出上限。位置、速度和 COM 均采用向量范数 RMSE；bootstrap 的重采样单位是物理案例而不是帧。

常速度结果仅作为弱、确定性的参照。学习器相对常速度的退化率逐案例报告，但**不作为场景准入门槛**；困难且可信的案例仍应保留。

## 因果输入与已知限制

当前 pilot 的 F2 提供当前时刻的规定杯体控制曲线，F1/F3 没有 control group；未来流体状态、未来密度/压力和自由刚体未来轨迹没有进入 rollout。密度、压力、质量仅作为初始属性。所有被评测 test cases 都通过了 sidecar schema、world 坐标、时间轴、三角形 provenance 和 per-seed 一致性检查；模型当前使用每一帧的有限三角形 AABB 摘要。

本轮只评测 T1 numerical particle rollout。T2 material transport、T3 external observables 和 F6 coupled free-body route 不在该实验中打分。

## 学习曲线和下一步

每个 route/seed 最多 8 epochs，至少 3 epochs；以 validation autonomous rollout 的 case macro RMSE、patience=2 和 min-delta 作为停止与 checkpoint 选择规则，并在机器可读报告中保存每一 epoch 曲线。下一步应验证三角形语义/可见性并补齐 T2/T3/T4；之后才考虑三维 F6 的 coupled body-state model。

机器可读明细见 `r3-g4-sidecar-baseline-audit.json`；实际运行入口和 GPU 分配见 `r3_g4_run_manifest.json`。
