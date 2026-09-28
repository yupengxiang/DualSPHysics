# Core continuation status — UPDATE-388（2026-09-29）

## 安全复核 P1/P2/P3 修复收口

针对 UPDATE-387 的独立安全复核，三个不重叠修复已分别提交：

- residual process proof builder：`818ffc20`；
- graph_raw terminal runtime verifier：`06146527`；
- MLP diagnostic rollout launcher：`7f8c6646`。

### 修复边界

- MLP：process proof 只能从本 launcher 的真实 Popen execution capability 产生，具备一次性使用和 start/end identity；输入 interpreter、script、manifest、checkpoint 采用 stable FD/O_NOFOLLOW 与快照复核，拒绝 TOCTOU drift 和全零 nonce。
- graph_raw：正报告必须深度重验三 seed 的 training/terminal/rollout/process/evaluation/validator evidence；加入 producer、exit-attestation、command digest、artifact identity binding，固定完整 manifest/checkpoint 路径，拒绝空 evidence forged positive，并限制 JSON array 长度。
- residual：evaluate command 逐 token 固定绑定 canonical interpreter、`core_learning.py`、manifest/data-root/checkpoint/case/split/835/chunk/nonce/output/diagnostic；normalized proof 保存并重算 command digest，artifact 必须同时有 producer 与 independent-validator digest attestation。

验证结果：相关联合测试 `147 passed`，五个脚本 py_compile、git diff-check 通过。安全复核指出的三个 P1 已关闭；尚未把任何 positive diagnostic receipt 当作 formal/T1/T2 证据。所有现有 17 条 evaluator 仍由其原命令自然运行，修复过程未启动、停止、重启或读取 live artifact。

当前 Core gate 不变：formal training/T1/T2/qualification/credit 仍为 `false/0`，registry、ledger、denominator、gate、completion 未修改。

