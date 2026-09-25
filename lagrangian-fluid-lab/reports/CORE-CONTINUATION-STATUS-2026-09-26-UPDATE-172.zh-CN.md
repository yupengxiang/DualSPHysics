# UPDATE-172：F8 R008 PartExtra 接入 B/C 闭合输出清单

时间：2026-09-26（Asia/Shanghai）

## 本次推进

新增 `f8_r008_auxiliary_output_inventory_v1.py`，提供只读、diagnostic-only 的 B/C bundle 配对检查。它分别调用现有 stage verifier 检查 B、C 的授权绑定、receipt、manifest 与封闭 `outputs/` 文件树；要求 C receipt 的 `materialization_receipt_binding` 精确指向当前 B receipt。B verifier 已重算的 particle cohorts 用来推导 `CaseNbound=fixed+moving+floating` 与 `CaseNfloat=floating`，不接收 caller 提交的人口数字。

对 C manifest 中每个根目录 `PartExtra_####.bi4`，新诊断都以 `O_NOFOLLOW` beneath-open 的 held FD 调用既有 PartExtra finite parser，并按 manifest SHA/bytes、文件 identity、文件名 `Cpart`、B 阶段人口以及对应 `frames/Part_####.bi4` 的实际 `TimeStep` 位模式交叉核验。对应主帧的 PART item name、原生 `Cpart:uint`、`Step:uint` 和 root 粒子群计数也须分别与清单序号、PartExtra `Step`、B cohorts 相符；关键 metadata 在本层显式要求唯一且类型正确。扫描末尾重新打开每个用作配对的主帧，复核 held `ScanResult.input_identity` 和 manifest SHA，以关闭同 inode 写入后恢复原字节的竞争窗口。扫描前后再次校验 B/C stage 和 held 目录/文件身份；诊断不写回任何 bundle。

C manifest 的每个文件均获得路径、长度、SHA 与分类记录：主帧明确标为本诊断未扫描；PartExtra 列出 finite 计数；`RunPARTs.csv`、单/多 piece `PartOut`、`Part_Head.ibi4`、`PartInfo.ibi4`、`PartMotionRef[2].ibi4`、`PartFloatInfo[2].ibi4` 识别为已知但尚未由本入口做完整 finite scan 的辅助格式；其他输出保留为 `unclassified_output`。闭合 manifest 只证明当前 bundle 中的输出文件清单闭合，**不**证明某个可选输出模式本应开启。若清单里没有 PartExtra，返回值明确写作“没有观察到成员、预期未知”，不推断为禁用。

因此本次补上了 PartExtra 的 B/C bundle membership 与同帧关联，但没有关掉 `native_state_finite`：完整辅助输出模式期望、PartOut/RunPARTs 数值有限性、motion/floating 输出、剩余未知输出、source/runtime 认证与最终 gate/evidence 接线仍未完成。native integrity、T1、readiness 均未评估，资格信用为 0。

## 验证与边界

- Terra High/high 配置的只读代码复核初轮为 `REVISE`：指出主帧 Cpart/Step/name 配对、identity 复验及已知 writer 文件类别问题；按意见修复并补负测。Follow-up 再指出重复 metadata 唯一性；在读取处加入显式唯一/类型检查及 `CaseNfloat`/`Cpart`/`Step` 重复值负测。最终 follow-up 无剩余 P0–P3。两轮 reviewer 均不能独立 attestate Terra High 模型身份，故这不记为 Terra High verdict。
- 项目 `.venv` 下六个相关 suite：**117 passed**，覆盖新 bundle 诊断、PartExtra finite parser、主帧 finite inventory/scan、native-state evidence 和完整 per-case bundle verifier。首次综合回归曾因合成 BI4 wrapper 未转发新增 keyword-only `Cpart`/`Step` 参数导致 3 项 fixture TypeError；修正 wrapper 后全套复跑通过。
- Python `py_compile` 与 `git diff --check` 通过。系统 Python 的 h5py/NumPy ABI 不兼容导致 evidence suite 首次收集失败；改用仓库 `.venv`（NumPy 2.2.6 / h5py 3.16.0）后，同一套六个 suite 全部通过。
- 所有新增 bundle 输入都由合成测试 fixture 构造。未读取生产 B/C bundle、PartExtra、frame 或 HDF5；未调用 GenCase、native decoder、solver、worker、GPU、queue；未改 registry、ledger、资格分母或既有 evidence。
- 所有输出保持诊断态：`native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false`、`qualification_credit=0`。

## 后续

1. 将已有 PartOut/RunPARTs 结构诊断接入同一 C bundle 文件清单，并为其浮点 payload 增加完整 finite scan；仅解析 ID/Motive/count 不能关闭 finite 清单。
2. 审计并扫描 PartMotionRef、PartFloatInfo 及其他 CPU native auxiliary 格式；对未知类型继续 fail-closed。
3. 绑定可信输出模式配置/实际 invocation 与终端完成证据，以区分“未输出”与“输出缺失”；随后再接 source/runtime trust 和独立 native-integrity gate。
4. 当前 R002 因 GenCase 输入缺陷关闭且没有成功 C bundle，本实现仅经合成闭环测试。待将来另有明确授权的新 candidate 形成真实 B/C bundle 后，才能执行只读生产验证；不重试 R001/R002。
