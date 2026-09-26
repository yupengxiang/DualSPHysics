# 计划文献来源审计（2026-09-24）

> 本文件正文表格和后续逐轮记载保留各自审计时点的历史状态。最新机器核验状态由 2026-09-26 的 [UPDATE-198](CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-198.zh-CN.md) 与下方 RERUN14 更新覆盖。

范围：仅核查 `PLAN.md` §1.3 六项已列工作是否存在、出版信息及其与表中设计启示是否一致；没有扩展检索新文献，也没有据此判断本项目的创新性。

| 工作／主来源 | 书目核对 | 来源直接支持的启示 | 状态 |
|---|---|---|---|
| [Learning to Simulate Complex Physics with Graph Networks — PMLR](https://proceedings.mlr.press/v119/sanchez-gonzalez20a.html) | Sanchez-Gonzalez et al., ICML 2020, PMLR 119；另由 [DBLP ICML 记录](https://dblp.org/rec/conf/icml/Sanchez-Gonzalez20)交叉核对 | 粒子图与消息传递可学习物理演化；论文评估多步 rollout 和误差积累，单步误差不足以代表长期能力。 | 出版方与 DBLP 人工书目交叉核对通过；机器核验仍为 `verify_pending`（arXiv 406；Semantic Scholar 精确匹配；Crossref 标题搜索无精确命中） |
| [LagrangeBench — NeurIPS 2023 Datasets and Benchmarks](https://proceedings.neurips.cc/paper_files/paper/2023/hash/ccac3b120c7dc86d45f56830732b62be-Abstract.html) | Toshev et al., NeurIPS 2023, Datasets and Benchmarks Track；DOI `10.52202/075280-2830` | 七个 2D/3D SPH 数据集、JAX API、GNS/SEGNN 基线，以及动能 MSE、Sinkhorn 距离等指标；计划已把“统一训练接口”收紧为来源可直接支持的 API 描述。 | 人工主来源核对通过；机器核验 `verified`（Crossref + Semantic Scholar 精确匹配） |
| [Neural SPH — PMLR](https://proceedings.mlr.press/v235/toshev24a.html) | Toshev et al., ICML 2024, PMLR 235；另由 [DBLP ICML 记录](https://dblp.org/rec/conf/icml/ToshevEAB24)及 [arXiv 作者记录](https://arxiv.org/abs/2402.06275)交叉核对 | 论文指出张力不稳定引起的粒子聚团，并研究将压力、黏性、外力成分加入 GNN；这支持计划中不把仅含已知外力的残差基线称为完整 Neural SPH。 | 出版方、DBLP 与 arXiv 人工书目交叉核对通过；机器核验仍为 `verify_pending`（arXiv API 406；Semantic Scholar 精确匹配；Crossref 标题搜索无精确命中） |
| [FD-Bench — arXiv 2505.20349](https://arxiv.org/abs/2505.20349) | Wang et al.; arXiv v2 页面记录日期为 2026-05-21，并在 comments 标注 accepted by KDD 2026。此处不声称已核到独立 ACM proceedings 页面。 | 来源直接提出空间、时间、损失模块的公平对照、传统数值求解器比较及跨分辨率／初始条件／时间窗泛化；对应计划中的变量隔离设计。 | 作者 arXiv 主来源人工核对通过；机器核验 `verified`（Crossref + Semantic Scholar 精确匹配） |
| [Fueltank — AAAI proceedings](https://ojs.aaai.org/index.php/AAAI/article/view/33752) | Chen et al., *A Pioneering Neural Network Method for Efficient and Robust Fuel Sloshing Simulation in Aircraft*, AAAI 2025, 39(15), 15957–15965；DOI `10.1609/aaai.v39i15.33752`；另由 [DBLP AAAI 记录](https://dblp.org/rec/conf/aaai/ChenZWJC25)交叉核对 | AAAI 页面称其航空燃油晃荡数据覆盖四类油箱和多方向旋转工况。计划据此只指出相关工作已存在，不推导本项目 F8 的资格或优先权。 | 出版方与 DBLP 人工书目交叉核对通过；机器核验仍为 `unverified`（Crossref 精确匹配；Semantic Scholar 未找到；按工具既定规则确认目录不足两个） |
| [FluidLab — 官方项目页](https://fluidlab2023.github.io/) | Xian et al., ICLR 2023 Spotlight；作者项目页、[OpenReview 论文](https://openreview.net/pdf?id=Cp-io_BoFaE)和 [DBLP ICLR 记录](https://dblp.org/rec/conf/iclr/XianZXT0FG23)交叉核对 | 官方页描述的是多材料、可微分的流体操控仿真环境。将其与 CFD 真值数据区分，是本项目的数据来源／证据规则，而不是 FluidLab 页面直接声称的结论。 | 官方项目页、OpenReview 与 DBLP 人工书目交叉核对通过；机器核验仍为 `verify_pending`（arXiv API 406；Semantic Scholar 精确匹配；Crossref 标题搜索无精确命中） |

## 核验范围与限制

初始审计的检索源为出版方／作者官方页面：PMLR、NeurIPS proceedings、arXiv、AAAI proceedings 与 FluidLab 作者项目页。当时未发现本机 Zotero/Obsidian 连接器、本地 `papers/` 或 `literature/` PDF 库，也未发现 `verify_papers.py` 或相应 ARIS helper。故当时依 research-lit 降级规则，将每项自动状态保留为 `UNVERIFIED`；这里的人工核对不冒充 arXiv／Crossref／Semantic Scholar 三源自动校验。后续工具与回执见下文。

源页支持的是表中列明的设计动机，不证明这些文献已在同一真实 CFD 任务、材料路径或验收协议下覆盖本计划的产品目标。尤其是“FluidLab 仿真数据不能直接充当本项目 CFD 真值”属于本项目的数据谱系原则；“F8 是否能成为合格第三机制家族”则仍需独立的数值资格证据。

## 机器核验后续

为补齐 research-lit helper 缺失，新增本地入口 [`verify_papers.py`](../scripts/verify_papers.py)：只用 Python 标准库，批量查 arXiv、按 DOI／精确标题查 Crossref、再用 Semantic Scholar batch API 交叉核对；需要至少两个独立目录精确匹配规范化标题，且不得有目录间标题冲突，才标记 `verified`。网络错误只会得到 `verify_pending`，不会算通过。API 用法分别依据 [arXiv API 手册](https://info.arxiv.org/help/api/user-manual.html)、[Crossref REST API](https://api.crossref.org/swagger-docs) 和 [Semantic Scholar Academic Graph API](https://api.semanticscholar.org/api-docs/)。

首次在线记录见[机器核验回执](PLAN-REFERENCES-VERIFICATION-2026-09-24.json)：arXiv 请求因内容协商返回 406，Semantic Scholar batch 请求被限流（429），故六项均为 `verify_pending`。修正 Accept 头后，曾对 GNS 做只读单记录诊断并获得官方 API 标题匹配；该诊断没有改动首次回执。

第二次全量重跑见[第二份机器核验回执](PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN1.json)：2 项 `verified`（LagrangeBench、FD-Bench）、1 项 `unverified`（Fueltank 只有 Crossref 确认）、3 项 `verify_pending`（GNS、Neural SPH、FluidLab；批量 arXiv 请求仍返回 HTTP 406）。该次原始回执中三条无 DOI 文献被 Crossref 的首个模糊搜索结果记作 `mismatch`；代码复核发现这是把非精确搜索首项当作冲突造成的误报。修正后新增的回归测试通过，原始回执保持不变。

随后在新会话按技能规则重试一次，见[第三份机器核验回执](PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN2.json)：状态仍为 2 项 `verified`、1 项 `unverified`、3 项 `verify_pending`。Semantic Scholar 本次可用；三条无 DOI 记录的 Crossref 精确标题搜索均为 `not_found`，不再报冲突；arXiv 对五条有 arXiv ID 的记录仍统一返回 HTTP 406。依技能规则，这三篇保持 pending，不在本会话继续重试；自动核验尚未整体通过。

对持续 406 的本地根因排查发现，请求代码此前显式发送 `Accept: application/atom+xml`；[arXiv 官方 API 手册](https://info.arxiv.org/help/api/user-manual.html)的 Python `urllib` 示例不设置 `Accept`，并说明 API 响应固定为 Atom。已移除该显式头并添加请求头回归断言；但在线结果尚未验证这一推测。

第四次全量核验见[第四份机器核验回执](PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN3.json)：仍为 2 项 `verified`、1 项 `unverified`、3 项 `verify_pending`。移除显式 `Accept` 头后，五条 arXiv 请求仍全部返回 HTTP 406，故该改动不足以解决当前失败；Semantic Scholar 与 Crossref 的结果和第三次相同。

在新的续作会话进行的第五次重跑见[第五份机器核验回执](PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN4.json)：结果仍为 2 项 `verified`、1 项 `unverified`、3 项 `verify_pending`，五条 arXiv 请求仍返回 HTTP 406。另对原先机器状态未闭合的条目人工补做独立目录交叉核对：GNS、Neural SPH、Fueltank 和 FluidLab 的出版信息分别能在 PMLR／AAAI／ICLR 官方页面与 DBLP 记录中对应；Neural SPH 另有 arXiv 作者记录，FluidLab 另有 OpenReview 论文页。该人工补核提高了书目来源的可追溯性，但不改变 `verify_papers.py` 的三源机器 verdict，也不替代其预定 API 结果，因此上述三项 pending 和 FuelTank 的 unverified 状态保持不变。

本会话按技能要求在下一次会话重试一次，见[第六份机器核验回执](PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN5.json)：结果仍为 2 项 `verified`、1 项 `unverified`、3 项 `verify_pending`，arXiv 仍返回 HTTP 406。依 `verify_pending` 规则，本会话不再重试；需等后续会话或上游 API 状态改变后再试，不能根据人工来源核对提升机器状态。

后续续作会话再次按规则只重试一次，见[第七份机器核验回执](PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN6.json)：状态仍为 2 项 `verified`、1 项 `unverified`、3 项 `verify_pending`。五个 arXiv ID 查询继续返回 HTTP 406；FluidLab 的 Crossref 请求遇到临时 TLS EOF；FuelTank 仍只有 Crossref 精确命中。另用出版方/作者主页面只读核对了 GNS、LagrangeBench、Neural SPH、FuelTank 和 FluidLab 的相应书目信息与设计启示（详见 UPDATE-39），但没有把人工核对替代三源机器判据。本次已重试，按规则不在同一会话继续请求。

2026-09-25 上海时间的新会话再次按原三源判据重试一次，候选输入固定于[清单](PLAN-REFERENCES-CANDIDATES-2026-09-25.json)，新增[第八份机器核验回执](PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN7.json)：结果仍为 2 项 `verified`、1 项 `unverified`、3 项 `verify_pending`。五条 arXiv ID 的批量 API 请求仍返回 HTTP 406；Neural SPH 的 Crossref 请求遇到临时 TLS EOF，GNS 与 FluidLab 的 Crossref 精确标题搜索未命中；FuelTank 仍只有 Crossref 机器目录确认。离线回归 7 项通过，核验器代码未改。本会话已用完一次重试额度，不再重试或由人工网页状态升格。详见 [UPDATE-51](CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-51.zh-CN.md)。

同日稍后的 RERUN8 见[第九份机器核验回执](PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN8.json)：5 项 `verified`、1 项 `unverified`、0 项 pending。五个 arXiv 标题均成功匹配，Semantic Scholar 也匹配五篇；FuelTank 只有 Crossref 精确命中，Semantic Scholar DOI 查询未找到，因此仍为 `unverified`。附加的 Semantic Scholar title-match 请求遇 HTTP 429，DBLP 查询遇 bot challenge；这些诊断未重试，也未替代机器判据。详见 [UPDATE-62](CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-62.zh-CN.md)。

新会话按原三源工具执行一次 RERUN9，见[第十份机器核验回执](PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN9.json)：6 项全部为 `verify_pending`，没有 `verified` 或 `unverified`。五个 arXiv API 请求均返回 HTTP 406；六项 Semantic Scholar 请求均返回 HTTP 429；Crossref 仍对 LagrangeBench、FD-Bench 与 FuelTank 返回精确 DOI／标题匹配，对 GNS、Neural SPH、FluidLab 的精确标题查询未命中。由于 transient API errors 按工具语义优先产生 pending，本结果不构成负面书目结论。遵循每会话一次的规则，本会话不再重试；既有人工书目交叉核对不更改机器 verdict。详见 [UPDATE-130](CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-130.zh-CN.md)。

离线回归：`tests/test_verify_papers.py`，7 项通过，覆盖三源成功、标题冲突、临时网络失败、无 DOI 的 Crossref 精确标题查找与模糊未命中、以及 DOI-only 记录。该工具只验证书目身份，不判断论文主张、质量或本项目创新性。

## 2026-09-26 机器核验收束（RERUN14）

新增 [OpenAlex Works API](https://help.openalex.org/api/) 为第四个独立目录。其官方文档将 API 描述为 OpenAlex 全量 works 数据集的 REST 查询入口，并支持按外部 DOI 获取单条记录（[Get Singleton](https://help.openalex.org/api/get-single-entities/)）。核验器以已给 DOI 精确查询；候选没有出版 DOI 时，以其 arXiv ID 构造规范 `10.48550/arxiv.<id>` DOI 查询。只有 OpenAlex 返回记录的 DOI 与查询身份相符、规范化标题完全相等且记录含合法 OpenAlex work ID 时才记 `matched`；返回身份/标题冲突仍阻止总体验证。总门仍要求至少两个目录精确匹配，未降低标题标准或将人工页面计作机器目录。

[RERUN14](PLAN-REFERENCES-VERIFICATION-2026-09-26-RERUN14.json) 对冻结的六条候选得到 **6 verified、0 unverified、0 verify_pending**，且无目录冲突：GNS、Neural SPH、FluidLab 为 arXiv、Semantic Scholar、OpenAlex 精确匹配；LagrangeBench 与 FD-Bench 四目录均精确匹配；FuelTank 由 Crossref 与 OpenAlex 精确匹配。回执 SHA-256：`1d15f656b6299fe997315ea43d66ec5e8d15fb99b7efce04bef45fd5da259f86`。定向测试 `tests/test_verify_papers.py` **10 passed**，并通过 `py_compile` 与 `git diff --check`。这闭合六条文献的自动书目身份核验，不判断文献主张，也不改变 Core T1/T2、训练、评测或产品复现状态。
