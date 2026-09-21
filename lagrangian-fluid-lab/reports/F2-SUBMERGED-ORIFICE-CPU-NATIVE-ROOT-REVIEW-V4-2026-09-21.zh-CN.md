# F2 submerged-orifice：v4 CPU/native authorization 与 hard preflight

日期：2026-09-21  
范围：只授权一个全新 case 的 CPU GenCase + native BI4 decode；solver、GPU、job、queue、ledger、registry 和 matrix submission 均保持关闭。

## v4 authorization

授权 case 为 `F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2`，matrix index 为 `4`，`q=0.5`、`dp=0.0075 m`。v4 receipt 的 decision 为 `approved_for_exactly_one_fresh_cpu_native_preflight`，`qualification_claim=none`、`matrix_credit=0`，父 15 行 denominator 仍为 `planned=15, executed=0, passed=0, failed=0, unattempted=15`。

Receipt：[`root-review-receipt-v4.json`](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/root-review-receipt-v4.json)  
SHA-256：`dbec4516a16ccea184ff96ff240518891c298e6381becfeae484c19bcc4cd3cf`

Receipt 明确 `cpu_gencase=true`、`native_decode=true`；`solver_launch/gpu_launch/job_spec_creation/matrix_submission=false`，queue/ledger/registry mutation 全部为 `0`。它 hash-bind 了 fresh Definition、v3 static receipt、v3 proposal-only contract、v4 runner、GenCase binary 和 native decoder。

静态 contract：[`preflight-contract-v4.json`](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/preflight-contract-v4.json)  
SHA-256：`ebeecd9eea44e8a376161a8c0d3e03522b51ec7504e819ce5e7343c3bc963e99`

新的运行输出 prefix 是：

`campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/preflight-v4/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2`

它与旧失败 anchor、旧 Definition、旧 BI4 和旧 preflight receipt 分离。

## runner and tests

- [`f2_submerged_orifice_root_review_v4.py`](../scripts/f2_submerged_orifice_root_review_v4.py)：`e37810d54306c0814416b05e37b3a58087f63bd809576cc694dc3db3f6cae365`
- [`f2_submerged_orifice_preflight_v4.py`](../scripts/f2_submerged_orifice_preflight_v4.py)：`d5991953cd863c5a6bcaf71c91a20121d6e1d8e676dc5c6f398393f718512cab`
- [`test_f2_submerged_orifice_root_review_v4.py`](../tests/test_f2_submerged_orifice_root_review_v4.py)：`d67a053ee089dad1bc8f2a34f16e6534eca67006038b75d8bdf758322b775e11`
- [`test_f2_submerged_orifice_preflight_v4.py`](../tests/test_f2_submerged_orifice_preflight_v4.py)：`fcda0157e1e66dc181097f00f812cdb6968c1166c9b7d1688a883cb6ff262e90`

在 runtime output 尚未 materialize 时，v4 定向回归为 **10 passed**；两个 adapter 的 `py_compile` 与 receipt/contract CLI verify 也通过。runner 的静态 `write-contract` 不会调用 GenCase 或 native decoder；执行必须显式调用 `run-preflight`。

## CPU/native result

共享工作区随后出现了唯一 v4 output，表明 root 已显式运行该授权步骤。本报告没有把它解释为 solver 或资格执行。

Preflight：[`preflight.json`](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/preflight-v4/preflight.json)  
SHA-256：`a6f89c4c91dbf6debcc955a3a54362e5fe0f9dd48aea9ea62c0f802f3c993bd3`

结果为 `cpu_native_preflight_failed_hard_audit`、`preflight_pass=false`：

- GenCase/native decode 完成；496,104 total、255,906 boundary、240,198 fluid。
- native IDs 唯一且与 generated XML 对齐；positions/velocities/density/BoundNor/NormalSize 全部 finite。
- outer endpoint 为 `0`，gate endpoint penetration 为 `0`。
- `BoundNor` 零法向为 `64,899`，派生 `NormalSize` 零值同为 `64,899`，违反 exact-zero hard gate。
- discrete/native mass 相对误差为 `+4.718017578125%`，超过 `2.5%` gate。
- `qualification_claim=none`、`matrix_credit=0`；没有 solver trajectory、event result、T1 credit 或 matrix credit。
- execution controls 记录 solver/GPU/job 未调用，queue/ledger/registry mutation 为 `0`，matrix submission 为 `false`。

因此当前 blocker 是新 Definition 的 BoundNor/NormalSize 完整性与质量 gate；不能重试同一输入、放宽 hard gate、进入 solver 或改写 matrix/ledger/registry。
