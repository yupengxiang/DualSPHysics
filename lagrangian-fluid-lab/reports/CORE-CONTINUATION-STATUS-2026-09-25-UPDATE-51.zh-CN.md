# UPDATE-51：计划参考文献机器核验续跑

日期：2026-09-25（Asia/Shanghai）
范围：仅按原三源判据重跑 PLAN §1.3 的六条既有参考文献；不扩展候选、不下载论文、不以人工页面核对替代机器状态。

## 结果

- 新增原样输入清单 [`PLAN-REFERENCES-CANDIDATES-2026-09-25.json`](PLAN-REFERENCES-CANDIDATES-2026-09-25.json) 和不可覆盖机器回执 [`RERUN7`](PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN7.json)。回执 UTC 时间为 `2026-09-24T16:13:15Z`，对应上海时间 2026-09-25。
- 六条状态仍为 2 项 `verified`（LagrangeBench、FD-Bench）、1 项 `unverified`（Fueltank）和 3 项 `verify_pending`（GNS、Neural SPH、FluidLab）。
- 五条 arXiv ID 的 API 批量请求仍返回 HTTP 406；Neural SPH 的 Crossref 请求遇到临时 TLS EOF。GNS 与 FluidLab 的 Crossref 精确标题搜索为 `not_found`；FuelTank 的 Crossref 精确 DOI 命中而 Semantic Scholar 为 `not_found`。
- 本会话已完成对 `verify_pending` 的一次重试；遵守技能规则，本会话不再重试，也不根据出版方/作者页面人工核对升级机器 verdict。六项自动核验仍未整体通过。
- `tests/test_verify_papers.py`：7 passed。没有修改核验器代码。
- 为下一次故障定位做了只读本机检查：`HTTP(S)_PROXY`/`ALL_PROXY` 等代理变量未设置，`urllib.request.getproxies()` 为空；这不能排除网络出口侧代理/过滤，也没有再次请求任何目录 API。

## 后续

待下一会话再按原方法重试一次，或先通过独立诊断查明 arXiv HTTP 406 的响应来源；任何新方法都须保留目录身份与标题精确匹配判据，网络错误仍只能记为 pending。Fueltank 在现有三目录规则下只有一个机器目录精确确认，不可升格。
