# Core 接续状态更新 21（2026-09-24）

本更新完成一个 F3 静止无滑移墙的受约束 MLS 离线原型比较，不对历史 R003 重新积分，也不启动科学作业。

- 单平面 synthetic 试验中，零壁速 KKT 约束保留 affine 精确性；对四个 (h) 值的二次 no-slip 场均降低近壁查询误差，但加权拟合残差升高约 35–40%。故意不满足 no-slip 的常量样本被明显改写，证明该方法依赖边界物理条件而非中性钳位。详见[设计审查](F3-ROW30-NOSLIP-CONSTRAINED-MLS-DESIGN-REVIEW-2026-09-24.zh-CN.md)。
- R003 的 40 个外向墙面重建目前只提供研究动机；尚未在对应 CFD source frame 上运行该约束或做历史重积分。R003 的失败分母、row acceptance 与 T2 credit 均不变。
- 相关目标组合测试 **9 passed**；没有 worker、solver、GPU 或队列启动。该原型未更改注册后端、历史数据或 Core 账本。
