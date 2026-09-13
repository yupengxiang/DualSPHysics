# L1-R continuation: F3-REF0081818 终态交接

当前权威入口是 [当前能力交接](F3-REF0081818-CURRENT-CAPABILITY.zh-CN.md)、[机器收口记录](F3-REF0081818-CAMPAIGN-CLOSEOUT.json) 和 [机器状态](EXECUTION-STATE.json)。有界活动已经收口为负结论：配方 gate、32 个独立开发案例、材料候选和六个学习逻辑运行均有实际证据；材料 T2/模型正式资格未通过，且父 CPU 保守上界与训练次数已达到限制。旧的 [阶段交接](L1R-CONTINUATION-HANDOFF.zh-CN.md) 保留为历史 checkpoint，不覆盖当前状态。

## 当前交付

| 内容 | 证据 |
|---|---|
| F3 配方、三分辨率阶梯、控制域、长窗、坐标系和评分面板 | `F3-075-REF0081818-GATE.json`, `F3-075-REF0081818-SCORES-*.json` |
| 32 个独立开发案例及 train/validation/test 契约 | `F3-REF0081818-TRAINING-DEVELOPMENT-FULL.json` |
| 材料名义 s2/s4 候选与子步比较 | `F3-MATERIAL-REFERENCE-*.json`, `F3-REF0081818-MATERIAL-COMPARISON-NOMINAL-SUBSTEP.json` |
| 材料 cadence 两次超时及完整尝试索引 | `F3-REF0081818-MATERIAL-ARCHIVE-INDEX.json` |
| 两路线三种子真实训练、16/16 回放和失败门 | `F3-REF0081818-TRAINING-CLOSURE.json` |
| 八卡并行授权及 CPU/GPU 绑定策略 | `F3-075-REF0081818-TRAINING-PARALLEL-AUTHORIZATION.json` |
| 资源封账与活动终止谓词 | `RESOURCE-LEDGER.json`, `F3-REF0081818-CAMPAIGN-CLOSEOUT.json` |

大体积 CFD、材料和训练输出留在本地外部归档；Git 中只保留紧凑记录与哈希。`formal_release`、`formal_model_qualification`、`qualified_T2_macro` 和 `qualified_T2_path` 均保持 false。

## 历史检查

原 F3 输入修复、Q1/Q2 证据和早期阶段状态仍在本目录中，不能把旧 checkpoint 的“活动未关闭”描述当作当前状态。上游/vendor 文件及失败 attempt 不改写。

## 资源安全

活动窗口已冻结，不能再从当前账本启动新的计费训练或材料配置。若要追求通过 T2 或模型质量门，必须先建立新的父预算和新的有界授权；不能通过改类别、删失败样本或改判现有负结果来继续。
