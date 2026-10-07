14 哨点初始帧核对的实际绑定详见 `checkpoints/SENTINEL_INITIAL_VERIFICATION_001.json`；只给 frame0 转换一致性信用。

## 2026-10-07 17:56 UTC：v4 集成与真实缺失证据

`checkpoints/INTEGRATION_RESULT_002.json` 记录实际输入哈希及收据。active consumer 为 `scripts/ds_data02_stage2_consumers_v4.py`；主分支 guarded 17 项测试通过，制造轨迹 operator replay 通过。该容差仅用于制造轨迹，不授予真实数据科学资格，也不能排除原生保存帧之间未解析的重复穿越。旧 v1/v2/v3 与全部历史报告保留。

真实 full-timeline field audit 截至本次快照共 80 个不同案例（F2=43、F4=24、F6=13）；后续动态进度以具体执行收据为准。F2 science-002 和 F6 science-001 的 detached batch parents 仍存活；F4 science-001 的历史 running 标记是已明确无进程的 stale 状态，不用于重启已完成项。F2 释放一个 I/O slot 后调度 F4 未完成 24 项，scan-F4-168 使用恢复 request 002。

F6-240/241 已完成 native exclusions 对齐：3+4 个 position 排除。数值排除类别已建立，物理去向/动力学影响未知；必须结合实际 MapRealPos、底壁几何和原生状态诊断。rigid-body massbody 与 SPH support weight 分开，禁止粒子总质量代替刚体物理质量。

三个执行分支持续进行：reference 的 14 个初始帧 individual guard jobs 已全部完成、转换一致性 PASS（主进程已逐一核对收据）；继续 v2.3 provenance 反例及 F2-S1 三网格/time/output 复用与缺口准备；forensics 做 16 个 native 诊断和 provenance 反例、扩展已完成 scans；consumers 做 source-bound 真实单案例 replay 与全 336 的物理条件/几何控制谱系审计。具体读取真实时序由主进程安排 I/O；无模型、无 hidden test、无公开发布。目标未完成。

# 第二阶段恢复入口

当前目标仍在执行，完成条件未满足。先读 `checkpoints/CHECKPOINT_004_INTEGRATED.json`、`checkpoints/INTEGRATION_RESULT_001.json` 和 `checkpoints/CONSUMER_V3_VERIFICATION_001.json`，再检查真实进程和共享ledger。不要只根据running状态文件重启任务。

已验证的长任务：F2剩余19项，batch stage2-F2-science-002，PID 1060070、start_ticks 217766475；F6全48项，batch stage2-F6-science-001，PID 1060071、start_ticks 217766476。进程独立会话启动，launch记录在数据根runtime/batch-launchers，各批次收据在runtime/batches。guard子进程继续绑定batch父进程死亡，最多两个科学I/O批次、每批一个worker，父预算和500GiB空闲下限生效。

旧exec sessions 30970/20699已不存在，独立ps确认旧父进程及worker均退出。F2旧批次终态interrupted，保留完成28例；F4旧batch文件残留running，但scan-F4-168-001执行收据是SIGTERM中断失败、实际PID不存在，保留已完成24例。两个受中断案例登记新attempt002，旧证据不改。见BATCH_RECOVERY_001.json，不能重启旧batch或把中断解释为物理失败。

全部336例入口：CURRENT336.json。新的335个扫描请求与一个已完成复用案例在SCIENTIFIC_SCAN_QUEUES.json。未启动的F1/F3/F5/F7只是已准备队列；F4剩余24项在当前任一科学I/O槽位释放后恢复，其中scan-F4-168使用002，其余未启动请求使用001。已完成收据与数组hash匹配才可复用。

F2-S1的401帧已扫描，3个遗漏ID均与原生PartOut/RunPARTs精确对齐，原因为位置排除；实际三点越过求解域x下界。物理去向和动力学影响仍未知。原案例保留，下一步预登记同输入扩大数值域的有界配对影响实验，并检查其它F2案例是否同因。

14个哨点的实际XML、启动argv、原控制和native step日志已复核；初态等价、raw-vs-typed和时空精度研究尚未完成。37项运行器/科学读取/原生对账测试通过，不授予QN/QE。S1的标签与消费者收口仍需实际CURRENT接口集成。

每个实际solver只通过共享runner启动，启动前核对GPU UUID授权与外部进程、空间预约和父累计预算。尚未启动新CFD或模型。checkpoint不代表目标达成。

当前消费者入口为scripts/ds_data02_stage2_consumers_v3.py，历史v1/v2仅保留重放谱系。主进程共享预算下13项v3反例测试全部通过；真实14个F5同manifest case_id产品维持同group/role。这个开发角色接口还不代表全局物理条件、控制模板或参数支持泄漏审阅完成。四个历史probe的launch源码均已由确切Git blob hash恢复；此前003失败保留。

已合入14个来源绑定的原生遗漏对账：11个F2案例有324个位置排除，3个F4案例有5个密度排除，物理去向及动态影响仍未知。F2-S1首帧418104粒子、14个字段检查全部通过；只证明该帧原生到typed转换一致性，不证明初态物理正确或空间/时间收敛。

2026-10-07T17:22Z：原生遗漏解码v2批次14项全部成功；此前不支持参数的v1失败保留，两个批次的请求字节均与批次launch digest一致。14项尚需完成scan/native来源绑定与原因对账，不能据解码成功授予科学资格。F2/F4科学扫描分别完成20/17项，其它请求继续由现有活进程推进。

消费者分支提交250fa6679已通过两次真实CURRENT探针，但集成审阅发现跨粒子分块累计穿越被覆盖、分辨率可能被划分到不同谱系组等问题，修复及反例交给原子代理，以新的不可变v2模块执行后再集成。probe001的源码digest与当前模块不一致，历史源码恢复状态待查；probe002绑定当前模块。不将接口成功与标签正确性等同。参考子代理当前收窄为F2-S1首帧原生/typed等价检查，之后再扩展到14哨点。
