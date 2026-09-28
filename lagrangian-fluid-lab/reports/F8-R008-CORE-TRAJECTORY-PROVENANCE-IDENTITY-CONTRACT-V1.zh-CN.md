# F8 R008 worker/scheduler → Core trajectory provenance identity v1

状态：`synthetic_only_non_authorizing_core_trajectory_provenance_contract_design`

本合同只验证三份 bounded canonical JSON 的内部身份链：

1. 复用现有的 signed synthetic worker/runtime handoff；
2. 将 scheduler dispatch 精确绑定到 handoff digest、attempt/case/nonce、worker/runtime 以及 source/runtime/input/output pins；
3. 将 Core trajectory manifest 精确绑定到 dispatch、case 和 trajectory schema，并计算三段链的 canonical digest。

本合同不打开 trajectory/HDF5/BI4/solver frame，不启动、停止或排队 worker/scheduler，不认证生产 scheduler，不消费 ledger，不修改 registry/completion/gate。trajectory 只有 manifest identity，artifact 内容验证仍为 `false`。

授权边界固定为：`diagnostic_only=true`、`readiness_pass=false`、`T1_numerical=false`、`qualification_credit=0`。因此这不是 R008 的 T1 结果，也不授予任何生产执行权限。

剩余 blocker：生产 scheduler/runtime 身份、trajectory artifact 内容、terminal supervisor/final-fput/native-integrity 证据，以及 target kernel/source/build/runtime pin 仍未闭合。
