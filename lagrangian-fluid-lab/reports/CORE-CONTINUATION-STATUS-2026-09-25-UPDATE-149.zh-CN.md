# Core 计划续推状态 UPDATE-149

## 参考文献三源机器核验 RERUN11

使用未变更的候选输入 `reports/PLAN-REFERENCES-CANDIDATES-2026-09-25.json` 和 `scripts/verify_papers.py`，按原 arXiv、Crossref、Semantic Scholar 精确标题判据执行一次新核验；没有改变候选、匹配逻辑或任何历史回执。候选输入 SHA-256 为 `adde26aa69fa1fb7107dc73a7d9d3bb7aceedca2410787906e6bea4e538c835a`，核验器 SHA-256 为 `5739b48c2b85d0c12cdf6732154759bf0d5ea63fc756bf8e13940b55f85760a8`。机器时间为 `2026-09-25T11:39:17.765377+00:00`，回执 SHA-256 为 `f7b3dd8ea8c6a0873827a5753aea8ae3cc1f6a8d4b13ebf45fa02ca16c94be48`。

结果与 RERUN10 相同：**2 verified / 1 unverified / 3 verify_pending**。LagrangeBench、FD-Bench 仍由 Crossref 与 Semantic Scholar 双源精确匹配；FuelTank 仍只有 Crossref 命中。GNS、Neural SPH、FluidLab 的 arXiv 请求仍为 HTTP 406，Semantic Scholar 精确命中但不足以达到既定双源门槛。总 verdict 保持 `WARN`；未把人工网页核对提升为机器通过。离线 verifier 回归 `tests/test_verify_papers.py` 为 **7 passed**。RERUN11 是新增审计记录而非验证状态改善；在 API 状态或预登记规则变化前，不立即重放同一请求。

新回执：[`PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN11.json`](PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN11.json)。
