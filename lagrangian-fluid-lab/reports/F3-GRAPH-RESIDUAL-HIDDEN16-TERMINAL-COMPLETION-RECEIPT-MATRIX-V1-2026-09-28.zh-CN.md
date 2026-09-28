# F3 graph_residual hidden16 full835 终态回执矩阵 V1

该矩阵只绑定三个未来终态 JSON 回执：seed17、seed29、seed43。固定契约为：

- `model_kind=graph_residual`、`hidden=16`、`updates=500`；
- `case_id=F3_DEV_00_a0p903125`、`split=test`；
- 每个 seed 为完整 `835 transitions / 836 frames`；
- evaluation、progress、trajectory 使用唯一的 full835 diagnostic namespace；
- training receipt 与 checkpoint 的路径、大小、SHA-256、seed 和 update 必须一致；
- 独立 HDF5 validator 回执可以绑定，但不是矩阵输入的必需项。

适配器只读取受限大小的终态回执 JSON。它使用 descriptor-relative `O_NOFOLLOW` 逐级打开输入，拒绝重复键、非 finite 数值、路径穿越、符号链接、读取期间身份变化和超大文件；不会打开回执声明的 checkpoint、evaluation、progress、trajectory 或 HDF5 文件。

当前默认输入是尚未产生的未来终态回执，因此报告状态为：

```text
status=blocked_fail_closed
source_bound=false
diagnostic_only=true
formal/T1/T2/qualification=false
credit=0
```

`running`、`partial`、`legacy`、hidden/config drift、重复或复用的 artifact identity，以及任何非零 credit 都保持 fail-closed。该报告不修改 registry、ledger、denominator、gate、completion 或 PLAN。
