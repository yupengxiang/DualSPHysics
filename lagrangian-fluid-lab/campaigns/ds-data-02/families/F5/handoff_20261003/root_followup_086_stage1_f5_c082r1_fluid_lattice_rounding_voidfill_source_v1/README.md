# F5 fresh086：Root256 后的 fluid-only 格点/文本诊断与唯一 void-fill 备选

这是 fresh085 之后的 F5 隔离 source-only 包。Root256 已实际完成只读 CSV 诊断，但它保留
Root246 的整体 QA 失败；fresh086 不修改 Root256 或 fresh085 的任何字节。Root256 的全行
元数据显示 194427 行、UID 唯一连续、fluid 31658，x 轴 raw residual 最大约
`1.0e-5` cells、float32 cast 最大约 `1.1444e-5` cells，最大 float32 ULP
`4.7684e-7 m`。这些是全行指标，不能代替 per-fluid 诊断。

`workers/diagnose_r1_fluid_lattice_text_rounding.py` 仍保持 disabled。Root 启用后才读取
Root246 已注册的官方 CSV，并且只绑定 Root 提供的 opaque SHA
`a1165d9d1d6645f22774eb57c6be0a236b1fbba90f46577cc2ab3fa51d2abfb8`。它逐个 fluid Type3
粒子报告：

* Decimal source-grid residual 与解析后的 binary64 residual；
* float32 是否能精确表示解析值、float32 ULP、到 CSV 文本值的误差；
* 按 CSV 文本最后一位小数给出的 round-to-nearest half-place bound，并列出逐轴最坏样例；
* clip-only 40695/40740 两种 tie cohort 的缺口、x/y/z 分布、native fixed/moving 占用；
* fluid source-lattice key 到 fixed、moving 及其并集的接触距离 envelope，以及 Type0/Mk50
  六个 x 段的中心 profile 支持表。

Native fixed/moving 占用和 lattice-key 距离只用于区分“预期 clip cohort 中的 key 被 native
粒子占据”与“key 为空”的观测；worker 不填补空 key、不移动坐标、不把 clip cohort 当成
producer fluid count，也不把该诊断变成 containment 或动力学通过。

fresh086 只准备一个有官方语法依据的 prospective GenCase 表示候选：把旧的
`drawbox`/`boxfill=solid` 流体命令替换为官方 `fillbox`/`modefill=void`，保持闭合解析床、
层方向、tank、sidewalls、piston、clipplane、DP、流体 point/size、motion、3D、16 s 和
0.02 s 全部不变。候选 seed `(1.01,0,0.03)` 位于原 fluid window 内。它的 genuine
GenCase request 使用 actual-count-from-producer、`expected_fluid=null`，仍完全 disabled；
没有成功或 40710/31658 计数预言。

source plan hash 与 canonical physical hash 分开：候选 Definition SHA 为
`c523936bc9640f211494b22a63c7ac82c9cf8dde06973c4c37b93a078392e39b`，canonical owner
仍为 `280c865dae624ad8ee2c16ef1f3ca9ff72c4fd27b13846a192bfe620993faeaa`。fresh085 的
source-draw-order-analysis 当前 SHA 是
`d1726c08a9085b4bd84f62664a38ed98eedfd02063e56700a74a061e2019fbec`；fresh086 request
显式绑定这个当前值，不复用 fresh085 中的 stale hash。

Initial QA、Mk50 coverage、short native solver、typed/XMF、bed audit、full16 和 full801
全部 disabled。候选必须先取得新的 genuine GenCase receipt、实际 native initial QA 与完整
Mk50 footprint 证据，随后仍需短事件动态和 Root visual review。
