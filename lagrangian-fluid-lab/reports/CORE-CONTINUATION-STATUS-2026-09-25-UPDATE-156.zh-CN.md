# Core 计划续推状态 UPDATE-156

## RERUN11 的 arXiv HTTP 406 定向诊断

本次只对 RERUN11 中持续出现的 arXiv HTTP 406 做有限、只读诊断；没有运行 `verify_papers.py` 全量核验，没有创建 RERUN12，没有改候选、匹配规则或任何既有回执。RERUN11 机器 verdict 继续为 **2 verified / 1 unverified / 3 verify_pending**。

### 官方接口与状态核对

- [arXiv API User's Manual](https://info.arxiv.org/help/api/user-manual.html) 说明 query 接口接受 HTTP GET/POST，`id_list` 是逗号分隔参数；正常响应为 HTTP 200 和 Atom 内容。
- [arXiv API Basics](https://info.arxiv.org/help/api/basics.html) 展示 `export.arxiv.org/api/query` 的公开调用方式。当前仓库核验器使用 HTTPS、单个 `id_list` 查询，并且对 arXiv 请求不附加显式 `Accept` header；请求形状与文档一致。
- [arXiv Operational Status](https://status.arxiv.org/) 在本次检查时将 `export.arxiv.org` 标为 Up。但没有可比较的前后状态证据证明这是一次状态转变；“当前 Up”本身也不能解释实际收到的 406。

### 一次性诊断请求

只请求公开论文 ID `2002.09405`，`max_results=1`，没有写入项目状态：

| UTC | 请求 | 结果 |
|---|---|---|
| 13:31:18 | HTTPS；核验器相同 User-Agent；无显式 `Accept` | HTTP 406，响应体为空；响应头包含 `Via: 1.1 varnish, 1.1 varnish`、`X-Cache: MISS, MISS` |
| 13:32:21 | 官方文档所示 HTTP scheme | 重定向至 HTTPS 后仍为 HTTP 406，响应体为空 |
| 13:32:44 | HTTPS；Python 标准库默认 User-Agent | HTTP 406，响应体为空 |

因此，这个样本排除了 HTTP/HTTPS scheme 差异和核验器专用 User-Agent 是显而易见的唯一原因；不能据此判断 406 由 arXiv 源站还是中间网络路径产生。官方接口文档没有说明该 406 响应，错误体为空且有 Varnish 路径头，现有观测不足以进一步归因。没有改动核验器来猜测性地伪装请求或替换数据源。

### 判定与后续

本轮官方状态页的 `Up` 没有历史对照，不能确认为 RERUN11 后发生了 API 状态变化；原请求仍返回 406，故不满足立刻全量重跑的证据条件。继续保留 RERUN11 的三源机器判据与所有 verdict，不以人工网页书目核对升格条目。后续仅在有可核验的 API 状态/接口规则变化，或新增预登记诊断规则时重新评估重试；若诊断条件仍不变，则维持 `verify_pending`。
