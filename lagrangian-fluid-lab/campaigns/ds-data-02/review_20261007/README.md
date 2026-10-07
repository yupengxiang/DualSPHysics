# DS-DATA-02 外部审阅入口

当前结论：七族各48例、总336例首阶段视觉可用案例已交付；**数值精度未验收，Q-N/Q-E=0**。本次只整理、校验并发布代码与审阅材料，没有新增科学计算。

## 交给外部 ChatGPT

上传 `DS_DATA_02_STAGE1_REVIEW_20261007.zip`，把 [RESEARCH_REVIEW_REQUEST.md](RESEARCH_REVIEW_REQUEST.md) 内容作为审阅提示。先阅读 [全面总结](STAGE1_SUMMARY_ZH.md)，随后按 [证据索引](EVIDENCE_INDEX.json) 深入核查。无需把服务器绝对路径视为网页地址。

- [336例目录](CASES_336.json)：参数、帧/时域、产物、scope与视觉记录。
- [七族参数与遗漏统计](FAMILY_SUMMARIES.json)、[实际启动配方索引](NUMERICAL_RECIPE_INDEX.json)。
- [分支/提交索引](BRANCH_INDEX.json)、[未提交现场的保存清单](WORKTREE_SNAPSHOT_MANIFEST.json)、[代码副本索引](SOURCE_INDEX.json)。
- [代表性真实预览](PREVIEW_GALLERY.md)、[资源与存储](RESOURCE_STATUS.json)、[工程验证范围](VALIDATION.json)。
- 上传包另有 `PUBLICATION_RECEIPT.json`（远程实际HEAD）和 `PACKAGE_VALIDATION.json`（包检查结果）。

## 远程查看

仓库：https://github.com/yupengxiang/DualSPHysics。审阅分支：[codex/ds-data-02-stage1-review-20261007](https://github.com/yupengxiang/DualSPHysics/tree/codex/ds-data-02-stage1-review-20261007)；科学完成点：[fab8dd3b3ac2](https://github.com/yupengxiang/DualSPHysics/commit/fab8dd3b3ac28ef5e21efea9cc3f04afa7f116ee)。F1–F7、infra、integration均保留各自活动分支，见 BRANCH_INDEX。

历史计划/早期handoff保留原样，当前状态以本报告和checkpoint335的最终交付索引为准。活动分支有共享累积历史，不能当作七组互不重叠的补丁直接合并。代码推送不包括原始科学数据发布或默认分支合并。

## 校验与复现的边界

在解压目录运行 `python3 verify_review_package.py`，它只核查本包的代码、元数据、图像与336例目录，不启动求解器、不读取科学数组、不授予Q-N。源码副本 `source/` 仅包含在上传ZIP中，仓库从原始路径查看代码。完整XMF/H5/BI4/科学表格及solver日志不在上传包里；它不是独立可运行的全部科学数据发行版。
