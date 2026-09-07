# R3 G1：契约与质量门禁修复

状态：**已修复审阅者复现的三项契约问题，并扩展 W11 坏文件与原子发布测试。** 这属于工程验收；材料示踪和物理数据的科学验收仍未通过。

## 修复

- W08 的 `study_id`、`paired_background_id`、`physical_case_id`、`lineage_group_id` 已分离。参数不同的受控案例共享背景而不共享谱系；相同物理参数的数值/观测派生版本使用同一物理谱系。W08 自检现在同时调用等价于 W10 的 lineage 规则。
- 刚体齐次变换先检查全部 16 个元素有限，再检查末行与旋转正交性；NaN 平移不再通过。
- 质量比例逐项要求有限且非负，再检查类别一致与总和闭合；`{-0.1,1.1}` 和含 NaN 的分布均被拒绝。
- W11 对 position、velocity、density、pressure、mass 在 valid 下逐项检查；检查全时间生命周期连续、无后生身份、固定分辨率粒子质量不随时间变化及数组形状一致。
- 开发包先在 `.partial` 路径完成材料增强和全部审计，通过后才原子替换最终文件。失败重建不会抢先发布最终文件名，也不会覆盖已有合格目标。

## 状态语义

`work-packages.json` 升级为 schema 2，保留历史 `status=complete`，但明确它只代表上一轮执行结束。每项新增 `execution_status`、`acceptance_status`、`validation_scope` 和 `open_blockers`。W07/W08 明确为设计完成、实验未验收；W03 为 provisional；W10 为 development snapshot。

这些修复关闭了已知反例，不等于材料轨迹或所有家族已经取得科学验收。下一项 G2 将直接攻击隔壁插值、运动壁面、示踪质量代表性和采样误差分离。
