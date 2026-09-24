# UPDATE-62：文献机器核验恢复与 F8 执行信任边界复查

日期：2026-09-25（Asia/Shanghai）

## 文献机器核验

按既定 arXiv/Crossref/Semantic Scholar 精确标题判据执行一次全量核验，新增不可覆盖回执 [RERUN8](PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN8.json)：5 项 `verified`、1 项 `unverified`、0 项 `verify_pending`。原先五条 arXiv ID 批量查询的 HTTP 406 在本次消失；核验器自己的 `_fetch_arxiv` 也成功读到五个精确标题。FuelTank 仍仅有 Crossref 命中、Semantic Scholar 返回 `not_found`；单次额外 title-match 查询受到 Semantic Scholar HTTP 429，未重试。DBLP 官方搜索 API 单次请求遇 bot challenge，未绕过或升格为机器确认。六项机器核验仍未整体 PASS，旧回执均未改写。

查询参数遵循 [arXiv API 官方手册](https://info.arxiv.org/help/api/user-manual.html)的 `id_list` 逗号分隔语义；Semantic Scholar 的 title-match 端点按其[官方 API 文档](https://api.semanticscholar.org/api-docs/snippets)尝试；DBLP API 行为参考其[官方搜索 API 文档](https://dblp.org/faq/How%2Bto%2Buse%2Bthe%2Bdblp%2Bsearch%2BAPI.html)。

## F8 trust/sandbox 主机能力

以当前普通用户（uid 1001）运行 `/usr/bin/bwrap` 0.6.1：创建 user/PID/network namespace，只读挂载系统目录、创建临时 `/tmp`，并运行 `/usr/bin/true`，成功退出 0；`unprivileged_userns_clone=1`。这是 rootless 隔离原语可用的有限证明，不证明 solver 被隔离、事件采集完整、binary 来源可信或日志由 supervisor 诚实签发。

本次只检查可见设备、PATH 工具和当前 Git 配置：未发现 TPM 设备节点、`tpm2_*`/`cosign`/`systemd-creds` 工具或仓库级 Git commit signing 配置。该结果不证明系统全局不存在外部 trust root；但当前工作区内仍未找到已配置的受信 supervisor、独立 activation key 或 builder attestation。OpenSSL/GPG 的存在仅代表可用密码学工具，不构成独立密钥托管或远程身份见证。

## F8 合同只读审查结果

按用户要求以 `gpt-5.6-terra` / `high` 配置提交两份只读审查请求，分别审阅 C execution-evidence v3 synthetic-only draft 与 non-qualifying harness v4 draft。两名 reviewer 均明确不能 attestate 实际 Terra High 身份；其结论只作为未认证技术意见记录，不算 Terra High review 或 PASS，也不解锁实现。

- C v3：`REVISE`。待修项包括每个引用字段的 stage-role 与摘要关系、process journal 后代树状态机/PID 重用和时间顺序、复杂嵌套字段 exact schema、签名/信任激活编码、mount identity、nonce/timeline 和错误优先级。
- Harness v4：`REVISE`。`gate_state="open"` 可能被通用消费者误读；调用方可自行使 synthetic token 相等；缺少跨生产资格入口的 schema/evidence-class 拒绝约束；异常/缺失返回时的调用者 fail-closed 语义未冻结；parser 严格参数及字符串全匹配未固定。

旧草案未覆盖；暂不实现 parser/verifier。R008 真实 execution gate 继续 `open`，`T1_numerical=false`、零资格信用。未运行 solver/native decoder/GenCase/worker/GPU/queue，未读取 production solver frame，未更改冻结输入。
