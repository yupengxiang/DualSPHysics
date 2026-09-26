# UPDATE-181：F4R GenCase 格点相位黑箱探针

时间：2026-09-26（Asia/Shanghai）

## 范围与执行

官方仓库 `upstream/master` 固定提交 `ef3721a861fda961f0e2f9ec4cd317b19de99086` 保留 GenCase 二进制与文档，但 `src` 中未找到普通 `drawbox/boxfill` 生成实现。官方 XML 变更记录称 `<pointref>` 可按 reference position 和 `Dp` 拟合；官方使用指南说明粒子在 3-D Cartesian mesh nodes 生成，但没有给出本案例 box 端点的精确 tie-breaking。为缩小这一边界，本轮以池体单一 `drawbox/boxfill=solid` 合成探针调用随仓库 GenCase v5.4.354.01（SHA-256 `a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226`），`-threads:1 -save:vtkfluid`；四个全新输出基名均位于 `/tmp/f4r-gencase-lattice-probe.ki06B4`。几何仅复用 F4R pool box `[0.08,1.12]×[0.04,0.36]×[0.04,0.18] m` 与 `dp=0.006 m`，不含液滴、壁面或 solver。

## 原始对照

GenCase summary 的粒子数/轴向范围与其 binary Fluid VTK 中独立解码出的点数、每轴唯一坐标数量和最小/最大值相符；每轴间距约为 `0.006 m`。

| `<pointref>` | VTK 点阵尺寸 | 总数 | X 范围 (m) | Y 范围 (m) | Z 范围 (m) | 未缩放池流体质量 (kg) |
|---|---:|---:|---:|---:|---:|---:|
| 省略（默认） | `175×54×24` | 226,800 | 0.078–1.122 | 0.042–0.360 | 0.042–0.180 | 48.988800 |
| `(0,0,0)` | `175×54×24` | 226,800 | 0.078–1.122 | 0.042–0.360 | 0.042–0.180 | 48.988800 |
| `(0.003,0.003,0.003) = 0.5 dp` | `174×55×25` | 239,250 | 0.081–1.119 | 0.039–0.363 | 0.039–0.183 | 51.678000 |
| `(0.003,0.0045,0.0045) = (0.5,0.75,0.75) dp` | `174×54×24` | 225,504 | 0.081–1.119 | 0.0405–0.3585 | 0.0405–0.1785 | 48.708864 |

每粒质量为 `ρ dp³ = 0.000216 kg`，所有质量都按真实生成粒子数直接求和，没有做 mass scaling。省略 `<pointref>` 与显式零 reference 的 Fluid VTK SHA 完全相同；相同 pool box 的 226,800 数也复现 UPDATE-177 绑定的细档池粒子数。统一半粒距相位将 X 两端移入盒内，却使 Y/Z 两端越界，并令池质量增加 `5.4894%`。对本细档几何按三个轴分别选取 reference 后，所有粒子中心位于连续池盒内，粒数/质量相对默认值下降 `0.5714%`。因此 `pointref=dp/2` 不是各向同性修复；任何相位选择都必须重算 population 和未缩放质量。

在“端点映射到最近格点”的经验模型下，对登记的三个 `dp` 做 `1e-4` 归一化相位扫描，没有找到能令任一轴在全部三个分辨率下同时内收两端的共同 phase。此为离散网格扫描结果，不是全连续区间证明；它提示满足“全部端点内收”的方案可能必须按分辨率改变相位，这会成为跨分辨率设计中的显式变量，不能伪装成固定 phase 的等价对照。

## 结论边界

当前二进制对这一组 axis-aligned `drawbox/solid` 参数的黑箱输出，强烈支持端点按 reference/Dp 格点相位作最近格点拟合：默认零相位生成的 X 端点分别比连续盒外伸约 `dp/3`，且每轴点阵与 `(175,54,24)` 一致。这补上了此前“全局格点相位支持但生成规则未核”的关键证据。然而它只覆盖一个 pool box、一个 `dp` 与两个显式 phase 对照；并非源码证明，不覆盖液滴/墙体/复杂几何，也不证明初始越界导致帧 8→9 的动态穿墙。

当前第四组 inward reference 只是可复现的细档几何探针，不冻结为 F4R 数值候选；尚须在三档分辨率和 center/offset 全矩阵中检查完整 fluid+boundary population、液滴质量、未缩放总质量与点位；动态 solver 因果和 `2T₀` 延长仍未运行。`T1/T2=false`、qualification credit=0。

回执及四个输入定义见 [机器回执与探针目录](../campaigns/core-v1/cfd/f4r-gencase-lattice-probe-v1/receipt.json)。该轮只运行了 GenCase，未读取 production HDF5、未运行 solver/worker/GPU/queue、未写 registry/ledger。

## 后续建议

下一项安全探索是冻结跨三档分辨率的 phase 选择规则并对六份完整 Definition 做 fresh-namespace GenCase-only 对照，报告每种 fluid/Mk 的粒数、质量和连续几何超界；在该表审查完成前，不选择真实 solver candidate。动态归因/事件窗延长另属 solver 运行，需要专门范围合同，不能由本次 GenCase 探针代替。

**外部依据：**[官方 v5.4 变更记录](https://github.com/DualSPHysics/DualSPHysics/blob/master/CHANGES.txt)；[官方 GenCase 使用说明](https://github.com/DualSPHysics/DualSPHysics/wiki/5.-Running-DualSPHysics)。
