# Core 接续状态 UPDATE-33：F8 R008 冻结几何／边界／法向声明审计

日期：2026-09-24

## 本轮推进

对冻结 Definition/control pack 中全部 **47** 份 Definition（15 qualification + 32 production）新增纯 XML 静态审计。审计器通过稳定的 no-follow、openat 风格有界读取，重新验证 pack receipt 与 Definition 字节哈希；逐案从 frozen scope 和各自 `dp` 重算几何声明，不调用 GenCase/native/solver。

47 案例的 `dp` 分布为 `0.006 m × 5`、`0.0075 m × 39`、`0.009 m × 3`。逐份 XML 核实并重算：流体盒 `z=±H`、`H=0.045 m`；壁面参考盒 `±(H+dp)`；四层粒子层请求偏移 `1..4 dp`；计算域 `±(H+6dp)`，相对最外层请求保留 `2dp` 裕量；四层支持厚度 `4dp ≥ 2√3 dp`。同时核对顶／底面 wall shape、`GeometryForNormals`、`setnormalinvert=true`、normal 层 `vdp=-0.5`、active normal/`hdp_Actual.vtk`、`distanceh=3`、`svshapes=true`、`Boundary=2` 和 `XYPeriodic=0`。

周期边界语义由冻结 scope 的 `periodic x/y; fixed no-slip mDBC z walls` 与被显式绑定的输入语义源共同校验；`XYPeriodic=0` 按 presence semantics 处理，不误读为关闭 x/y 周期。Terra High（`gpt-5.6-terra`, high）对最终审计器及变异测试 follow-up 为 `PASS`。不可变机器回执：[Definition geometry audit v1](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/definition-geometry-audit-v1/receipt.json)。

## 验证结果与边界

- Terra High 报告定向审查测试 **11 passed**；几何审计、pack 验证和既审 B/C/D 文件读取器组合回归 **71 passed**；审计归档测试与再次审计 **13 passed**。最终扩大到 table v2、B/C/D wrapper、provenance、safe BI4 与几何/pack 全链的联合回归为 **149 passed**；`py_compile` 和 `git diff --check` 通过。
- 结果仅证明冻结静态 XML 声明、来源/hash 绑定和公式一致性。**没有**证明生成粒子数、生成的 hdp 网格、`BoundNor` 覆盖率、法向方向或长度，也没有证明 solver 行为。历史回执中提到的 4096/6656 粒子数及 normal 门限仍是待未来原生输出验证的门禁，不是本轮验证结果。
- 未读取生产 B/C/D bundle 或 solver frames；未调用 GenCase、native decoder、solver、worker、GPU 或 queue；registry/ledger 未变。`readiness_pass=false`、`T1_numerical=false`、资格信用为 0，未授予任何运行授权。

## 下一步

补齐 v2 native-fluid-table producer 与既有 metric adapter 的版本化对接和静态回归；同时保留生成几何及 `BoundNor` 的原生输出验证为独立执行门。该静态审计不代替 15-case T1，也不改变 Core 未完成状态。
