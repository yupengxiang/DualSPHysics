# F6 DS-DATA-02 checkpoint / F6 交接

本 checkpoint 冻结两个真正三维、无 Chrono/contact 的 F6 parent Definition：简单自由响应与无接触规则波激励。每个 parent 有 control/native/normal 文件，GenCase 请求由 shared runtime 执行；F6 owner 不启动 solver/GPU。

## Current state

- 旧 DS-DATA-01 13.57M identity 浮箱轨迹已审计但 `reused_count=0`，仅用于成本锚点。
- 两背景三分辨率、完整 0–12 s 事件窗、独立积分/保存采样计划、观测误差预算和 48 独立 nested 8/24/48 split 已冻结。
- 最短执行链：通过 shared runtime 提交 `execution_requests/simple_free_response_gencase.json` 和 `execution_requests/wave_no_contact_gencase.json`；完成后运行 `ds_data02_f6.py audit-parents`；仅对通过的 parent 提交 qualification request。
- Q-I、Q-N、production 严格 pending；不能用 Definition、canary、短预览或旧 training permission 代替实际 solver/native 证据。

## Actual parent evidence
- Parent audit status: **pass**; F6 owner launched no solver/GPU.
- Qualification requests: `qualification_requests/simple_free_response.json`, `qualification_requests/wave_no_contact.json`.
- GenCase checks include actual 3D/data2d=false, positive type-3 fluid and type-2 floating ledgers, effective transverse layers, finite walls, control coverage, draft/density ratio, rigid mass/inertia, no Chrono/contact solver, and all input hashes.
- Q-I/Q-N/production remain pending until root dispatches complete-window solver and postprocessors; the old 13.57M-identity candidate remains excluded from reuse.
- Parent audit status: **pass**; F6 owner launched no solver/GPU.
- Qualification requests: `qualification_requests/simple_free_response.json`, `qualification_requests/wave_no_contact.json`.
- GenCase checks include actual 3D/data2d=false, positive type-3 fluid and type-2 floating ledgers, effective transverse layers, finite walls, control coverage, draft/density ratio, rigid mass/inertia, no Chrono/contact solver, and all input hashes.
- Q-I/Q-N/production remain pending until root dispatches complete-window solver and postprocessors; the old 13.57M-identity candidate remains excluded from reuse.
