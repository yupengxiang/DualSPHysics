# F4 tallwall120 材料可靠性根因审计（2026-09-21）

本审计只读复用既有 frame-70 negative preflight 的 trace，在首次 reliability loss 的 native transition `frame 40 -> 41` 读取两个原生 source frame。它没有重算旧 trace，没有修改 solver/GPU/queue、registry、ledger、阈值、CDF 或事件门。

## 根因证据

首次失效 cohort 为 128 个 seed：125 个在第一个 RK2 子步失效，3 个在第二个 RK2 子步失效。两组的唯一失败组件都是下一 support field（`g1`）的 `reconstruction_error` gate：

| 指标 | frame 40→41 cohort 观测 | 固定 gate |
|---|---:|---:|
| g1 reconstruction error（全部 128） | p50 `0.1806703396` m/s，p95 `0.3014220162`，max `0.3062661856` | ≤ `0.04698137929` m/s |
| ESS | min `12.8653` | ≥ `4` |
| geometry rank | 全部 `3` | ≥ `3` |
| anisotropy | min `0.61659` | ≥ `0.005` |
| support distance | max `0.0050541` m | ≤ `0.03` m |
| selected visible neighbours | 全部 `24` | k=`24` |
| wall blocked / nonfinite velocity | `0 / 0` | 必须为 `0` |

baseline24 的 replay 与已提交 trace **exact match=true**。因此当前阻塞由 local reconstruction residual 的 field1 峰值主导；审计没有发现 wall visibility、neighbor 数量不足、ESS、rank、anisotropy 或 support-distance 触发。该结论定位了可靠性根因窗口，不把它解释成物理事件门结论。

## 候选 contract

审计固定记录两个已经登记的候选，均保持原 gate 和 unknown 分母不变：

| candidate | 改动 | frame 40→41 一步结果 | 结论 |
|---|---|---:|---|
| `f4_ess32_v2` | visible Shepard k=32，仍用 local residual | 首失效 cohort survivor `0/128`；整体 reliable `385` | 不能解决该首失效 cohort，仅 proposal |
| `f4_affine_bound_v2` | k=24，增加 conservative local affine query-bias | 首失效 cohort survivor `0/128`；整体 reliable `384` | 更严格，不能作为修复结论，仅 proposal |

这两个结果是一个 transition 的 counterfactual support audit，不是 trajectory canary，也没有 qualification credit。后续若要执行 candidate，必须使用新的 output stem 和完整 bounded source window；unknown 上限仍为 `0.01`，right-censor、CDF、事件定义和 scientific denominator 必须原样保留。

## 交付与验证

根因 audit receipt：

```text
campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-root-cause-audit-20260921.json
SHA256 a4fa8e9283b4588f8ff25ace474ef57705191ba27c84a5ec9fbceefca935d0e6
```

候选 contract receipt：

```text
campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-candidate-contract-20260921.json
SHA256 566d39c8c32f42859d7f2b1b93ef087dbf6e01d1666bead10d740d9ca2709d6d
```

实现脚本 `scripts/f4_tallwall120_root_cause_audit_v1.py` 的 SHA256 为 `4d0e9635d256c9931f29d8ee4909721c10fe67e5a91f124affc632cdf9692427`；测试 `tests/test_f4_tallwall120_root_cause_audit_v1.py` 的 SHA256 为 `7c8b51756ad80c6e73afe8dd4d9adb30739b4f29fe5e481124fe31114050742b`。合并测试：`7 passed`。

资格状态保持 `T2_macro=false`、`T2_path=false`、`qualification_credit=none`；Core gate 不变。执行约束 receipt 记录了 `existing_trace_modified=false`、`solver_started=false`、`gpu_started=false`、`queue_mutation=0`、`registry_mutation=0`、`central_ledger_mutation=0`、`scientific_denominator_changed=false`。
