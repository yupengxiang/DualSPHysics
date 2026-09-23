# 计划文献来源审计（2026-09-24）

范围：仅核查 `PLAN.md` §1.3 六项已列工作是否存在、出版信息及其与表中设计启示是否一致；没有扩展检索新文献，也没有据此判断本项目的创新性。

| 工作／主来源 | 书目核对 | 来源直接支持的启示 | 状态 |
|---|---|---|---|
| [Learning to Simulate Complex Physics with Graph Networks — PMLR](https://proceedings.mlr.press/v119/sanchez-gonzalez20a.html) | Sanchez-Gonzalez et al., ICML 2020, PMLR 119 | 粒子图与消息传递可学习物理演化；论文评估多步 rollout 和误差积累，单步误差不足以代表长期能力。 | 人工主来源核对通过；自动三源校验 UNVERIFIED |
| [LagrangeBench — NeurIPS 2023 Datasets and Benchmarks](https://proceedings.neurips.cc/paper_files/paper/2023/hash/ccac3b120c7dc86d45f56830732b62be-Abstract.html) | Toshev et al., NeurIPS 2023, Datasets and Benchmarks Track；DOI `10.52202/075280-2830` | 七个 2D/3D SPH 数据集、JAX API、GNS/SEGNN 基线，以及动能 MSE、Sinkhorn 距离等指标；计划已把“统一训练接口”收紧为来源可直接支持的 API 描述。 | 人工主来源核对通过；自动三源校验 UNVERIFIED |
| [Neural SPH — PMLR](https://proceedings.mlr.press/v235/toshev24a.html) | Toshev et al., ICML 2024, PMLR 235 | 论文指出张力不稳定引起的粒子聚团，并研究将压力、黏性、外力成分加入 GNN；这支持计划中不把仅含已知外力的残差基线称为完整 Neural SPH。 | 人工主来源核对通过；自动三源校验 UNVERIFIED |
| [FD-Bench — arXiv 2505.20349](https://arxiv.org/abs/2505.20349) | Wang et al.; arXiv v2 页面记录日期为 2026-05-21，并在 comments 标注 accepted by KDD 2026。此处不声称已核到独立 ACM proceedings 页面。 | 来源直接提出空间、时间、损失模块的公平对照、传统数值求解器比较及跨分辨率／初始条件／时间窗泛化；对应计划中的变量隔离设计。 | 作者 arXiv 主来源人工核对通过；自动三源校验 UNVERIFIED |
| [Fueltank — AAAI proceedings](https://ojs.aaai.org/index.php/AAAI/article/view/33752) | Chen et al., *A Pioneering Neural Network Method for Efficient and Robust Fuel Sloshing Simulation in Aircraft*, AAAI 2025, 39(15), 15957–15965；DOI `10.1609/aaai.v39i15.33752` | AAAI 页面称其航空燃油晃荡数据覆盖四类油箱和多方向旋转工况。计划据此只指出相关工作已存在，不推导本项目 F8 的资格或优先权。 | 出版方主来源人工核对通过；自动三源校验 UNVERIFIED |
| [FluidLab — 官方项目页](https://fluidlab2023.github.io/) | Xian et al., ICLR 2023 Spotlight；作者项目页提供论文与项目链接。OpenReview 直链在本次访问时触发浏览器验证，未以该页面补充核验。 | 官方页描述的是多材料、可微分的流体操控仿真环境。将其与 CFD 真值数据区分，是本项目的数据来源／证据规则，而不是 FluidLab 页面直接声称的结论。 | 官方作者项目页人工核对通过；自动三源校验 UNVERIFIED |

## 核验范围与限制

初始审计的检索源为出版方／作者官方页面：PMLR、NeurIPS proceedings、arXiv、AAAI proceedings 与 FluidLab 作者项目页。当时未发现本机 Zotero/Obsidian 连接器、本地 `papers/` 或 `literature/` PDF 库，也未发现 `verify_papers.py` 或相应 ARIS helper。故当时依 research-lit 降级规则，将每项自动状态保留为 `UNVERIFIED`；这里的人工核对不冒充 arXiv／Crossref／Semantic Scholar 三源自动校验。后续工具与回执见下文。

源页支持的是表中列明的设计动机，不证明这些文献已在同一真实 CFD 任务、材料路径或验收协议下覆盖本计划的产品目标。尤其是“FluidLab 仿真数据不能直接充当本项目 CFD 真值”属于本项目的数据谱系原则；“F8 是否能成为合格第三机制家族”则仍需独立的数值资格证据。

## 机器核验后续

为补齐 research-lit helper 缺失，新增本地入口 [`verify_papers.py`](../scripts/verify_papers.py)：只用 Python 标准库，批量查 arXiv、按 DOI／精确标题查 Crossref、再用 Semantic Scholar batch API 交叉核对；需要至少两个独立目录精确匹配规范化标题，且不得有目录间标题冲突，才标记 `verified`。网络错误只会得到 `verify_pending`，不会算通过。API 用法分别依据 [arXiv API 手册](https://info.arxiv.org/help/api/user-manual.html)、[Crossref REST API](https://api.crossref.org/swagger-docs) 和 [Semantic Scholar Academic Graph API](https://api.semanticscholar.org/api-docs/)。

首次在线记录见[机器核验回执](PLAN-REFERENCES-VERIFICATION-2026-09-24.json)：Crossref 对 LagrangeBench、FD-Bench、Fueltank 返回了精确标题与 DOI 匹配；arXiv 请求因通用 `Accept` 头被拒（406），Semantic Scholar batch 请求被限流（429），故六项都保持 `verify_pending`，没有将任何一项升级。修正 arXiv 内容协商后，仅对 GNS 做了一次只读单记录诊断，官方 API 返回了匹配标题；它不是全量三源核验，也没有改动回执中的状态。Semantic Scholar 的 429 按技能规则不在本会话重试，需后续会话重跑；因此计划中的自动交叉校验仍未完成。

离线回归：`tests/test_verify_papers.py`，6 项通过，覆盖三源成功、标题冲突、临时网络失败、无 DOI 的 Crossref 标题查找和 DOI-only 记录。该工具只验证书目身份，不判断论文主张、质量或本项目创新性。
