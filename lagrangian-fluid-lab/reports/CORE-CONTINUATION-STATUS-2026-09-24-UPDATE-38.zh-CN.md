# Core continuation status — 2026-09-24 UPDATE-38

## Outcome

实现 F8 R008 native-state finite evidence v1 的合成数据路径：逐帧流式读取 held C raw BI4 的完整 `Pos`/`Posd`、`Vel`、`Rhop` 数组（包含 non-fluid 粒子），记录原生 dtype 下的 finite/NaN/±Inf 计数、数组 SHA 和极值原始位模式；完整时间轴及 observation-window membership 均保留。结果强制为 `native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false`、资格信用 0。

每帧 finite scan 现直接将同一个 decoder `ScanResult` 与 D safe-decode receipt、递归输出清单、数组字节哈希及确定性 XML 对照；收集前后重新校验 B/C/D provenance 与 metric-free table-v2 semantic chain。修订后的[实现合同](F8-R008-NATIVE-STATE-FINITE-EVIDENCE-CONTRACT-V1-2026-09-24.zh-CN.md)去掉了未使用的 metric-review receipt，并准确记载冻结路径式 verifier 的目录对象重绑定及其残余 TOCTOU 边界。

独立证据文件以输出目录上的 unnamed `O_TMPFILE` 写入、fsync/hash 后通过 procfs FD hard-link 原子 no-replace 发布。原子 link 为提交点；final inode/hash、目录 fsync、descriptor close 与输出目录路径绑定状态分别报告，不会把提交后故障误报成未发布，也不会自动覆盖/清理不可信 final name。

## 独立审查与验证

Terra High 首轮只读实现复核给出 `REVISE`，指出发布后状态、输出目录路径身份与 evidence-layer 负例覆盖需要加强。对应实现和测试已修订。随后请求同一 `gpt-5.6-terra` high 跟进复核，但代理服务返回 `Selected model is at capacity`；没有改用其他模型，也不宣称本修订已有 Terra High `PASS`。最终独立复审仍待模型可用后完成。

最终版本的两个新增测试模块：

```text
.venv/bin/python -m pytest -q \
  tests/test_f8_r008_native_state_finite_scan_v1.py \
  tests/test_f8_r008_native_state_finite_evidence_v1.py
23 passed
```

覆盖 float32/float64 原生位模式、signed-zero extrema tie、全非有限数组 null extrema、non-fluid NaN/Inf、粒子上限、held raw-frame 截断拒绝且不发布、D safe-decode 数组摘要不符拒绝且不发布、O_TMPFILE no-replace、提交后校验失败状态及输出目录路径替换检测。`py_compile` 与 `git diff --check` 通过。较早的相邻 decoder/B/C/D/table/D-producer 联合回归为 161 passed（在本次发布硬化前）；本次硬化后的复验范围以两个新增模块 23 passed 为准。

## 边界与后续

所有正负输入均为 pytest 临时合成 B/C/D、BI4 与 table。未读取生产 bundle/solver frame，未调用 GenCase、native decoder、solver、worker、GPU 或 queue。当前双侧 stage/table 重验仍使用被冻结的 path API，held FDs 校验目录对象身份，但不构成 filesystem 原子快照；同 UID 并发篡改、授权/审查真实性、Python loaded-module/runtime identity 仍属外部信任边界。finite evidence 不是 native-integrity adjudication，也不闭合 density/Mach/wall/overlap/BoundNor 或 15-case 聚合规则。

下一步：模型容量允许后完成 Terra High high 的只读实现跟进复核；之后再推进 PLAN 中独立授权的静态/预检项目。F8 solver、T1、资格信用及 readiness 状态不变。详见 [PLAN.md F8 状态](../../PLAN.md)。
