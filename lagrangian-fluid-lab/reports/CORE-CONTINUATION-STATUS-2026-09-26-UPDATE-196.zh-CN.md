# UPDATE-196：刷新 Core 完成门与异机复现状态

时间：2026-09-26（Asia/Shanghai）

## 只读核对

使用锁定 Python 3.12 环境运行 `scripts/core_campaign.py status`（未请求 `--write-snapshot`）：

- `can_finalize=false`；T1 为 F3/F4 **2/3**，宏观 T2 **0/2**，正式训练 **0/9**。
- T1 已登记评测 **0/288**，另有第三家族 **144** 个目标 case-run 尚未登记；总目标缺 **432**。材料目标 **0/288**。
- 因果谱系合同及证据结构有效性通过，`issues=[]`。
- 独立全产品复现当前为 **false**。登记的 `cross-host-reproduction-contract-20260920.json` 明确是 `diagnostic_only=true`、`full_product_reproduction=false`；另一份单案例模型对照虽有 835-transition 全时域分数，但注明完整数据包移动另属验收，且不是当前所需的绑定 supporting-evidence + root-review 复现合同。均不能升级为产品门通过。

另只读查询 Core runtime scheduler：queued/reserved/launching/running/attention 均为 0；无当前作业。没有启动作业、读取新 production frames、修改 registry/ledger 或写 completion snapshot。

## 结论

当前真正未闭合的主门仍是第三个可信 T1 家族、两族宏观 T2、432 个 T1 与 288 个材料 case-run、9 次正式训练及独立全产品异机复现。旧状态中“独立复现通过”只适用于已有诊断或 reader/model 子项，不能代替严格总门。本报告只刷新状态，不增加资格或授权。
