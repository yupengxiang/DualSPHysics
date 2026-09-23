# Core 接续状态更新 22（2026-09-24）

本更新对 F3 R003 的 40 个 wall-occluded seed 做了绑定 source/trace/backend 哈希的只读首失效区间反事实回放。

- 原始首 stage 与已提交回放吻合（k2=17、k4=23）。单最近闭壁零速约束下，40/40 seed 均完成首失效子步之后至下一输出帧的短区间；没有重试步，但这只是支持门控的局部轨迹，不是完整 attempt。
- 反向证据同样重要：396 个近壁 stage 求值中 140 个 residual 超过原 F3 对照上限，涉及16/40 seed；116个内部 stage 仍有外向法向速度。没有重算后续时间、CDF、驻留或事件门，故不改变 R003 的失败、分母、row acceptance 或 T2 credit。细节和逐 seed 复现入口见[只读回放报告](F3-ROW30-R003-NOSLIP-CONSTRAINED-FIRST-FAILURE-REPLAY-2026-09-24.zh-CN.md)。
- 修正了旧 stage-replay 文档中的一位 backend SHA 抄录错误；绑定值与 trace summary 和当前文件一致。
- 全程未改历史 trace、启动 worker/solver/GPU/队列或重复已消耗的 row30 资源预检。Core 总体仍未完成，既有 F8/F3/F4 执行授权边界不变。
