# A8 Core 产品与异机复现 coarse bridge v1（2026-09-28）

## 结论

新的 product/reproducibility bridge 已把现有 Core/F3/F4/F8 资产接成一个 bounded local package 链：

`reader manifest → reader receipt → diagnostic rollout → diagnostic score → reproduction receipt`

当前 `coarse_chain_passed=true`，但 `local_package_ready=false`。原因不是 reader、诊断 rollout 或 score 链断裂，而是历史 A8 bundle 仍声明 `core.reader_bundle.v1`；当前 reader package 合同要求 `core.reader_bundle.v2`，故 bridge fail-closed，不把历史 bundle 冒充为 v2。

机器产物：

- [package manifest](A8-CORE-PRODUCT-LOCAL-PACKAGE-MANIFEST-V1-2026-09-28.json)
- [reproduction receipt](A8-CORE-PRODUCT-REPRO-RECEIPT-V1-2026-09-28.json)
- [bridge report](A8-CORE-PRODUCT-REPRO-BRIDGE-V1-2026-09-28.json)

## 接入范围

- Core reader bundle index、F3 compact manifest、F4 compact manifest；manifest preflight 复用现有 `scripts.core_package.inspect_reader_manifests`。
- F3 reader receipt 与 F4 Core reader smoke receipt。
- F8 terminal-matrix readiness consistency 与 target-kernel local inventory 两份 bounded receipt；它们只作为 readiness context，不被解释为 Core 产品资格。
- 已有 Ada↔H200 F3 单案例 diagnostic pair，作为历史 diagnostic rollout/score 输入；bridge 没有重跑模型。
- CLI、package manifest、diagnostic rollout projection、score projection、reproduction receipt 均由新脚本统一生成并交叉绑定。

所有输入均以严格 bounded JSON 读取。bridge 没有打开或重哈希 HDF5、NPZ、trajectory、checkpoint，也没有启动 solver、worker、GPU 或 queue。

## 结果与限制

- manifest、reader、diagnostic rollout、score 四个 stage 均通过；诊断 pair 的历史 cross-host agreement 保持 diagnostic-only。
- `formal_training=false`、`T1_numerical=false`、`T2_macro=false`、`T2_path=false`、`qualification=false`、`credit=0`。
- registry、ledger、denominator、gate、completion、PLAN mutation 均为 `0`。
- `cross_host_reproduction=false`、`full_product_reproduction=false`；历史 Ada↔H200 数值一致性不等于完整产品复现。
- 下一步是提供/构建经过当前 v2 verifier 的实际 portable bundle，再在独立授权下运行 full bundle verification 与异机 reader/model/scoring chain；本 bridge 不自动启动该 workload。

验证命令：

```sh
lagrangian-fluid-lab/campaigns/core-v1/environments/cross-host-py312-torch212-cu132-v1/runtime/h200/bin/python3.12 \
  lagrangian-fluid-lab/scripts/core_product_repro_bridge_v1.py validate \
  --lab-root /home/jade/Projects/DualSPHysics \
  --manifest lagrangian-fluid-lab/reports/A8-CORE-PRODUCT-LOCAL-PACKAGE-MANIFEST-V1-2026-09-28.json \
  --receipt lagrangian-fluid-lab/reports/A8-CORE-PRODUCT-REPRO-RECEIPT-V1-2026-09-28.json \
  --report lagrangian-fluid-lab/reports/A8-CORE-PRODUCT-REPRO-BRIDGE-V1-2026-09-28.json
```

结果：`passed=true`。
