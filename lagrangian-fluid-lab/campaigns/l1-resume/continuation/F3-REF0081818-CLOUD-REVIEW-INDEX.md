# F3-REF0081818 云端审阅索引

这份文件是云端审阅的第一入口。它把本次活动的输入边界、执行链路、最终证据和未达到的资格条件放在同一处；机器可读的同一份清单见 `F3-REF0081818-CLOUD-REVIEW-MANIFEST.json`。

## 审阅入口

- 仓库：`https://github.com/yupengxiang/DualSPHysics`
- 分支：`codex/lagrangian-fluid-exploration`
- 先读叙述：`lagrangian-fluid-lab/campaigns/l1-resume/continuation/F3-REF0081818-CURRENT-CAPABILITY.zh-CN.md`
- 再读机器收口：`lagrangian-fluid-lab/campaigns/l1-resume/continuation/F3-REF0081818-CAMPAIGN-CLOSEOUT.json`
- 当前状态：`terminal_negative_with_parent_resource_block`
- 活动状态：`activity_closed=true`，`objective_delivery_status=completed_as_bounded_negative_closure`

远程审阅者可以这样定位同一份材料：

```bash
git clone https://github.com/yupengxiang/DualSPHysics.git
cd DualSPHysics
git checkout codex/lagrangian-fluid-exploration
git log -1 --oneline
```

审阅时应以包含本索引文件的分支最新提交为准，并用 `git rev-parse HEAD` 记录实际审阅提交；本索引不把自身的提交哈希写入内容，以避免自引用哈希。

## 输入、授权和执行链路

附件 `F3_Long_Run_a8e5038_2026-09-10.zip` 的 SHA256 是
`69de49852be0cf8dcc8f5f38fa515971dfad7085ae5ef23347e56cb5870b977d`。它是规划和验证说明的输入，不是所有者授权本身。实际执行边界以仓库中的授权、资源账本和执行记录为准，尤其是：

- `F3-075-REF0081818-AUTHORIZATION.json`
- `F3-075-REF0081818-DOWNSTREAM-AUTHORIZATION.json`
- `F3-075-REF0081818-TRAINING-PARALLEL-AUTHORIZATION.json`
- `RESOURCE-LIMITS.json`、`RESOURCE-LEDGER.json` 和 `RESOURCE-ACTIVE-WINDOWS.json`

完整链路是：

```text
规划/授权边界
  -> 数值参考配方与 gate/score
  -> 32 个独立开发案例与数据契约
  -> 两个材料候选、子步比较和两次 cadence 超时
  -> 两条学习路线、6 个训练运行、96 个留出回放
  -> 资源账本冻结与有界负结论收口
```

## 已完成的工作和证据

| 阶段 | 结果 | 主要证据（均已纳入 Git） |
| --- | --- | --- |
| 数值参考配方 | `passed`；`dp=0.0075 m`，参考阶梯 `0.010/0.0075/0.006 m`，时间窗 `0–8.35 s` | `F3-075-REF0081818-GATE.json`；`F3-075-REF0081818-SCORES-633a9f1c021fcbbaa2fa5a8a85f204753b6a801f7109003538f0c92a39425fa3.json` |
| 独立开发数据 | 32 个案例，契约 `passed`；仍属于 development | `F3-REF0081818-TRAINING-DEVELOPMENT-FULL.json`；开发 registry/reconciliation |
| 材料闭环 | 两个 nominal candidate 完成；子步预算失败；cadence 配置真实超时两次；`qualified_T2_macro=false`、`qualified_T2_path=false` | `F3-REF0081818-MATERIAL-ARCHIVE-INDEX.json`；`F3-REF0081818-MATERIAL-COMPARISON-NOMINAL-SUBSTEP.json`；各次 attempt record |
| 学习闭环 | `particle_mlp` 与 `local_interaction` 各 3 个 seed，均到 16384 steps；96/96 留出回放触发 hard-wall/crossing；无模型发布 | `F3-REF0081818-TRAINING-CLOSURE.json`；`F3-075-REF0081818-TRAINING-PARALLEL-AUTHORIZATION.json` |
| 资源与终止 | qualification `75/80`、development `32/40`、material `16/32`、training `12/12`；GPU `17.7132/64 h`；CPU 保守上界 `911.958/896 core·h`；活动窗口关闭 | `RESOURCE-LEDGER.json`；`RESOURCE-ACTIVE-WINDOWS.json`；`EXECUTION-STATE.json` |
| 总收口 | 所有适用有界分支有实际终态，但没有可发布材料或模型 | `F3-REF0081818-CAMPAIGN-CLOSEOUT.json` |

