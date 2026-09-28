# Core continuation status — UPDATE-390

日期：2026-09-29

本轮按由粗到细策略并行推进了三条互不覆盖的工作：Core formal source closure V7、F3 MLP hidden16 full835 终态 intake，以及 F3 material coarse root/scheduler intake。后续 subagent 策略仍为 `gpt-5.6-luna`、reasoning `max`；历史模型 receipt 不改写。

## 已完成并单独提交

- `9d1a10f6`：WP-CF-01 canonical formal runtime source closure，补齐 13 个 lazy/runtime 文件并区分 live closure 与历史 baseline。
- `6bc69dbc`：生成并验证 planning-only V7 source closure、audit、receipt 和 SHA-256 sidecar；V7 `closure_verification=true`，但 formal release、formal training、launch 和 root admission 全部关闭。
- `26cfeda3`：修复 F3 material coarse intake 直接 CLI 入口的 host-I/O validator import 假失败；专项回归 `11 passed`。
- `651a729a`：刷新当前源码/hash 绑定的 F3 material coarse intake。
- `d27542ff`、`2610603e`、`ad9907b4`：分别记录 MLP seed43、seed17、seed29 的真实自然退出 process proof。

## MLP hidden16 终态结果

seed17、29、43 三条 fresh nonce rollout 均完成 `835/835 transitions`、`836 frames`，并各自具有 evaluation、trajectory metadata、独立 HDF5 validator、artifact identity 与 trusted process proof。seed29 没有被停止或重启，使用原 namespace 自然完成。

三 seed intake builder 的终态均为 `blocked_fail_closed`、`source_bound=false`、`credit=0`。所有 runtime/validator/process checks 已闭合；唯一阻塞是 training evidence matrix 的 manifest SHA `5d53fd9c…c4f768` 与历史 summary/current manifest SHA `8d87da6a…e680` 不一致。该 source-lineage drift 是真实证据问题，不能通过改写旧 matrix 或历史 summary 消除。

## F3 material coarse

`CORE-F3-MATERIAL-COARSE-s2` 当前收据为 `blocked_missing_fresh_root_scheduler_receipts`。当前 `core_material.py`、`core_runtime.py`、job/runtime spec、normalized argv/cwd 和 source hash claim 均已绑定，host-I/O admission contract 也通过；缺口只剩 fresh root receipt 与 scheduler-owned host-I/O reservation。intake 仍不打开 HDF5、不启动 worker/solver/GPU/queue，不铸造 launch capability。

## Formal / denominator 边界

本轮定向回归共 `202 passed`，其中 formal source-closure 相关 `51 passed`；工作树干净。只读 denominator 审计确认 `432` 是最终 T1 目标，`288` 是当前已登记 T1 分母/缺口，另有 `144` 尚未登记；材料最终目标为 `288`，当前登记材料分母为 `0`。生成器状态与 checked-in `completion.json` 完全一致，没有改写任何数字。后续应优先在 schema/README 中澄清 `missing_registered_*` 与 `missing_target_*` 的命名语义。

Core formal gate 仍保持 `can_finalize=false`、formal training `0/9`、macro T2 `0/2`、第三 T1 family 未闭合、material case-run `0/288`、independent reproduction=false、`launch_allowed=false`、root admission=false。所有本轮结果仍为 diagnostic/preparation evidence，不修改 registry、ledger、denominator、gate 或 completion。

机器回执：[UPDATE-390 JSON](CORE-CONTINUATION-STATUS-2026-09-29-UPDATE-390.json)。
