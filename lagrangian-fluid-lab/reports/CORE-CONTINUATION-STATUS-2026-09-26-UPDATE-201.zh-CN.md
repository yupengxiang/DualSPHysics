# UPDATE-201：F8 R008 辅助输出按已验证群体闭合

时间：2026-09-26（Asia/Shanghai）

## 本次推进

把 UPDATE-200 对 DualSPHysics v5.4 CPU writer 的静态结论接入 F8 R008 auxiliary output inventory。inventory 现在通过 held lab-root FD 安全读取并 SHA-256 锁定五份官方 writer 源码（`JSph.cpp`、`JDsPartMotionSave.cpp`、`JPartMotRefBi4Save.cpp`、`JDsPartFloatSave.cpp`、`JPartFloatInfoBi4.cpp`）；任一源码漂移或无法安全读取都会 fail closed。

清点器以 B 阶段已验证的 XML/BI4 particle cohorts 和 C 阶段非空、manifest-bound primary BI4 frame axis 推导预期：moving/floating 均为零时拒绝出现 `PartMotionRef*` 或 `PartFloatInfo*`，并将这两个输出族标为 `not_applicable_zero_population`；群体非零时要求相应 main file 在 C 输出 manifest 中，第二路 extra stream 仍仅作观察、不推断运行配置。其他辅助流以及资格 gate 仍保持 unresolved/false/zero credit。

## 验证

- auxiliary output inventory 定向 suite：30 passed。
- Head/Info、Motion/Float、PartExtra、RunPARTs/PartOut 相邻扫描 suites：82 passed。
- 两个 Python 文件 `py_compile` 通过，`git diff --check` 通过。
- 回归使用临时合成 B/C bundle；未读取或运行生产 solver bundle、生产 HDF5/frame，也未启动 GenCase/native decoder、solver、worker、GPU 或 queue。
- 当前 Core 总控只读复核：`can_finalize=false`；T1 家族 F3/F4（2/3），macro T2 0/2，正式训练 0/9，固定 T1 target 缺 432、material target 缺 288；独立复现 false，`issues=[]`。本次没有更改上述 gate、registry、ledger 或 qualification receipt。

## 边界与后续

此实现只约束已锁定官方 CPU writer 下的 population-conditional 主输出，不验证任一真实 C invocation 是否使用该源码/argv，也不核验实际输出树、额外保存间隔或 `SvExtraParts`。F8 R008 的可信执行来源和完整 15-case 真实 solver 证据仍未闭合；本更新不构成资格、readiness 或实验完成。
