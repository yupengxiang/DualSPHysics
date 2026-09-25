# Core 计划续推状态 UPDATE-150

## 修复 F8 R008 matrix adapter 的 source-log 无界读取与诊断包装缺口

对 15-case metric-matrix adapter 的独立审查发现 source-log 引用可指向任意绝对路径且散列读取无大小上限；旧负测也未覆盖保留 canonical schema 的额外 diagnostic 字段包装。现将矩阵消费的 timestep audit 明确版本为 `solver_timestep_audit.v2`，它和 source log 必须位于同一真实、逐级 no-follow 的目录，source log 只能以 sibling basename 引用；要求 exact receipt fields、single-link regular file、稳定 inode/hash 与精确字节绑定，并在流式散列前执行 256 MiB 上限。原 `solver_timestep_audit.v1` reader 未修改。per-case v2 输入现在要求精确 canonical 字段集，并固定 authorization、review-authenticity、runtime 字段为 caller-supplied/unverified 状态；外层、table、metric 三处 `qualification_credit` 均要求 builtin integer zero。新增负测覆盖路径逃逸、父目录 symlink、source symlink/FIFO/hardlink、超限文件、伪包装、audit schema 混用和非整数零/信任字段篡改。

仅 synthetic 验证：matrix adapter suite **44 passed**；matrix、native-fluid-table metric-bundle v2、per-case v2 三组联合回归 **77 passed**；旧 v1 metric-adapter 回归 **18 passed**；`py_compile` 与 `git diff --check` 通过。未读取 production bundle/solver log，未运行 GenCase/native decoder、solver、worker、GPU 或 queue；T1、readiness、资格 credit 仍 false/0。

历史 matrix-review-v2 收据及 readiness-audit-v5 均因实现/测试源绑定更新而保留为历史，不宣称仍是当前 PASS。GPT‑6 Luna Max 的 follow-up 独立审查已请求、尚未返回；后续需依据该审查更新版本化 review/readiness 收据。本改动不构成执行来源认证或资格判定。
