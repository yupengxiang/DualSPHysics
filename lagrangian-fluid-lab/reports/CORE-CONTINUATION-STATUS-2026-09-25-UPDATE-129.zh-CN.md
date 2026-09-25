# Core 计划续推状态 UPDATE-129

## 本次推进：F8 R008 fluid table 到 Core 轨迹的诊断转换原语

新增 `scripts/f8_r008_core_trajectory_adapter_v1.py`，把已通过 native-fluid-table v2 语义复核的 F8 fluid-only HDF5 table 流式转换为 Core 可读 HDF5：保留原生 time、particle ID、position、velocity、mass、valid 和 density，并按 F8 全流体 cohort 合同补 `particle_zone=0`。案例 ID 必须属于冻结的 15 行资格分母，源表属性必须标为 `qualification_only`。

输入只接受 exact-size（不超过 table v2 上限）、只读/CLOEXEC/single-link 的 held table FD；先以同一 FD 和 caller 提供的 raw-frame stream 重算/校验表，再逐帧分块转换。输出在 held private-directory FD 下以 0600 临时文件写入，完整复读与逐 chunk 比较后才 no-replace 发布；发布后再次比较 held FD 与 basename 的 inode、类型、link count、size，并重算输出 SHA。目标已存在时拒绝覆盖。

结果被固定为 `qualification`、`formal_eligible=false`、`full_t1_decision=false`、零资格信用。Core adapter 实际读回此合成产物，并验证 `training_transition()` 因 qualification split 而拒绝。该 helper 没有接入 trusted B/C/D provenance、worker/scheduler 或 Womersley 15 格 T1 adjudicator；它只打通诊断格式转换，不关闭 F8 执行/资格门。

## 独立复核、测试与边界

- GPT-6 Luna Max 初审指出两项 P2：source size cap 必须在哈希前执行；最终内容验证后还要确认发布 basename 仍指向已验证 inode。两项已修正，并分别增加“不允许超限输入触发哈希”和“最终核验时模拟同 UID 文件名替换”的回归测试。针对修订的 follow-up 为 **PASS**，未发现其他 P1/P2。
- 新增转换器 5 项测试；与现有 F8 Core adapter、Core dataset、native-fluid-table v2 语义及 producer 测试共 **75 passed**。
- 新增 Python 文件 `py_compile` 通过，`git diff --check` 通过。
- 所有测试均使用临时 synthetic BI4/HDF5/控制输入；未读取生产 bundle/HDF5/BI4/solver frame，未运行 B/C/D、native decoder、GenCase、solver、worker、GPU 或 queue，未提权。

剩余关键项仍包括真实执行 provenance 与可信输入源、supervisor/key registry/runtime 闭环、F8 worker/scheduler、15-case T1 判定，以及后续 F8 readiness/solver 独立门。诊断轨迹不能作为训练数据或资格证据。
