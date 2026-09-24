# Core continuation status — 2026-09-24 UPDATE-46

## F8 R008 native fluid/window gate reducer v1（局部实现）

新增 `f8_r008_native_fluid_gate_reducer_v1.py` 和 synthetic-only 单测。reducer 针对一个已由上游语义验证的 native-fluid-table v2，在同一只读、单链接 regular-file FD 上复核尺寸与 SHA-256，并在读取前后再次核对文件身份和摘要；按冻结 R008 case 合同对完整时间轴与包含端点的三周期观察窗做检查，只计算该窗口内的密度闭区间 `[950, 1050] kg/m³` 与 `Mach <= 0.0010125`，以及窗口样本完整性。

输出只包含 8 个 registry gate 中的 3 个局部结果；`native_state_finite`、wall、excluded-fluid、overlap 和 control-no-extrapolation 五项明确保持未评估。该 reducer 不验证 B/C/D 证据字节，也不认证调用方传入的 table-verification 映射；调用方仍须在调用前后重验 B/C/D 来源链及 table 语义。输出将 `evidence_bindings_verified`、`native_integrity_evaluated`、`T1_numerical`、`readiness_pass` 保持为 `false`，资格信用为 `0`，不得把局部结果直接解释为完整 native-integrity/T1 判定。

Terra High 对实现与测试文本进行只读静态审查，结论 `PASS`，未发现阻断问题；reviewer 未运行测试。focused suite **12 passed**；native-table、per-case bundle、观察窗 parser 与 T1 metric adapter 相邻回归 **82 passed**；两文件 `py_compile` 通过。共使用临时合成 HDF5 fixture，未读取生产数据，未运行 GenCase/native decoder/solver/worker/GPU/queue。

下一步仍是静态推进：由调用方明确编排并重验 B/C/D 与 table 语义后，才能把这些局部 gate 状态安全接入 per-case 证据记录；其余五项 gate 的证据与裁决合同仍未完成。此次实现本身不产生生产证据或资格结果。
