# R4 G4 四路线基线：输入可辨识性与训练状态语义审计

状态：**complete_with_findings**；`formal_ready=false`。本报告是独立静态证据，不修改训练器、F6、tracer、core mother case 或上游目录。

## 结论先行

当前源代码在 release manifest 的 linked sidecar 上激活 `115` 维 base+component 输入；LocalInteraction 另加 `8` 维邻域摘要，因此其首层应接 `123` 维。已有 pre-sidecar、sidecar-aware 12-run 矩阵和当前 6-job 小预算复跑的结果/ checkpoint 都记录为 43 维（LocalInteraction 首层 51 维）。所以这 6 次复跑只能作为历史 43-wide contract 下的 LocalInteraction/PhysicsResidual 诊断，不能作为当前 115/123-wide contract 或四路线排名证据。

当前 source 还存在一个独立的 DeepSets 语义差异：训练/one-step validation 的 mean 作用于随机采样的 target features，autonomous rollout 的 mean 作用于全体当前粒子。boundary component block 也按 sidecar 首次出现顺序装槽，F1/F2 同一 component-ID 集合的顺序不同，且 packed fields 不包含 `component_id`。

## 审计边界与数据

- 模式：`static_cpu`；未导入/执行 trainer，未调用 GPU API，checkpoint 仅以 CPU `map_location` 读取 metadata/state-dict shape。
- 当前 source：`experiments/r3_g4_baselines.py`，sha256 `aa6664ec956a4bb0416167a5d6a1fd57da91b5d47bc882047553aaa3eeb56e50`。
- release manifest：`release/v0.1-development/manifest.json`；记录 `13` 个 case，loader 可用 fluid case `12` 个，排除 `W05_F6_fine`。
- sidecar：linked case `12` 个，component count 范围 `1`–`3`；HDF5/sidecar 对齐与 finite 检查：`True`。

## 四路线输入与状态表

| route | 当前完整输入宽度 | route-specific 输入 | 输出/target | rollout state |
|---|---:|---:|---|---|
| `particle_mlp` | 115 | 0 | next solver velocity * dt / dp | bounded output is next velocity; trapezoidal position update |
| `deepset_context` | 115 | 0 | next solver velocity * dt / dp | bounded output is next velocity; trapezoidal position update |
| `local_interaction` | 123 | 8 | next solver velocity * dt / dp | bounded output is next velocity; trapezoidal position update |
| `physics_residual` | 115 | 0 | (next solver velocity - current solver velocity) / dt * dt^2 / dp | bounded output is normalized acceleration; semi-implicit velocity then trapezoidal position update |

base layout 是 `43` 维；linked sidecar 激活 `72` 维（`8×9`）component block。当前 active slices：`{"centered_xyz": [0, 3], "target_velocity_scaled": [3, 6], "context_com_velocity_scaled": [6, 9], "initial_density_pressure_mass": [9, 12], "gravity": [12, 15], "static_physics": [15, 18], "current_prescribed_control": [18, 28], "current_boundary_summary": [28, 35], "boundary_component_block": [35, 107], "family_one_hot": [107, 113], "elapsed_time": [113, 114], "dt": [114, 115]}`。

统一部分的字段与 normalization：centered position、target/current-context COM velocity、initial density/pressure/mass、gravity、static physics、current control、current boundary AABB、family one-hot、elapsed time、current dt；component block 额外含 presence/distance/normal/type/wall velocity。输出 `8*tanh(raw/8)` 在 train/validation/rollout 共用，记录的 hard displacement clip 为 0。

## rollout 与训练状态语义

- HDF5 loader 读取 `valid/type/time/position/velocity/density/pressure/mass`；control 读取 angle、transform 或 prescribed angular velocity；sidecar 读取 time、triangles、type、mk/component。未来 fluid state 不进入 model features；未来 velocity 是 teacher-forced label，未来 position/velocity 在 rollout 中只用于误差计算。
- train/one-step validation 使用 solver 当前帧 velocity；autonomous rollout 从 frame 0 position/velocity 开始，之后只使用自己的 predicted velocity/position、当前 prescribed control、当前 boundary summary 和 elapsed time。
- direct routes 的 label 是 `v[t+1]*dt/dp`；PhysicsResidual 的 label 是 `a[t]*dt²/dp`。因此 train MSE/one-step RMSE 不能横向当作同一个量，跨 route 应只用共同 autonomous position metric。
- seed 初始化已记录 Python/NumPy/Torch/CUDA seed，但没有 deterministic CUDA policy；checkpoint 是 inference snapshot，不是可恢复的 optimizer/RNG training state。

