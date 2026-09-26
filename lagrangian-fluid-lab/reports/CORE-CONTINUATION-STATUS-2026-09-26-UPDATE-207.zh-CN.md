# UPDATE-207：F8 R008 terminal completion contract v2 复核与 v3 修订

时间：2026-09-26（Asia/Shanghai）

对 [terminal completion evidence contract v2](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V2-2026-09-26.zh-CN.md) 做独立只读复核，结论为 REVISE。review 由 Terra High 配置的 agent 执行，但未提供可独立验证的模型身份 attestation，因此不把模型身份记作已认证。

主要发现：

- **P1：** 禁止 OPT 仍不足以绑定 child 实际打开的 Definition/control/initial-state；须固定 v5.4 argv/parser/profile，并由 supervisor syscall trace 将实际输入 FD、路径和字节哈希绑定至冻结 manifest。
- **P2：** TMAX:0 是已解析但不覆盖 Definition 的值；必须按源码“只有最终值大于 0 才覆盖”的规则计算有效 TimeMax，并固定 C-locale atof 语义。
- **P2：** LC_NUMERIC=C 是 receipt 自述还不够，须绑定真实执行环境与来源闭包，防止运行时 locale 改变影响解析或 RealStr 输出。
- **P3：** source root、外部依赖、build/output inventory 与 supervisor trust registry 的精确 pin 和验证顺序需要进一步冻结。

据此新增 additive [contract v3](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V3-2026-09-26.zh-CN.md)：禁止全部 OPT，增加 input-access trace、有效 TMAX 规则、运行环境及依赖 pin、exact schema 与外部 trust-root 验证次序。v3 仍只是 proposal，相关 trust/supervisor/trace/build/output 工件及 verifier 均不存在；未修改 gate、scope、分母或权限，也未执行测试/solver。

边界：只读 v5.4 源码与合同文本；未读取生产 bundle/HDF5/frame，未运行 GenCase/native decoder/solver/worker/GPU/queue，资格信用为零。
