# DS-DATA-02 七族并行数据集建设包

顺序：START_HERE_ZH.md → REVIEW_ZH.md → EXECUTION_PLAN_ZH.md → PARALLEL_OPERATIONS_ZH.md → QUALITY_AND_SCHEMA_ZH.md → SPLIT_AND_COUNTS_ZH.md → 对应families/Fn.md。

以提交0081645116664386f76f2bfa2ef428bcd74e846e为静态审阅基线；原始数据未在本轮独立重放。本包没有发布或启动任何模拟，也没有修改GitHub。纯数据目标，模型任务为0。

CAMPAIGN_PLAN.json和TASK_GRAPH.json是要接入本地已有runner的规划；不是已经运行的调度器。tools/policy_reference.py是无I/O的准入策略示例，须集成进实际数据验证路径；不能只运行它就宣布科学验收。

计划与参考策略自测：
```bash
python tools/validate_plan.py
python -m unittest discover -s tools -p 'test_*.py' -v
```

SOURCES.json记录审阅文件和官方/原始来源。SHA256SUMS只证明本包字节一致，不证明数据科学质量。
