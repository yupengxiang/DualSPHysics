# F8 R002 全新静态设计审查（2026-09-24）

本次只审查已封闭 R002 的 Definition、控制 CSV、历史预检回执/日志、官方 Poiseuille Definition 先例和既有静态复盘。subagent 按 `gpt-5.6-terra`, high 请求；其回复自称 Codex，且未提供实际模型身份 attestation，因此本记录只声明请求了 Terra model，不断言实际模型身份。

**结论：FAIL，R002 保持关闭。** Definition 缺少 `hswl`；与哈希闭合的历史 GenCase 文本记录一致，缺少该字段时 R002 在 Definition 第 5 行失败，返回码为 1。`rhopgradient`、`gamma`、`speedsystem`、`coefsound` 也不在 R002 中、但出现在官方模板先例中；审查只将它们记作静态兼容性缺口，不声称日志证明 GenCase 因这四项拒绝输入。

CSV 的静态检查通过：七列、705 行有限数值、时间严格递增且唯一，覆盖 `0–11.196636217394023 s`；名义步长与 `TimeOut` 一致，Definition 指向该相对路径。由于 GenCase 在 Definition 阶段停止，这不证明控制文件已被复制或加载。

审查请求中曾把日志的预期 SHA-256 抄错；复核后撤销了该哈希异常。当前日志实际 SHA 与既有 v2 审查收据绑定一致，日志没有证据显示在 Git 中被改写。该更正、全部源绑定、审查边界和零资格信用记录在[不可变审查回执](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r002/static-design-review-v3/receipt.json)。没有重试 R001/R002，没有运行测试、GenCase、native decoder、solver、GPU、queue 或 worker，也没有访问 HDF5/NPZ。任何修复都必须另立 F8 revision、namespace 和 scope 授权。
