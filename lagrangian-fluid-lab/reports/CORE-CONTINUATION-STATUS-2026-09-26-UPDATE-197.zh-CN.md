# UPDATE-197：arXiv 批量核验 406 诊断与修复

时间：2026-09-26（Asia/Shanghai）

## 本次推进

按原候选输入与三源判据执行 RERUN12，结果仍为 6 项 `verify_pending`：五个 arXiv ID 请求均 HTTP 406，Semantic Scholar 六项均 HTTP 429。保留不可覆盖的 [RERUN12 回执](PLAN-REFERENCES-VERIFICATION-2026-09-26-RERUN12.json)。

随后对同一 arXiv 查询做有限的 HTTP 客户端对照：官方 HTTP URL 返回 301 并指向相同 HTTPS URL；同一批五 ID 查询在 curl 默认头和 Python `urllib` 显式 `Accept: */*` 下均返回 200，而本项目原 `urllib` 批量请求未发送 `Accept` 并返回 406。单 ID 的 `urllib` 无 `Accept` 请求也曾返回 200，因此诊断结论限定为已观察到的批量请求行为，不推断为所有 arXiv 请求的普遍规则。

据此，`scripts/verify_papers.py` 仅对 arXiv API 显式添加 `Accept: */*`；Crossref 与 Semantic Scholar 仍发送 `application/json`，候选输入、标题匹配与“至少两个独立目录且无冲突”判据均未改变。专项离线测试 **7 passed**；`py_compile` 与 `git diff --check` 通过。

修复后新增不可覆盖的 [RERUN13 回执](PLAN-REFERENCES-VERIFICATION-2026-09-26-RERUN13.json)：

- **2 项 `verified`**：LagrangeBench、FD-Bench；arXiv 与 Crossref 均精确匹配。
- **0 项 `unverified`**。
- **4 项 `verify_pending`**：Semantic Scholar 六项请求均 HTTP 429；GNS、Neural SPH、FluidLab 的 Crossref 精确标题查询也未命中；FuelTank 仅有 Crossref 精确匹配。

arXiv 现对五个带 ID 的候选均精确匹配，但这不替代第二独立目录。没有将网页核对、单源命中或暂时 API 错误改写为通过/失败结论。

## 边界与后续

六篇整体机器核验仍未完成。避免在本轮继续重试 Semantic Scholar 429；后续应在合理退避后重跑，或按既有机器核验方法补入可由 Crossref 精确查询的正式 DOI/元数据，同时保持候选和判据可追溯。该修复不影响 Core T1/T2、训练、评测或异机复现状态，也不产生资格信用。
