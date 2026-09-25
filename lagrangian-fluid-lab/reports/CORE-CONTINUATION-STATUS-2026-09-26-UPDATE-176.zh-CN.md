# UPDATE-176：F4R 初始角点的 Cartesian lattice 相位核对

时间：2026-09-26（Asia/Shanghai）

## 新证据

本次只读复用 UPDATE-175 已提交的 HDF5 取证回执，没有再次打开 HDF5。对两个 `dp=0.006 m` 背景的四个冻结角点坐标除以 `dp` 并取最近整数，得到完全相同的格点索引：

| 角点 | `(kx, ky, kz)` | 连续池箱 x 边界关系 |
|---|---:|---|
| 左下 | `(13, 7, 8)` | x=`0.078 m`，低于 `0.08 m` 边界 `dp/3` |
| 左上 | `(13, 60, 8)` | x=`0.078 m`，低于 `0.08 m` 边界 `dp/3` |
| 右下 | `(187, 7, 8)` | x=`1.122 m`，高于 `1.12 m` 边界 `dp/3` |
| 右上 | `(187, 60, 8)` | x=`1.122 m`，高于 `1.12 m` 边界 `dp/3` |

最大坐标到最近 `k·dp` 节点的残差约 `2.10×10⁻⁸ m`，与既有 HDF5 float32 坐标精度一致。两份实际 F4R 定义的 SHA-256 分别为 center `1723ab90a7d19211b83f50cf7abb5149cf62ce2ea3e6709625cc1e31ef9fae71`、offset `b9d8c218a5eb4c368cd0900171e92126c23681e3dbe6ac9b67f56527ed887aba`；输入使用 `dp=0.006`、`boxfill=solid` 和 `<setdrawmode mode="full"/>`，未显式包含 `<lattice>` 或 `<pointref>`。本地官方 XML 模板注明 lattice 的 fluid 默认值为 1（模板 SHA-256 `b0c7be2eac1f2bbf9702519cc0c94aa5ca9ef3df94c5e1cda28a005d8a27a38e`）。

DualSPHysics 官方 Wiki 的 RedrawGenCase 文档说明 GenCase 用 3-D Cartesian lattice 定位粒子，粒子创建在 lattice nodes 上；RotatedBox 示例也对照了保留 lattice 节点的 box 与后续旋转后不再位于节点上的 box。[官方说明：RedrawGenCase 与 RotatedBox](https://github.com/DualSPHysics/DualSPHysics/wiki/7.-Testcases/ba7aa69f2b2d584219ffbcbc49f7adc34ce4c344)。

## 结论边界

由官方格点说明和已绑定初态坐标可确认：这八个记录角点落在坐标原点相位的 Cartesian `dp` 节点上；池体连续 x 边界恰落在 `13⅓ dp` 与 `186⅔ dp`，而输出角点在第 13/187 列节点，因此观测到的初始粒子中心偏出 `dp/3` 与全局 lattice 相位一致。这比“未知是否为 lattice”更进一步，但**尚不能确定 `boxfill=solid` 的节点纳入/边界容差实现**；本地 vendor 包没有 GenCase 生成器源码，XML 模板注释和 Wiki 都没有给出该具体算法。

这也没有建立初始角点外偏与 0.16 s 左右保存弦线穿墙之间的因果关系，更没有区分边界点生成、压力项及时间推进的责任。不可把“格点相位一致”扩大成“已证明它导致穿墙”。候选干预（例如改 lattice phase 或 box selection）尚未冻结为单一可解释参数，不能据此启动 F4 canary；用户授权的 F4 一次 CPU-native canary 仍保留，supportcap 旧 scope 和其他一次性状态不变。

本轮只读本地绑定回执、XML 与 GenCase 文档，没有运行 GenCase/native decoder/solver，也没有读取或写入新数据；T1/T2=false、credit=0。后续应先找到可核验的具体节点纳入规则，或将其明确列为待试验参数并设计不改变连续物理初态/质量的对照，再谈一次性预检。
