# UPDATE-217：F4 v5 prospective holdout 最终只读复核

时间：2026-09-26（Asia/Shanghai）

Terra High（配置：`gpt-5.6-terra`, high；agent `01a0de67-c5d8-7812-88ca-0b725927984f`）对已提交的最终设计、脚本、测试、回执和 UPDATE-216 作只读复核：未发现 P0–P2；确认 q 域审计、盒模态散度/六面零速度、truth-error 硬筛查与 RMSE 仅报告的语义、2,816 固定分母及 synthetic-only/零资格边界相互一致。reviewer 无法 attestate 模型身份，因此记录为 Terra High 配置复核，不称为身份认证签核。

审阅输出提到 18 个来源摘要；独立重算设计清单实际为 14 项代码/测试绑定加 5 项 JSON 审计来源，共 19 项，所有摘要仍与工作树一致。唯一建议为 P3：脚本中 `design_sha256` 与 `verify_design` 有相同的重复定义。当前行为相同，不影响已冻结设计/回执；为避免改动代码后使其与已评分回执绑定脱节，本轮保留原件，后续若清理须另起 revision 并重新生成绑定产物。

复核未运行测试或 workload、未重跑 holdout、未启动 preflight。CPU/native canary preflight 是否可执行仍须先确认新候选具备独立、精确绑定的 preflight 合同，且实时资源门通过；本复核不构成执行授权。
