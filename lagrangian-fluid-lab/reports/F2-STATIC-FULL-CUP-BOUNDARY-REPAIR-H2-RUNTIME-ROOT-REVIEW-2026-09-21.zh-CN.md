# F2 静态 full-cup H2 solver-canary root review（2026-09-21）

H2 的 CPU GenCase/native 输入门已通过，但仍没有任何 T1 资格信用。本 root review 只授权 `q=0, dp=0.010 m` 的一个全新 solver canary，窗口为 `0.60 s`、输出间隔 `0.02 s`；它绑定 H2 fresh Definition、输入 preflight 和 `c=3·hdp·dp` 支撑间距。旧 DBC／H1 mDBC Definition、旧轨迹和旧 BI4 不得作为该 canary 的输入。

授权状态保留为：solver/GPU/job-spec/队列/ledger 可以由后续明确执行步骤使用，registry 始终禁止，qualification credit 为 0，矩阵扩展和 same-input scientific retry 均禁止。执行控制在 review 写入时全部为 `now=false/0`；[runtime prepared manifest](../campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-runtime-v1/prepared.json) 只是 worker 输入，不是运行结果。

单元运行完成后必须检查完整 0.60 s 时间窗、有限状态、流体质量、实体墙端点、保存帧 chord crossing、缺帧和恢复状态，并将失败留在静态 full-cup 15 行固定分母中。即使该 canary 通过，也只能作为下一步范围资格的前置证据，不能自动注册 F2 T1 或启动其余矩阵。
