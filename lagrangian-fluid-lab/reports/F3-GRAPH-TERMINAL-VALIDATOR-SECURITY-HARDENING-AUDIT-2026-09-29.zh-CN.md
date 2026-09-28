# F3 graph terminal validator 独立安全审计

状态：`blocked_fail_closed`；本审计只读、未启动 workload、未调用 Popen、未打开生产 artifact，`credit=0`。

审计对象包括 raw/residual terminal validator、raw/residual execution bridge、evaluator artifact readiness 和 production validator capability。现有目标专项测试 `79 passed`，本次独立对抗测试 `7 passed`。

## P1

- `F3-SA-001`：production process proof 可由 receipt 自声明 command/PID/布尔值并自哈希，且没有完整 manifest/training/checkpoint 绑定；未来开启 capability 前必须使用完整预期身份和真实、不可由 JSON 自授权的 Popen/wait witness。
- `F3-SA-002`：多处先 stat/hash 后按 pathname 重新打开 HDF5/JSON，存在 TOCTOU；最终二次 stat/digest 不能覆盖中间窗口。
- `F3-SA-003`：residual module-level terminal token 可被同进程取出，`popen_factory` 可注入，不能作为真正 sealed capability。
- `F3-SA-004`：required HDF5 object 未先拒绝 external/soft link 与 virtual dataset，可能越过已检查的文件路径。

## P2

- `F3-SA-005`：production evaluation/validator payload 只检查选定字段，unknown fields 未统一拒绝；当前仍被 capability 未安装和 zero-credit 边界阻断。

本提交新增隔离 hardening contract：目录 fd 链 + `O_NOFOLLOW`、single-link regular file、一次性 descriptor snapshot、从内存 HDF5 snapshot 检查 hard-link/VDS、完整 command/manifest/training/checkpoint 绑定，以及默认/显式 execute 一律拒绝。未修改上述任何代理文件、PLAN、registry、ledger、gate 或 completion。
