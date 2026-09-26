# UPDATE-227：F8 final-fput declared-link diagnostic reducer

本轮新增 F8 R008 final-fput declared-link reducer v1 与合成测试。实现依据 V16 §6、V17 §§1/3.1/4，对四类 observer rows、FD/cookie/object/task/attempt 绑定、loss epochs、terminal-close causal refs、cgroup-empty 声明，以及 name-group 连续 `group_seq`、PIDFD action、FID object join、唯一 `FAN_CLOSE_WRITE` 与 EAGAIN drain 做 fail-closed 的字段/声明一致性检查。输出状态仅为 `diagnostic_declared_links_consistent_untrusted`，所有 trust/final-close/readiness/T1/execution/credit 字段恒为 false/0。

**41 项合成专项测试通过**，`py_compile` 通过。一次配置 Terra High 的只读子代理意见为 `REVISE`、无 P0，但列出 raw fanotify reparse、close-token/cookie bridge、producer sequence coverage、causal journal order/object binding、PIDFD/FID/census join 等未闭合项；reviewer 身份/effort 未 attested，未运行测试。该工具不重新解析 fanotify raw bytes，不验证内核 build/source 或 hook ABI，不认证 token、PIDFD、FID、cgroup readback 或 queue drain，也不证明最后引用/fput 调用链；它不能接入正式执行/资格门。因此 readiness v8 的 `trusted_terminal_supervisor_and_final_fput_observer_missing` 仍 open，F8 runtime readiness/T1/execution authority=false、qualification credit=0，v8 回执和历史记录均未改写。后续须先冻结 producer/close-cookie bridge 与 bounded raw UAPI parser 合同，再独立审查后迭代。

只读主机盘点记录当前 Ubuntu `22.04.5`、kernel `6.8.0-138-generic`、包 `6.8.0-138.138~22.04.1`，boot config SHA-256 `0ffca159bcee00c87b27e093889b710fe680ccfa37149e4e1ef8d5053e1e644c`，配置启用 fanotify、permission events 与 seccomp filter；当前进程 `CapEff=0`、`CapPrm=0`。此为本机 package/config 观察，不是 target kernel/runtime pin。只读检查 CPU Makefile 发现默认编译会写入 `bin/linux` 并在源码树产生对象文件；本轮未运行 compiler/Make/CMake。

本轮没有读取 production output/HDF5/PART/BI4，没有运行 GenCase/native decoder/solver/worker/GPU/queue，没有做 capability/filesystem probe、fanotify init/mark 或任何 sudo/root 操作；未改 registry、ledger、scope、denominator、T1/T2 或资格信用。

详见[实现边界与输入约定](F8-R008-FINAL-FPUT-JOIN-REDUCER-V1-2026-09-27.zh-CN.md)、[reducer](../scripts/f8_r008_final_fput_join_reducer_v1.py) 与[专项测试](../tests/test_f8_r008_final_fput_join_reducer_v1.py)。配置 Terra High 的只读子代理意见为 `REVISE`，身份/effort attestation 未取得。
