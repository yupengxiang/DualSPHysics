# UPDATE-209：F8 终态证据合同迭代与 F4 supportcap 合成筛查

时间：2026-09-26（Asia/Shanghai）

## F8 R008 terminal-completion evidence

V3 经 Terra High 配置的只读 reviewer 审查为 REVISE，reviewer 未 attestate 模型身份。关键缺口为：正时长/至少一步/主循环末次 SaveData 证明、自动加载 DsphConfig.xml、child 退出至重开哈希期间输出树可变竞态、trust bootstrap、argv 实际解析重演和 locale 运行时观测。新增 additive v4 合同，固定正时长和主循环保存要求、runtime_config 输入/缺失证明、外部 genesis/registry/time-attestation、no-follow 输入追踪、输出封存、运行时 locale 和按 BI4 header byteorder 解码。

V4 独立复审仍为 REVISE（reviewer 未 attestate 模型身份）：P1 trust registry 若把自身纳入七个 dependency pins 会形成 self-hash 循环；P1 output seal 和 exit-to-hash watcher 缺少可机验 wire fields/固定协议；P2 locale observations/monitor 没有完整事件 schema；P2 BI4 只写了 header 要点，未把完整 writer/decoder item-array grammar 与 producer byteorder profile 外部 pin。源码审查确认正时长末次保存和 DsphConfig 自动加载的处理方向与 v5.4 相符。

新增 [contract v5](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V5-2026-09-26.zh-CN.md) 作为 additive proposal：registry payload hash 改由外部 genesis anchor 固定，registry 内只含六个非自引用依赖；输出封存限定 Linux private tmpfs/mount namespace、cgroup 全回收及递归只读 mount_setattr，并定义 seal/watch 字段；locale probe/wrapper 增 exact schemas；BI4 profile 绑定 filecode、SI64、closed item/array schemas、decoder/writer closures 和 producing host byteorder。v5 当前等待独立只读复审，合同及所需 trust/supervisor/monitor/parser 工件均未实现或可用。

整个 F8 工作仅为源码与文本审查/合同撰写；未读生产 bundle/HDF5/PART/BI4，未运行 GenCase/native decoder/solver/worker/GPU/queue，未改 gate/scope/registry/ledger/分母。R008 仍 readiness=false、T1_numerical=false、credit=0。

## F4 supportcap 新候选 synthetic-only 筛查

新增 proposal-only v5 blend：在原 F4 v3 Shepard 与 v4 local-affine 预测之间按两者预测分歧缩放修正；不改 k=32 support、可见性、权重、固定 gate 或 denominator，不接 production tracer。

同一 held-out analytic-array 集共 5,632 查询（两个字段各 2,816），三算法 truth RMSE 如下，单位 m/s：

| 字段 | v3 Shepard | v4 affine | v5 blend | v5 相对 v3 |
|---|---:|---:|---:|---:|
| quintic shear | 0.0009615160 | 0.0004657555 | 0.0004431404 | −53.93% |
| gaussian interface | 0.0028313025 | 0.0082449261 | 0.0048028608 | +69.64% |

固定 gate 决策三者一致，5,632/5,632 pass；v5 最大 truth error 为 0.0185694 m/s，低于既有 0.0469814 m/s 数值，但不能以此抵销界面场退化。另两项未登记、仅用于设计筛查的解析计算均未形成候选：以 support 内 leave-one-out 预测方差作 blend weight，shear/interface RMSE 为 0.000460971/0.008040848 m/s；10 项基底（常数、线性、平方、交叉项）的局部二次最小二乘产生严重外推，RMSE 为 0.227652656/0.435053930 m/s，最大绝对向量误差为 1.591779/2.085154 m/s。二者均不改变 support gate，也没有资格意义。

v5 专项测试 **4 passed**，项目 .venv 下运行；校准回执绑定候选/脚本 SHA-256，记录 NumPy 2.2.6、SciPy 1.15.3。因为候选在界面场仍较 v3 差约 69.64%，v5 不提升为可预检候选，本轮不消费获准的一次 F4 CPU/native preflight；不启动 native/tracer/solver/worker/GPU/queue，不读 HDF5，不写 registry/ledger/T2，credit=0。

这不关闭 F4 的 T1 缺口，也不改变旧 v4 preflight 的 deferred/one-shot 状态。后续若继续 F4，应寻找对非线性界面有独立可靠性依据的预测器，并先在同一固定 synthetic matrix 上证明不过度牺牲任一场，再考虑已授权范围内的一次预检。
