# M3 七族 / 336 例范围目录（元数据限定）

本目录只整理 2026-10-10 stage2 收尾包中的 JSON/Markdown 证明。构建器没有打开 HDF5、BI4、JSONL、XMF、CSV 或 solver-output；这些路径只作为元数据指针保留。历史 78 扫描和 117 native join 的数字来自已有 proof JSON，不是本次新扫描。

## 计数与边界

- 336 例，7 族，每族 48 例。
- 335 例有实际 saved-mask/lifecycle 证明；1 例历史别名保持 UNKNOWN。
- 78 例有进一步字段扫描证明；ROOT434 仍记录 256 例未扫描。
- 原 118 例遗漏范围中 117 例有 per-fluid-ID native-cause / typed-saved-frame join；这不是合法通量、物理去向或动力学证明。
- 独立的 field335 metadata preflight 为 334 PASS、1 BLOCKED；缺失引用是 `F2H10V2_OFFSET_V1`。
- 当前所有家族 QI/QN/QE 为 UNKNOWN，目录不授予科学资格或 split-safe 状态。

## 七族范围

| 族 | 机制 | 例数 | mask | 字段扫描 | native join | 任务范围 | 资格 |
|---|---|---:|---:|---:|---:|---|---|
| F1 | eccentric lower-head / gravity release around a finite obstacle | 48 | 48 | 13 | 0 | initial fluid cohort mass/COM; obstacle interaction; open-top outflow and return diagnostics | UNKNOWN/UNKNOWN/UNKNOWN |
| F2 | prescribed rotating offset cup with receiver/aperture transport | 48 | 47 | 11 | 47 | receiver-volume first passage; finite aperture downward crossing; residence and gross/net flux with censoring | UNKNOWN/UNKNOWN/UNKNOWN |
| F3 | two-axis prescribed acceleration and sloshing response | 48 | 48 | 11 | 0 | initial fluid cohort; forced COM/front response; time-windowed acceleration response | UNKNOWN/UNKNOWN/UNKNOWN |
| F4 | finite drop impact into a finite pool | 48 | 48 | 11 | 22 | drop/pool source cohorts; first contact and rebound censoring; mass-weighted front and COM | UNKNOWN/UNKNOWN/UNKNOWN |
| F5 | compact runup with prescribed forcing and recovery window | 48 | 48 | 11 | 0 | runup/front measurement; mass distribution; recovery and tail censoring | UNKNOWN/UNKNOWN/UNKNOWN |
| F6 | free six-degree-of-freedom rigid release with fluid coupling | 48 | 48 | 11 | 48 | fluid observer; rigid pose/SE(3) telemetry when explicitly encoded; linear/angular velocity | UNKNOWN/UNKNOWN/UNKNOWN |
| F7 | finite wet-base tank with prescribed quintic moving obstacle | 48 | 48 | 10 | 0 | moving-obstacle exchange; left/right mass split; front/flux and neutral-tail residence | UNKNOWN/UNKNOWN/UNKNOWN |

## 证明来源

| ID | 作用 | schema | 文件 | SHA-256 |
|---|---|---|---|---|
| E001 | frozen 336-case header/XMF/source-digest catalog | ds02.stage2.current336.v1 | `/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json` | `df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b` |
| final_report_20261010 | 2026-10-10 closeout report; scope and limitations narrative | — | `/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-handoff/20261010-closeout-v1/FINAL_REPORT_ZH.md` | `7b0f86c7cbf4528cd8bd65d0f8f2128d7eed53c04ab5a9bacf041dd8196dc25b` |
| E002 | 335 saved-mask/lifecycle cases and one alias exception | ds02.stage2.typed-lifecycle-continuation-plan.v4 | `/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json` | `2d7ac52f5e3afd5b76b112fdc9dff4a9a8fc6bf4e7c1e045294f0fa93843febd` |
| E003 | 78 actual field-scan rows, 256 remaining and one manifest UNKNOWN | ds02.stage2.closed-actual-field-census.v2 | `/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/ROOT434_ACTUAL_H5_CLOSED_CENSUS_V2.json` | `41307b109235b9c346e1d4a84d3130c5a5e00310fb8d7e962401b047b7c63d4a` |
| E004 | 117 native-cause/typed-saved-frame joins in original-118 scope | ds02.stage2.original118-native-cause-actual-overlay.v1 | `/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/ORIGINAL118_NATIVE_JOIN_AFTER_ROOT717_INDEPENDENT_STRICT_V5_OVERLAY_V1.json` | `77789dc5778fd0f6a7ff2bd1d0c8482596d312d5acc2554745c092181a266fcc` |
| native_join_scope | canonical 118-row native scope partition | ds02.stage2.generic-native-typed-native-join.v1-manifest | `/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/ORIGINAL118_NATIVE_JOIN_AFTER_ROOT717_INDEPENDENT_STRICT_V5_OVERLAY_V1-canonical-base-scope.json` | `a434a7fd2aada798eaa7bc28d9c763ec3167f6839c1b2c3129fc17b29e91753b` |
| missing_manifest_preflight | 335-case metadata preflight identifying one missing manifest reference | ds02.stage2.root-field335-primary-bounded-metadata-preflight.v1 | `/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/governance/root-owned-source-interface-review-v1/field335-primary-v5-actual-metadata-preflight-v1.json` | `55db3fc7750433ebd739ee8d29973934bda0708df85d00f06bcc1eb9f62e70ee` |
| family_source_proof_v21 | seven family source-bound development cards | ds02.stage2.current336-source-proof.v21 | `/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v21-source-proof/CURRENT336-source-proof-v21.json` | `617c1957a8b203f7916c0b584f2a3bc684ffcf836c77cdef378b3f5ea2b22c40` |

## 保留的例外与未知

- 未解析历史别名：`F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090`（F2，CURRENT index 78）。E002、E004 及 canonical 118-row scope 都要求保留 UNKNOWN，不借用其他规范例的证据。
- 缺失 manifest 引用：`F2H10V2_OFFSET_V1`（F2）。field335 preflight 的明确原因是 `case manifest reference is missing`；这是 field-scan producer chain 的 UNKNOWN。CURRENT336 行仍有一个 manifest 元数据指针，但该指针不能替代缺失的 field335 引用闭合。
- native join 的 physical_fate、legal_flux、dynamics、QI/QN/QE 仍 UNKNOWN；mask 也不授予这些信用。
- 解析度、窗口、恢复转移及跨族等价性仍 UNKNOWN，所有家族卡 split_safe=false。

## 机器可读输出

- `scope_catalog.json`：完整元数据范围目录及来源/边界。
- `scope_catalog.csv`：336 行 case/task 索引，保留 manifest、XMF、trajectory 和 raw-root 指针但不读取其目标。
- `build_scope_catalog.py`：可从同一 stage2 快照重复生成；只打开本报告列出的元数据文件。
