# F3 material row30 R003 no-slip 边界层／时间细化离线 sweep（2026-09-25）

## 结论

仅对既有 R003 trace 中 40 个终态 `wall_occluded` seed 的首个失败 native interval 作离线反事实诊断。时间子步从既有 4 份细化到 1/2/4/8/16 倍；单帧剩余区间的终点随细化迅速收敛，但每档仍是 16/40 seed 的 constrained weighted residual 超过冻结 F3 原门，且外向法向查询比例不变。空间边界层 sweep 中，约束拟合残差在 0.25–1.9h 各距离均持续越门；无约束 MLS 在墙脚的外推速度也明显非零。

因此当前证据不支持“时间步太粗”是首要原因；单墙 no-slip 约束在该真实局部流场上仍与部分采样数据/原 residual 门不相容，不能作为 row30 修复方案。R003 仍未接受、unknown 不变、T2 credit=0；所有阈值/分母保持不变。

## 输入、范围与可复现性

新脚本 [`f3_r003_noslip_refinement_sweep_v1.py`](../scripts/f3_r003_noslip_refinement_sweep_v1.py) 锁定并复核：

| 输入 | SHA-256 |
|---|---|
| CFD source HDF5 | `fb304e0bc8e5d7f51eaab0af0d8dba8c928b8146e0bf5776002f83012e4480c4` |
| R003 trace HDF5 | `10e5219d6821d8963a82e068135f078a696a5a111fbd79f598408508c3799366` |
| 注册 `f3_native_volume_mls.py` | `e1c5fc39e73781d386c7da2874c1749b5223c8209eaf8f25bb4453346df51ff9` |

命令：

```text
./.venv/bin/python -m scripts.f3_r003_noslip_refinement_sweep_v1
./.venv/bin/python -m pytest -q tests/test_f3_r003_noslip_refinement_sweep_v1.py
```

脚本重新定位并复现 40 个 seed 的原始 `wall_occluded` 首失效 stage；读取各自对应 native source frame，不载入或重算 8.35 s 全轨迹。时间细化只积分首失效子步起至下一个 native 输出帧的剩余短区间；`factor=1` 对齐旧 replay 的 base step，之后逐次减半，最大 16 倍。空间剖面在失败查询最近闭壁投影脚处，沿指向流体内部的法线偏置 0.25、0.5、1、1.5、1.9h；比较 unconstrained MLS 在墙脚的速度外推，以及各内点的 constrained fit、残差、支持和法向速度。

只读打开固定的 900,096,638-byte source 与 515,193,688-byte trace。未写/改 trace、source、backend 或 registry；未运行 worker、solver、GPU、queue 或新的 CFD/native 作业。新增 helper tests **2 passed**，`py_compile` 和 `git diff --check` 通过。脚本/测试 SHA-256 分别为 `1656d6df971febe8454e61d08f7d624b0a7e5281762f63f4aa335f837eb9d778` / `6d5fe612f67c390647737f1a81fbba00bf9ccbf2e89722ab356b24fbad054af4`。

## 时间细化

原 F3 residual 门为 `0.04698137929009748 m/s`。5 档全部 **40/40 completed**；下表中的 residual 超限次数随求值次数增加而放大，但失败 seed 数稳定为 16/40。外向法向查询占比约 29.3%，亦无随时间细化下降。

| 时间细化因子 | 最大接受步数 | residual 超限求值数 | 超限 seed 数 | 最大 residual (m/s) | 外向法向求值数 | 对 factor-16 终点最大差 (m) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4 | 140 | 16 | 0.224018540 | 116 | 6.8081e-11 |
| 2 | 8 | 280 | 16 | 0.224018480 | 232 | 4.1025e-12 |
| 4 | 16 | 560 | 16 | 0.224018472 | 464 | 2.5089e-13 |
| 8 | 32 | 1,120 | 16 | 0.224018472 | 928 | 1.4588e-14 |
| 16 | 64 | 2,240 | 16 | 0.224018471 | 1,856 | — |

各层级终点差只在两端均 completed 的 seed 上比较，均为 40 个 seed；factor-1 到 factor-16 RMS endpoint 差为 `1.3327e-11 m`。这说明该固定 constrained velocity field 下的短区间 RK 积分已高度收敛，但不证明速度重建质量合格，也不外推到后续 native intervals。

## 墙脚与边界层结果

40 个墙脚 unconstrained MLS 均为 candidate-reliable：预测速度大小中位数 `0.06251798 m/s`、最大 `1.11648204 m/s`；weighted residual 最大 `0.07366731 m/s`。这是离散邻域外推，不是 CFD 墙面粒子实测值；静止墙的规定速度仍为零。

| 内点距离 | 可用 constrained fit | residual 超门 seed 数 | residual 最大 (m/s) | 外向法向点数 | 速度大小中位数／最大 (m/s) |
|---:|---:|---:|---:|---:|---:|
| 0.25h | 40/40 | 16 | 0.24120123 | 7 | 0.03560557 / 0.20370348 |
| 0.5h | 40/40 | 17 | 0.25146828 | 5 | 0.06789264 / 0.36339376 |
| 1.0h | 40/40 | 20 | 0.26979690 | 5 | 0.11647918 / 0.54724109 |
| 1.5h | 40/40 | 20 | 0.25216925 | 5 | 0.16457500 / 0.57273694 |
| 1.9h | 40/40 | 20 | 0.19399031 | 4 | 0.17058797 / 0.56862925 |

“可用”只表示 constrained 拟合在数值上返回，不表示通过原 F3 residual、轨迹 unknown、CDF 或驻留门。墙脚预测、残差与内点 profile 都使用同一 source frame；它们不是独立 CFD 基准，也不能把 KKT 的墙面零速约束当作质量验证。

## 边界与后续

这仍是单个首次失败 interval 的诊断，不重新评估未知率、CDF、驻留时间或事件量，不构成修复设计通过。既有 40 个 wall failures、3 个 low-ESS failures、每来源 1% unknown 门及新 attempt 的 root-decision/资源/worker 前置要求不变。若继续，只能再做有明确独立观测量的局部 field-consistency 分析；不能靠进一步减小 dt 消除当前 residual mismatch，也不应把该 no-slip 候选用于新 attempt。
