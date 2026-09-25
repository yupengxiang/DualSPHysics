# Core 计划续推状态 UPDATE-110

日期：2026-09-25（Asia/Shanghai）

## 本次推进：V5 Git source snapshot 安全加固

GPT‑6 Luna Max 只读复审指出 UPDATE-109 的 Git 读取边界仍有问题：`git status` 可能调用配置的 fsmonitor hook 并刷新 index；继承的 `GIT_DIR`/`GIT_WORK_TREE` 可重定向查询；重复使用可变 `HEAD` 会混合不同 commit 的树与 blob；逐文件上限没有聚合内存上限。复审还指出 Git `cwd` 与按路径重开的 worktree root 未绑定同一目录 inode。已将接口改为 `inspect_untrusted_v5_source_callgraph_against_git_head`：

- Git 子进程删除继承的 `GIT_*` 环境变量，隔离 system/global config，禁用 fsmonitor、hooks、pager 与 optional locks；不调用 `git status`。
- 打开仓库 root directory FD 并先校验路径/inode；Git 子进程通过该 FD 对应的 `/proc/self/fd/N` cwd 执行，worktree 源路径也从同一 FD 逐级 `openat`，检查后再次确认外部 root path 仍指向同一 inode。root 目录被替换或路径改向时 fail closed。
- 开始时固定并校验 commit ID；后续 `ls-tree`、`cat-file` 仅通过该 commit 对应的 immutable blob OID 查询，并按仓库 SHA-1/SHA-256 object format 复算 Git blob OID。完成时再次检查 HEAD；检查期间 HEAD 变化则 fail closed。
- 引用的工作树源文件经 directory FD + `O_NOFOLLOW` 分块同 pinned blob 比较，不缓存第二份完整工作树文件；index 可独立变化，但源工作树 bytes 必须匹配所固定的 HEAD blob。
- 每文件最多 1 MiB、单次检查引用源文件合计最多 2 MiB；先收齐并检查所有 blob 大小，再读取任何 blob。按源文件逐个验证 slice SHA，避免累计保留整个源集。

新增/扩展合成临时 Git repo 测试覆盖：正确与错误 slice hash、工作树偏离 pinned blob、index 暂存差异但工作树匹配、`GIT_DIR`/`GIT_WORK_TREE` 劫持、配置 fsmonitor hook 不执行且不调用 status、HEAD 在检查中移动、repo root 路径替换、每文件/聚合 cap、源目录 symlink 拒绝。V5 focused suite **65 passed**；`py_compile` 与 `git diff --check` 通过。

## 安全边界与未完成项

该 helper 仅证明 caller 声明的 byte range/hash 与一个固定 Git HEAD snapshot 中对应 allowlisted blob 的 bytes 一致，且本地工作树读取的 bytes 相同。`git_head_commit_at_start_and_end_matched` 只表示两次采样 commit ID 一致，不构成并发文件系统快照、签名或信任根。helper 不证明 range 恰好覆盖函数定义、不重算 AST/call edges/宏 feature closure、不比较 source tree 与 build attestation，也不绑定已加载 binary、runtime image 或事件生产者；所有完整性/资格输出仍 false/open/zero credit，F8 T1 不变。

本轮仅运行 parser focused synthetic tests 与静态语法检查；未读 production bundle/HDF5/one-shot receipt，未运行 planner/tick/canary/preparation/GenCase/native/solver/worker/GPU/queue。PLAN Core 全部待办仍未完成；下步继续在 fail-closed 边界内推进可信 admission capability / 拒绝路径，缺少可验证信任根时不得签发正 capability 或启动任务。
