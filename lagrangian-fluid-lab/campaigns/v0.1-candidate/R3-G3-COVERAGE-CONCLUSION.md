# R3 G3 结论：覆盖度与 topology holdout 审计

状态：**审计完成；W08 的连续轴矩阵仍是 design-only。F1/F2/F3 topology holdout 已完成独立的 declared→executable→run→structural 链接但保持 candidate/rejected；F6 仅完成 GenCase 与微时域 solver structural probe，尚无归一化轨迹；正式覆盖仍为零。**

## 逐级结果

登记表中的 30 个案例均有定义、均有成功求解记录，30/30 的轨迹数组通过结构审计；W01 的质量门通过 29 个，1 个（粗分辨率 O5 wave-runup）保留为预期失败。这个结果只说明早期机制探针的流水线完整，不能把 29 个 `accepted_probe` 当成物理参考真值。

| 家族 | declared | executable | run | structural | quality pass | 外部参考质量 | pilot T1 | learned eval |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| F1 | 4 | 4 | 4 | 4 | 4 | partial_external_anchor | 4 | 1 |
| F2 | 3 | 3 | 3 | 3 | 3 | no_external_anchor | 5 | 1 |
| F3 | 5 | 5 | 5 | 5 | 5 | partial_external_anchor | 3 | 1 |
| F4 | 4 | 4 | 4 | 4 | 4 | no_external_anchor | 0 | 0 |
| F5 | 6 | 6 | 6 | 6 | 5 | no_external_anchor | 0 | 0 |
| F6 | 6 | 6 | 6 | 6 | 6 | partial_2d_anchor_and_rejected_3d_test14 | 1 | 0 |

## 顶层状态语义

`work-packages.json` 中 13 个 package 的旧 `status` 全部为 `complete`，但这是历史兼容字段，不是科学验收或覆盖声明。当前审计将 `execution_status`、`acceptance_status`、`validation_scope` 和 `open_blockers` 单独保留：其中 3 个 package 只达到有限工程范围的 accepted 状态，10 个 package 虽有旧的 `status=complete` 但没有工程 accepted 状态。W08 的 authoritative 状态是 `execution_status=partial_materialization`、`acceptance_status=not_experimentally_accepted`，与连续轴 `design_only`、拓扑候选部分实体化的覆盖判定一致。

W08 的 204 张连续轴卡和 196 个唯一 execution unit 全部仍是 `planned_not_run`，没有与 registry、solver attempt、轨迹或训练/评测产物建立链接；连续轴 `coverage_claim=false`。另外显式声明的 W08 topology card 位于独立命名空间，不计入 204 张连续轴卡。

四个已声明 topology holdout 中，完整的 GenCase→solver→归一化 HDF5→结构链已完成的家族为 **F1, F2, F3**，仅完成可执行/solver structural probe 的为 **F6**，仍 planned-only 的为 **none**。每个案例都使用独立 `physical_case_id`/`lineage_group_id`，definition、运行证据和 candidate-only 验收状态由各自 materialization manifest 追溯；F6 明确没有归一化 HDF5，因此不计入 trajectory coverage。旧 registry probes 仅作 incidental 对照，未被挂到第二个 split。F1/F2/F3/F6 的 W07 planned card 数分别为 6、8、6、8；W07 卡仍不是生成数据。

## 训练/评测覆盖

W11 development pilot 为 13 例（train 6、validation 3、test 4）。T1 粒子 rollout 所需字段在 13 例都有；其中 12 个流体案例现在已经链接有限边界三角形 sidecar，但 HDF5/material 仍声明 `wall_visibility` 未提供，且没有 wall-aware destination specification，所以 T2 完整任务仍为 0 例；T3 的外部 observable reference 和 T4 的 terminal destination/event history 均为 0 例。selection 与 release 的 ID、split、谱系、校验和及 root-attribute 交叉审计单独记录。W12 真实 autonomous baseline 有两个路线、三种子，但实际测试案例只有 3 个（其中 2 个在 30-case registry 内），不能代表 13 例 pilot 或六个家族。

## 判定和下一步

“每族至少三个背景”在现有探针层面满足，但这是 breadth gate，不是 acceptance gate。所有家族的 reference-quality gate 仍未通过，因此当前没有任何 family 可以直接进入正式 v0.1 或 20–30 例生产 tranche。

下一步应对 F1/F2/F3 topology 候选补做分辨率与外部参考验收，对 F6 补齐归一化轨迹、较长时域和耦合物理验证；在通过前全部保持 `candidate/rejected`。随后把已生成的边界 sidecar 纳入 wall-aware material contract，补齐 destination、T3/T4 任务字段，再按通过 reference/resolution 门的家族运行小规模 development tranche。不要把 W08 204 张连续轴卡一次性提交给 GPU。

机器可读明细见 `r3-g3-coverage-audit.json`。