## 关键文件哈希

以下哈希用于审阅者在 checkout 后确认文件没有被替换：

| 文件 | SHA256 |
| --- | --- |
| `F3-REF0081818-CAMPAIGN-CLOSEOUT.json` | `0be3d733c2af36ad16d32d302a0af2f73694e9587983b66d5058456c59a7a56f` |
| `F3-REF0081818-CURRENT-CAPABILITY.zh-CN.md` | `06d60ffd3bbb503d51834a6143eaf9663bc66fa9833de606a76f738524435b4e` |
| `F3-075-REF0081818-GATE.json` | `cd250459e7babe619c8fe320c652618c4383b4d481985df9a2d5e240cfd687d4` |
| `F3-075-REF0081818-SCORES-633a9f1c021fcbbaa2fa5a8a85f204753b6a801f7109003538f0c92a39425fa3.json` | `633a9f1c021fcbbaa2fa5a8a85f204753b6a801f7109003538f0c92a39425fa3` |
| `F3-REF0081818-TRAINING-DEVELOPMENT-FULL.json` | `61a1a56f53bebe7edae6955b0469e4ee9cd1750b7388755c9d43d0407a0390db` |
| `F3-REF0081818-MATERIAL-ARCHIVE-INDEX.json` | `8f550b99823aaf4f63fc52fc83e17c7a5b84b42ea9e9b33969efc09a73e12faf` |
| `F3-REF0081818-MATERIAL-COMPARISON-NOMINAL-SUBSTEP.json` | `8246127d5056a2e7c39575715a8fd64616a0d7b7818da3b893d5673722803439` |
| `F3-REF0081818-TRAINING-CLOSURE.json` | `29991a5fe01b1b64fa3d624cd7582f7e44858a55c55f0fdaefc43235e53772e1` |
| `F3-075-REF0081818-TRAINING-PARALLEL-AUTHORIZATION.json` | `b9925d30ccfd41849502e01aefbb90909a89e7c035fad0f37527880c82b76991` |
| `RESOURCE-LEDGER.json` | `3601f948928ec9760bcf562b56d4b5511d35025f98992c98ed2c45e07909294e` |
| `EXECUTION-STATE.json` | `a9d196c0b365397d903a772fd990bfa94ceb50643b826b190e3245ab59963085` |

## 可以和不可以作出的结论

可以审阅并复核的结论是：数值参考配方通过了登记的数值 gate；32 个独立开发案例真实生成；材料候选和训练路线真实执行；所有失败和超时都保留在分母或 attempt record 中；最终活动以有界负结论收口。

不能作出的结论是：材料已经通过 T2、训练模型已经正式资格化、存在正式产品发布，或者仅凭这个 Git checkout 就能重放全部原始 HDF5/权重。

## 原始归档的边界

原始外部归档没有塞进 Git：

- `f3-ref0081818-material-archive/` 约 13 GB；
- `f3-ref0081818-training-archive/` 约 94 GB。

它们被 `.gitignore` 标记为 immutable external archives。Git 中提交的是可审阅的代码、输入审计、attempt record、artifact manifest、汇总 JSON 和哈希；`F3-REF0081818-MATERIAL-ARCHIVE-INDEX.json` 记录了外部归档中各执行尝试的路径、状态和 manifest 哈希。因而当前远程分支足以审阅方法、链路、状态和结论，但不声称提供 107 GB 原始重放载荷。若审阅者需要逐帧重放，必须另外提供对象存储或附件地址，并把地址及校验和补进新的审阅提交。

## 本地核验命令

```bash
sha256sum \
  lagrangian-fluid-lab/campaigns/l1-resume/continuation/F3-REF0081818-CAMPAIGN-CLOSEOUT.json \
  lagrangian-fluid-lab/campaigns/l1-resume/continuation/F3-REF0081818-CURRENT-CAPABILITY.zh-CN.md \
  lagrangian-fluid-lab/campaigns/l1-resume/continuation/F3-REF0081818-MATERIAL-COMPARISON-NOMINAL-SUBSTEP.json \
  lagrangian-fluid-lab/campaigns/l1-resume/continuation/F3-REF0081818-TRAINING-CLOSURE.json

python3 -m json.tool lagrangian-fluid-lab/campaigns/l1-resume/continuation/F3-REF0081818-CAMPAIGN-CLOSEOUT.json >/dev/null
git status --short
```

活动收口前的完整实验室测试记录为 `662 passed, 1 skipped`；本次审阅索引只增加文档和机器清单，不改变实验结果或代码路径。
