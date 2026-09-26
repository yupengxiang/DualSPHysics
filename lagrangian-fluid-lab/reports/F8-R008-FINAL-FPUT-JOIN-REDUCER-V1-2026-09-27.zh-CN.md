# F8 R008 final-fput declared-link reducer v1

**状态：**additive diagnostic-only implementation。它只检查调用方提供的字段和关联是否相互一致；不是 kernel observer、fanotify raw decoder、trusted supervisor 或最终关闭证明。运行时 readiness、F8 T1、执行权限和资格信用均不变。

## 实现范围

依据 V16 §6 与 V17 §§1、3.1、4，新增纯函数模块 `scripts/f8_r008_final_fput_join_reducer_v1.py`，输入 schema 为 `core.cfd.f8.r008_final_fput_join_input.v1`。它严格拒绝缺失/多余字段、错误 attempt/ref、FD generation/cookie/object/task 不一致、observer 事件缺失/重复/乱序、非零 loss/overflow/sequence-gap/reader-lag、错误 cgroup-empty 声明、close 返回值异常、fanotify group 序号缺口、PIDFD 生命周期不匹配，以及目标对象没有且仅有一个 `FAN_CLOSE_WRITE` 与 close-token 声明相连等情况。

关联顺序被限定为：

```text
fd_install_entry → __fput_entry → fsnotify_close → __fput_return
                                      ↘ name-group group_seq → FAN_CLOSE_WRITE → EAGAIN drain
```

observer rows 使用单一有序数组；同 hook 的 `hook_seq` 必须递增、observer 的 `monotonic_ns` 必须严格递增。fanotify 仅按各自 group 的连续 `group_seq` 处理，不用 fanotify 时间戳与 observer 或另一 queue 推断全序。PIDFD action 必须回指 raw row 的 PIDFD info index、PID 与 declared task-generation；object join 与目标 close context 的 object identity 对照。

V17 对 `loss_epoch` 只要求携带每个 producer/CPU 的 epoch identity 与可审计 counters，未定义内层机器 schema。本 reducer additive 地定义 `f8-final-fput-loss-epoch-v1`，要求 producer/CPU/epoch roster 有序唯一、四类 counters 全为零且在四条 observer rows 间稳定。cgroup-empty diagnostic wrapper 也明确固定输入字段和值；这些只是本 reducer 的输入格式，不会补写或替代 V17 历史回执。

成功结果状态为 `diagnostic_declared_links_consistent_untrusted`，并恒定输出：

- `final_close_claim=false`
- `trusted_observation=false`
- `kernel_source_pinned=false`
- `observer_runtime_authenticated=false`
- `fanotify_raw_bytes_reparsed=false`
- `cgroup_empty_reread=false`
- `close_syscall_to_fput_order_checked=false`
- `readiness_pass=false`、`T1_numerical=false`、`execution_authority=false`、`qualification_credit=0`

## 不可据此声称的内容

- reducer **不解析** `raw_record.bytes_b64` 内的 fanotify metadata/info-record bytes，也不复算 FID/DFID_NAME/PIDFD 与 declared rows 的字节对应关系；只检查 base64、长度、摘要、info type multiset 和声明字段之间的对应。专项测试特意证明：哈希/长度正确但内容并非 fanotify struct 的合成字节仍会得到字段级 diagnostic，因此该结果绝不能解释为真实事件 join。实际 raw-byte parser 必须由 pinned UAPI implementation 独立验证。
- `fdinfo_raw_bytes_b64` 未被解释为内核身份；kernel build/source/profile 字符串、observer rows、`loss_epoch`、PIDFD action、fanotify object join、close context、token refs、cgroup-empty readback 和 EAGAIN 声明均由调用者提供且不可信。
- 没有证明 `fd_install` cookie 到 `__fput`/`fsnotify_close` 的 kernel callsite/参数 ABI，也未证明 `FAN_CLOSE_WRITE` 来自同一 writable OFD；对象 generation、terminal exit、所有 final-write tokens、cgroup-empty 时序均未由独立 source 或 runtime observer 认证。close syscall 序号与 observer `monotonic_ns` 之间也没有共同可信时基，故不声称 close-exit 到 `__fput_entry` 的时序已被比较。
- 函数只接受 Python dict，不提供安全文件读取、bounded JSON parser、签名验证、hash-chain/trust root、kernel hooks、collector 或 supervisor。不可把它接入 worker、readiness、campaign admission、registry 或资格门。
- 为限制合成输入解码成本，模块拒绝超过 1,024 UTF-8 bytes 的标识字符串、64 KiB 单条 raw/info event bytes、16 KiB PIDFD fdinfo bytes、4,096 条 name-group event/loss epoch、16 MiB 单组解码 payload。它们是本地 diagnostic 的硬上限，不是经资源资格/内核队列研究冻结的 runtime profile；超限一律拒绝。

因此 readiness v8 的 `trusted_terminal_supervisor_and_final_fput_observer_missing` 仍 open；所有 v8 blockers、F8 T1=false、资格 credit=0 均不变。没有读取 production output/HDF5/PART/BI4，没有运行 GenCase/native decoder/solver/worker/GPU/queue，没有调用 sudo 或做 privileged probe。

## 验证与本机静态 profile 观察

`tests/test_f8_r008_final_fput_join_reducer_v1.py` 的 **41 项合成测试通过**，包含正向字段闭合、缺失/重复/乱序、跨 attempt/cookie/object/task/FD/PIDFD、token/ref 不匹配、group 序号缺口、重复 close-write、raw digest/info multiset 错误、loss、overflow、short read、未 drain、size cap 和结果恒不授权。另有刻意的界限测试证明：任意合成 bytes 即使不是真实 fanotify struct，只要声明的长度/hash一致，仍会通过字段级 diagnostic；输出持续标 `fanotify_raw_bytes_reparsed=false`。`py_compile` 通过。测试不使用真实 kernel/fanotify rows。

同轮只读复核本机 profile：Ubuntu 22.04.5，运行内核 `6.8.0-138-generic`，安装包 `6.8.0-138.138~22.04.1`；`/boot/config-6.8.0-138-generic` SHA-256 为 `0ffca159bcee00c87b27e093889b710fe680ccfa37149e4e1ef8d5053e1e644c`，配置含 `CONFIG_FANOTIFY=y`、`CONFIG_FANOTIFY_ACCESS_PERMISSIONS=y` 与 `CONFIG_SECCOMP_FILTER=y`。当前进程 `CapEff=0`、`CapPrm=0`。这只是当前主机的 package/config 观察，不证明正在运行的 kernel image/source provenance，也不是未来 target worker profile；无 sudo/特权探测或运行时 fanotify 初始化。

另只读检查 CPU Makefile：默认输出固定到 `bin/linux/DualSPHysics5.4CPU_linux64`，对象文件落在源码目录，并递归构建 MoorDynPlus；未运行 compiler/Make/CMake。未经隔离工作树和资源门，不应把该默认目标直接构建进共享工作区。

一次配置 Terra High 的只读子代理意见为 `REVISE`（reviewer 身份/effort 未 attested，且未运行测试）：它指出此原型不能作为 V16/V17 证据验证器；无 P0，但 raw fanotify reparse、close-token/cookie bridge、producer sequence coverage、causal journal order/object binding、PIDFD/FID/census join 仍未闭合。主代理保留这些事项为 hard-open，不声称 review PASS。后续应先单独冻结 producer/close-cookie bridge 与 bounded raw UAPI parser 合同，经独立审查后再扩展；当前 module 不得接入 worker/readiness。
