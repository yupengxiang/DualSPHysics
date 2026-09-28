# F3 material T2 coarse proposal（2026-09-28）

本文件只描述 `CORE-F3-MATERIAL-COARSE-s2` 的 fresh source-bound proposal，不是授权、排队记录、执行 receipt，也不是 T2 结果。状态固定为：

- `proposal_only=true`
- `diagnostic_only=true`
- `formal=false`
- `formal_eligible=false`
- `qualification_claim=none`
- `qualification_credit=0`、`T2_credit=0`
- `T2_macro=false`、`T2_path=false`
- `launch_admitted=false`

## 精确绑定

| 对象 | 路径 | SHA-256 |
|---|---|---|
| 当前 material module | `scripts/core_material.py` | `9e294e64c431c725717caf86eb001dc3a3505a312e279386796b6a472b5ee94e` |
| coarse native source（只做字节 hash） | `campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5` | `3d178d8c5e6ee4057a10a384c9289df5723bcabbfe58850803cf54996c4a9575` |
| candidate job spec | `campaigns/core-v1/material/jobs/core-f3-material-coarse-s2.json` | `1f1080e497feab414863e3e02dd31dbec91c0d09e4ef9ac855e0cdbbda070628` |
| source audit manifest | `campaigns/l1-resume/continuation/R0081818-NOMINAL-AUDIT.json` | `eff6e351eaeb6ec270a2ec9883a15d0fbea1c04bd57c213e94db4cd0c90d6c11` |
| source preparation manifest | `campaigns/l1-resume/continuation/R0081818-NOMINAL-PREPARED.json` | `043febcc4e2deb9c515ed32fe99b8ed7241c68fa8dbf72b9ad8d1f7e5ef6684f` |
| F3 revision/source manifest | `diagnostics/f3-audit/F3-075-REF0081818-MANIFEST.json` | `0d4cbd7d22daaff864bccb82e57348631e0a057a3465490a6bbc19e67c0aa078` |
| frozen material runtime spec | `campaigns/core-v1/material/evidence/f3-qualification-diagnostic-runtime-spec-2026-09-19.json` | `06c2d549d971d679f48b0d46480a7decc64d1ab58a3e35ece8cb5a61a04a1aa9` |
| queue registration | `campaigns/core-v1/material/evidence/diagnostic-queue-registration.json` | `71ce17d5421d27dde2f849f7d1b3a226bfa0e6b275440f10f45eb0ec9a9da2cc` |

source manifest 只证明 coarse reference 的 metadata：`R0081818-NOMINAL`、836 个 native saved frames、索引 `0..835`、时间 `0..8.350015121408111 s`。proposal 没有打开 HDF5、没有读取 material trace、没有生成 trace 或 metric。

## 规范化入口

工作目录必须精确为：

`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab`

唯一允许的 child argv 是：

```text
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python -m scripts.core_material --source /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5 --output {attempt_dir}/material.h5 --seeds 512 --substeps 2 --neighbour-variant baseline24
```

同一 attempt 的恢复只能在上述 argv 末尾追加 `--resume`。不得使用 `python scripts/core_material.py ...` 或绝对 raw script path。当前绑定的历史 job spec 哈希正确，但其 argv 仍是 raw script path，因此不能直接复用；proposal 只记录该事实，不修改历史 job spec。

runtime spec 的 `implementation_binding.core_material_sha256` 仍为旧值 `1880c02a50168ae3325c39993a55103a1ebba06adcc48a486b7f6f4825d94b7e`，与当前代码不一致。root/scheduler 在任何未来运行前必须重新绑定当前代码，不能把 `ready_for_root_queue` 解读为授权。

## frozen-worker、资源和 attempt contract

未来若获得新授权，只能由 scheduler-owned `core_runtime` frozen-worker 处理：先建立代码 snapshot，再在新 attempt namespace 中启动 module entry。当前 proposal 没有调用 `core_runtime`、没有 submit/worker/queue 操作，也没有创建 attempt 目录。

候选资源请求为 CPU-only：2 CPU cores、4096 MiB RAM、`gpu_peak_mib=0`、`io_weight=0.1`。在任何执行前必须取得新鲜、可审计的 host-I/O admission snapshot，至少包含 `cpu_count`、`load1`、`ram_total_mib`、`ram_available_mib`、`disk_free_bytes`、`io_capacity`，并满足 scheduler 的 CPU、RAM、I/O capacity 和磁盘条件。GPU 显存余量不能替代 host-I/O admission；本 proposal 没有采集该 snapshot。

新 namespace 模板为：

```text
campaigns/core-v1/runtime/attempts/core-f3-material-coarse-s2/<fresh-attempt-id>
```

`<fresh-attempt-id>` 必须由 scheduler 新建，不能复用历史 attempt。若 worker 中断，只能在同一 namespace 用原子 checkpoint `--resume`，不能改 scientific configuration 或另起 attempt 伪造连续性。

## 836-frame、checkpoint、resume 和 metrics

proposal 要求完整 native window：`native_frame_count=836`、最终 `committed_frame=835`，不得使用 `--stop-after`。checkpoint schema 为 `core.material.checkpoint.v1`，字段必须完整为：

```text
position, reliable, first_passage, return_time, residence,
residence_left, residence_right, returned
```

输出必须包含：

```text
material.h5
material.json
material.h5.checkpoint.npz
material.h5.checkpoint.json
```

`material.json` 必须留下完整 receipt 和 material metrics：精确 argv、source/code/dependency hashes、`committed_frame`、`native_frame_count`、wall/CPU/RSS、source-group closure、unknown mass、first-failure frame/time、first-passage/return CDF bounds、left/right/opposite residence、right-censored mass 和 common reliable coverage。固定阈值为每 source `unknown_fraction_max <= 0.01`、`mass_closure_error <= 1e-12`；这些是未来结果的检查条件，不是本 proposal 的实测结果。

## 明确禁止项与当前阻塞

禁止：

- raw script-path 入口；
- 任何 GPU/CUDA override、非空 `CUDA_VISIBLE_DEVICES` 或 `gpu_peak_mib>0`；
- `--stop-after`、`--kill-after` 等 partial/test hook；
- `row30`、`--retry-row30`、`--force-retry`、`f3-material-30-canonical-s4-r003` 等 row30 retry 语义；
- 启动 `core_runtime` job、CPU material worker、GPU、solver、native、GenCase 或 queue；
- 读取/生成 material trace；
- 修改 registry、completion、ledger、denominator、gate 或 `PLAN.md`；
- 从该 proposal 推导任何 T2 credit。

当前 fail-closed blockers：

1. 没有 fresh root/scheduler authorization；
2. 没有 measured host-I/O admission；
3. source preparation manifest 明确 `launch_allowed=false`；
4. 历史 job spec 使用了禁止的 raw script path，需规范化 module argv；
5. runtime spec 的旧 core material hash 未绑定当前代码。

机器可读版本见 [F3-MATERIAL-COARSE-PROPOSAL-2026-09-28.json](F3-MATERIAL-COARSE-PROPOSAL-2026-09-28.json)。
