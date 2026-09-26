# UPDATE-184：正式评测将 ID/OOD 测试合并到 held-out 分母

时间：2026-09-26（Asia/Shanghai）

## 问题与修复

`PLAN.md` 为新 scope 固定 16/4/6/6 划分，其中 12 个 held-out 案例分别标为 `id_test` 和 `ood_test`。学习 CLI 的逻辑 `--split test` 与 evaluator 正式分支此前只按字面 `split == "test"` 取案例，因此新 scope 的 ID/OOD 测试数据会全部漏出评测分母。修复没有改写 `CoreDataset.case_ids()` 的精确标签语义，也没有把 validation 纳入 test。

现在 `evaluate` 和默认 `rollout` 路径将逻辑 `test` 映射为 manifest 顺序中的 `test`、`id_test`、`ood_test` 全集；正式分支按该 12 例/族集合重算家庭分母。回执的 `case_splits` 仍保留每例原始标签，混合标签时 `split` 为 `mixed`；`test_included` 对任何 held-out 标签为真。显式请求 `--split id_test` 或 `--split ood_test` 仍只选择对应分区。训练采样、validation checkpoint 选择与 legacy F3 的 `test` 标签路径未改。

新增 synthetic CLI 回归覆盖诊断与正式分支，检查 3 族各 12 个 held-out 案例完整进入分母、18 个 ID 与 18 个 OOD 标签被保留、validation 不混入。正式分支测试通过 monkeypatch 只打开代码分支；它没有提升 legacy reader 的 formal eligibility，也没有生成正式资格或训练证据。

## 历史 training-contract 收据

同一邻接回归发现 `training-contract-v1` 收据绑定的 PLAN、learning、planner、model 与 contract 源码哈希已和当前工作树不一致。只读 verifier 返回的所有 mismatch 均为 `contract.source:*`，同时继续给出 `formal_training_allowed=false`、`formal_job_count=0`、`credit=0`。保留这份旧收据及其 sidecar 原样不动，不将源码失配重新解释为训练授权；测试现明确验证这种 fail-closed 行为和只读性。

## 验证与边界

- 变更后的两条 held-out CLI 回归与整个 `test_core_training_contract.py`：**12 passed**。
- 邻接四文件套件在更新 stale-receipt 断言前为 **101 passed、2 failed**；两项失败均为旧 v1 收据仍被期待匹配已演进源码。源码 verifier 确认这不是 evaluation 逻辑失败。更新断言后，上述相关测试 **12 passed**；没有再重跑耗时约 2 分 41 秒的四文件全套。
- 未启动训练、solver、worker、GPU 或 queue；未改写旧 training contract/receipt、registry、ledger 或资格分母。正式训练仍关闭，资格信用为 0。

## 剩余工作

该修复关闭了 reader/evaluator 对计划 16/4/6/6 split 的接口错位，不代表正式评测已执行。Core 仍缺真实 T1 和材料 case-run、9 个正式训练运行、完整 held-out 评测证据与异机复现；全局 Core 总门仍为 `can_finalize=false`。