## artifact 记录核对

| collection | jobs | routes | seeds | result width | checkpoint width | current contract compatible | provenance |
|---|---:|---|---|---|---|---|---|
| `pre_sidecar_12_run` | 12 | particle_mlp,deepset_context,local_interaction,physics_residual | 17,29,43 | [43] | [43] | False | False |
| `sidecar_12_run` | 12 | particle_mlp,deepset_context,local_interaction,physics_residual | 17,29,43 | [43] | [43] | False | False |
| `small_six_rerun` | 6 | local_interaction,physics_residual | 17,29,43 | [43] | [43] | False | False |

12-run 矩阵的 route×seed coverage 本身完整，但不等于当前 source contract 完整；6-run 矩阵只覆盖两条 route。small manifest 记录了 seed、command、GPU index、output/checkpoint/log 路径，但没有 config/source/data/contract content hash。

## 6 次小预算复跑：能支持什么

- 每条 LocalInteraction/PhysicsResidual 各有 seeds `17/29/43`，6/6 job 完成，三个共享 test cases 的 rollout 状态和 learned position RMSE/dp 均为 finite。
- 可以看每条 route 的 seed spread，以及在相同小预算、相同 test case、相同 seed 下的成对 exploratory 对比；也可以与同一结果中的 constant-velocity diagnostic 做逐 case 对照。
- 当前小复跑的 route-level test summary：

| route | case macro mean | seed macro sample std | epochs observed |
|---|---:|---:|---|
| `local_interaction` | 43.3271 | 3.7149 | [2, 3] |
| `physics_residual` | 10.4168 | 1.5263 | [3] |

## 6 次小预算复跑：不能支持什么

- 不能给出 ParticleMLP/DeepSets/LocalInteraction/PhysicsResidual 四路线排名：small matrix 没有 ParticleMLP、DeepSets。
- 不能比较当前 sidecar component-aware source：当前 active width 是 115/123，而六个 checkpoint 是 43/51；也不能把旧 43-wide 12-run 与当前 source 混成一张表。
- 不能把 small 与 12-run 解释成训练预算改进：epochs、hidden width、粒子抽样、validation 抽样、early stopping 均不同，且缺少 trainer/config/data content binding。
- 不能横向比较 direct/PhysicsResidual 的 train MSE/one-step RMSE；不能外推到 material transport、density/pressure prediction、free-body coupling、T2/T3/T4、wall-contact validity 或 formal acceptance。

## Findings

1. **`current_sidecar_width_115_vs_recorded_width_43`**（blocker_for_current_contract_comparison）
   - 证据：`{"all_recorded_checkpoint_widths": [43], "all_recorded_result_widths": [43], "artifact_paths": ["experiments/r3_g4_run_manifest.json", "experiments/r3_g4_sidecar_run_manifest.json", "experiments/r3-g4-baseline-routes/run_manifest.json"], "base_width": 43, "component_block_width": 72, "current_source_active_width": 115, "local_current_first_linear_input": 123, "small_local_first_linear_inputs": [51], "source_lines": {"component_block": {"end": 797, "start": 730}, "feature_width_case_call": 1029}}`
   - 影响：The 43-wide results/checkpoints are historical base-contract artifacts and cannot establish behavior of the current linked-sidecar component input.
   - 要求：Freeze one input-contract ID and rerun all four routes against the active 115/123-wide layout before making a current route comparison.

2. **`small_rerun_is_not_a_four_route_matrix`**（scope_limit）
   - 证据：`{"completed_jobs": 6, "expected_jobs": 6, "manifest": "experiments/r3-g4-baseline-routes/run_manifest.json", "missing_routes": ["deepset_context", "particle_mlp"], "seed_set": [17, 29, 43], "small_expected_routes": ["local_interaction", "physics_residual"]}`
   - 影响：The six jobs support only paired diagnostics for LocalInteraction and PhysicsResidual; they do not support a four-route ranking.
   - 要求：If a route comparison is needed, run ParticleMLP and DeepSets under the identical current contract, seed set, budget, and artifact-binding rules.

