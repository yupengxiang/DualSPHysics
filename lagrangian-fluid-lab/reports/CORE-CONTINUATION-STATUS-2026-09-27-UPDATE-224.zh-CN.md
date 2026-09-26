# UPDATE-224：F4 supportcap v5 一次性 CPU/native 预检

日期：2026-09-27（Asia/Shanghai）

## 结果

按用户授权，仅执行一次固定 F4 v5 CPU/native input-and-environment preflight：

```text
.venv/bin/python scripts/f4_supportcap_affine_shepard_blend_preflight_v1.py run
```

机器回执状态为 `preflight_passed_runtime_not_authorized`；resource blockers 为空，failure 为 null。预检已消费 one-shot，retry policy 为 `same_scope_retry_allowed=false`。资源快照：128 个 process-visible CPU，1/5/15 分钟 load `127.20458984375/128.640625/132.373046875`；可用 RAM `226,617,241,600` bytes（门槛 16 GiB），可用磁盘 `8,161,168,670,720` bytes（门槛 8 GiB），无活跃 material worker。CPU thread limits 均为 1、`CUDA_VISIBLE_DEVICES` 为空。环境为 Python 3.10.12、NumPy 2.2.6、SciPy 1.15.3、h5py 3.16.0。

只读核验的源文件为 F4 已具 T1 数值资格的 trajectory，大小 `10,326,356,548` bytes，SHA-256 `91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e`；文件在 hash 匹配后以只读方式打开。必需 dataset/shape 通过，row 0–41 共 42 个时间戳严格递增，范围 `0.0–0.1640080936314531 s`。

## 授权边界与产物

已落盘 [preflight receipt](../campaigns/core-v1/material/candidates/f4-supportcap-affine-shepard-blend-v5/cpu-native-preflight-v1/preflight-receipt.json)（SHA-256 `2dd0df933ad609b22f280c8925e5174ea3149d5bf801dc63a8c65e42a66f891f`）和 [one-shot lock](../campaigns/core-v1/material/candidates/f4-supportcap-affine-shepard-blend-v5/cpu-native-preflight-v1/one-shot-lock.json)（SHA-256 `dbcb74d8deef67770f4d280ee35db496756bba2c0492c9b379fb9a9bb7e77ecc`）；私有 owner-only marker 位于 `/home/jade/.local/f4_supportcap_affine_shepard_blend_v5_cpu_native_preflight_v1.consumed.json`。fresh canary output namespace 仍不存在，不得创建或重试。

回执明确记录 `native_particle_frames_loaded=false`、`candidate_executed=false`、`canary_started=false`、`tracer_started=false`、`solver_started=false`、`gpu_initialized=false`、`worker_or_queue_started=false`、`T2_started=false`；registry/ledger mutation 为 0，qualification credit 为 0。该结果只证明授权范围内的静态闭包、环境与输入元数据预检通过；不授权运行 predictor/CPU canary、tracer、solver、GPU、worker、queue 或 T2。

定向安全 suite `tests/test_f4_supportcap_affine_shepard_blend_preflight_v1.py`：**14 passed**；脚本和测试 `py_compile`、`git diff --check` 通过。没有改动 scope、registry、ledger、分母或资格状态。
