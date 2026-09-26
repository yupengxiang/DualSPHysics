# UPDATE-198：补入 OpenAlex 目录并闭合六篇文献机器核验

时间：2026-09-26（Asia/Shanghai）

## 本次推进

RERUN13 之后，针对 GNS、Neural SPH、FluidLab 的 Crossref 标题搜索扩大到 20 条返回记录，仍未发现规范化精确标题；没有把模糊近似命中记为确认。随后检查 OpenAlex 官方 API：它提供独立的 works 目录，并支持按外部 DOI 查询单条 work。现有 arXiv-only 候选可用规范 `10.48550/arxiv.<id>` DOI 精确定位。

据此，`scripts/verify_papers.py` 增加第四个机器目录 OpenAlex。规则仍为**至少两个不同目录精确匹配规范化标题，且任何目录冲突均阻止验证**；带出版 DOI 的候选按其原 DOI 查询，无出版 DOI 时使用该候选 arXiv ID 对应的 arXiv DOI。候选清单、标题规范化规则、Crossref/Semantic Scholar/arXiv 判定均未放宽。OpenAlex 记录还必须带规范 DOI 与 OpenAlex work ID；目录网络错误仍保留为 `verify_pending`，不充当通过或否定结果。

RERUN14 使用原六条候选得到 **6 项 `verified`、0 项 `unverified`、0 项 `verify_pending`**，没有标题或 DOI 冲突：

- GNS、Neural SPH、FluidLab：arXiv、Semantic Scholar、OpenAlex 均精确匹配；Crossref 无精确标题记录。
- LagrangeBench、FD-Bench：arXiv、Crossref、Semantic Scholar、OpenAlex 均精确匹配。
- FuelTank：Crossref 与 OpenAlex 精确匹配；Semantic Scholar 返回 `not_found`，无 arXiv 候选 ID。

不可覆盖回执：[RERUN14](PLAN-REFERENCES-VERIFICATION-2026-09-26-RERUN14.json)，SHA-256 `1d15f656b6299fe997315ea43d66ec5e8d15fb99b7efce04bef45fd5da259f86`。OpenAlex API 的查询语义依据其[官方 API reference](https://help.openalex.org/api/)及[单条实体／外部 DOI 查询说明](https://help.openalex.org/api/get-single-entities/)；所作结论仅是机器目录之间的书目身份匹配。

定向测试 `tests/test_verify_papers.py` **10 passed**；`py_compile` 与 `git diff --check` 通过。

## 边界

PLAN §1.3 六项文献的自动书目身份核验已完成。该结论不评估论文科学主张或本项目创新性，也不改变 Core T1/T2、训练、评测或异机产品复现门。当前 Core 全局状态仍未完成，后续继续处理其他未闭合工作包。
