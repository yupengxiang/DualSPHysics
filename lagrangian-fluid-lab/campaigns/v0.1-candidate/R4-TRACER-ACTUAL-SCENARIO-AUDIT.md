# R4 tracer actual-scenario contract audit

状态：**candidate-only / rejected；本轮仅 CPU/static audit，未启动 CFD、GenCase、CUDA 或 GPU。**

本报告把已有 synthetic 反例推进到已物化 development release 的实际 HDF5、sidecar、manifest 和 G4 输入边界。结构字段通过不等于材料轨迹或 wall-aware transport 已被正式接纳。

## 结论摘要

- release cases：13；带 material group：12；seed/source 结构通过：12；source semantics 明示：0。
- 质量权重闭合：12/12；输出 cadence 声明匹配：13/13。
- 显式积分子步 provenance：0/12；完整 support failure channel：0/12。
- sidecar 结构通过：12；candidate open-face policy 通过：9；正式 wall-aware admission：0。
- destination spec：0；source-destination closure：0；formal material target：0。
- 已报告 terminal failed mass：23.1290003 kg，占已表示初始质量 3.067562%。

## 逐案例实际证据

| case | material/seed | weight closure | saved cadence | substeps | failed mass kg | wall/open-face | destination closure |
|---|---|---|---|---|---:|---|---|
| `F1_dam_break_plain` | pass | pass | 0.04991399999999996 s / pass | missing | 2.75200013 | candidate_sidecar_policy_only | blocked_no_destination_spec |
| `F1_opposing_columns` | pass | pass | 0.050014999999999976 s / pass | missing | 0 | candidate_sidecar_policy_only | blocked_no_destination_spec |
| `F1_center_obstacle` | pass | pass | 0.04999400000000004 s / pass | missing | 2.75200013 | candidate_sidecar_policy_only | blocked_no_destination_spec |
| `F1_twin_obstacle` | pass | pass | 0.05000099999999996 s / pass | missing | 0 | candidate_sidecar_policy_only | blocked_no_destination_spec |
| `W06_narrow_slow_center` | pass | pass | 0.01000000000000012 s / pass | missing | 1.296875 | candidate_sidecar_policy_only | blocked_no_destination_spec |
| `W06_standard_slow_center` | pass | pass | 0.010009999999999852 s / pass | missing | 1.71875 | candidate_sidecar_policy_only | blocked_no_destination_spec |
| `W06_wide_slow_center` | pass | pass | 0.010007000000000016 s / pass | missing | 7.765625 | candidate_sidecar_policy_only | blocked_no_destination_spec |
| `W06_narrow_fast_center` | pass | pass | 0.009989999999999943 s / pass | missing | 5.015625 | candidate_sidecar_policy_only | blocked_no_destination_spec |
| `W06_standard_fast_center` | pass | pass | 0.010000000000000009 s / pass | missing | 1.828125 | candidate_sidecar_policy_only | blocked_no_destination_spec |
| `F3_impulse_slosh` | pass | pass | 0.050034800000000004 s / pass | missing | 0 | candidate_sidecar_policy_only | blocked_no_destination_spec |
| `F3_baffled_slosh` | pass | pass | 0.0500409 s / pass | missing | 0 | candidate_sidecar_policy_only | blocked_no_destination_spec |
| `F3_transverse_slosh` | pass | pass | 0.05000199999999999 s / pass | missing | 0 | candidate_sidecar_policy_only | blocked_no_destination_spec |
| `W05_F6_fine` | failed | blocked_missing_material | 0.020000000000000018 s / pass | missing | 0 | blocked_missing_wall_contract | blocked_no_destination_spec |

`failed mass` 使用 material 的初始 `mass_weight`，按每个 case 的 `source_label` 单独报告；没有把 surviving tracer 重新归一到 1。

## Failed mass / source

