# A8 Core reader bundle v2 / reproduction bridge 回执（2026-09-28）

本轮没有改写历史 `a8-full-reproduce-v1`。旧包的 `bundle.json` 明确是
`core.reader_bundle.v1`，且历史包缺少部分 provenance 资产；因此没有通过改标签
冒充 v2。使用当前 `F3 core.dataset.v2` 清单、仓库中完整 provenance 文件和旧包中
内容寻址的 NPZ 资产，以 hardlink 方式发布了新的
`campaigns/core-v1/reproduction/a8-full-reproduce-v2/`。

## 已完成的可验证部分

- 新索引 schema：`core.reader_bundle.v2`；32 个 F3 cases，182 个登记文件。
- `core_package.py --verify-bundle`：`passed=true`，`verified_files=182`。
- A8 coarse bridge：`coarse_chain_passed=true`、`local_package_ready=true`、
  `blockers=[]`。
- 三份 V2 JSON 的交叉哈希验证：`passed=true`、`errors=[]`。
- 旧 v1 包保持不变；新包与旧包不共享可变复制，数据资产使用 hardlink。

## 明确未完成的科学门

该包是 reader-only diagnostic package，本次没有绑定 checkpoint（
`checkpoint_count=0`、`model_reproduction_supported=false`）。因此不能推出模型复现、
formal training、T1/T2、qualification 或 credit；这些字段保持
`false/0`，cross-host historical diagnostic 也不升格为正式复现。

bridge 本身只读取有界 JSON projection，未打开 HDF5/NPZ/checkpoint，未启动 GPU、
solver、worker 或 queue，也没有修改 registry、ledger、denominator、gate、completion
或 PLAN。构包和独立 verifier 的完整资产校验属于本次包发布步骤，不改变上述科学门边界。

机器产物：

- `A8-CORE-PRODUCT-V2-LOCAL-PACKAGE-MANIFEST-2026-09-28.json`
- `A8-CORE-PRODUCT-V2-REPRO-RECEIPT-2026-09-28.json`
- `A8-CORE-PRODUCT-V2-REPRO-BRIDGE-2026-09-28.json`

