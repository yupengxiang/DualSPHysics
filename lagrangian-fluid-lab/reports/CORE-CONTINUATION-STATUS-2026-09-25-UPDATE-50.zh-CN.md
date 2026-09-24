# Core continuation status — 2026-09-25 UPDATE-50

## F8 R008 C 阶段控制门合同草案复核

对 C-execution contract 草案进行了一轮限定只读检查，结果为 `REVISE`。该 reviewer 明确不能提供 Terra High 身份 attestation，因此本结论只作为未认证身份的技术意见，不记录成 Terra High 审查或 PASS；Terra High 复核仍待完成。

意见提出的阻断级缺口已加到草案：receipt 自报无法证明实际 `execve` 与 B 输入文件被 solver 读取，必须先定义可信 supervisor、进程/环境/动态代码/输入 inode 绑定及 B→solver 输入的 TOCTOU 防护；控制判据应证明所有实际 control query 满足 `0 <= t_query < effective_TimeMax <= T_end`，不能拿最终帧或最终积分时刻代替；CPU `TERMINATE` 需运行期间可信写入事件/访问控制证明，事后目录清单不够。

其他需纳入合同的来源路径包括递归 `OPT` 文件、可能启用的 `DsphConfig.xml`、严格解析后的参数 allowlist、`PARTBEGIN` restart 与输出路径覆盖，以及 CPU/GPU variant 到 binary/source 的身份闭合。ordinary finish 文本和零退出码不能排除 `NSTEPS` 提前结束或 minimum-fluid stop。修订草案仍是待审设计，不是执行 schema 或授权；如可信见证无法闭合，control gate 必须保持 open。

只读能力探针确认当前主机可用 rootless `bwrap`/user+PID namespace；在临时 mount namespace 中验证了根挂载只读、单文件 bind 只读和私有 `/tmp` tmpfs 可写。探针只运行 `/usr/bin/true`/`findmnt`，没有写宿主文件，也未运行 solver。该能力可作为后续隔离设计的候选，但不证明 solver 已读取绑定输入、不能单独防止 namespace 外同 UID 写者，也不提供 `execve`/binary-source/event-monitor 见证；因此不关闭任何审查 finding。

本次未运行测试、未读 production solver bundle/frame、未运行 GenCase/native decoder/solver/worker/GPU/queue，未修改冻结范围、阈值、分母、registry 或资源账本。
