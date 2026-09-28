# F4 Tallwall120 材料 receipt consistency audit v1

审计时间：2026-09-28T00:00:00Z  
机器报告：`reports/F4-TALLWALL120-MATERIAL-RECEIPT-CONSISTENCY-AUDIT-2026-09-28.json`  
状态：`blocked_fail_closed`

## 范围与输入边界

本审计只消费小体积 JSON、Python 源文件和文件元数据。没有打开、读取或重新 hash 生产 trajectory HDF5；没有启动 worker、solver、native runtime、GPU、queue 或 scheduler，也没有取得 root 授权。DEV_07 的目标 HDF5 只做存在性/字节数元数据观察。

没有修改历史 coarse proposal receipt、collection manifest、reader smoke receipt、DEV_07 diagnostic receipt、registry、ledger、denominator、gate 或 completion 状态。

## 事实绑定

- 当前 `build_proposal()` 与 committed coarse proposal receipt 的 semantic projection 匹配；当前 planner code snapshot 仍为 `5351b95e863b2f50353f9dc6080f374a49345fdb824fff14dba1bd9c286eab7e`。
- 原始报告 shape 不相同：当前 builder 使用 `source`/`created_at_utc`，历史 receipt 使用规范化的 `source_manifest_contract`/`observed_at_utc`。该差异被显式记录，没有覆盖历史 receipt。
- 当前 collection manifest：`808fe201c4df28f2be9b48a514f338689c38bcb96db0b0c0590946b79fb9ad09`。
- reader smoke receipt 记录的 manifest SHA：`86100523e66202f567ee29da6e178702f0e3ab19c63bd0cf861ff8a5fa0f86b4`。二者不一致，因此 reader smoke receipt 当前未被视为 current-manifest-bound。
- DEV_07 collection row 仍声明 `archives-v1/.../product/trajectory.h5`，当前 target/proposal 声明 `archives-v2/.../product/trajectory.h5`；两者 source SHA 都是 `6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae`，但路径不一致，不能静默折叠。
- DEV_07 diagnostic receipt 的 source path 与 source SHA 均绑定 target，且 source before/after 未变化；但它是 diagnostic-negative：event window `right_censored_or_unresolved`、`unknown_fraction_max=1.0`、common reliable path coverage 为 `0.0`、`T2=false`、`credit=0`，不得提升为 material qualification。

## Fail-closed 结论

4 个检查保持失败并作为阻塞事实：

1. committed receipt 的原始 top-level shape 与当前 `build_proposal()` 不同；
2. 当前 planner 包含 `failed_static_check:collection_source_path_exact`，历史 receipt 没有该 derived blocker；
3. reader smoke receipt 的 manifest SHA 已漂移；
4. collection 的 `archives-v1` 路径与 proposal 的 `archives-v2` target 不一致。

本审计严格输出 `T1=false`、`T2=false`、`credit=0`，所有 registry/ledger/denominator/gate/completion mutation 均为 `0`。后续仍需完成 collection row 重绑定、fresh root/material admission、resource/runtime authorization、trusted reader formal eligibility，以及完整可靠 material trace/event window，才能进入任何运行授权或科学资格判断。
