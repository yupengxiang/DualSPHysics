# 第二阶段恢复入口

当前目标仍在执行，完成条件未满足。先读 `checkpoints/CHECKPOINT_001.json`，再检查真实进程和共享ledger。不要只根据running状态文件重启任务。

已验证的长任务：F2科学扫描批次，exec session 30970；F4科学扫描批次，exec session 20699。各自独立batch-receipt位于数据根runtime/batches/stage2-F2-science-001和stage2-F4-science-001。当前最多两个科学I/O批次、每批一个worker；由strict guard重新验证每例输入hash，父预算和500GiB空闲下限继续生效。

全部336例入口：CURRENT336.json。新的335个扫描请求与一个已完成复用案例在SCIENTIFIC_SCAN_QUEUES.json。未启动的F1/F3/F5/F6/F7只是已准备队列，不冒充后台任务。可在I/O槽位释放后启动；先处理F6缺失取证，并推进其余家族参考准备。

F2-S1的401帧已扫描，3个遗漏ID均与原生PartOut/RunPARTs精确对齐，原因为位置排除；实际三点越过求解域x下界。物理去向和动力学影响仍未知。原案例保留，下一步预登记同输入扩大数值域的有界配对影响实验，并检查其它F2案例是否同因。

14个哨点的实际XML、启动argv、原控制和native step日志已复核；初态等价、raw-vs-typed和时空精度研究尚未完成。37项运行器/科学读取/原生对账测试通过，不授予QN/QE。S1的标签与消费者收口仍需实际CURRENT接口集成。

每个实际solver只通过共享runner启动，启动前核对GPU UUID授权与外部进程、空间预约和父累计预算。尚未启动新CFD或模型。checkpoint不代表目标达成。
