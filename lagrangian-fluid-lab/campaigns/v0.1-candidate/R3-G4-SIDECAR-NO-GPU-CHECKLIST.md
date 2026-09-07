# R3 G4 sidecar-aware baseline：无 GPU 验证清单

本清单对应将边界 triangle sidecar 接入 G4 baseline 的一次新运行。它只
验证输入契约、路径、报告和小规模 CPU 行为；不把 CPU 检查误当成物理
验收，也不替代之后的 4 GPU × 12 runs 矩阵。

## 当前只读审计结果

- release manifest 有 13 个 case；其中 12 个 F1/F2/F3 case 通过
  `geometry.boundary_sidecar` 链接 sidecar，`W05_F6_fine` 没有 sidecar，且
  该 case 没有 fluid type-3 状态，应继续从 G4 learned route 排除。
- 12 个已链接 sidecar 均满足：`case_id` 与 manifest 一致，
  `coordinate_frame=world`，`triangles_world` 形状为 `[T,N,3,3]`，时间轴与
  对应 solver HDF5 **逐元素相等**，三角形坐标有限且非退化，
  `triangle_type` 仅包含 0/1。当前审计数量为 12/12。
- 当前旧 G4 artifact 是在 sidecar 接入前产生的，故其 12 个 test rollout
  的 `boundary_available=false` 是预期的；不能将旧结果重新聚合后当作
  sidecar-aware 结果。

## 实现完成后、占 GPU 前的 CPU 检查

### 1. loader 与几何输入

- `load_cases(release/v0.1-development/manifest.json)` 返回 12 个 fluid
  case，不返回 F6 body-only case。
- 对每个有 sidecar 链接的 record，loader 必须解析
  `release_root / geometry.boundary_sidecar`，并校验 sidecar 的 case id、
  world 坐标、时间轴、形状、有限性、非退化性和 0/1 类型；链接存在但
  无效时应报 input-contract error，不能静默退回全零边界。
- sidecar 只应给当前 solver frame 的边界摘要。对动态 W06 case，至少
  检查 frame-0 与后续 frame 的 AABB 摘要可随控制变换变化；训练/rollout
  不能读取未来 fluid state 或未来自由刚体状态。
- 无 sidecar 的 tiny/synthetic case 仍应保留旧的全零摘要和
  `boundary_available=false` fallback，保证缺失性是显式的。
- `build_features` 在 frame 0 和最后一个可预测 frame 上应输出固定宽度、
  全部有限的 tensor；如仍使用当前 7 个边界摘要量，`feature_width()` 应
  仍为 43。若实现改变宽度，必须同步测试、checkpoint 和报告契约。

### 2. G4 output contract

对每个 test rollout，至少检查以下字段存在且来源一致：

- `boundary_source`：sidecar-aware case 应明确标记 world triangle summary
  的来源，而不是 `missing_boundary_sidecar`；
- `boundary_available=true`：只对真实验证过的 sidecar；
- `control_source`、`mass_identity_preserved`、`status` 以及已有 RMSE/ADE/FDE
  字段仍保持旧口径。

`r3_g4_aggregate.py` 应把这些字段原样提升到每个 case 的
`boundary_sources` / `boundary_available`，并据此计算
`boundary_geometry_gate`。这个 gate 只针对实际被聚合的 3 个 test cases，
不应因为未进入 learned route 的 F6 而错误失败；但 `formal_ready` 仍必须
保持 `false`，因为当前实验只有 T1、没有 material destination/wall
visibility/T3/T4 和 coupled F6 route。

### 3. runner、manifest 与 artifact provenance

- `r3_g4_run.py::task_list()` 应产生恰好 12 个唯一的
  `(route, seed)` 组合（4 routes × seeds 17/29/43），且只使用物理 GPU
  index 4/5/6/7；index 0–3 不得出现在运行 manifest。
- 新实验必须使用全新的 results/logs/checkpoints/run-manifest 目录，不能
  覆盖旧的 `experiments/r3_g4_results`。runner 当前将 artifact 路径写成
  相对于 `lagrangian-fluid-lab` 的路径，因此这些目录应位于 lab 根目录内。
- aggregate 必须只读取 run manifest 点名的 JSON，并检查 route/seed、结果
  目录、完成状态、物理 GPU index/UUID 映射；旧目录里残留的 JSON 不能被
  扫入新报告。
- 无 GPU 的 runner 检查只调用 `task_list` 和 mock 的 `launch`/
  `subprocess.run`；不得直接执行 `r3_g4_run.py` 主流程或触碰保留 GPU。

## 建议的 CPU 命令与断言

在实现 agent 提交后，先运行：

```bash
lagrangian-fluid-lab/.venv/bin/pytest -q \
  lagrangian-fluid-lab/tests/test_r3_g4_baselines.py \
  lagrangian-fluid-lab/tests/test_r3_g4_aggregate.py \
  lagrangian-fluid-lab/tests/test_r3_g4_run.py
```

随后用一个只读 Python probe 检查 12 个 sidecar 与 13 个 release case 的
数量、时间轴和 `load_cases` 结果，并在 CPU 上对每条 route 做至少一次
`build_features`/单步 `rollout` finite check。这个 probe 不应写入
`experiments/r3_g4_results` 或 release 文件。

## GPU 矩阵后的报告 gate

新 run manifest 聚合后应满足：

```text
run_count = 12
route_seed_gate = true
physical_gpu_gate = true
artifact_provenance_gate = true
boundary_geometry_gate = true
nonfinite_rollout_gate = true
formal_ready = false
```

`boundary_geometry_gate=true` 只表示 3 个 G4 test case 的当前边界摘要已
进入输入并通过 provenance；它不表示 triangle sidecar 已用于碰撞修正，
也不表示 T2 material transport 已完成。结论文件应明确写出这一点，并
移除旧的“W11 没有 sidecar”措辞；仍保留 T2/T3/T4 和 F6 的真实 blocker。
