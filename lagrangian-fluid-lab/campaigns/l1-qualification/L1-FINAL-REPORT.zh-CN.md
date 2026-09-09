# L1 自主拉格朗日流体资格活动最终报告

日期：2026-09-09<br>
分支：`codex/lagrangian-fluid-exploration`<br>
基线提交：`dc9533eecf7ee608a1db04ea4e26bb80cd2b456a`<br>
活动范围：F1 plain dam-break；DualSPHysics 5.4；0--1.5 s；保存间隔约 0.001 s

## 结论

本轮没有得到可进入 T1 的数值参考配方，因此没有 T1 数据集、development tranche、训练集或正式 release。W1 的时间敏感性门通过，确定 `CFL=0.05` 作为空间研究的数值时间策略；W1 空间阶梯在三个高度均未通过细化一致性与完整轨迹门。依 reviewer 规划执行的一个 W2-A mDBC + 显式法向受控实验同样失败，且失败更严重。`F6 新 solver=0`、`formal_release=false`、`hidden test=false` 均保持不变。

这是一份有界负结果和覆盖图，不是把失败结果改名为合格结果。历史 N4 证据未重跑、未改名、未占用其额度。

## 范围来源与指令区分

用户请求是本轮实际授权：读取引用任务最后一轮的云端 reviewer 计划，按计划推进，完成后推送远程并准备 reviewer 交接文档。附件 `Lagrangian_Fluid_L1_Autonomous_dc9533e.zip` 是一次性范围模板和静态校验材料；它不是已经执行的结果，也不是额外签名或 reviewer 回写。本活动只在用户明确采纳后使用其范围，并保留这一语义边界。附件 SHA-256 为 `2140048e019b2074668799aef145314af90eae242498450c069bbdb910aab5e3`；内部 `SHA256SUMS` 和 `PLAN_VALIDATION.json`（16/16）已验证，但后者只证明计划元数据静态有效。

用户补充的 GPU 安全规则已作为本轮执行策略锁定：仅使用 allowlist 中的 GPU 4--7；启动前至少保留 6144 MiB 空闲；运行中每秒检查，低于 4096 MiB（4 GiB）立即终止 L1 solver；一次只运行一个 solver；GPU 0--3 只保护、不触碰。W1 中 2 次 guard failure 被保留为真实失败 attempt，未隐藏。

## 执行与门禁结果

| 阶段 | 实际结果 | 判定 |
|---|---|---|
| W0 | 历史证据、输入语义、身份/排除规则和 GPU/存储策略锁定 | 完成 |
| W1 time | `dp=0.014`，比较 CFL 0.1 与 0.05；h10/h11 均在 21 个登记时刻通过 | `CFL=0.05` 进入空间阶段 |
| W1 space | h09/h10/h11 各跑 coarse/medium/fine；三个 fine 均失败 | 无 T1 高度 |
| W1 conditional `.007` | 没有高度同时满足“细化改善且进入条件补阶” | 未授权 |
| W2-A | h11 fine、mDBC、显式五面法向；solver code 0 但全时域审计失败 | 受控假设失败 |
| W4/W5/W6 | 无 T1，故无内部点、开发批次或训练数据 | 阻塞 |

## W1 time：只确定数值时间策略

两例都保存 1501 帧，并在登记的 21 个物理时间上比较 CFL=0.1 参考与 CFL=0.05 主方案：

| 高度 | 最大 distribution TV | 最大 COM L2 (m) | 最大 front q90 差 (m) | 门 |
|---|---:|---:|---:|---|
| h10 = 0.460 m | 0.0018382353 | 0.0004830945 | 0.0005003214 | pass |
| h11 = 0.506 m | 0.0040485830 | 0.0009089826 | 0.0015766621 | pass |

相应门限为 TV=0.01、COM=0.012 m、front q90=0.012 m。该结论是离散数值配方选择，不等价于连续流体真值验证。

## W1 space：三个高度均未形成 T1

所有 case 均生成完整 0--1.5 s / 1501 帧归一化输出；coarse→medium 的比较都在登记比较门内，但 medium→fine 在三个高度都触发 TV 超限，且 fine 本身的闭壁/身份门也失败。

| 高度 | 初始流体粒子数（coarse/medium/fine） | fine 审计 | 关键证据 |
|---|---:|---|---|
| h09 = 0.414 m | 6732 / 19344 / 48510 | failed | 1013 帧闭壁越界；最大越界质量 0.004 kg；TV medium→fine=0.0556495 |
| h10 = 0.460 m | 7344 / 21216 / 54285 | failed | 871 帧闭壁越界；最大越界质量 0.004 kg；TV medium→fine=0.0611363 |
| h11 = 0.506 m | 7956 / 23712 / 60060 | failed | 52 帧闭壁越界；352 个 native `position` 排除；最终质量比 0.9941392；TV medium→fine=0.0686456 |

