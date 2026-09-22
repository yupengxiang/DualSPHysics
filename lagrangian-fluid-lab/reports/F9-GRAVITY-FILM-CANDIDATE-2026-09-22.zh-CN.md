# F9 重力驱动自由表面薄膜候选审计（2026-09-22）

Terra High 的 frontier search 找到一个符合 PLAN 默认自由表面边界、且区别于 F1–F7 的候选：`F9_GRAVITY_FILM_NUSSELT_R001`。

F9 是固定倾斜平面上的单相牛顿薄膜：切向重力驱动黏性剪切，底面为固定无滑移 mDBC，顶部是真实自由表面零切应力；没有 inlet/outlet、泵、运动边界、障碍物、浮体、Chrono 或表面张力。它的可证伪基准是 Nusselt 速度剖面、通量、自由表面高度、法向静水压力和 `h²/nu` 启动瞬态。

本轮只核对官方 OpenChannel、mDBC Poiseuille、Periodicity 示例及参数文档，并绑定 F1/F2/F5/F6/F7 的 closure evidence。官方 OpenChannel 含 inlet/outlet，不能作为 F9 运行结果；它只提供自由表面和层流语义先例。倾斜周期自由表面与 streamwise normal-offset 的组合仍需目标-specific native 语义验证。

进一步绑定了官方 `JSph.cpp`：`XPeriodicIncZ`／`YPeriodicIncZ` 的独立参数可以设置周期偏移，而 `XYPeriodic` 分支会重置偏移量。因此 F9 的未来 Definition 必须使用独立的 X/Y 周期参数，不能声明 `XYPeriodic`，且偏移符号仍须通过目标 native preflight 验证。

当前状态：`proposal_only_root_review_required`，资格 credit 为 0。没有写 Definition，没有运行 GenCase、solver、GPU、decoder 或 queue，也没有改变 registry、ledger、denominator 或 training。

机器可读收据：`campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/candidate-card-v1.json`。

Terra High 的独立 frontier review 判定 F9 为当前最可信的自由表面第三 T1 候选，但仅给出 `CONDITIONAL-GO`（静态准备）；正式 admission 仍为 `NO-GO`。审查收据位于 `campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/root-review/terra-high-frontier-review-v1.json`。
