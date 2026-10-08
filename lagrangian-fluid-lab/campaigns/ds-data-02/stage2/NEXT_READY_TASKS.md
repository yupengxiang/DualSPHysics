# 下一就绪任务：检查点 021 及后续实际核验

完整 Stage2 目标继续，未完成。沿用原父账、额度及截止时间；336 例属于已接触开发素材。实际状态与证据见 checkpoints/CHECKPOINT_021_INTEGRATED.json。

1. F7 corrected v6 单并发批次（session39780）已完成14/22例、无失败；proof020已独立核验323例，F1–F6各48、F7为35。为优先关闭F6输入后验哈希，own批次父PID1571139已SIGSTOP，仅阻止后续派发，当前子任务未取消。F6终态核验后须检查同PID命令并SIGCONT恢复，目标仍active。不得重复已有原生审计或丢失恢复入口。
2. F6 static/Kabsch combined-v5 正在同父 v6 入口实际运行（session59059）。一次两份 H5 的 static/Kabsch共享读取；runtime负责实际前后哈希。终态必须同时通过 worker validate、精确 manifest/source/receipt及必需 JSON 检查；代码或CLI测试不算实际完成。
3. F2 removal v4已实际成功并独立核验 original175/expanded111，C59/C61失败保留。缺失质量宽度仍分别高于.003，不能改阈值或解读为物理去向/冲量/动力学误差。后续消费准确保存时间括号和多面/inside/UNKNOWN。
4. F1-S1同/半CFL与F1-S2粗/细36帧快照已实际成功独立核验；F1-S2 medium9帧snapshot-v2也已实际完成并验证前后stat稳定。四canonical观测暂缓，enforcer-v1缺少跨解码完整stat比较且未知child状态可误通过，等待additive-v2修正并绑定v8后实际运行。MK相对/绝对编号明确，pressure/EOS仍未解码；相邻网格差异不能直接称真值误差。
5. all118 weighted-impact、mechanism-bounds及mechanism-probe-v2均已实际完成并独立核验；1328原生ID，F2=1078/F4=51/F6=199；F4端点46低于密度下限、5高于上限。F2-S1三ID来源仍partial。继续实际impact-ledger消费和准确CURRENT来源补齐；去向、合法通量、动力学保持UNKNOWN，整初始质量分母和冻结阈值不变。
6. F7-S2 dense same-CFL的C60超时保留701帧、约7秒部分原生证据，不授予原计划12秒全窗参考信用；半CFL未启动。先交付明确NVMe外部solver输出入口，保持同父ledger、GPU UUID租约、两个文件系统检查与实际字节费用；暂不新增Home大solver写入。
7. portable v10/v11/v12根请求已保存，v12 metadata preflight通过；v12取消清理与v13同父supplemental trace-delta/sidecar记账测试通过，尚无实际回放。补齐root supervisor自身CPU/日志/报告记账闭合，待IO槽后实际raw→typed→label/private loader/no-model evaluator；bridge唯一登记主体，不包第二层ledger-owning runtime，不把复制既有typed文件当重建。
8. dp009 GenCase已实际完成，流体55352×.000729=40.351608kg，相对冻结样本40.2kg误差+.377%；不授予QN。继续辨析既有owner连续体积.0402m³与cell-centre drawbox extent.036036m³的来源语义，不能后验改质量目标。14哨点连续几何/MK/control、匹配3档网格和积分/输出误差分离仍需真实观测及证据。
9. 七族完整原始锚点、经检验的任务标签与删失/未知区间、有效条件/控制/几何/恢复谱系安全development划分、七份实质family card、无模型evaluator及依赖/许可/访问与单案例复现入口仍须完成。

检查点、局部成功或测试通过不构成完整目标达成；三名既有代理继续各自分支，root负责集成、独立核验和资源排程。
