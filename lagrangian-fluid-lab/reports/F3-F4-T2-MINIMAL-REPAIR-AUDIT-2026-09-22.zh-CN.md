# F3/F4 材料 T2 最小闭环审计（2026-09-22）

这是上一轮只读最小修复审计的版本化回执重生成。它重新绑定当前 CPU/JSON
证据 hash，但不打开 terminal H5、不启动 solver/GPU/queue，也不改变门槛、
registry、ledger 或失败分母。

机器可读回执为
[`f3-f4-t2-minimal-repair-audit-20260922.json`](../campaigns/core-v1/material/evidence/f3-f4-t2-minimal-repair-audit-20260922.json)，
SHA-256 为 `2e147623aa0ac78e03bc5f07d4857a284a084e492b670af0ddabfa4e557ccb81`。

当前结论保持 `T2_macro=false`、`T2_path=false`、`qualification_claim=none`：
F3 的 per-source unknown/CDF 门、F4 的 unknown/完整事件窗门和 33 行覆盖仍未
闭合。`registry_mutation=0`、`central_ledger_mutation=0`；该回执只修复证据
绑定，不授予科学资格。
