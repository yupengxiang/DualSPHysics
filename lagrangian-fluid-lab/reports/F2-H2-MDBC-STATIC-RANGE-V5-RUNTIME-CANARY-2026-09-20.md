# F2 H2 mDBC static-range v5 runtime canary

时间：2026-09-20（Asia/Shanghai）  
范围：`F2_H2_mdbc_static_range_qualification_v5`，固定矩阵第 11 行，`q=0.75`、`dp=0.0075 m`。该执行只验证一个 root-approved runtime canary，不给 T1 或矩阵分子 credit。

## 绑定和准入

- v5 CPU/native matrix：`campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/prepared-20260920-v5-all/matrix-preparation.json`，SHA-256 `d82e019cd59d26dbed6846912371062206b6e6ef4b83568537d822a9fa8f0495`。
- root review：`campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5-runtime-root-review-cell11-v2.json`，SHA-256 `e1411397f1dfe97da5feb8c5c8953ca90e09f07c90a43b0479b0e094ddf75e75`。
- runtime adapter：[f2_h2_mdbc_static_range_v5_runtime.py](../scripts/f2_h2_mdbc_static_range_v5_runtime.py)，SHA-256 `6e65078ec7756d0f485d837578dac1fd299e1ae7c0728a5f11ff4815863aa97b`。
- runtime prepared view：`runtime-cell11-v2/prepared.json`，SHA-256 `77d2314fc2fdda38874ffa6c06ae554a156c980adc1806da81bd51b6c67985c2`；job spec SHA-256 `12ad1cdfebd66117ceb76425b91da0bafe61cd87221a98bcb60cfdecc800a524`。

适配器把 v5 CPU schema 转成新的 `core.cfd.v1` view，重新绑定 anchor 的 solver、decoder、mDBC 参数和所有输入哈希。root review 只授权一个 cell 的 solver/GPU/queue canary；ledger、registry、材料侧车、模型训练均明确禁止。

## 实际执行

队列 job `f2-h2-v5-cell11-runtime-smoke-002` 在 Ada GPU 3 上执行并成功完成。attempt 为：

`campaigns/core-v1/runtime/attempts/f2-h2-v5-cell11-runtime-smoke-002/20260920T201716-e0f23af4ff1c`

- solver wall：`33.1678 s`，solver 本身 `21.7256 s`；GPU process reservation `0.00980549 h`，峰值显存 `566 MiB`，峰值进程 RSS `394.8 MiB`。
- native 转换得到 31 帧、56898 个流体粒子，终止时间 `0.6000085214 s`，达到固定 `0.60 s` 窗口。
- hard integrity 通过：结构扫描通过，有限值通过，粒子身份完整，质量变化最大相对值 `0`，壁面 endpoint violation `0`，保存帧 chord crossing `0`。
- 初始和终止 native 质量均为 `24.003844372637104 kg`；使用 native `rho*dp^3`，没有质量重标定。
- 静止保持 canary 的事件窗记为 `not_assessed`；这不被解释成通过，也不替代空间、时间推进和 cadence 的完整资格矩阵。

机器证据为 [runtime-canary-evidence-cell11-v1.json](../campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/runtime-canary-evidence-cell11-v1.json)，SHA-256 `28bb42c91cc00c293a0be7d17570cf39c6e080e66c37f86447fe5a8cbe792735`。trajectory SHA-256 `8f144684e3214b8291fecc4fa77cf0f270b4062689872ffdedfd9f26dbad4c59`，audit SHA-256 `045ab5ce6ec266f9c5becf561e2448711b7cad3a00021ba668c46cf921214b18`，队列 execution receipt 的 attempt-level SHA-256 `4ff2147091ac542129910b7c97ffdd3989546f7a763eb3db3fd74203ce813d33`。

## 科学结论和边界

这是一个完整、可读取的正 runtime/hard-integrity canary，但仍是 `qualification_claim=none`、`qualified=false`、`T1_numerical=false`，矩阵 credit 为 `0`。没有扩大 15 行分母，没有写入 registry 或 ledger，也没有提交材料或训练作业。后续若继续该 scope，必须逐行执行固定 15-cell 资格研究，并保留所有失败；不能由本次单点成功推断 F2 T1 或 Core 完成。

验证：runtime adapter 与 evidence 合同测试 **5 passed**；连同既有 v5 CPU-preparation 测试，定向集合 **9 passed**。
