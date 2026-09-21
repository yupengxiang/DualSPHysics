# F6 v10 v4 资格矩阵 native preflight 审计（2026-09-21）

F6 v4 scope `F6_fluid_rigid_body_physical_anchor_aligned_sampling_v3` 的 15 个矩阵
单元已经各自生成 fresh Definition、GenCase XML/BI4，并完成一次 CPU GenCase 和一次
native decode。每格都有独立目录、Definition identity 和 one-shot lock；没有启动
solver、CUDA、runtime queue，也没有写 registry、ledger 或 qualification matrix。

## 结果

- 13 个空间单元和 2 个时间／输出对照全部为
  `cpu_native_preflight_pass_exact_one`，聚合审计 `matrix_complete=true`。
- 三档粒距为 `0.025/0.020/0.015 m`；所有流体粒子均位于 v4 连续盒
  `[0.175,0.050,0.040]--[1.315,0.515,0.280] m` 内。
- 每格的流体连续质量相对误差均在 5% 门内，固定／浮体／流体粒子身份、有限值、
  刚体质量、质心和惯量门均通过。
- 中心内部时间格实际写入 `CFL=0.1, DtIni=1e-4, DtMin=5e-6`；原生输出格写入
  `TimeOut=0.0025 s`，预期 native 帧数为 601；其余格为 301 帧、`TimeOut=0.005 s`。
- 旧 v1、v2、v3 预检目录保留了网格相位和质量门失败，不被 v4 聚合审计覆盖，也不
  被重新解释成成功。

## 科学边界

这份审计只证明输入和 native 初态可以逐格复现；它没有运行流体／刚体时间演化，不能
证明接触事件、浮力响应、闭合面无穿透、开口质量通量或 observation hold 的完整性。
因此 v4 仍是 `qualification_only`、`qualification_claim=none`、`T1=false`、
`qualification_credit=0`，也不能进入训练或模型评测分母。

证据：

- [聚合审计](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-qualification-preflight-v4-20260921/qualification-preflight-audit.json)
- [v4 设计](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-qualification-design-20260921/design.json)
- [v4 root admission](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-qualification-design-20260921/root-admission.json)
- [fresh preflight materializer](../scripts/f6_physical_anchor_observation_axis_v10_fresh_preflight.py)
- [聚合审计测试](../tests/test_f6_physical_anchor_observation_axis_v10_qualification_preflight.py)

下一步只授权独立 root review 选定的 8 个 solver canary。solver canary 仍不能继承
旧 v10 runtime 结果；即使部分或全部 canary 失败，也保留失败分母并按预登记规则决定
是否重新审查 scope。
