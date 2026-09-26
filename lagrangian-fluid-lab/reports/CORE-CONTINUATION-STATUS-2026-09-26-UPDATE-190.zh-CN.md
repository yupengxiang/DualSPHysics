# UPDATE-190：F3 model-material v2 保守 RK stage 失败边界

时间：2026-09-26（Asia/Shanghai）

在 UPDATE-189 的最早失败原因修复上补齐模型侧处理约定：任一 RK stage 无可靠重建时，不猜测 wall reflection、投影或速度修补；该步不推进位置，tracer 进入永久 unknown，保留全部初始 tracer 质量于 unknown 分母。后续 stage 即使恢复可靠，也不得令它复活。该策略是诊断候选的保守删失，不等价于物理壁面相互作用模型或 T2 资格。

新增端到端合成 trace 场景：初始态可靠，第一积分步 k1 以 `wall_occluded` 失败、k4 恢复可靠，下一保存区间的所有模拟 stage 又均返回可靠。输出仍保持原位置，两个失败后保存帧均为 `permanent_unknown`，首次原因没有被改写，最终 unknown fraction 仍按全部 tracer 计为 1.0（逐帧 `[0.0, 1.0, 1.0]）。当前扩展测试单项 **1 passed**；实现改动前的四套邻接回归为 **23 passed**。由于主机 1 分钟 load 最新读数 `241.94 > 128 CPUs`，本更新未重跑完整 suite；本次只改测试/状态记录，生产数据及运行入口均未触及。

此处关闭的是 F3 model-material v2 的保守 RK stage 失败/censor 语义，不证明 native 闭壁查询的物理正确性；v1/temporal-v3 保持历史基线。阶段计时 profiling 与真实材料运行仍开放，row30 v5 one-shot 不重试；全局 Core 目标未完成。
