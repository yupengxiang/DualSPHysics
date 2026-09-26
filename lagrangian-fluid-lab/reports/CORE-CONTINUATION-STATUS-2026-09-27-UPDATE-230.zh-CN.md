# UPDATE-230：Linux v6.8 direct-close/final-fput source-path 核对

对上游 Linux v6.8 静态追踪 `fd_install`、`close(fd)`、`__fput_sync`、`__fput`、`fsnotify_close` 与 fanotify event handling，保存 tag peeled commit `e8f897f4afef0031fe618a8e94127a0934896aba` 和 7 个上游源文件 SHA-256。tag signature 未验证，且该 upstream source 不代表目标 kernel/build。

核心校正：`SYSCALL_DEFINE1(close)` 先从 fd table 移除 `file`，调用 `filp_flush`，随后同步调用 `__fput_sync(file)` 才返回用户态；`__fput_sync` 只有在 reference decrement 到零时才 inline 调用 `__fput`。如果 `FMODE_OPENED`，`__fput(file)` 调用 `fsnotify_close(file)`；同一 file 参数且 `FMODE_WRITE` 映射为 `FS_CLOSE_WRITE`。所以 pinned direct-close path 中，已观测到匹配 `__fput` 后 close syscall exit 可作其后的源码顺序上界；syscall exit 单独仍不证明 refcount 到零、`__fput` 发生或对象身份正确。close 返回错误也不保证 FD 仍留在表中，因为表项在 `filp_flush` 前已移除且后续仍执行 `__fput_sync`。通用 `fput()` 可延期到 task_work/workqueue，不能与直接 sys_close 分支混为一谈。

新发现的执行风险：FID/name fanotify event 以相同 hash/type/PID、FSID、parent/child FID、name 与 flags 为条件做 merge，并对 queued mask 执行 OR；未及时取走的 `FAN_MODIFY` 可能与之后的 `FAN_CLOSE_WRITE` 合成多 bit mask。当前 reducer v2 parser 有意拒绝合并 mask。静态建议：writer cgroup empty 后先将 name group 排至 EAGAIN 并保存独立 pre-close barrier，再执行唯一 close，之后单独记录 post-close drain；这样才有机会把历史 MODIFY 和 CLOSE_WRITE 分开。它仅是待纳入 contract 的设计建议，不是运行时保证；若 barrier 后仍有 writer event、队列 loss/merge 或 target kernel 不符，attempt 仍 incomplete。

本轮只读上游源码并通过 HTTPS 对返回字节重算 hash；没有读取/探测目标 kernel、capability 或 filesystem，没有 sudo/root、fanotify 初始化、运行时事件、production data、native build、worker/solver/GPU/queue，也未改 V17、readiness、T1、scope、registry/ledger 或资格信用。readiness/T1/execution=false、credit=0。

完整源 hash 与字段化结论见 [source audit JSON](F8-R008-FINAL-FPUT-LINUX-V6.8-SOURCE-AUDIT-V1.json)。上游路径：[close/fput syscall](https://github.com/torvalds/linux/blob/v6.8/fs/open.c)、[FD install/close](https://github.com/torvalds/linux/blob/v6.8/fs/file.c)、[fput/final cleanup](https://github.com/torvalds/linux/blob/v6.8/fs/file_table.c)、[fsnotify close mask](https://github.com/torvalds/linux/blob/v6.8/include/linux/fsnotify.h)、[fanotify mapping/merge](https://github.com/torvalds/linux/blob/v6.8/fs/notify/fanotify/fanotify.c)。
