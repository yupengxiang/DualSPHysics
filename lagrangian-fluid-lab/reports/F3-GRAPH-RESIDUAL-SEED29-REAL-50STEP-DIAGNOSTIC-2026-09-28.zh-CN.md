# F3 `graph_residual` seed29 真实 50-step 独立诊断

本次独立诊断已完成：在物理 GPU6（`CUDA_VISIBLE_DEVICES=6`，进程内 `cuda:0`）上，真实 F3 `F3_DEV_00_a0p903125` 完成训练 `500/500`，并完成 `--maximum-steps 50 --diagnostic` 的 autonomous 评测 `50/50`。本记录明确为 `diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`credit=0`；不授予正式训练、资格或 gate credit。

评测窗口是有意 bounded 的右删失：50 个预测 transitions 对应 trajectory 的 51 帧；完整登记分母仍为 835 transitions / 836 trajectory frames，未完成完整分母，不能把 bounded 窗口当作完整 case 结果。`failure_category=maximum_steps_limit` 是窗口上限分类，不是科学失败；`scientific_failure_category=null`、`scientific_status=not_assessed`。

## 协议与完成证据

| 项目 | 绑定值 |
|---|---|
| manifest / data root | `campaigns/core-v1/f3-dataset-v2.json` / `.` |
| case / split | `F3_DEV_00_a0p903125` / `test` |
| model / seed | `graph_residual` / `29` |
| updates / centers / hidden | `500` / `256` / `8` |
| learning rate / normalization transitions | `0.001` / `16` |
| max neighbors / evaluate chunk | `192` / `34560` |
| GPU / process device | physical GPU6 / `cuda:0` |
| output prefix | `/tmp/f3-graph-residual500-seed29-20260928-*` |

训练 receipt 为 `core.training.v1`，`completed_updates=500`、`evidence_status=complete`，checkpoint 为 `update=500` 且已核验。`residual_prior` 执行 `500` 次、覆盖 `17,280,000` rows，`finite=true`、`history_complete=true`；训练邻居截断比例为 `0.0`。

评测 receipt 为 `core.evaluation.v1`，exit code 为 `0`；请求窗口 `50/50` transitions 完成，evaluation progress 为 `completed`，`finite_rollout_complete=true`，且 `future_state_inputs=false`。evaluation receipt、progress 和 trajectory HDF5 属性均确认没有未来状态输入。

## 分母、有限性与物理不变量

| 项目 | 结果 |
|---|---:|
| bounded 执行 transitions | `50/50` |
| bounded trajectory frames（含初始帧） | `51` |
| 完整登记分母 | `835 transitions / 836 frames` |
| full registered denominator complete | `false` |
| raw error coverage | `50/835 = 0.059880239520958084` |
| failure category | `maximum_steps_limit`，first failure frame `51` |
| scientific failure | `null`；status=`not_assessed` |
| position / velocity / mass finite | 全部 `true` |
| valid mask | 全部 `true`，`1,762,560 / 1,762,560` |
| mass range / unique values | `0.00042187501094304025–0.00042187501094304025 kg` / `1` |
| mass error max / changed-mass frames | `0.0 kg` / `0` |
| validity mismatch frames | `0` |
| kinetic-energy error max | `0.14455218643128437 J` |

HDF5 trajectory shape 为 position `(51,34560,3)`、velocity `(51,34560,3)`、valid `(51,34560)`、time `(51,)`、mass `(34560,)`；`autonomous_prediction=true` 且 `future_state_inputs=false`。

## 原始指标表

| 指标 | seed29 bounded 结果 |
|---|---:|
| selection score | `0.9405079338327175` |
| position RMSE, step 50 | `0.011656636805092279 m` |
| position RMSE, 50-frame mean | `0.0037844461402610384 m` |
| velocity RMSE, step 50 | `0.06257107137184988 m/s` |
| velocity RMSE, 50-frame mean | `0.026029290856529195 m/s` |
| position ADE / FDE, step 50 | `0.018218477496905517 / 0.018218477496905517 m` |
| velocity ADE / FDE, step 50 | `0.10068512659037639 / 0.10068512659037639 m/s` |

作为分析参考，已记录同协议 seed17 bounded 诊断的指标，但它不是 qualification baseline：seed29 相对 seed17 的 selection score、position step/frame-mean RMSE、velocity step/frame-mean RMSE 分别增加 `5.017646331229031e-05`、`0.0012304185749359466 m`、`0.0004184480869749785 m`、`0.009577629470797773 m/s`、`0.0035981770393034504 m/s`。这只说明 bounded seed sensitivity，不能外推完整 835-transition 行为。

## 资源与 wall time

- 训练 receipt-native wall=`2203.6724585308693 s`；`/usr/bin/time` 进程 wall=`2244.41 s`。
- 训练 peak GPU allocator=`1599798272 B`（`1525.6865234375 MiB`）；外部 GPU6 采样峰值=`5915 MiB`。
- 训练 peak RSS=`2959.53125 MiB`；外部 `ps` 采样峰值=`2677.875 MiB`。
- 评测 progress wall=`1052.7886696259957 s`；`/usr/bin/time` 进程 wall=`1057.05 s`。
- 评测无 receipt-native allocator/RSS peak；外部 GPU6 采样峰值=`3049 MiB`，进程 time peak RSS=`3408.625 MiB`，外部 `ps` 采样峰值=`3414.15625 MiB`。

## SHA-256 证据索引

所有运行文件均使用唯一前缀 `/tmp/f3-graph-residual500-seed29-20260928-`：

- training JSON：`727aacf1845a6dd6e52eb685968063fb4c46ea507f84d75f68d5063e4680009c`
- checkpoint：`c037455244ac1ffdd6908908eaf76b3b66e3ec5baaa63d8b9107641248e10287`
- training progress：`5ec7e47ed3a4b5fe9b25b4588b816d1cf8986fa4ffd20319f467e816296947ae`
- training log：`34439490de92cfec0329877a41129be9834436e2f36f05b939c9750ccc66055e`
- evaluation JSON：`ec026ad8bb23e3ee1233caf6337afc4638543e0784f0bbcc1a95b3bd69088f63`
- trajectory HDF5：`a734d53ebb94cdafc46669bbb338e17898389809a80d74bea3b9a5b70fdb187b`
- evaluation progress：`de3b0a51116c9aa5aeb16389195b2551974898b61aeaa718b3347269e86b10e6`
- evaluation log：`0982f8b56b1220ca27313dbf314d3bbdec99253f676bbaf1c321a71ee43652b6`
- training time：`ea25ff5d9519f49e978f1d891970a71904d216f1bd7858aa8c2eed2613ea146d`
- evaluation time：`314df4be16380888862f0bfb521d1820329c14cc5c974fc543d79695f807f972`
- launcher status：`bb75b4adaff74673cfb549d93f75fe5a557dd989acaf47cfdb57b2813af9cf51`
- resource samples：`6cd0f30185be31ca26cdd16abac47537194c4c121b751d707363553a27a501c4`

## 结论与副作用审计

观察：本次训练和 bounded autonomous prefix 均成功执行，因果输入契约满足，短窗数组有限且质量不变量通过；seed29 的 bounded 指标相对 seed17 同协议参考略差。

解释：该结果只能反映 seed29 在 50-step 右删失窗口内的行为；`raw_error_coverage=0.059880239520958084` 明确不是完整分母覆盖率。

下一步建议：若需要模型决策，应另行授权并执行固定 835-transition 全窗口诊断；在适用 gate 满足前，本次结果不得升级为 formal candidate 或 qualification。

本次没有修改源码、生产 HDF5、manifest、registry、ledger、denominator、gate 或 `PLAN.md`；没有启动 solver/worker/queue。只新增本 JSON 与本 `.zh-CN.md` 报告，`credit=0`。
