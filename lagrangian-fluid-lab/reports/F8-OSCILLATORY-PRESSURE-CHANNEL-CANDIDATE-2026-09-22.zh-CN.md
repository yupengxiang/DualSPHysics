# F8 振荡压力驱动通道候选审计（2026-09-22）

本记录只建立一个静态、可审计的第三 T1 候选，不代表 root admission、数值资格或 Core 完成。

候选为 `F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001`：完全充满的单相黏性流体，在 x/y 周期通道内由零均值时间变化的均匀加速度驱动，z 方向固定无滑移壁。预登记观察量是壁法向速度剖面的幅值与相位、中心线相位滞后、横向速度、周期平均通量、启动黏性扩散以及分辨率／时间步收敛。

本轮静态核对了官方 Poiseuille、ExternalForces、Periodicity 示例以及 AccInput／Parameters XML 规范，并绑定了附件 PLAN 的哈希。官方资料分别支持所需语义，但没有证明目标 Definition 的组合已经执行通过。

PLAN 强调 Core 的研究重点是三维自由表面流动；同时其明确 Core 家族门槛写的是至少三个真正不同机制家族，没有将自由表面单独列为绝对门槛。因此 F8 必须先取得 root 对“非自由表面机制是否属于 Core”的明确解释，随后才能决定是否制作 Definition 和申请一次受控资格 canary。

当前状态：`proposal_only_root_review_required`，资格 credit 为 0。没有写 Definition，没有运行 GenCase、CPU/GPU solver、decoder 或队列，也没有改变 registry、ledger、denominator 或 training。

Terra High 的独立 root-style review 给出 `CONDITIONAL-GO` 仅限静态 admission preparation；正式 root-admit 为 `NO-GO`。本轮已将机制语义冻结为 body-force-driven / Womersley-equivalent，明确 `accinput` 的线性加速度、体力密度和只有在连续介质等价性验证后才能使用的压力梯度解释；同时冻结 `H, nu, omega, A`、Mach／密度门、时间步、cadence、瞬态窗口和幅值／相位／通量误差门。合同位于 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json`，审查收据位于 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/root-review/terra-high-root-review-v1.json`。

机器可读收据：`campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/candidate-card-v1.json`。
