# 本次独立审阅：证据、边界与重要更正

审阅基线：`f104e5409cec2c8dd4043f93ffc4f6c7cda96646`。

## 读取与执行范围

云端通过GitHub连接器核对了远端ref、L1R交接、Q1结果清单、Q2清单/报告/XML、实际finite_wall_audit.py以及Q2生成脚本；并读取前次上传的L1-R任务书核对依赖范围。没有访问本地原始BI4/HDF5，没有复跑CFD、GenCase、295项回归或训练，没有改动GitHub。

本包`source_expression_results.json`为当前底壁逻辑的源表达式合成计算，非完整仓库函数执行。容器直接获取原文件字节的网络请求失败，未冒称完成源文件字节哈希验证。`probe_finite_wall.py --lab ...`可在本地对真实模块重复只读检查，并记录实际源文件摘要。

## F1：Q1尚不是物理正控验收

`campaigns/l1-resume/L1R-REVIEW-HANDOFF.md`明确称官方结果只验证执行路径。601帧原始输出、GenCase零法向检查和solver完成，不等于外部水位、压力或材料路径通过。应直接消费现有原始资产，完成几何正确的转换和观测检查，不重新求解。

## F2：Q2应称为“官方mDBC边界配置派生”，不是完整官方数值recipe

来源文件：
- `campaigns/l1-resume/q1/Q1-OFFICIAL-RESULTS.json`：官方CaseDamBreak3D源摘要；
- `campaigns/l1-resume/cases/q2-mdbc-bridge/L1R_Q2_MDBC_BRIDGE_h11_fine_dp0p01_cfl005_t0p6/..._Def.xml`；
- `scripts/l1r_q2_mdbc_bridge.py`：prepare仍显式设StepAlgorithm=1，继承本地源其余常数。

| 设置 | Q1清单中的官方源 | Q2源XML |
|---|---:|---:|
| StepAlgorithm | 2 | 1 |
| Visco | 0.01 | 0.08 |
| DensityDT | 3 | 2 |
| Boundary / SlipMode / NoPenetration | 2 / 1 / 0 | 2 / 1 / 0 |

这不证明哪一项导致底壁异常，亦不否定保持旧数值策略、只改变边界实现这一研究本身的价值。它限制的是“完整官方配方已经被验证失败”的结论。后续整体候选是系统级替代配方，不是假单因素实验；若需因果归因，再做有限桥接。

## F3：跨容差带漏检

实际`finite_wall_audit.py::_segment_face_hits`同时要求：本段终点已经超过容差带，并且名义平面交点位于本段内。两者会让慢速/多帧跨墙漏检。

以底面z=0、tol=0.0051 m、固定x=0.6,y=0.2为例：
- 保存z=[0.002,-0.006]：检出一次；
- 同一直线增加一个保存点z=[0.002,-0.002,-0.006]：两个相邻区间均未检出；
- 但两组终点都超过容差带，且都跨过同一个名义平面。

因此Q2的“有endpoint异常但无swept事件”并不构成无真实穿越的证据。也不能仅凭这个合成反例断言所有Q2异常都是这条bug造成。修复应分开：几何跨平面locator、容差越限episode、实体内状态；保留事件时间区间，不把保存弦线等同真实连续轨迹。

## F4：未声明运行域不能证明无域越界

Q2准备记录`wall_spec.runtime_domain=null`；实际`outside_runtime_domain_mask`在None时返回全false。因此0计数首先意味着此路径没有做显式域检查，而不是域越界已经独立验证。填充实际Run输出/生成执行配置中的求解域并核实语义；不以GenCase点包络冒充运行域。不抹去已确认的原生零排除记录。

## F5：Q2是明显不同的短时失败，不是此前82.9%损失的重演

Q2已知0–0.60001 s、60060个流体节点、质量保留1；最大瞬时底壁越界质量0.03200000152 kg/60.06000285 kg≈0.05328%。这不是累计越界质量，也没有给出最大穿透深度和最终停留时长。旧W2-A时域1.5 s，不能将两个最终状态当作同时间窗严格改善比。Q2不能放行，但值得基于现有数据定位，而不是重开全套边界扫描。

## 参考方法依据

English et al., “Modified dynamic boundary conditions (mDBC) for general-purpose SPH…”, Computational Particle Mechanics，DOI 10.1007/s40571-021-00403-3，2021在线发表/2022卷期。方法区分实际界面、边界粒子、ghost及足够的边界核支持；参数组合和物理面需实际检查。此文不能替代本项目对特定案例的验证。云端使用HTML全文核对概念，未分析PDF。

## 计划范围

前次`PLAN_ZH.md`第5–10节已包含官方物理验证、合规完整配方、有限修复与F3后备。Q0/Q1/Q2的阶段性结束不等于原L1-R全部合法路径耗尽。后续继续以原所有者采纳与累计预算为边界，不因“剩余额度大”而无目标耗尽。
