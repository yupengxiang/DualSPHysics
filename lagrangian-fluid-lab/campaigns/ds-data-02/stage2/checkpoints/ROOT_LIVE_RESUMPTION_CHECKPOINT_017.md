# Stage2 根进程检查点 017

长期目标仍为 active，尚未完成。本检查点保留完整目标与资源边界。

- 336 例字段审计已独立复核259例：F3=32、F5=35，另四族各48；F7未启动，须等真实扫描父进程退出。
- F2 portable v25元数据入口实际通过，60输入pre/post/current SHA一致，OS trace无H5 open；完整typed401回放仍待执行，raw重建另计。
- F2 native v4 raw→typed进程仍在运行，占用补充重I/O槽，partial H5不视为成功；session68908。
- F4两组实际小JSON比较完成，t0为共同时间直接比较，晚期保留UNKNOWN_NO_INTERPOLATION。
- F1-S2、F6-S1、F7-S1新档GenCase实际完成；质量、材料配比与刚体inertia/COM的连续匹配待实际审核。
- 16个绑定来源的遗漏边界CPU请求串行运行，session68533；数值排除原因不代表物理去向或零动力学影响。

准确路径、进程身份、资源累计和下一任务见CHECKPOINT_017_INTEGRATED.json。不得创建、缩窄或完成另一目标，不开展模型工作，不把计划或制造测试冒充实际验收。
