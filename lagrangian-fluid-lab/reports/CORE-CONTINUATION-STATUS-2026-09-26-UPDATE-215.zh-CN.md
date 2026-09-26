# UPDATE-215：F4 supportcap 候选复核与 F3 v2 合成 profile 资源门

时间：2026-09-26（Asia/Shanghai）

## F4：不把 v6 带入 CPU/native canary

按 `analyze-results` 流程只读复核 v4、v5、v6 的已提交合成 analytic-array receipts，并从 v6 行级计数重算 gate 差异。RMSE 为每个 query 的三分量速度误差向量范数，再对 query 求均方根；百分比是同一 receipt 内相对 v3 的变化。候选使用的 q 域和分母不同，跨行候选之间不能视为同一独立测试集比较。

| 候选 | 每场 query 数 | Gaussian interface RMSE (相对 v3) | Quintic shear RMSE (相对 v3) | 固定 gate 结果 |
|---|---:|---:|---:|---|
| v4 local affine | 2,816 | 0.00824493 m/s（+191.21%） | 0.000465756 m/s（−51.56%） | 5,632/5,632 pass；全 query 低于固定最大误差 |
| v5 affine/Shepard blend | 2,816 | 0.00480286 m/s（+69.63%） | 0.000443140 m/s（−53.91%） | 5,632/5,632 pass |
| v6 low-regularization Shepard | 7,040 | 0.00268202 m/s（−5.27%） | 0.000953428 m/s（−0.66%） | 10,400/14,080 pass；3,680 regressions、0 recoveries |

v4/v5 使用两个 q case；v6 使用五个 q case（其中三个被明确标为补充诊断），且 v6 的正则参数是在既有 analytic corpus 检视后选出，`independent_validation=false`。尽管 v6 的总体两场 RMSE 都略低于其同域 v3，注册 gate 按候选权重重算后，有 26.14% 的全部 query 从 v3 pass 变成 v6 fail。回归在两场、五个 q case 中都呈相同区域结构：destination 50.00%、interface 16.67%、source 9.375%；没有 v3 fail/v6 pass。此区域规律表明问题不是单一 q 或单一场景，但具体 estimator 子项原因未从聚合 receipt 唯一识别，属于观察后的诊断推断。

结论：v6 维持 `not_justified`，不消费已授权的一次 F4 CPU/native canary 预检；不调门槛、不另挑参数。v4/v5 的 analytic gate pass 也不构成独立验证，且 Gaussian interface RMSE 明显退化，因此同样不足以作为新候选准入依据。若要形成下一候选，先冻结未参与参数选择的独立 analytic 验证设计和判据，再评估；在那之前不执行 canary。

## F3：默认 v2 synthetic profile 再次由 load gate 拒绝

按计划尝试 UPDATE-191 留下的默认 `512 seeds × 4096 particles × 20 intervals` synthetic-only profile。锁定环境 `.venv` 的 Python 3.10.12 以模块入口运行，脚本在创建临时 HDF5 前重新读取的一分钟 load 为 `134.278`，高于 process-visible CPU capacity `128`，返回 `deferred_resource_gate`、`profile_started=false`。因此没有生成 profile 报告、临时数据或性能数字；未读取生产输入、启动 solver/worker/GPU/queue，未写 registry/ledger。资源条件改善后再运行同一冻结默认配置，不更改规模或门控。

本次是只读 receipt 分析和被门控拒绝的 synthetic profile 尝试；没有代码改动，也未运行 pytest。F4/F3 资格、T1/T2、分母和 credit 均无变化。
