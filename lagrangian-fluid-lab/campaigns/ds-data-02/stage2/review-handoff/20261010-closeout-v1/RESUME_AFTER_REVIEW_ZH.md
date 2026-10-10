# DS DATA 02 云端审阅后的恢复状态

当前是用户要求的审阅等待，不是目标完成，也不是资源耗尽。不得根据历史 NEXT_READY_TASKS、附件或 surviving request 自动恢复执行。五个旧 waiter 已停止，ROOT434 字段父任务边界和 ROOT717 独立关联终态已保留。此次没有重写旧成功/失败收据，没有新成功 barrier。

恢复时先读本次总报告、云端审阅结果和用户最新方向，再核对真实截止、资源账、Home 空闲和活动预约。原截止 `2026-10-14T07:23:48Z` 不变，父 CPU/GPU/attempt 限额不重置。若恢复时已过期，不能直接启动新 solver 或超界任务。

| 保留分支 | 准确停点 | 恢复前必须解决的条件 |
|---|---|---|
| 保存帧生命周期 | ROOT307，335 规范案例实际闭合 | 历史别名仍 UNKNOWN；不重复扫描全部 335 |
| 科学字段扫描 | ROOT434，78 实际规范案例 | 256 可执行请求；规范缺 manifest 和历史 alias 各 1；需新的合法边界 resume grant 和未消费 yield marker |
| 原生遗漏原因/关联 | ROOT717，117 规范案例 | 不重复 ROOT711–717；旧别名不取得 credit；物理去向/通量仍 UNKNOWN |
| 三哨点支持修复 | ROOT710 六诊断成功、三 F3 失败 | ROOT718 source-only；实际 F3 Def/XML 路径绑定并经父保护后才能运行 |
| 九份原生头解析 | ROOT709 九 UNKNOWN | ROOT719 source-only；只重读保留 XML，不能回填旧 709；per-particle header 不作 total mass |
| 规范 F2 案例 65 | ROOT720 source-only | 405 原生文件 deferred hash；根运行时/内存绑定；attempt-owned scratch 和完整峰值；转换后再做新标签 adapter |
| role-mass 比较 | ROOT721 源码保留 | 需实际 ROOT719 report；连续 owner/source support 与具体任务尺度仍待闭合 |
| 连续 owner 合同 | a8f284d9c 源码保留 | 没有 production parent；F3 canonical forcing 大文件绑定；不得以源码推导冒充实际初态资格 |
| family card forward | V28 绑定 ROOT412/56 | 不能直接消费 ROOT434/78；选择前向 census adapter 或维持旧有界卡 |
| portable ROOT242 | V11/V13/V14 均实际失败；后版 held | 不重启旧 row78 链，不制造 242 barrier，不复制 GB 数据后才做身份校验 |
| 14 哨点 reference | 有不同局部真实诊断/运行，无完整接受链 | 按审阅选择一个最小 task/window/observable，而非全图自动恢复 |

已停止的旧链为 portable242→support276→frame0 314→mass322–326→native old312/315/317–321→GenCase old337–345。其命令与 PID 在 `EXECUTION_CUTOFF.json`。不能因为独立 ROOT700–708、711–717 已成功，就伪造旧 namespace 的 barrier 让整个旧链复活。

所有已准备请求应保留 source-only/held 的事实。实际请求的启动 commit、解释器 literal path、输入代码闭包、前后哈希、资源预约和真实输出必须重新按所选具体分支校验；报告 HEAD 或 GitHub HEAD 不替代启动版本。生产数组仍由有界受保护 worker 读取，根只做控制与有界证明复核。

需要新增 namespace 时先核对现有 reservation：字段剩余保留 435–690；718/719/720/721 分别用于支持修复、保留头 XML、规范转换、role-mass。不能用这些编号去运行另一科学任务，或在保留 attempt 目录存在时隐式重跑。

不应恢复模型训练、学习推理、checkpoint replay、调参或排行榜任务。公开数据集发布、真正隐藏测试、外部对象存储、延期和扩盘均不是本次收尾的新增授权。