| case | source | initial represented mass kg | failed tracer count | failed mass kg | failed fraction | reason |
|---|---:|---:|---:|---:|---:|---|
| `F1_dam_break_plain` | `1` | 74.8800036 | 1 | 2.75200013 | 3.675214% | support_distance_exceedance |
| `F1_opposing_columns` | `1` | 44.3520021 | 0 | 0 | 0.000000% | none |
| `F1_opposing_columns` | `2` | 44.3520021 | 0 | 0 | 0.000000% | none |
| `F1_center_obstacle` | `1` | 74.8800036 | 1 | 2.75200013 | 3.675214% | support_distance_exceedance |
| `F1_twin_obstacle` | `1` | 74.8800036 | 0 | 0 | 0.000000% | none |
| `W06_narrow_slow_center` | `1` | 6.1875 | 0 | 0 | 0.000000% | none |
| `W06_narrow_slow_center` | `2` | 7.734375 | 1 | 0.359375 | 4.646465% | support_distance_exceedance |
| `W06_narrow_slow_center` | `3` | 7.734375 | 2 | 0.9375 | 12.121212% | support_distance_exceedance |
| `W06_standard_slow_center` | `1` | 7.875 | 0 | 0 | 0.000000% | none |
| `W06_standard_slow_center` | `2` | 9.84375 | 1 | 0.859375 | 8.730159% | support_distance_exceedance |
| `W06_standard_slow_center` | `3` | 9.84375 | 1 | 0.859375 | 8.730159% | support_distance_exceedance |
| `W06_wide_slow_center` | `1` | 9.5625 | 2 | 2.296875 | 24.019608% | support_distance_exceedance |
| `W06_wide_slow_center` | `2` | 11.953125 | 1 | 2.5625 | 21.437908% | support_distance_exceedance |
| `W06_wide_slow_center` | `3` | 11.953125 | 3 | 2.90625 | 24.313725% | support_distance_exceedance |
| `W06_narrow_fast_center` | `1` | 6.1875 | 2 | 1.203125 | 19.444444% | support_distance_exceedance |
| `W06_narrow_fast_center` | `2` | 7.734375 | 1 | 0.6875 | 8.888889% | support_distance_exceedance |
| `W06_narrow_fast_center` | `3` | 7.734375 | 5 | 3.125 | 40.404040% | support_distance_exceedance |
| `W06_standard_fast_center` | `1` | 7.875 | 1 | 0.71875 | 9.126984% | support_distance_exceedance |
| `W06_standard_fast_center` | `2` | 9.84375 | 2 | 1.109375 | 11.269841% | support_distance_exceedance |
| `W06_standard_fast_center` | `3` | 9.84375 | 0 | 0 | 0.000000% | none |
| `F3_impulse_slosh` | `1` | 104.832005 | 0 | 0 | 0.000000% | none |
| `F3_baffled_slosh` | `1` | 99.0720047 | 0 | 0 | 0.000000% | none |
| `F3_transverse_slosh` | `1` | 104.832005 | 0 | 0 | 0.000000% | none |

## 已有能力与实际缺口

已有 production tracer 路径包括：source-stratified 初始 Mk seed、初始质量权重、Heun、独立 `frame_stride` 与 `substeps_per_interval`、ESS/几何秩/各向异性/重构误差 gate、有限三角面 visibility、rigid-pose 插值和 swept-wall 检查。G4 已拒绝显式 future fluid/free-body state，也能读取 sidecar 的 component geometry features。

本 audit 在当前实际 artifact 中发现：

