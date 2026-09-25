# UPDATE-175：F4R 细档角粒子诊断与完整事件窗静态核算

时间：2026-09-26（Asia/Shanghai）

## 本次推进

针对 PLAN 的 F4R 旧矩阵，完成两个 `dp=0.006 m` 背景的有界只读复核。它与当前 F4 tall-wall/supportcap 候选不是同一 scope。本次没有重跑旧 solver，也没有触碰 supportcap 的一次性 canary 预检授权。

审计器先在同一个 held file descriptor 上完整校验 SHA-256，再由 h5py 打开同一 FD；只读取全粒子 ID 轴和四个冻结 ID 的 `time/position/velocity/valid` 轨迹切片及初始 `Mk`。两源文件摘要与既有矩阵/forensics 一致：

| 背景 | HDF5 SHA-256 | 帧数 | 末帧时间 |
|---|---|---:|---:|
| center | `02e65782880f341bb95adad8269813c2fe8ae470af1eab3e697af2af7bd2eebd` | 31 | 0.600021 s |
| offset | `d3eb6c634fdc239d7a38464a06a9fb927b237f921087a3c8434444f97113a448` | 31 | 0.600028 s |

两个背景中相同的四个池源 ID（67069、68341、292573、293845）在 t=0 的粒子中心相对连续池箱 x 边界偏出约 `0.002 m = dp/3`，但仍在物理水槽内。该结果证明粒子中心与连续几何边界存在差异，不足以识别 GenCase 的格点/box-fill 规则或证明它导致了后续穿墙。

每个背景的四条选中保存轨迹均在帧 8→9 的有限左/右壁面弦线上出现向外穿越：center 保存区间为 `[0.160007, 0.180022] s`，offset 为 `[0.160043, 0.180035] s`；线性弦线估计约为 center `[0.162052, 0.162164] s`、offset `[0.162311, 0.162406] s`。这是保存帧间的线段诊断，不是 solver 子步路径或精确首次穿墙时间。有限壁面端点计数与水槽 AABB 外点计数分别保留，未合并成 gate。

原始六例质量分母未变，未缩放粒子质量。连续总质量为 52.416 kg；center 三档离散总质量 spread 为最大值的 4.441%，offset 为 4.994%，六例合并 min–max span 为 4.994%。细档中心/偏置总质量分别为 55.520640 kg / 55.375488 kg。

## F4 完整事件窗公式

按 PLAN 公式对六个输入定义做静态核算，六份 Definition SHA 均与绑定矩阵一致；矩阵 SHA-256 为 `30dfdf2b43a69357d232c9b20e8df3836eae561f069a7e6921137b4f87c9455c`。六例共同输入为：液团最高点 `z=0.54 m`、池面 `z=0.18 m`、向下初速 `0.5 m/s`、`g=9.81 m/s²`、池深 `h_p=0.14 m`、输出间隔 `0.02 s`。以整个水槽长度 `L=1.2 m` 作为 scope-wide 水平传播距离上界（明确的保守假设），解析飞行时间 `t_b=0.22469856 s`；未取整公式值为 `4.32053604 s`，故 `T₀=4.34 s`。若后续硬完整性通过但仍被事件截断，PLAN 允许的一次延长上界为 `2T₀=8.68 s`。

这只是连续输入下的窗口设计值，不证明事件已覆盖；现有轨迹仍只到约 0.6 s。当前没有授权或启动 F4R solver 延长，因此没有新的 runtime 结论。系数 4 仍是研究设计默认值，不是事件完整性的证明。

## 代码复核与验证

新增 `scripts/f4r_corner_penetration_audit_v2.py` 与合成回归，回执及中文诊断报告写入 `campaigns/core-v1/cfd/f4r-corner-penetration-audit-v2/`。独立静态复核指出的四类问题已处理：将细节结论改为发布前断言、避免把几何不匹配归因为格点相位、输出采用临时目录加原子 no-replace 发布、增加 float32→JSON 初态比较覆盖并显式记录 `1e-7 m` 表示容差。审计产物写出后，仅对人类报告补入实际帧区间/弦线估计表；机器回执与数据未改。

相关两套 `.venv` 回归 **14 passed**，`py_compile` 与 `git diff --check` 通过。复核线程虽按 Terra High/high 配置请求，但其结果称当前 Terra High 接口不可用；因此只采纳并修复具体静态发现，不宣称 Terra High verdict 或身份 attestation。

本次校验的两个 HDF5 共 425,718,372 bytes；未运行 GenCase/native decoder/solver/worker/GPU/queue，没有 registry/ledger/qualification 写入，T1/T2 均 false、credit=0。F3 row30 与 F8 R002 未重试，F4 supportcap 新候选 canary 预检授权状态未改变。

## 尚未完成

- 未证明初始几何/离散生成与后续穿墙的因果关系，也未分离边界生成、压力与数值更新时间的责任。
- 未在完整 `T₀` 事件窗运行或判定事件完整性；`2T₀` 也只是条件式上界。
- 下一步继续只读追踪官方 GenCase 的 drawbox/粒子格点实现，形成可证伪的单参数研究设计；任何真实求解仍须遵守独立执行边界。
