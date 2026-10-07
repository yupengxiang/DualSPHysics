# DS-DATA-02 Stage 2：数值与任务级验收，不训练模型

审阅日期：2026-10-07。科学冻结点：`fab8dd3b3ac28ef5e21efea9cc3f04afa7f116ee`，checkpoint335。
本轮远端核对：`codex/ds-data-02-stage1-review-20261007` -> `c30f8348d66debc83c581fed964aa3a2868dc2f2`。

## 入口
- `START_HERE_ZH.md`：主Agent接令与范围。
- `REVIEW_ZH.md` / `REVIEW_FINDINGS.json`：来源、复核、严重性和限制。
- `STAGE2_PLAN_ZH.md`：分阶段执行、验收、失败分支和停止条件。
- `PARALLEL_OPERATIONS_ZH.md`：七族并行与共享资源。
- `SENTINEL_MATRIX.json`：14个真实现有案例、实际粒距、候选三档和证据路径；仅为待本地核对的实验设计。
- `families/F1.md` 至 `F7.md`：可分别交给family owner的任务书。
- `QUALITY_LABEL_SPLIT_ZH.md`：精度、标签、未知、划分和数据产品。
- `CAMPAIGN_PLAN.json`：机器可读范围和软预算；不是已经实现的运行命令。
- `MINIMUM_REPLAY_BUNDLE_ZH.md`：最小追加原始数据建议，不要求传输全部336例。
- `SOURCES.json`：主来源与外部方法依据。
- `audit/`：本轮实际CPU复核输出；没有CFD/训练结果。

收到的源ZIP缺少正常末尾目录记录。已在不改变源ZIP的前提下按local header恢复5946项，逐项CRC/长度检查，并对PACKAGE_MANIFEST的5944个文件及7896组物理字段比较执行独立校验，均通过。此事影响传输封装，不等于科学产物损坏。源HDF5/BI4/DAT未提供，本轮没有独立复算科学数组。
