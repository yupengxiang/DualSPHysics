# Core continuation status — 2026-09-28 — UPDATE-274

## F8 R008 attempt/output binder single-link hardening

本轮审计对照 F8 native-integrity proposal v7 §3 与 UPDATE-236 的 bounded synthetic attempt/output binder。合同要求每个 writer artifact 是 `st_nlink == 1` 的 single-link regular file；原有 `f8_r008_attempt_output_binding_diagnostic_v1.py` 已使用 no-follow FD、dev/inode、长度和 SHA-256 复核，但未检查 link count。因此一个位于输出 root 外的 hard-link alias 仍可能被结构层接受。

本次只在现有 v1 binder 内补齐该合同约束：path pre-stat、held FD stat 和读后 path stat 均要求 `st_nlink == 1`，并将 link count 纳入读前/读后稳定身份比较。新增合成负测创建 root 外 hard link，确认结果为 rejected、`artifact_identity_bound=false`、`gate_decision_eligible=false`、credit `0`。没有改变输入/输出 schema，也没有让诊断层认证 source、runtime、producer 或 fresh-root 历史。

验证结果：binder 专项 **10 passed**；与 fanotify raw parser、final-fput reducer v1/v2/v3、PartOut/RunPARTs diagnostic、RunPARTs/RealStr cadence 及既有相邻合同联合回归 **132 passed**；`python3 -m py_compile` 与 `git diff --check` 通过。

本轮只使用 pytest 临时目录和 synthetic bytes；未读取 production bundle/frame/HDF5，未运行 GenCase/native decoder/solver/worker/GPU/queue，未执行特权或 filesystem probe，未修改/重写历史 receipt、registry、ledger、denominator 或 gate。结果仍为 diagnostic-only，`source_authenticated=false`、`runtime_authenticated=false`、`native_integrity_evaluated=false`、`T1_numerical=false`、`qualification_credit=0`。
