# UPDATE-220：F8 R008 V18 静态 fanotify profile 闭环

日期：2026-09-27（Asia/Shanghai）

## 本轮完成

新增 proposal-only fanotify profile JSON 与严格 schema verifier，固定 V17 permission/name 两组的 symbolic init flags、PIDFD/FID 字段关联及 event-FD 分支；两组均要求 `CAP_SYS_ADMIN` 位于 `init_user_ns`，拒绝 PIDFD 降级。verifier 将 ABI 观察值限制标注为 Linux v6.8 x86-64：name/FID `0x1e83`、permission `0x0087`、`event_f_flags=0x80000`；目标 ABI 的 raw values 保持 null，不能据本 manifest 推断目标内核/ABI 通过。

新增 execution-readiness audit v7，传递重验并纳入 V6 的哈希证据闭包，同时绑定 V17/V18、profile manifest、verifier 及测试。状态明确为静态 profile schema pass、runtime readiness blocked；新增 pinned-kernel/runtime conformance 与 trusted supervisor/final-fput observer blocker。`readiness_pass=false`、T1=false、qualification credit=0；没有调用 fanotify init/mark、探测 host capability/filesystem、读生产 HDF5/PART/BI4，或运行 GenCase/native/solver/worker/GPU/queue；未更改 scope、registry、ledger、分母或资格信用。

## 验证与未决环境限制

使用命令 `lagrangian-fluid-lab/.venv/bin/python -m pytest -q lagrangian-fluid-lab/tests/test_f8_r008_terminal_fanotify_profile_verifier_v1.py lagrangian-fluid-lab/tests/test_f8_r008_execution_readiness_audit_v7.py`，profile verifier 与 audit v7 定向套件 **10 passed**；两份 Python 文件 `py_compile` 通过，`git diff --check` 通过。曾尝试同时收集 V6 历史测试，但系统 `h5py` 与当前 NumPy 二进制 ABI 不兼容（`numpy.dtype size changed`），故该历史测试套件未能收集/执行；未改装或升级环境依赖。V7 本身通过重新核验 V6 receipt 所列源文件、测试及其传递证据哈希，不导入旧 V6 builder 的 HDF5 依赖链。

Terra High 配置的代码复核关闭了路径约束、JSON 类型混淆、合同摘要和公开 writer 路径问题；最终窄复核未发现代码 P0/P1，指出的记录计数与 receipt 链接差异已按本报告/receipt 校正。reviewer 身份未 attested。静态通过不代表 fanotify runtime conformance、执行许可或 F8 T1 资格。

F4 预检门单独观察到 1-min load `142.21 > 128`，故没有启动或消费 CPU/native preflight one-shot；未创建 marker/lock/receipt。详见 [V7 receipt](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-execution-readiness-audit-v7/receipt.json)、[profile manifest](F8-R008-TERMINAL-FANOTIFY-PROFILES-V1-2026-09-27.json) 与 [V18 contract](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V18-2026-09-26.zh-CN.md)。
