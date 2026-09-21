# F7 预设旋转内泵循环路线根审查材料（2026-09-22）

本文件记录官方 DualSPHysics `main/13_Pump` 的只读源绑定、隔离适配器/观测器合约和候选判断；没有生成 Definition、BI4、trajectory，没有运行 GenCase/native solver/GPU/queue，也没有修改 Core registry、ledger、matrix 或 denominator。

## 候选结论

官方 Pump 例子可提出一个物理上有区别的 F7：封闭单相流体由预设旋转内部泵体输入角动量，研究循环、回流和驻留，而不是 F1 的溃坝绕流、F2 的源到接收器转移、F3 的冲量/挡板交换、F4 的落体碰撞、F5 的活塞爬坡或 F6 的自由刚体耦合。当前结论是 **root-review-only、未准入、零 credit**。

- 官方 Definition SHA-256：`746ae80f4c21bca62a01d59ee04d0eaaf3d1af830c36dafef4b684ca8f3c9453`。
- 几何为 fixed `mk=0` + moving pump `mk=2`，fluid `mk=1`，运动对象 `ref=2`；官方轴长约 `0.200000 m`。
- 官方运动是两段旋转：前段 `2.0 s`、角加速度 `500.0 deg/s²`、初速 `90.0 deg/s`；后段角加速度为 0 并保持转速，官方示例时域 `6.0 s`。
- 新候选拟把唯一研究轴冻结为预设角加速度 `250--750 deg/s²`，15 行仍是 13 个空间格 + 2 个时间/输出对照；15/15 未物化、0 执行、0 credit。
- 两个对照已明确为真实控制变化：`internal_time` 的 CFL `0.20→0.10`（须检查实际 dt/步数分离），`native_output` 的 `TimeOut 0.02→0.01 s`（须检查实际帧数/间隔分离）。

## 隔离合约与必须保持的阻塞

1. 已实现隔离的只读 F7 geometry adapter：解析 allowlisted 官方 binary fixed / ASCII moving POLYDATA、XML mk 标签和两段旋转，并在内存中返回 Core `PrescribedGeometry`；源三角形退化项被显式计数并过滤，不能把这个清理结果当成物理证据。XML 解析器还校验 degree 单位、1→2 链和 finish 截止；Core pose/gradient velocity 仍是有误差界的采样近似，不能称为 exact runtime motion。
2. 已实现隔离的只读 F7 material observer：固定 all-initial-fluid 分母、不做 survivor renormalization、校验 body-frame/angular-control/region hash、报告 unknown exit，并把 residence 作为事件指标而非终态质量桶；显式 torque contract 仍只形成待根审查的合约，不宣称物理独立性。
3. F7 geometry 已通过只读 public Core CFD adapter 接入，但尚未接入 Definition writer 或 trajectory producer；没有与 trajectory 绑定的真实 `control/frame` 和 torque 产物，因此不能开始材料 T2。
4. root-review contract v2 已绑定 F1/F2、F5、F6 的路线关闭收据和官方 Pump 源哈希；它只增加静态完整性证据，不改变阻塞或授权。
5. 官方 CPU/GPU wrapper 含清理和求解命令，只能作为哈希绑定的参考，绝不是执行授权。
6. 对抗性 root review 必须确认“泵驱动循环”不是把普通 moving-wall 或 F6 运动换名；若不能观测扭矩输入和回流，候选应关闭。

## 状态与授权

当前 Core 仍为 `t1_families=['F3', 'F4']`、`missing_t1_case_runs=288`、`missing_material_case_runs=288`。

本包只授权后续人工/root review 讨论：不授权 Definition writer、不授权 CPU/native preflight、不授权 solver/GPU/queue，不产生 T1/T2 分母或资格变化。接口审查状态为 `blocked_after_core_adapter_before_runtime_admission`。

机器可读文件：
- `campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/candidate-card-v1.json`
- `campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/source-audit-v1.json`
- `campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/interface-review-v1.json`
- `campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/root-review-receipt-v1.json`

定向回归：`pytest -q tests/test_f7_pump_recirculation_root_review_v1.py tests/test_f7_pump_geometry_adapter_v1.py tests/test_f7_pump_transport_observer_v1.py`。
