# F2 静态 full-cup H2 solver canary：科学负结果（2026-09-21）

root review 授权的唯一 H2 solver canary 已在本地 Ada GPU0 执行。DualSPHysics 正常完成 `0.600037 s`、31 个保存帧和 10,755 步；运行输出明确为 code 0。CPU/native 预检通过的 23,100 个流体粒子中，最终仍有 14 个被排除。

完整轨迹审计发现：

- 墙外粒子帧 `168`，涉及 `28` 个粒子身份；
- 保存帧 chord crossings `21`；
- 结构审计因此 `hard_integrity_pass=false`；
- 观察窗已达到，不是提前截断或缺帧造成的负结果。

coordinator 最终回执为 failed，但原因发生在科学产品写完之后：旧 `f2_static_full_cup_runtime.py` 只读取 `source_prepared_sha256`，H2 manifest 使用的是语义等价的 `source_preflight_sha256`，导致 postrun metadata rebind 的 `KeyError`。这个基础设施问题已在代码中兼容修复，并与科学硬失败分开记录；不重跑同一输入，也不把结果改记为“仅基础设施失败”。

回执在 [runtime-postrun-audit-v1.json](../campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-runtime-postrun-audit-v1.json)。该 canary 保留静态 full-cup 15 行固定分母：`executed=1, passed=0, failed=1, unattempted=14`，`qualification_claim=none`、`T1_numerical=false`、registry/ledger 无变更、matrix credit 为零。H2 支撑间距只通过了初始输入门，不能据此推进 F2 T1 资格或扩大矩阵。
