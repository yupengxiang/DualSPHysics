# R3 G4 历史结论：无 sidecar 的因果输入与多路线学习基线

> **历史快照（pre-sidecar）。** 本文件保留用于比较上一轮没有边界三角形 sidecar 的基线，不能作为当前 G4 结果入口。当前权威报告和结论是 [`r3-g4-sidecar-baseline-audit.json`](r3-g4-sidecar-baseline-audit.json) 与 [`R3-G4-SIDECAR-CONCLUSION.md`](R3-G4-SIDECAR-CONCLUSION.md)。

状态：**development-only；基线路线和指标闭环已执行，但当前 W11 pilot 没有完整边界三角形 sidecar，因此不能宣布正式学习排行榜或物理验收。**

## 路线与统一口径

| 路线 | runs | seeds | case-macro position RMSE/dp | case bootstrap 95% |
|---|---:|---|---:|---:|
| particle_mlp | 3 | [17, 29, 43] | 18.75369958082835 | 2.0503466526667276–50.34132639567057 |
| deepset_context | 3 | [17, 29, 43] | 10.262081854873234 | 1.249433736006419–26.396507898966473 |
| local_interaction | 3 | [17, 29, 43] | 27.28867008950975 | 4.354780912399292–73.01725006103516 |
| physics_residual | 3 | [17, 29, 43] | 8.336135069529215 | 2.946463108062744–18.596529006958008 |

所有学习路线都使用初始质量加权 COM、统一的 solver velocity 状态（训练使用当前帧速度，rollout 从帧 0 速度开始并只消费自己的下一帧速度）、不依赖文件终点的 elapsed time，以及相同的 `8*tanh(raw/8)` 平滑输出上限。位置、速度和 COM 均采用向量范数 RMSE；bootstrap 的重采样单位是物理案例而不是帧。

常速度结果仅作为弱、确定性的参照。学习器相对常速度的退化率逐案例报告，但**不作为场景准入门槛**；困难且可信的案例仍应保留。

## 因果输入与已知限制

当前 pilot 的 F2 提供当前时刻的规定杯体控制曲线，F1/F3 没有 control group；未来流体状态、未来密度/压力和自由刚体未来轨迹没有进入 rollout。密度、压力、质量仅作为初始属性。所有 12 个可训练 fluid cases 的 boundary availability 仍为 false，因为 W11 尚未发布完整 wall triangle sidecar；这是真实阻塞项，不是由零向量伪造的几何输入。

本轮只评测 T1 numerical particle rollout。T2 material transport、T3 external observables 和 F6 coupled free-body route 不在该实验中打分。

## 学习曲线和下一步

每个 route/seed 最多 8 epochs，至少 3 epochs；以 validation autonomous rollout 的 case macro RMSE、patience=2 和 min-delta 作为停止与 checkpoint 选择规则，并在机器可读报告中保存每一 epoch 曲线。下一步应先补齐边界 sidecar，再复跑相同 matrix；之后才考虑三维 F6 的 coupled body-state model。

机器可读历史明细见 `r3-g4-baseline-audit.json`；当前 sidecar-aware 明细见 `r3-g4-sidecar-baseline-audit.json`。实际运行入口和 GPU 分配见 `r3_g4_run_manifest.json`。
