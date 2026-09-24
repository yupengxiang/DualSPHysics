# F8 R008 安全 BI4 scanner 静态代码审查（2026-09-24）

状态：Terra High（`gpt-5.6-terra`, high）同一审查线程最终结论 `PASS`。该结论只覆盖有界 Python scanner/materializer 的静态代码审查与合成样例；不代表历史 `bi4_dump` 来源链完成、不代表生产 BI4 已解码，也不授予 GenCase、decoder、solver、worker、GPU 或 queue 权限。

实现位于 `scripts/f8_r008_safe_bi4_decoder_v1.py`。它在同一已打开的 input FD 上先绑定 SHA-256 与 `fstat`，再按冻结的 64 MiB raw、两节点 item tree、64 arrays、每数组至多 10,752 elements、16 MiB 聚合 payload、2 MiB metadata 和 24 MiB 总输出界限流式检查 JBinaryData 结构；完整名称/计数/类型验证通过后才创建输出。数组按原始字节流式复制，XML/数组 manifest、普通文件属性、单链接约束和输出树在完成后逐项重核。使用 no-follow/exclusive dirfd 操作，不调用现有 `bi4_dump`。

R008 子集拒绝非小端/SI64、text arrays、超限/未知 type、路径不安全名称、重复兄弟名、XML 1.0 非法文本及非官方数值格式；只接受固定 writer 默认 `%.7E`/`%.15E`，并分别保留 item 与 array 的 hide 标志。输出父目录必须由调用者提供为专用一次性目录：当前用户拥有、POSIX group/world 不可写；调用者还须保证无 ACL、capability、特权挂载或其他跨 UID 写者，同 UID 并发写者视为可信。这是明确威胁模型，不是本模块对 ACL/特权状态的探测。

Terra High 首轮曾要求修订输出父目录威胁边界、可见性字段覆盖及格式保真；修订后同一 reviewer follow-up PASS。审查归档与源码/测试/官方 writer 的逐文件 SHA-256 绑定见 [`safe-bi4-decoder-review-v1/receipt.json`](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/safe-bi4-decoder-review-v1/receipt.json)。该 reviewer 没有运行测试；父代理单独验证：

- 合成 BI4 decoder suite：17 passed。样例只在 pytest 临时目录内构造，不读取生产 `.bi4`。
- R008 相关回归：128 passed，5 deselected，0 failed。排除的五项仅要求 R008 一次性运行 namespace 仍为空；该 namespace 已消费，按 fail-closed 规则保留，没有重置或重试。
- Python bytecode validation 通过；未编译或调用 native decoder、GenCase、solver、worker、GPU 或 queue。

此前用户授权的三个单次探索任务已有不可变结果，均未在本次重试：F8 R002 静态审查判定 `FAIL_static_GenCase_readiness` 且 scope closed；F3 row30 资源预检 `blocked_no_worker_authorized`；F4 supportcap R002 CPU canary 预检 `preflight_passed_runtime_not_authorized`，canary 未启动。分别见 [F8 R002 v3 review](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r002/static-design-review-v3/receipt.json)、[F3 row30 preflight v2](../campaigns/core-v1/material/evidence/f3-material-row30-resource-preflight-v2/receipt.json)、[F4 supportcap preflight R002](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/cpu-native-canary-preflight-r002-v1/preflight-receipt.json)。

剩余缺口：历史 `bi4_dump` 的 build/source lineage 仍未证；尚无 R008 solver frames、B/C/D per-case provenance verifier 或 provenance-v2 table；15-case T1 未执行/审定。当前 readiness 仍为 false，资格信用为零。本 PASS 仅允许继续静态实现和审查。
