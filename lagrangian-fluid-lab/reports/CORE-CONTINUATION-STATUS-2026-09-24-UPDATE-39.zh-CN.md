# Core continuation status — 2026-09-24 UPDATE-39

## Outcome

本会话按计划重新核验 §1.3 的六项参考文献。确认 `verify_papers.py` 位于 `lagrangian-fluid-lab/scripts/`；本地候选仍是原六项，没有 Zotero/Obsidian connector、local PDF library 或 `research-wiki/`。新增机器回执 [RERUN6](PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN6.json)，没有覆盖历史文件。

RERUN6 结果为 `2 verified / 1 unverified / 3 verify_pending`：LagrangeBench、FD-Bench 已由 Crossref 与 Semantic Scholar 精确匹配；FuelTank 仅 Crossref 命中、Semantic Scholar 未命中；GNS、Neural SPH、FluidLab 因 arXiv API 对五个 ID 一律返回 HTTP 406 而保持 pending，FluidLab 的 Crossref 请求另遇一次 TLS EOF。依 verifier 规则，本会话不再重复同一批 API 请求，也不依据人工来源将状态提升。

只读复核了出版方/作者来源：GNS [PMLR](https://proceedings.mlr.press/v119/sanchez-gonzalez20a.html)，LagrangeBench [NeurIPS proceedings](https://proceedings.neurips.cc/paper_files/paper/2023/hash/ccac3b120c7dc86d45f56830732b62be-Abstract.html)，Neural SPH [PMLR](https://proceedings.mlr.press/v235/toshev24a.html)，FuelTank [AAAI proceedings PDF](https://ojs.aaai.org/index.php/AAAI/article/download/33752/35907)，FluidLab [作者项目页](https://fluidlab2023.github.io/)。这些页面可核对出版信息与既有审计摘录中的设计启示；它们不替代 verifier 的双目录机器匹配，也不改变项目创新性或资格判断。

## 边界与后续

本次只读公共 bibliographic endpoints 和本地候选/回执，没有下载 PDF、访问 Zotero/Obsidian、写入 research wiki，也没有读取生产 bundle 或运行任何 CFD/native/solver/worker/GPU/queue 工作。

引用核验仍未全绿，但属于上游 arXiv/Crossref/Semantic Scholar 可用性与 FuelTank 第二目录缺失；后续会话或目录状态改变后再按既定规则尝试。F8 R008 仍是零资格信用；此前 F8 R002、F3 row30、F4 supportcap 单次任务均按其现有回执关闭，不重试。整体 Core 尚未完成。