3. **`deepset_train_rollout_context_cardinality_mismatch`**（semantic_gap）
   - 证据：`{"rollout_context": "rollout passes all current predicted particles to the same mean aggregator", "sample_budgets_observed": {"pre_sidecar_12_run": [{"clip_dp": 0.0, "device": "cuda", "epochs_requested": 8, "hidden": 128, "learning_rate": 0.001, "max_particles": 256, "min_delta": 1e-05, "min_epochs": 3, "patience": 2, "validation_particles": 512}], "sidecar_12_run": [{"clip_dp": 0.0, "device": "cuda", "epochs_requested": 8, "hidden": 128, "learning_rate": 0.001, "max_particles": 256, "min_delta": 1e-05, "min_epochs": 3, "patience": 2, "validation_particles": 512}], "small_six_rerun": [{"clip_dp": 0.0, "device": "cuda", "epochs_requested": 3, "hidden": 32, "learning_rate": 0.001, "max_particles": 64, "min_delta": 1e-05, "min_epochs": 2, "patience": 1, "validation_particles": 96}]}, "source_lines": {"deep_set_class": {"end": 96, "start": 80}, "rollout": {"end": 1012, "start": 920}, "train_particle_sampling": 1045}, "train_context": "DeepSetContext.mean is over sampled target features passed by one_step_loss"}`
   - 影响：DeepSets sees a sample-cardinality-dependent context during training/one-step validation and a full-set context during autonomous rollout.
   - 要求：Either construct the DeepSets context from the same full current context in train/validation/rollout, or explicitly define and record sampled-set semantics as the task contract.

4. **`boundary_component_slots_not_canonical`**（input_identifiability_gap）
   - 证据：`{"component_id_in_packed_fields": false, "observed_orders": {"F1_center_obstacle": [[0, 17], [0, 18]], "F1_dam_break_plain": [[0, 17]], "F1_opposing_columns": [[0, 17]], "F1_twin_obstacle": [[0, 17], [0, 18], [0, 19]], "F3_baffled_slosh": [[0, 17], [0, 18]], "F3_impulse_slosh": [[0, 17]], "F3_transverse_slosh": [[0, 17]], "W06_narrow_fast_center": [[0, 19], [0, 18], [1, 17]], "W06_narrow_slow_center": [[0, 19], [0, 18], [1, 17]], "W06_standard_fast_center": [[0, 19], [0, 18], [1, 17]], "W06_standard_slow_center": [[0, 19], [0, 18], [1, 17]], "W06_wide_slow_center": [[0, 19], [0, 18], [1, 17]]}, "same_id_set_order_varies": true, "source_line_component_order": 331}`
   - 影响：When the current 72-wide component block is enabled, slot 0/1/2 is not a stable semantic component across cases with the same IDs; the packed tensor omits component_id.
   - 要求：Use a schema-defined canonical component-slot order (or an explicit slot/role encoding) before the next component-aware training run.

