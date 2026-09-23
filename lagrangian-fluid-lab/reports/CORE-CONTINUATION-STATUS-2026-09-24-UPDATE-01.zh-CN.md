# Core 计划续接状态更新（2026-09-24）

本更新承接 2026-09-23 的状态记录。它记录本轮的只读复核、资源门和测试结果，不扩大已有运行授权，也不把代码测试或执行成功误记为科学资格。

## 本轮完成

- 对 PLAN 中六项文献人工核对官方出版页/项目页，书目信息和核心主张已记入[文献来源审计](LITERATURE-SOURCE-AUDIT-2026-09-24.zh-CN.md)。缺少规范 `verify_papers.py`，因此六项的自动交叉验证仍全为 **UNVERIFIED**。
- F4 supportcap R002 的授权、冻结 recipe 和静态绑定通过只读检查；新的环境快照发现 1 分钟 load 超过 CPU affinity，故未调用会先写入 one-shot start receipt 的执行器。详见[资源门快照](F4-SUPPORTCAP-R002-CPU-PREFLIGHT-RESOURCE-GATE-2026-09-24.zh-CN.md)。一次 CPU-native 预检授权仍未消耗，solver/GPU/queue/T2/runtime 均未获授权。
- F3 material row30 R003 的完整运行已有终态审计：进程返回成功、836/836 帧完整且质量闭合，但每来源未知比例分别为 1.0742% 和 1.0254%，均超过冻结的 1% 门；该 attempt 未绑定独立 512-vs-4096 CDF 对照。因此 `row_acceptance=false`、T2 credit=0。终态审计本身未独立打开/哈希 HDF5；随后单独完成了输出 HDF5 哈希核验与 43 个失败 seed 的只读近壁诊断，细节见 [R003 失败归因](F3-MATERIAL-ROW30-R003-FAILURE-ATTRIBUTION-2026-09-24.zh-CN.md)。新 attempt 仍需新的 root decision，旧尝试不重跑。
- F8 R008 CPU/native 预检已有 post-run 审计确认其证据哈希闭合：GenCase 与 native decode 成功、几何审计通过；固定粒子数为 4,096、流体粒子数为 6,656、总数 10,752。该结果仍为 zero-credit preflight，solver 未启动，也不计为 T1 家族。
- Core 接口、打包、评测、复现、训练契约和完成判据的定向测试共 **120 passed**：Core reader/model/package/reproduction 71 项、F4 supportcap R002 静态/预检 17 项、Core campaign 完成判据 32 项。
- 上述文献审计和 F4 资源快照已各自提交并推送；本更新本身只是工作记录，不更改数据、登记或资格。

## 当前全局门

`core_campaign.py status`（只读模式，未请求写 completion snapshot）仍给出 `can_finalize=false`：

| 门 | 当前状态 |
|---|---|
| 不同 T1 家族 | 2/3（F3、F4；F8 尚非合格家族） |
| 宏观 T2 家族 | 0/2 |
| 正式训练 | 0/9 |
| T1 目标 case-run | 0/432，缺 432 |
| 模型材料目标 case-run | 0/288，缺 288 |
| 异机完整产品复现 | 未通过 |
| 因果谱系 / 当前证据有效性检查 | 通过 / 通过 |

总控显示 `issues=[]` 并不表示 Core 完成；上表中的各项 completion gap 仍然存在。F8 R008 的 CPU/native preflight、F4 已通过的 T1 scope、以及模型/reader 的单元测试均不能替代三家族资格、T2、正式训练、完整评测分母或异机产品复现。

## 资源与授权边界

- F4 supportcap R002 的最新非消耗性快照：CPU affinity 128；load `135.782 / 135.310 / 134.949`；RAM `225,616,523,264` bytes；磁盘 `8,186,858,048,960` bytes；F3 material worker PID 为空。唯一不通过项是 1 分钟 load > 128；R002 receipt 与输出目录仍不存在。
- F3 row30 R003 的终态科学失败和旧 resource-preflight v2 回执都不能自行授权新尝试。新尝试需新的 root decision；用户原先针对 row30 的 resource/scheduler preflight 授权不等于启动 worker。
- F8 R008 预检之后没有 solver 授权。F8 R002 的历史失败也不得以同输入重试；遵守既有 receipt 中的版本与 retry 边界。

## 接续顺序

1. 可继续做不消耗 one-shot 的只读资源快照和代码/契约工作；只有 load、RAM、磁盘、worker 及新鲜 namespace 均满足绑定门槛，才调用 F4 R002 唯一一次 CPU-native preflight。
2. 保留 F3 row30 R003 负结果；未经新的 root decision 和单独运行授权，不启动新的 row30 worker。
3. 不把 F8 R008 的原生输入预检升级为 solver 资格。需要 solver canary 时仍受其单独授权范围控制。
4. 继续 Core 中可独立推进的 reader/evaluator/产品工作，但总体验收仍须补第三个 T1 家族、两家族宏观 T2、9 次正式训练、432/288 case-run 分母及真实异机产品复现。
