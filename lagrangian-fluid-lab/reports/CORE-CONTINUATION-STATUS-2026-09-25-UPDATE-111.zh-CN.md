# Core 计划续推状态 UPDATE-111

日期：2026-09-25（Asia/Shanghai）

## 本次推进：关闭 Git replacement 与 lazy-fetch 语义

UPDATE-110 的 follow-up 复核发现两个 Git 对象解析边界：replacement refs 默认可让同一个 commit OID 解析成不同对象；partial clone 对缺失 promisor object 可按需发起远端 fetch。Git 官方文档确认 replacement refs 默认参与对象查询，并提供 `--no-replace-objects` / `GIT_NO_REPLACE_OBJECTS` 关闭方式；Git 同样提供 `GIT_NO_LAZY_FETCH=1` 禁止 missing-object 按需 fetch。[git-replace 文档](https://git-scm.com/docs/git-replace)、[Git 全局选项与环境变量](https://git-scm.com/docs/git)

已修改 V5 source snapshot 读取器：所有 Git 命令显式带 `--no-replace-objects`，受控环境设置 `GIT_NO_REPLACE_OBJECTS=1` 和 `GIT_NO_LAZY_FETCH=1`。缺对象现在应本地失败关闭，而不是读取替代对象或触发网络取回。Git 2.34 不支持较新文档列出的 `--no-lazy-fetch` 命令行选项，因此采用兼容环境变量，不传该新选项；`GIT_NO_REPLACE_OBJECTS` 同时由 Git CLI flag 和环境变量双重固定。

新增 replacement-ref 合成负测：HEAD 固定在 commit A、建立 A→B replacement ref、让工作树内容匹配 B；检查必须按 A 原始树读取并拒绝与 B 不同的工作树 bytes。扩展受控环境测试断言 lazy fetch / replacement 禁用变量。根路径替换测试改为在 `ls-tree` 已完成后才替换 pathname，使后续 Git 与源文件读取必须继续走原 pinned directory FD，最后因路径 inode 改变而拒绝。V5 focused suite **66 passed**；`py_compile`、`git diff --check` 通过。

## 边界

没有创建 partial clone 或配置真实 promisor remote，也没有触发或测量网络请求；fetch 阻断依据是环境变量传递测试及官方 Git 语义。replacement refs 使用纯合成本地 repo 测试。所有源 slice/function-definition/AST/build/runtime 与事件来源信任缺口仍在；`gate_state="open"`、qualification credit 为零，F8 T1 未变。未读取 production bundle/HDF5/one-shot receipt，未运行 planner/tick/canary/preparation/GenCase/native/solver/worker/GPU/queue。
