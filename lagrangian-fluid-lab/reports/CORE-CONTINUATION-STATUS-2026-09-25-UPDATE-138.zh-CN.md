# Core 计划续推状态 UPDATE-138

## 更正 F8 R008 逐案例 verifier 与真实 worker 证据缺口的边界

只读复核发现 UPDATE-136 将两类缺口合并表述，容易让人误以为逐案例 verifier 本身不存在。仓库已有 `f8_r008_per_case_bundle_verifier_v1.py`：它对单次 B/C/D bundle 做 no-follow/tree/hash/link-count 检查，闭合 receipt/manifest 链，并从合成或调用方提供的字节重算 GenCase cohort、BI4 元数据与数组、逐帧时间和 D 解码输出。其 v2 Terra High 静态实现审查回执为 `PASS`，当前受审三份源码字节数和 SHA-256 与回执仍相符。native-fluid-table metric bundle verifier v2 与 15-case metric-matrix adapter v2 也已存在，仍是非授权诊断。

验证回归：`test_f8_r008_per_case_provenance_implementation_review_v2.py`、per-case B/C/D verifier、native-fluid-table metric bundle verifier v2、15-case metric-matrix adapter v2 合计 **82 passed**。这些只验证源码/回执绑定及临时合成输入，不读取 production bundle 或 solver frame。

因此更准确的剩余缺口是：尚无经认证的 worker/执行来源契约；调用方提供的授权、stage receipts 和运行时假设没有可信签发者、supervisor、loaded-module identity 的独立认证；也没有任何完整、来源验证的真实 15 行 solver 结果。UPDATE-137 的 attempt-evidence binder 只证明调用者提供对象之间的 bounded byte/identity/status 一致性，所有案例和 attempts 仍 unresolved、T1 false、信用为零。现有静态 verifier 的 Terra High PASS 不关闭 worker 信任或执行准入门。

本次没有改写历史 UPDATE-136、冻结 scope、审查回执或生产证据，也没有执行 GenCase/native decoder/solver/worker/GPU/queue。
