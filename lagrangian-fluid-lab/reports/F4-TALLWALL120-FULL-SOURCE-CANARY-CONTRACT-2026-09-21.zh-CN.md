# F4 tallwall120 full-source canary 合同（proposal-only，2026-09-21）

根因审计显示，`f4_ess32_v2` 在 frame 40→41 的 128-seed 首失效 cohort 中仍为 `0/128` survivor；因此本轮不自动执行 full-source canary。合同保留为可审计的 deferred proposal，执行需要后续显式 review。没有启动 solver、GPU、queue，也没有改写旧负 trace。

## 新 output stem 与完整窗口

候选是已登记的 `f4_ess32_v2`：`f4_ckdtree_visible_shepard_ess32_v2`，k=32，仍使用 local residual、原 regularization、原 reconstruction/ESS/rank/anisotropy gate 和 unknown 上限 `0.01`。

未来执行必须使用新的 output stem：

```text
campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-f4-ess32-full-source-canary-20260921
```

计划窗口是 cell-14 原生完整窗口 `frame 0..1085`，`1086 frames`、`217485 particles`、`0..4.340002980805959 s`。只允许相邻 native frame 的 `x/v` 线性插值和每个 native interval 两个 RK2 子步；禁止 stride、合成 cadence、saved-chord imputation。

执行分两阶段：先运行 `stop_after_frame=40`，在已审计首失效 transition 前生成 checkpoint；再从 frame 40 的已验证 manifest 恢复到 frame 1085。每个 native frame 发布 content-addressed checkpoint generation；中断后只恢复最新已提交 generation，不能从零重跑或覆盖旧 generation。旧 baseline24 negative trace 只作为 source/code binding 输入，candidate 不复制其状态。

## 资源与判据

合同限定单 CPU 进程、cKDTree workers=1，并将 OpenBLAS/OMP/MKL/NUMEXPR 线程设为 1。已有 baseline frame-70 trace 的实测参考是 `37.2689576910343 s`、`730744 KiB RSS`；合同资源预算为 wall `1800 s`、RSS `1048576 KiB`、新增磁盘 `512 MiB`，超过预算 fail-fast。HDF5 source 保持只读，reference frame cache 上限为 2。

结构成功要求 source SHA、全窗口 committed frame/time、exact native rows、frame-40 resume manifest/generation SHA、512 seed 分母和 mass closure 全部成立。材料 gate 只有在所有 source label 的 unknown fraction `<=0.01` 且事件窗口完整时才观察为 pass；unknown 超限、full endpoint 仍 right-censored/unresolved、mass closure 失败、分母丢失、cadence substitution 或任何阈值改变都 fail。right-censor 保持 unknown，不给 partial credit。

无论结果如何，该合同不会授予 T2 credit，不能改变 `T2_macro`、`T2_path`、CDF、事件门、scientific denominator、Core gate、registry 或 ledger。

## Hash binding 与交付

合同 receipt：

```text
campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-f4-ess32-full-source-canary-contract-20260921.json
SHA256 cfb7f20c8e5276d1148f21b32980ae2ef55afdf656924dc72aeddc06631a8f91
```

绑定包括原生 source SHA `91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e`、preflight receipt SHA `f5e6dc499e19349324799f36a154b5bfc7c6bb9be03b0c0e9df27a4acd7fc9bf`、root-cause audit SHA `a4fa8e9283b4588f8ff25ace474ef57705191ba27c84a5ec9fbceefca935d0e6`、candidate contract SHA `566d39c8c32f42859d7f2b1b93ef087dbf6e01d1666bead10d740d9ca2709d6d`，以及既有 tracer/core/neighbour/wall implementation hashes。合同实现脚本 `scripts/f4_tallwall120_full_source_canary_contract_v1.py` SHA256 为 `9b327940cfe7bc1919534ed78d5c1fd1cac3e87db4191f81b6a60e8adf11e29e`；合同测试 `tests/test_f4_tallwall120_full_source_canary_contract_v1.py` SHA256 为 `01ed6aecedd495da8dd58121a3cc1366c545e099d00fd9e0bce941d8a397c43b`。

本次合同及既有 root-cause/preflight 合并测试：`10 passed`。当前路线结论为 `proposal_only_deferred_after_one_transition_failure`；重新开启时必须沿用该窗口、资源预算、判据和 hash bindings，并使用新 output stem。
