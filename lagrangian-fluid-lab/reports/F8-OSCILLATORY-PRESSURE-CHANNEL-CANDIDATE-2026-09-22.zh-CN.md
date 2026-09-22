# F8 振荡压力驱动通道候选审计（2026-09-22）

本记录只建立一个静态、可审计的第三 T1 候选，不代表 root admission、数值资格或 Core 完成。

候选为 `F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001`：完全充满的单相黏性流体，在 x/y 周期通道内由零均值时间变化的均匀加速度驱动，z 方向固定无滑移壁。预登记观察量是壁法向速度剖面的幅值与相位、中心线相位滞后、横向速度、周期平均通量、启动黏性扩散以及分辨率／时间步收敛。

本轮静态核对了官方 Poiseuille、ExternalForces、Periodicity 示例以及 AccInput／Parameters XML 规范，并绑定了附件 PLAN 的哈希。官方资料分别支持所需语义，但没有证明目标 Definition 的组合已经执行通过。

PLAN 强调 Core 的研究重点是三维自由表面流动；同时其明确 Core 家族门槛写的是至少三个真正不同机制家族，没有将自由表面单独列为绝对门槛。因此 F8 必须先取得 root 对“非自由表面机制是否属于 Core”的明确解释，随后才能决定是否制作 Definition 和申请一次受控资格 canary。

当前状态：`proposal_only_root_review_required`，资格 credit 为 0。没有写 Definition，没有运行 GenCase、CPU/GPU solver、decoder 或队列，也没有改变 registry、ledger、denominator 或 training。

机器可读收据：`campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/candidate-card-v1.json`。
