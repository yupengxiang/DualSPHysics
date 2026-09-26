# UPDATE-216：F4 v5 prospective synthetic holdout 设计与评分

时间：2026-09-26（Asia/Shanghai）

## 结果

在第一次 synthetic 评分前，按只读复核意见修正并冻结最终 v2-review1 设计。q 域为 `0.05` 与 `0.975`；脚本在生成设计时从三个历史 calibration profile、v3 candidate card、v5/v6 calibration receipts 和未评分的 heldout v1 草案读取并哈希绑定 q 来源，确认与这些 pinned records 无重叠。v1 草案中的 `.95` 因曾出现在未评分设计中而未复用。truth-error 上限明确作为本 synthetic screen 的硬通过条件，不冒充注册 gate estimator；RMSE 仍仅报告、不要求不回归。

锁定设计 SHA-256：`6ed19197f1312dd8d20ce6b9e1a7e4674a582d7293fb6e9c4f1bb3dd72aed396`。设计绑定 14 项代码及测试哈希、5 项历史 JSON 来源哈希；复算校验通过。定向测试 5 passed，`py_compile` 通过。设计与回执位于 `campaigns/core-v1/material/candidates/f4-supportcap-affine-shepard-blend-v5/synthetic-calibration-v1/`。

负载 gate 在点云构造前通过：评分开始时 1 分钟 load 为 `126.2007/128`。在 CPU analytic arrays 上用冻结的 2,816 个 query 完成一次评分（约 2.10 秒，峰值 RSS 574,452 KiB）：v3/v5 全 query truth-vector RMSE 分别为 `0.00251353` 与 `0.00115806 m/s`（v5 相对低 53.93%）；两者注册 gate decision 和 support distance 完全相同，均为 2,816/2,816 pass；两 q 的 source unknown fraction 均为 0%，v5 synthetic truth-error 条件全通过。

## 边界与下一步

这是新的解析盒域制造场 synthetic stress screen，不是外部独立验证、真实 DualSPHysics F4 流场验证或候选优越性结论；`qualification_claim=none`、credit 为 0，T1/T2 不变。回执将下一步明确为“任何获准 preflight 前需独立审查”。目前没有启动 CPU/native canary preflight，故此前授权的一次性预检仍未消费；也没有 native/tracer、solver、GPU、worker、queue、registry 或 ledger 操作。运行后一分钟 load 回升至 `135.11`，不继续发起额外负载任务。

只读审阅发生在最终 revision 之前，指出 `.95` 与旧草案重合及 truth-error 标签易误解；本轮已据此修订，但最终 revision 未再接受 Terra High 独立复审。该审阅工具没有 attestation 可证明 reviewer 身份，因此不计为 Terra High 签核或 preflight 依据。后续若需 subagent，按用户指定统一使用 Terra High。

详见：[最终设计](../campaigns/core-v1/material/candidates/f4-supportcap-affine-shepard-blend-v5/synthetic-calibration-v1/heldout-design-v2-final.json)、[评分回执](../campaigns/core-v1/material/candidates/f4-supportcap-affine-shepard-blend-v5/synthetic-calibration-v1/heldout-receipt-v2-final.json)、[评分脚本](../scripts/f4_supportcap_affine_shepard_blend_heldout_v2.py) 与 [定向测试](../tests/test_f4_supportcap_affine_shepard_blend_heldout_v2.py)。
