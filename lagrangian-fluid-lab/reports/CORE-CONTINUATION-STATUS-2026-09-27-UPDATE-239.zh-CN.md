# Core continuation status — 2026-09-27 — UPDATE-239

## F3 real-case full-window material sidecar smoke

在 F3 reader 全时域验证之后，使用现有 `core.material.v2` 对真实 `F3_DEV_00_a0p903125` 做了一个受界限的材料侧车 smoke：512 个独立几何 seed、baseline visible-Shepard k=24、substeps=2，完整覆盖原生 836 帧至 `8.350012828223477 s`。运行摘要保存在 [`F3-MATERIAL-REAL-SMOKE-2026-09-27.json`](F3-MATERIAL-REAL-SMOKE-2026-09-27.json)；临时 trace 为 28,728,240 bytes，wall `191.37327233492397 s`，peak RSS `601408 KiB`。

结果保持 unknown/censoring 语义：mass closure 为 1，unknown 单调不下降，但 source 0 final unknown=`0.0390625`、source 1=`0.03125`，共同可靠路径覆盖=`0.96484375`，固定 unknown ≤1% gate 不通过。source 0/1 的 observed first-passage fractions 为 `0.3125/0.296875`，observed return fractions 为 `0.29296875/0.296875`；这些是单例诊断统计，不是 T2 资格结论。

该结果首次把 F3 真实 reader → 全窗口材料侧车路径走通，但也明确暴露 baseline 材料重建的可靠性缺口；没有通过改阈值、删失分母或换名来修复。状态为 `qualification_claim=none`、`material_reliability=not_established`、`qualified_T2_macro=false`、`qualified_T2_path=false`、`qualification_credit=0`。未修改生产 HDF5、registry、ledger、split 或分母；未启动 solver/worker/GPU/queue。32-case/33-row 正式材料矩阵仍未执行，后续需独立的候选修复、真实多例验证和正式 admission。临时二进制 trace 不纳入仓库，摘要保留其 SHA-256。
