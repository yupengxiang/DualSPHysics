# F8 static review bundle v1（2026-09-22）

本 bundle 是 F8 振荡黏性通道候选进入下一次 root review 前的静态闭环，
不是 admission，也不是 T1 资格。它绑定当前 candidate card、parameter
contract、旧 root review、Womersley oracle contract、实现和测试；旧 root
review 不被覆盖。

已冻结：

- 13 个物理/空间资格格：`q=0, 0.5, 1` 的三档分辨率，加上 `q=0.25,
  0.75` 的生产/细档独立内点；
- 2 个控制格：收紧时间推进、原生 dense cadence 对照；
- 固定 15 行分母、无 partial credit、失败行保留；
- body-force-driven 命名，暂不接受未经 root 解释的 pressure-driven 标签；
- 时间轴、中心速度、完整壁法向剖面和截面通量的 parser contract；
- steady oracle 不覆盖启动瞬态，`H²/nu` 衰减必须由新 CFD 或独立瞬态 oracle 证明。

仍待 root 决定：非自由表面 F8 是否属于 PLAN 的 Core 第三家族。当前没有
写 Definition/control，没有 GenCase/native decode/solver/GPU/queue/registry/
ledger/training，qualification credit 为 0。
