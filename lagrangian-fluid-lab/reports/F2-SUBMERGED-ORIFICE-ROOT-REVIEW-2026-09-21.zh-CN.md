# F2 submerged-orifice transfer：root review 与单 anchor CPU/native preflight

日期：2026-09-21  
范围：`F2_submerged_orifice_transfer_v1`，仅 root review、一个 fresh Definition、CPU GenCase 和 native BI4 decode。  
anchor：矩阵第 4 行，`q=0.5`、`dp=0.0075 m`、`orifice_height=0.18 m`、`F2_ORIFICE_q0p50_dp0075_spatial`。

## Root review 结论

独立 adapter 重新调用 `verify_bundle()`，并重新核对 candidate card、15-row fixed matrix、failure denominator、lineage、review contract、scope adapter 和 preflight adapter 的 SHA。矩阵保留 15 行且全部 `not_started`；denominator planned 为 15、credit 为 0；lineage `source_reuse=false`；旧失败证据绑定 4 条。此次新 Definition 没有复用任何旧 Definition、generated source、BI4 或 trajectory。

root review 决策为 `approved_for_one_anchor_cpu_native_preflight`。权限只包括 CPU GenCase 和 native decode；solver、GPU、job spec、queue、ledger、registry 和 matrix submission 全部关闭。`qualification_claim=none`、T1/numerator/matrix credit 均为 0。

root-review JSON：

`campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/root-review-cpu-preflight-v1.json`

SHA-256：`df130049034494078a2fc780ac90d6afb19052ac34391b42d71f4be153391a9e`

## Fresh CPU/native 结果

GenCase 返回 code 0，生成 495,396 个粒子（boundary 264,228、fluid 231,168），native decode 的 ID 唯一、数组有限、XML/native fluid ID 对齐；原生质量相对误差为 0.78125%，外壁端点和 gate 穿透均为 0。

硬拒绝条件是法向完整性：`BoundNor.bin` 对 264,228 个 boundary 粒子中有 63,161 个零法向（23.9%）。GenCase log 同样报告 `Final zero normals: 63,161/264,228` 和 boundary particles without normal data。因此该 anchor 的 `preflight_pass=false`，不能进入 solver 或任何资格判断。没有重跑相同输入，也没有放宽 hard audit。

preflight JSON：

`campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/anchor-q0p5-dp0p0075/preflight.json`

SHA-256：`a29673207eba9cf2d3e62ad3693a0224b749e3cdfc95a9c50eb5733d375837dc`

fresh Definition SHA-256：`6770d2350e589fa84d18eaeb7a7abe7165e7468bf18dbc3e1e271f30be770dbd`  
GenCase log SHA-256：`8629193a20c689daf044d63a180ff7f24eb642538c575ac419322e2c2bdb95e5`  
generated XML SHA-256：`ffc1463d3aa6dbe9d853b9783cad4ff4c8ca287b196f3e41b42df52c82c65b6b`  
native BI4 SHA-256：`fcfc0769aca5f42e73e0e815ada704e1d81430c0cdbfca876a09f3527f613546`  
native decoder SHA-256：`b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e`

## Core gate 影响

这是新的输入闭合证据，但属于 hard preflight failure：不产生 T1、qualification、numerator 或 matrix credit；Core gate 不改变。failure denominator 仍保留 15 行，当前候选不能授权 solver。后续若要修复法向，必须提出新的版本化几何/normal contract 并重新 root review，不能在本 anchor 上重试。

## 测试与执行边界

通过：

```text
.venv/bin/python scripts/f2_submerged_orifice_preflight_v1.py verify-root-review
.venv/bin/python -m pytest -q tests/test_f2_submerged_orifice_scope_v1.py tests/test_f2_submerged_orifice_preflight_v1.py
```

本次执行过的二进制只有 CPU `GenCase_linux64` 和 native `bi4_dump`。未启动 solver、CUDA/GPU、queue、job、ledger 或 registry；没有运行 GenCase 之外的作业提交路径。
