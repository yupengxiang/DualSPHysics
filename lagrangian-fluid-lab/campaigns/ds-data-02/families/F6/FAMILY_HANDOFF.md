# F6 DS-DATA-02 checkpoint / F6 交接

本 checkpoint 冻结两个真正三维、无 Chrono/contact 的 F6 parent Definition：简单自由响应与无接触规则波激励。每个 parent 有 control/native/normal 文件，GenCase 请求由 shared runtime 执行；F6 owner 不启动 solver/GPU。

## Current state

- 旧 DS-DATA-01 13.57M identity 浮箱轨迹已审计但 `reused_count=0`，仅用于成本锚点。
- 两背景三分辨率、完整 0–12 s 事件窗、独立积分/保存采样计划、观测误差预算和 48 独立 nested 8/24/48 split 已冻结。
- QUAL_01 失败证据已写入 `repair_evidence.json`：simple parent 的 floating boundary +Y 越界保留 Error_BoundaryOut.vtk；wave parent 的 mkbound=10 没有 moving block。修复各计为根因第 1 次，不扩大 RhopOut、不屏蔽 boundary abort。
- 当前最短执行链是通过 shared runtime 提交 `execution_requests/simple_free_response_gencase.json` 与 `execution_requests/wave_no_contact_gencase.json`（均为 GENCASE_02）；完成后运行 `ds_data02_f6.py audit-parents`；仅对通过的 parent 生成新的 SOLVER_QUAL_02 请求。
- 积分步长试验必须先从同一完整 parent 的 RunPARTs.csv/Run.out 测得稳定 baseline 最小 dt，再把固定 DtFixed 物化为不超过其一半；实际 dt 分布和 native step count 与保存帧对照分开核查。
- Q-I、Q-N、production 严格 pending；不能用 Definition、canary、短预览或旧 training permission 代替实际 solver/native 证据。
