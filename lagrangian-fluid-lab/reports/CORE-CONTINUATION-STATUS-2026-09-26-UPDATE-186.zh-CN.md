# UPDATE-186：F4 tallwall120 配对诊断比较器提案

## 结果

新增 [F4 Tallwall120 paired diagnostic v2](../scripts/f4_tallwall120_pair_acceptance_v2.py)，与既有 v1 sidecar validator 并存，不改写历史输入、旧回执或 migration spec。比较器固定到当前活动 scope `F4_resting_pool_laminar_tallwall120_x_v1`、revision `F4_tallwall120_material_baseline24_v1`、case 与 recipe；拒绝迁移中的 `F4_drop_resting_pool_x_v2` 身份。

这是**提案级诊断政策**，不是已登记的 F4 科学门，也不是 T2 acceptance collector。政策把 `T=4.34 s` 明确用作归一化基准；若初始事件窗需要延长，只允许一次至名义 `8.68 s`，归一化 T 不变。实际 source endpoint 与名义 horizon 分开绑定；返回后的 `0.3497487083913345 s` gravity-time follow window 是独立完成条件，不充当 T。

提案数值如下，均需后续科学审定后才能谈正式登记：

| 指标 | 提案门 | 定义 |
|---|---:|---|
| 每 source unknown mass | `<= 0.01` | 各源独立以 all-initial-mass 为分母 |
| worst-case CDF interval gap | `<= 0.02` | contact/upward/return/residence，各源分别计算；左右连续阶梯 CDF 在两侧轴并集上比较，取区间端点组合的最大差 |
| residence mean interval gap | `<= 0.0868 s` | `T × 0.02`；每源比较两个 all-mass 加权驻留均值区间的最坏端点差 |
| paired-event time MAE | `<= 0.01085 s` | `T × 0.0025`；按共同 tracer ID 的事件质量加权，逐事件/逐源计算 |
| event detection error budget | `<= 0.00217 s` | `MAE limit × 0.20`；对每对共同事件取两侧 detection error bound 之和的最大值 |
| wall event endpoint / saved chord | `<= 1e-8 m` / `0` crossings | 继续采用 F4 已有几何容差 |

CDF 的 `0.02` 是此提案新定义的 F4 “2 个百分点最坏质量区间差”政策值；虽然数值与旧材料中提及的 F3 值相同，但实现不读取或继承 F3 gate，且这里仍是 `proposed_not_registered`。这项工程变更不能把它升级成权威科学容差。

source denominator 以逐 tracer canonical records 表示，并由该记录重算 contact/upward/return/residence CDF 全部 change points、unknown mass 与 residence mean bounds；不再接受“样本事件时间”和“CDF 曲线”两份互不一致的摘要。unknown tracer 必须声明首次不可靠时刻，且首次不可靠之后的事件不能声称为已观测事件。manifest body 绑定 generation/checkpoint/trace-output digest，canonical summary 再绑定完整 artifact digest envelope 和 manifest digest。

配对事件 MAE 只用于有共同观测 tracer 的事件；无共同事件时输出 `status=not_applicable`、`value_s=null`，并关闭 MAE gate，不以零误差通过。source hash 必须由调用方外部提供并与两侧声明一致；比较器仅处理 JSON，不自行打开源文件、HDF5、generation 或 checkpoint，也无法验证调用方提供的“外部 digest”是否真的来自独立可信 verifier（调用方可自行构造 payload 与对应 digest）。因此此 API 只能保持 diagnostic-only，未来接入 admission/collector 前还需要受信任的 verifier identity、签名或不可变 receipt。输出完整覆盖、由 endpoint/cadence 推导的可达 frame 数、seed 数量、scope/revision、事件窗与 right-censor 条件均 fail-closed。

## 验证与边界

- 新专项：**25 passed**；含新专项及 10 个相邻 F4/material/admission/collector/sidecar 回归文件：**131 passed**（项目 `.venv`）。
- 新增脚本与专项测试 `py_compile` 通过，`git diff --check` 通过。
- 只使用合成 JSON；未读取真实 source/HDF5，未启动 solver、worker、GPU 或 queue；未写 registry、ledger、旧 evidence 或资格回执。
- Terra High/high subagent 最终只读静态审查：诊断范围内 PASS，无 P0/P1。审查指出的 P2 是本 API 无法验证调用方 external digest 的独立可信来源；代码与本报告已明确此限制，结果不得用于 admission/qualification。审查建议的冻结外部 digest 下 tracer/CDF/residence 篡改负测已补齐，coverage 绑定冻结负测已有覆盖。
- v2 尚未接入真实 HDF5 summary builder、macro sidecar preflight、33-row matrix 或 T2 collector；数值政策待科学审定，所有输出恒为 `diagnostic_only`、`qualification_claim=none`、credit `0`、`T2_macro/path=false`。
