# Core 计划续推状态 UPDATE-142

## 参考文献三源机器核验 RERUN10

在新的续推轮次中，使用冻结候选输入 `PLAN-REFERENCES-CANDIDATES-2026-09-25.json` 按原 `verify_papers.py` 判据运行一次新核验；没有改动核验器、候选字段或匹配规则，也没有覆盖任何历史回执。输入 SHA-256 为 `adde26aa69fa1fb7107dc73a7d9d3bb7aceedca2410787906e6bea4e538c835a`，脚本 SHA-256 为 `5739b48c2b85d0c12cdf6732154759bf0d5ea63fc756bf8e13940b55f85760a8`，新回执 SHA-256 为 `456bbd7fbf161ed45f09ffda869f6979448bbd34f70c7d597b96e203e0cd9715`。机器记录时间为 `2026-09-25T10:43:57.050414Z`。

结果从 RERUN9 的 `0 verified / 0 unverified / 6 verify_pending` 变为 **2 verified / 1 unverified / 3 verify_pending**：

| 文献 | 结果 | 机器来源状态 |
|---|---|---|
| GNS | `verify_pending` | arXiv HTTP 406；Crossref 未命中；Semantic Scholar 精确标题匹配 |
| LagrangeBench | `verified` | arXiv HTTP 406；Crossref 与 Semantic Scholar 精确标题匹配 |
| Neural SPH | `verify_pending` | arXiv HTTP 406；Crossref 未命中；Semantic Scholar 精确标题匹配 |
| FD-Bench | `verified` | arXiv HTTP 406；Crossref 与 Semantic Scholar 精确标题匹配 |
| FuelTank | `unverified` | Crossref 精确标题匹配；Semantic Scholar 未命中；无 arXiv ID |
| FluidLab | `verify_pending` | arXiv HTTP 406；Crossref 未命中；Semantic Scholar 精确标题匹配 |

因此，LagrangeBench 与 FD-Bench 已达到原定至少两个 catalog 精确匹配且无冲突的机器条件；FuelTank 仍只有一个独立目录匹配，另外三篇仍因暂时性 arXiv API 406 保持 pending。按 `research-lit` 的验证规则，pending 未被提升为 verified，人工来源核对也未替换机器状态；六项整体核验仍未完成。离线 verifier 回归 `tests/test_verify_papers.py`：**7 passed**。本次没有改动代码、外部数据、训练/CFD 资产或执行权限。

新回执：[`PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN10.json`](PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN10.json)。