h09 的 coarse→medium 最大（TV, COM, front q90）为 (0.0312829, 0.0138885 m, 0.0164582 m)；h10 为 (0.0429393, 0.0219127 m, 0.0161277 m)；h11 为 (0.0492305, 0.0290330 m, 0.0181917 m)。fine 的边界异常不是可以由比较门“平均掉”的误差：h09/h10 的粒子分别在约 0.382/0.379 s 从 y 闭壁两侧越界，h11 在约 0.381 s 有 z 方向越界，并在后续出现 native 排除。

由于没有一个高度满足首阶梯的准入条件，预登记 `.014/.010/.007` 第二阶梯不执行，W2 只按 reviewer 规划做一次边界表示控制。

## W2-A：mDBC + 显式法向控制实验

控制变量固定为 h11、fine、`dp=0.010 m`、`CFL=0.05`、重力、时间轴、流体几何和数值常数；唯一目标变量是边界表示：`Boundary=2`（mDBC），并用 `GeometryForNormals` 生成 bottom/left/right/front/back 五个闭合面，配置 `[CaseName]_hdp_Actual.vtk`、`distanceh=2.0`、`svshapes=true`。open top 保持非吸收面。

求解器实际返回 code 0，输出 1501 帧；日志确认 `Boundary="mDBC"`。但完整审计为 `failed_or_unknown`：

- 初始 60,060 个流体身份中 49,769 个被 solver 以 native `position` 排除，最终保留 10,291 个，身份/质量保留率 `0.1713453213`；排除证据与 `RunPARTs.csv` 完全对齐，原因计数为 `position: 49769`。
- 首个闭壁越界在 frame 130、`t=0.130014 s`；1371 帧存在闭壁越界，最大越界闭壁质量为 18.314 kg。
- 审计值没有 NaN/Inf；密度范围为 765.039--1193.828 kg/m³，但这不能抵消边界与身份门失败。
- W2-A 不是修复成功，也不是 T1 候选；不扩展该假设，除非 owner/reviewer 明确授权新的单一受控假设。

这组结果把“没有显式法向输入”从唯一可疑点中排除了一部分，但不能单独证明最终根因。当前最稳妥的根因表述是：fine 分辨率下闭壁/边界表示导致可观测粒子越界，mDBC + 本次显式法向几何没有闭合该问题；具体是几何法向语义、粒子层/法向距离还是 solver 读入语义，仍需下一次有界实验才能区分。

## 资源与安全

共计 19 次 qualification solver attempt：W1 为 18 次（11 完成、7 失败/中断），W2-A 为 1 次完成但审计失败；其中 GPU attempt 14 次、CPU attempt 5 次。W1 的 2 次显存 guard 失败均记录为 return code -12；没有终止外部训练进程。W2-A 在 GPU 4 上运行，启动快照空闲显存 6964 MiB，运行中未触发 4 GiB guard。校正后的 solver GPU 墙钟为 1.074716 GPU·h，CPU solver 为 4.251255 CPU core·h（8 threads 计）；详见 `RESOURCE-LEDGER.json`。

归一化 HDF5 本身总计约 13.02 GiB，原始 `.bi4` 和 CSV 还要另计；这些大文件按 lab `.gitignore` 保留在本机，不强行塞入 Git。小型 sidecar、审计、case XML、preflight、报告和 SHA-256 清单进入交付提交。

## 门禁关闭状态

| 项目 | 状态 |
|---|---|
| T1 数值参考配方 | 未获得 |
| T2 / 外部观测 | 未执行；不将 T1 失败冒充 T2 结论 |
| W4 内部点与输入 lineage | 不适用 |
| W5 development tranche | blocked |
| W6 training | blocked；训练 attempt=0 |
| F6 本活动新 solver | 0 |
| 正式 release / hidden test | false / false |

## Reviewer 交接入口

`L1-REVIEW-PACKET.md` 是面向云端 reviewer 的单页交接；它列出结论、失败证据、精确文件、复现命令和待 owner 决策。机器可读摘要在 `L1-RESULTS.json`，资源在 `RESOURCE-LEDGER.json`，数据完整性在 `DATA-MANIFEST.json`，错误/覆盖范围在 `ERROR-AND-COVERAGE-MAP.zh-CN.md`。
