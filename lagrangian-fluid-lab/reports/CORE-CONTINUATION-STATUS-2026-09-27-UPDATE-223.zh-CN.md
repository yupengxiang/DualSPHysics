# UPDATE-223：修正 F8 syscall ABI 静态审阅意见

日期：2026-09-27（Asia/Shanghai）

Terra High 配置（`gpt-5.6-terra`/high）的离线只读审阅对 UPDATE-222 未发现 P0/P1，指出两项 P2 和三项措辞/来源记录 P3；reviewer identity 未 attested。UPDATE-222 已按意见修订：

- 将 x32 dispatch 明确限定为 `CONFIG_X86_X32_ABI=y`；配置关闭时不声称 x32 table 会被分派。
- `nr == -1` 改为默认拒绝；raw number 本身不能证明是 tracer skip。只有可信且已验证的 tracer 协调状态才可将其作为独立控制事件处理，仍需目标 kernel conformance。
- 将 512..547 精确称为 syscall table 的号码字段值，避免误称源文件文本行号；native 表范围表述为 0..461（含 holes），移除“548+ 可用”的过度概括。
- 增补 `v6.8` annotated-tag object 与 peeled commit、raw-source 获取路径，以及 `syscalltbl.sh`/`syscallhdr.sh` 生成脚本来源哈希；明确 GitHub API 对 tag 签名的状态为 `unknown_key`，不宣称签名验证。

UPDATE-222 表内记录的 8 个 Linux v6.8 raw source SHA-256 已逐一重新下载复算，全部匹配；tag object 为 `90d1f30371ae3337beb01666b226320728d35c70`，peeled commit 为 `e8f897f4afef0031fe618a8e94127a0934896aba`。本次只更正文档并追加本记录，`git diff --check` 通过；没有运行测试或构建，因为无代码变化。

这仍只闭合源码语义澄清，不是 syscall policy 实现/审批：目标 kernel build/config、逐号 disposition/predicate、ptrace/seccomp 修改顺序、raw selector conformance、实际 workload trace、trusted supervisor 和 F8 runtime readiness 仍未完成。未运行 F8 solver/worker/GPU/queue、privileged probe 或生产数据访问；F4 canary 预检未启动，授权未消费；scope/registry/ledger/分母/资格信用不变。
