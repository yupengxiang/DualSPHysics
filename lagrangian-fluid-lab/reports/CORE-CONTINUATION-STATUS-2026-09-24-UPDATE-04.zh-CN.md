# Core 计划续接状态更新（2026-09-24，update 04）

本更新记录文献来源复核的纠错与当前 Core 总控状态；不改变实验资格、登记分母、资源预算或执行授权。

## 文献审计纠错

- 更正 LagrangeBench 作者名单：官方 NeurIPS 论文页、正式 PDF 与 arXiv 元数据一致，采用 Artur P. Toshev、Gianluca Galletti、Fabian Fritz、Stefan Adami、Nikolaus A. Adams。详见[更新后的来源审计](LITERATURE-SOURCE-AUDIT-2026-09-24.zh-CN.md)。
- FD-Bench 已在 KDD 官方 Papers 目录中查到 2026 Datasets & Benchmarks track 条目，DOI 为 `10.1145/3770855.3817497`；候选清单和 fallback 清单都补入该 DOI。会议目录与 arXiv v2 的十人名单一致；一位合作者个人主页出现额外作者，作为待 ACM DOI landing page 可访问后复核的 roster discrepancy 记录。
- `verify_papers.py` 规范 helper 仍不可用，因此六项的**自动**验证状态仍全部为 `UNVERIFIED`。网页/官方页面核对只记录为人工 primary-source 检查，不冒充三层机器校验。

## 总控只读状态

刚才重新运行 `core_campaign.py status`，`can_finalize=false`、`issues=[]`，但 completion gaps 仍在：

| 门 | 当前观测 |
|---|---|
| 合格 T1 家族 | 2/3（F3、F4） |
| 宏观 T2 家族 | 0/2 |
| 正式训练 | 0/9 |
| 当前已登记 T1 分母 | 0/288；当前登记缺 288 |
| Core 目标 T1 分母 | 0/432；尚有 144 个 case-run 对应未登记的第三家族 |
| 模型材料目标分母 | 0/288 |
| 完整异机产品复现 | 未通过 |

F8 R008 后验 CPU/native 预检仍是 zero-credit，不改变 T1 家族数。F4 supportcap R002 仍受 1 分钟 load 门限制；F3 row30 的一次资源/调度预检已由 v2 receipt 消耗，仍不得据此启动 worker。上述门槛不由文献审计或测试通过替代。
