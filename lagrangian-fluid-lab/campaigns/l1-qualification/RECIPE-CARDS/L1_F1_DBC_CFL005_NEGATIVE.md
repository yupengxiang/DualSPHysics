# Recipe card: F1 DBC / CFL 0.05（数值时间策略，非 T1 配方）

状态：`qualified_for_space` only；`T1=false`，不可直接作为训练数据或 release。<br>
适用范围：F1 plain dam-break，`t=0..1.5 s`，21 个登记时刻，DualSPHysics 5.4。

## 固定输入

- source definition：`cases/F1/F1_dam_break_plain/F1_dam_break_plain_Def.xml`
- boundary：DBC (`Boundary=1`)
- `dp=0.014 m`；`SavePosDouble=2`；`StepAlgorithm=1`；`VerletSteps=40`；`Shifting=0`
- `TimeOut=0.001 s`；gravity `z=-9.81 m/s²`
- 空间研究高度：h09=`0.414 m`、h10=`0.460 m`、h11=`0.506 m`

## 通过的内容

相对于 CFL=0.1，CFL=0.05 在 h10/h11 的 21 个登记时刻均通过时间门：

| 高度 | max TV | max COM L2 (m) | max front q90 (m) |
|---|---:|---:|---:|
| h10 | 0.0018382353 | 0.0004830945 | 0.0005003214 |
| h11 | 0.0040485830 | 0.0009089826 | 0.0015766621 |

时间门限为 (0.01, 0.012 m, 0.012 m)。因此该卡只负责锁定空间阶梯所用的 CFL，不负责证明空间收敛或物理真实性。

## 空间阶梯否决

三种高度都出现 coarse→medium 的诊断通过，但 medium→fine 的 TV 分别为 h09=`0.0556495`、h10=`0.0611363`、h11=`0.0686456`；三个 fine case 还存在闭壁越界。h11 fine 另有 352 个 native `position` 排除。故无高度成为 T1 候选，不执行 `.007 m` 补阶，也不启动 development/training。

完整机器证据：`l1-f1-qualification.json`、`audits/L1_W1_TIME_*.json`、`audits/L1_W1_SPACE_*.json`。
