# residual seed43 admission + secure runner v2 缺口审计

状态：`closed_minimal_fail_closed`。

盘点时 residual seed43 只有既有 rollout/real-50-step diagnostic 报告，没有 seed43 专属 admission、secure runner v2 或专项测试。训练 receipt 与 checkpoint 仅作为有界输入文件证据，不代表真实生产调度器、GPU 运行或正式资格。

本次最小闭环新增：

- receipt-bound、外部 Ed25519 scheduler reservation、namespace/descriptor/one-shot consumption 的 admission；
- command/environment/GPU snapshot/namespace/runner source 绑定的 secure runner v2；
- terminal envelope 的严格绑定校验，但不生成 terminal receipt；
- admission 与 runner 专项测试。

执行能力刻意未安装：不调用 `Popen`/`wait`，不探测或声称 live GPU，不写 Core gate、registry、ledger、denominator 或 PLAN，credit 保持 `0`。测试中的 scheduler key、authority 与 GPU snapshot 是临时 synthetic fixture，不能升级为生产证据。

本报告范围明确排除 raw seed17 SA-003、residual seed29 以及 Core gate 数据。
