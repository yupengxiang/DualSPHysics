# F6 v10 observation-axis 资格矩阵设计（2026-09-21）

这一步冻结的是 v4 候选资格研究的参数卡和静态矩阵。设计本身不启动 GenCase、
solver、GPU、runtime queue，也不写 registry、ledger 或 qualification matrix。矩阵
产物的状态是 `root_review_only_not_submitted`；所有单元都是 `qualification_only`，
`qualification_claim=none`、`qualification_credit=0`、`T1=false`。

## 研究轴与固定签名

F6 v10 把单一研究轴定义为刚体初始质心释放高度
`body_release_com_z_m ∈ [0.49, 0.61] m`，令

\[
z(q)=0.49+0.12q,\qquad q\in[0,1].
\]

这只改变初态的自由落体事件时间，保持 F6 v4 候选中的流体、刚体、边界、材料参数
和控制机制不变。为使三档粒距都通过离散支持范围硬门，v4 固定连续流体盒为
低面 `[0.175,0.050,0.040] m`、尺寸 `[1.14,0.465,0.24] m`；该几何和体积是
新 scope 的一部分，不能继承旧 v10 v2 几何。空间资格锚点为 `q=0, 0.5, 1`，
独立内部点为 `q=0.25, 0.75`。空间格使用三档粒距 `0.025/0.020/0.015 m`，
锚点各三档，两个内部点各生产档和细档，共 13 个空间单元。另在中心生产档加入
一个内部时间推进对照和一个原生输出 cadence 对照，因此总矩阵固定为 15 个单元。

每个单元有独立的 Definition、生成 XML 和 BI4 要求，旧 v10 canary 不能作为输入。
每格必须先通过静态 GenCase/native preflight，之后才可获得独立 solver 授权；
不能从一次 canary 推导其他分辨率或参数点的资格。

## 时间与事件合同

- solver 报告的实际 `TimeStep` 是唯一评分时间轴；不能把帧编号或规定输出间隔冒充
  实际时间。
- 初始目标时域为 `0--1.5 s`，必要时整个 scope 一次性延长到 `3.0 s`；不能只
  延长成功单元。
- 基线输出间隔目标为 `0.005 s`，最大实际相邻间隔 `0.0055 s`；原生 cadence
  对照使用 `0.0025/0.00275 s`。内部时间对照收紧 CFL，并确认实际推进步数变化。
- `[1.0,1.5] s` 是 observation hold，只要求被实际时间轴 bracket，不声称平衡。
- 接触时间窗口由连续初态和刚体几何独立计算，再与 solver sidecar 核对；闭合面接触、
  穿透和开顶质量通量仍是逐格硬门。

## 证据边界

先前 v1（旧低面）和 v2/v3（网格相位修正）预检中的失败保留在独立目录中：它们分别
暴露了粒子越过连续盒边界和 `dp=0.025` 质量闭合失败。没有放宽几何或质量门，也没有
覆盖失败分母；v4 以新的 scope/revision 从 fresh 输入重新开始。v4 15 格 native
preflight 已全部 exact-one 通过，详见聚合审计，但这仍不是 runtime 事件窗或 T1
资格。

当前设计绑定了 v10 fresh Definition contract、CPU/native preflight receipt 和
solver canary receipt 的 SHA-256。后两者只作设计上下文，且本身已标记为非资格证据；
它们不替代 15 格的新输入、逐格 preflight、实际时间轴审查和固定 8→32 生产规则。
qualification-only 结果不得进入训练、归一化统计、模型选择或 Core 模型分母。

产物：

- [设计记录](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-qualification-design-20260921/design.json)
- [15 格矩阵](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-qualification-design-20260921/matrix.json)
- [候选参数卡](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-qualification-design-20260921/candidate-card.json)
- [root admission](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-qualification-design-20260921/root-admission.json)
- [15 格 native preflight 聚合审计](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-qualification-preflight-v4-20260921/qualification-preflight-audit.json)
- [自动契约测试](../tests/test_f6_physical_anchor_observation_axis_v10_qualification_design.py)

下一步是对 v4 的独立 solver canary 研究建立 root authorization，先运行预登记的
8 个 canary 单元并逐格保留失败分母；在全部硬门和事件完整性通过前，不提交 F6 T1，
也不进入 8→32 生产。