- **trajectory_io_no_material_group (P1)**：直接 CSV→HDF5 转换器只建立 solver 数值身份轴，不建立 protocol 所需的 material/ 组。 证据：`scripts/trajectory_io.py:69`。最小接口：材料 seed/source/质量权重/valid 轨迹必须由显式 material producer 写入；本轮不改生产代码。
- **trajectory_io_units_only_added_by_later_wrapper (P1)**：trajectory_io.create_partial 本身没有写入 world_frame/time_units/length_units/mass_units；实际 release 依靠 W11 wrapper 后补。 证据：`scripts/trajectory_io.py:73`。最小接口：让 converter 的 protocol output contract 与 materialization wrapper 分层且显式，避免直接消费者拿到不完整 HDF5。
- **material_artifact_no_substep_provenance (P1)**：当前 material writer 调用 advect_hdf5 时没有保存每个 saved interval 使用的积分子步数。 证据：`scripts/w11_build_pilot.py:39`。最小接口：在 material attrs/manifest 中持久化 integration_method、substeps_per_saved_interval 和实际 substep dt。
- **material_writer_not_wall_aware (P1)**：现有 W11 material writer 未把 sidecar barrier_provider 传给 advector；artifact 中 wall_visibility 也不是 true。 证据：`scripts/w11_build_pilot.py:45`。最小接口：实际场景 material materialization 必须显式链接 sidecar、open-face policy 和 barrier provider。
- **g4_loader_does_not_load_material_group (P1)**：G4 _load_case 只读取 stable solver fluid identity 和 initial density/pressure/mass，不读取 material/ seed/source/mass_weight。 证据：`experiments/r3_g4_baselines.py:614`。最小接口：material transport 不能复用 particle rollout loader；需新增显式 material input contract。
- **g4_boundary_input_omits_open_face_semantics (P1)**：G4 component features 有距离/法向/Type/壁速度，但没有 open/closed/rim/supporting policy 字段。 证据：`experiments/r3_g4_baselines.py:407`。最小接口：sidecar component 到 G4 的输入必须携带可审计的 open-face/rim/supporting 语义，而非只传几何摘要。
- **g4_legacy_aabb_is_not_wall_contract (P2)**：无 sidecar 时 G4 仍可从静态 AABB 得到 boundary_available；AABB 不能识别开口/挡板拓扑。 证据：`experiments/r3_g4_baselines.py:606`。最小接口：正式 wall-aware material target 必须拒绝 legacy AABB-only geometry，或明确标记为 non-identifiable。
- **open_lifecycle_exit_reason_not_protocol_numerical_loss (P2)**：现有 transport_metrics 对 open lifecycle 把失效 mass 命名为 unknown_exit；trajectory-v0.1 的 closure 必须显式处理 numerical_loss/退出语义。 证据：`scripts/transport_metrics.py:190`。最小接口：为 open-face 穿出提供有符号事件/exit reason；不能把末帧缺失自动解释成 numerical loss 或 physical exit。
- **cross_resolution_compare_has_no_stable_key_guard (P1)**：现有 compare_traces 按 trace array 位置做差，API 没有 stable material key 或 resolution-group guard；它只能安全用于同一 HDF5/同一 seed axis 的 cadence/substep 对照。 证据：`scripts/r3_g2_tracer_convergence.py:201`。最小接口：跨分辨率比较必须改为 source×destination mass aggregate 或显式稳定 key；本轮只在 audit negative control 中执行该禁令。
- **actual_release_substep_provenance_missing (P1)**：12/12 个 material artifact 没有显式积分子步 provenance。 证据：`release material groups: integration=Heun but no substeps_per_saved_interval`。最小接口：重做 materialization 时把输出 cadence、积分子步和子步 dt 一起写入 artifact/manifest。
- **actual_release_wall_visibility_not_used (P1)**：12/12 个 material artifact 没有声明使用 wall-aware visibility。 证据：`material.attrs.wall_visibility and linked sidecars`。最小接口：用 sidecar + open-face policy 重新生成或重算 tracer；sidecar 存在本身不追溯修改旧轨迹。
- **actual_release_destination_spec_missing (P1)**：当前 release 没有任何可执行 destination specification，因此 source-destination closure 不能被正式计算。 证据：`release manifest cases[].destination_spec and material.destination_spec`。最小接口：为一个真实案例先冻结 source、destination_frame、destinations、in_domain_unclassified、numerical_loss/exit reason。
- **actual_release_support_reason_channel_missing (P1)**：当前 material 只保留 nearest_support_distance，缺少 support_gate_pass/ESS/geometry/reconstruction/wall_crossing 的完整 failure reason channel。 证据：`material datasets under release/v0.1-development/data/*/material`。最小接口：每个 failed tracer 必须可按 support gate、wall crossing、numeric loss 或 explicit exit reason 归因，并按初始 mass/source 汇总。
- **actual_release_source_semantics_provenance_missing (P2)**：12/12 个 material artifact 没有显式说明 source_label 是 initial solver Mk proxy，而不是物理材料 lineage。 证据：`material.attrs.source_label_semantics and material/source_label`。最小接口：持久化 source origin/lineage semantics；若只有 Mk proxy，必须保持 candidate-only 并禁止升级为材料真值。
- **actual_release_has_no_explicit_resolution_pair (P2)**：当前 release 没有可审计的同一物理场景跨分辨率 pair；不能把不同 lineage/family 案例误当成 resolution convergence。 证据：`manifest cases do not declare resolution_group_id/resolution_group`。最小接口：下一轮显式声明 physical_case_id/resolution_group_id，并只做质量聚合或 explicit stable-key comparison。

## 反例 / 不可宣称项

- 12 个 F1/F2/F3 case 有有限 sidecar，但 material attrs 仍是 `wall_visibility=not supplied in development pilot`；sidecar 存在不能追溯地让旧轨迹变成 wall-aware。
- `F1_center_obstacle`、`F1_twin_obstacle`、`F3_baffled_slosh` 的 policy 含未确认 implicit cap；其余 candidate policy 也不是物理 admission。
- `W05_F6_fine` 没有 material group 和 boundary sidecar，因此不能从它得到 material source、failed mass/source 或 wall/open-face 结论。
- 现有 material group 的 failure 可按初始质量/source 报告，但 artifact 没有完整 support gate/ESS/geometry/reconstruction/wall-crossing reason channel；对 terminal failure 的 support-distance 只能是部分证据。
- 当前 release 没有 destination specification；legacy world-x bins 不能替代 open-face/outlet/destination contract。

## 跨分辨率规则

固定排列置换 negative control：同一 source×destination mass table 换存储顺序后，质量聚合保持不变，而 naive array-index mismatch 为 `4`。因此跨分辨率禁止按 array index matching；当前 release 也没有显式 resolution pair，不能把不同 lineage 当作 convergence。

## 下一步最小真实场景实验（本轮未执行）

建议只选 `W06_standard_slow_center`：复用已有 251 帧、约 0.01 s saved cadence 的 HDF5 和对应 moving-cup sidecar，不重跑 CFD。先冻结 cup/receiver/floor 的 open-face、rim、supporting 和 destination/outlet 语义，再用 32/64 个质量加权 seed × 1/4 个显式积分子步，在 sidecar provider 下做 CPU tracer rollout。

实验输出必须同时保存：`substeps_per_saved_interval`、实际子步 dt、每步 support gate/ESS/geometry/reconstruction、wall crossing、source×destination mass（含 `in_domain_unclassified` 与 `numerical_loss`/explicit exit reason）及 failed mass/source。只比较质量分布和事件统计，不按跨分辨率数组位置对齐；完成后再决定是否值得扩展到第二个 case。

机器可读证据由 `scripts/r4_tracer_actual_scenario_audit.py` 生成。