5. **`run_content_provenance_not_bound`**（reproducibility_gap）
   - 证据：`{"collections": {"pre_sidecar_12_run": {"manifest": {"allowed_gpu_indices": [4, 5, 6, 7], "budget": null, "config_ref": "experiments/r3_g4_config.json", "exists": true, "finished_at_utc": null, "formal_ready": null, "manifest_ref": null, "path": "experiments/r3_g4_run_manifest.json", "provenance_fields_present": ["config"], "routes_declared": null, "scope": "R3-G4 corrected development baseline execution manifest", "seeds_declared": null, "sha256": "61356c3ce11ef54ded5da6a3165de4f47de6e6ab7bf50174bd723cc7b0553a09", "started_at_utc": "2026-09-07T03:24:44.867886+00:00", "status": "complete", "trainer_ref": null}, "provenance": {"checkpoint_fields_present": [], "manifest_fields_present": ["config"], "result_fields_present": [], "source_config_data_content_bound": false}}, "sidecar_12_run": {"manifest": {"allowed_gpu_indices": [4, 5, 6, 7], "budget": null, "config_ref": "experiments/r3_g4_config.json", "exists": true, "finished_at_utc": null, "formal_ready": null, "manifest_ref": null, "path": "experiments/r3_g4_sidecar_run_manifest.json", "provenance_fields_present": ["config"], "routes_declared": null, "scope": "R3-G4 corrected development baseline execution manifest", "seeds_declared": null, "sha256": "c797b88c3dfe0d52d0d0c68c93533c8749b1cd3d389ab2a41e5b3c6e061c5768", "started_at_utc": "2026-09-07T04:10:53.763824+00:00", "status": "complete", "trainer_ref": null}, "provenance": {"checkpoint_fields_present": [], "manifest_fields_present": ["config"], "result_fields_present": [], "source_config_data_content_bound": false}}, "small_six_rerun": {"manifest": {"allowed_gpu_indices": [4, 5], "budget": {"clip_dp": 0.0, "epochs_requested": 3, "hidden": 32, "max_particles": 64, "min_epochs": 2, "patience": 1, "validation_particles": 96}, "config_ref": null, "exists": true, "finished_at_utc": "2026-09-07T08:35:54.285700+00:00", "formal_ready": false, "manifest_ref": "release/v0.1-development/manifest.json", "path": "experiments/r3-g4-baseline-routes/run_manifest.json", "provenance_fields_present": ["trainer", "manifest"], "routes_declared": ["local_interaction", "physics_residual"], "scope": "R3-G4 independent candidate-only baseline routes", "seeds_declared": [17, 29, 43], "sha256": "f71cd95117e83aa977bb43fbfb5fba1021bd02edb298523a9504e09d9026e4f4", "started_at_utc": "2026-09-07T08:34:14.877311+00:00", "status": "complete", "trainer_ref": "experiments/r3_g4_baselines.py"}, "provenance": {"checkpoint_fields_present": [], "manifest_fields_present": ["trainer", "manifest"], "result_fields_present": [], "source_config_data_content_bound": false}}}, "config": {"budget": {"epochs_requested": 8, "hidden_width": 128, "learning_rate": 0.001, "maximum_particles_per_training_frame": 256, "min_delta": 1e-05, "min_epochs": 3, "patience": 2, "position_clip_dp": 0.0, "validation_particles": 512}, "exists": true, "path": "experiments/r3_g4_config.json", "provenance_fields_missing": ["trainer_sha256", "data_manifest_sha256", "input_contract_id"], "routes": ["particle_mlp", "deepset_context", "local_interaction", "physics_residual"], "schema_version": 1, "seeds": [17, 29, 43], "semantic_fields_missing": ["input_contract_id", "feature_layout", "normalization_contract_id", "target_semantics", "rollout_state_semantics", "trainer_sha256", "data_manifest_sha256", "checkpoint_schema", "determinism_policy"], "sha256": "7748d7a317a093d3a74ba93fd9c50f672804dcf459b65b55c33780dd0366cda3", "smooth_output_cap": {"applied_in": ["train", "validation", "rollout"], "function": "8*tanh(raw/8)", "normalized_units": 8.0}}}`
   - 影响：Seeds, commands, and paths are recorded, but the result/checkpoint artifacts are not cryptographically bound to the exact trainer source, config, release manifest, data, or input-normalization contract. The six-run manifest has no config reference.
   - 要求：Record source/config/data/contract hashes in both result and checkpoint metadata; add a config reference and digest to the six-job manifest as well.

6. **`checkpoint_is_inference_snapshot_not_training_state`**（training_state_gap）
   - 证据：`{"checkpoint_payload_keys": {"pre_sidecar_12_run": ["feature_width", "route", "seed", "state_dict"], "sidecar_12_run": ["feature_width", "route", "seed", "state_dict"], "small_six_rerun": ["feature_width", "route", "seed", "state_dict"]}, "checkpoint_save_line": 1113, "optimizer_state_saved_in_source": false, "rng_state_saved_in_source": false}`
   - 影响：A checkpoint can identify route, seed, and feature width, but it cannot resume the optimizer/RNG/early-stopping state or prove the state was selected under a particular config.
   - 要求：Declare inference-only versus resumable checkpoints; for the latter save optimizer, scheduler, RNG, epoch, best metric, and contract/config IDs.

7. **`route_training_targets_are_not_the_same_quantity`**（metric_scope_limit）
   - 证据：`{"common_autonomous_metric": "vector position RMSE / dp", "direct_target_line": 854, "physics_target_line": 851, "route_targets": {"deepset_context": "v[t+1] * dt / dp", "local_interaction": "v[t+1] * dt / dp", "particle_mlp": "v[t+1] * dt / dp", "physics_residual": "a[t] * dt^2 / dp"}}`
   - 影响：Train MSE and one-step RMSE are not cross-route comparable because PhysicsResidual predicts a normalized acceleration residual while the other routes predict next velocity.
   - 要求：Keep target-specific losses separate and compare routes only on a common autonomous evaluation metric under one exact input/state contract.

8. **`seed_reproducibility_not_closed`**（reproducibility_gap）
   - 证据：`{"deterministic_cuda_controls_present": false, "seed_calls_present": true, "small_devices_recorded": ["4", "5"], "small_seed_set": [17, 29, 43]}`
   - 影响：The three seeds are initialized and recorded, but CUDA deterministic-algorithm policy and RNG snapshots are absent; exact rerun identity is therefore not closed.
   - 要求：Add a deterministic policy (or explicitly record nondeterministic status) and capture Python/NumPy/Torch RNG state when reproducibility is required.

## 下一轮统一控制输入和训练状态语义：最小改动清单

1. **`contract_id_and_content_hashes`**：Add one immutable input_contract_id containing active feature slices, normalization, target mode, rollout state, sidecar slot schema, and output-cap/clip semantics; bind trainer/config/release-data hashes in run/result/checkpoint records.
   - 最小性：One ID plus five hashes closes the current 43-versus-115 ambiguity without changing F6, tracer, or upstream inputs.

2. **`canonical_component_slots`**：Canonicalize boundary-component slots before packing the 72-wide block (schema role/order or stable ID encoding) and record the observed slot map.
   - 最小性：The current component tensor otherwise has target-relative values but no stable component identity.

3. **`single_current_context_builder`**：Make DeepSets train/validation/rollout consume the same declared current context cardinality, preferably full current context; retain target subsampling only for loss rows.
   - 最小性：This removes the only route-specific train-to-rollout context-cardinality mismatch identified statically.

4. **`explicit_target_and_checkpoint_state`**：Record route target_mode (`next_velocity` versus `acceleration_residual`) and mark checkpoints inference-only or save optimizer/RNG/epoch/best-metric state for resume.
   - 最小性：It prevents target losses and inference snapshots from being mistaken for common training-state evidence.

5. **`uniform_four_route_rerun`**：For the next comparison, rerun all four routes on the same current contract, seeds 17/29/43, budget, test cases, deterministic policy, and CPU-verifiable provenance; do not mix the 43-wide artifacts into the 115-wide result table.
   - 最小性：Only this closes route coverage and controls the remaining matrix confounds.

## Check summary

| check | value |
|---|---|
| `static_cpu_mode` | `True` |
| `trainer_source_exists_and_parses` | `True` |
| `four_route_classes_and_dispatch_found` | `True` |
| `required_source_reads_identified` | `True` |
| `release_hdf5_contract_inspected` | `True` |
| `release_sidecar_alignment_inspected` | `True` |
| `current_sidecar_component_path_is_active` | `True` |
| `config_declares_four_routes_and_three_seeds` | `True` |
| `12_run_manifests_link_declared_config` | `True` |
| `small_manifest_links_declared_config` | `False` |
| `small_six_matrix_complete` | `True` |
| `small_six_has_all_four_routes` | `False` |
| `recorded_width_matches_current_source` | `False` |
| `recorded_checkpoint_width_matches_current_source` | `False` |
| `deep_set_train_context_matches_rollout_context` | `False` |
| `component_slots_are_canonical` | `False` |
| `source_config_data_content_bound` | `False` |
| `checkpoint_contains_resumable_training_state` | `False` |
| `cuda_determinism_policy_closed` | `False` |

本审计只新增本脚本、对应 JSON/Markdown 和 `test_r4_g4_` 测试；不提交、不推送。
