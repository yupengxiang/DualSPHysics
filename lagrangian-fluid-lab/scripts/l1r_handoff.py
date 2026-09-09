"""Build a truthful checkpoint handoff from observed continuation evidence."""

import json
from datetime import datetime, timezone
from scripts.l1r_continuation_evidence import LAB, OUT, write, check_budget
from scripts import l1r_q2_mdbc_bridge as q2


def main():
    budget = check_budget()
    q1 = json.loads((OUT / "Q1-ACCEPTANCE.json").read_text())
    oldq2 = json.loads((OUT / "Q2-TRAJECTORIES.json").read_text())
    q0 = json.loads((OUT / "q0-final/SUMMARY.json").read_text())
    metrics = json.loads((OUT / "Q1-OBSERVABLES.json").read_text())["metrics"]
    cases = []
    for name in (
        "Q2C3_OFFICIAL_CANONICAL_t06",
        "Q2C4_OFFICIAL_HALFGRID_t06",
        "F1_OFFICIAL_NS_NOP0_dp02_t15",
    ):
        a = json.loads((OUT / (name + "-AUDIT.json")).read_text())
        cases.append(
            {
                "case_id": name,
                "status": a["audit_status"],
                "initial_mass_kg": a["initial_fluid_mass_kg"],
                "final_mass_kg": a["final_valid_mass_kg"],
                "mass_retention": a["final_valid_mass_fraction_of_initial"],
                "max_wall_mass_kg": a["penetration"][
                    "max_outside_closed_container_mass_kg"
                ],
            }
        )
    failures = []
    for f in sorted(
        (LAB / "campaigns/l1-resume/runs/branches").glob("F3*/attempts/*/attempt.json")
    ):
        a = json.loads(f.read_text())
        text = (f.parent / "Run.out").read_text()
        failures.append(
            {
                "case_id": a["case_id"],
                "attempt": str(f.relative_to(LAB)),
                "returncode": a["returncode"],
                "saved_frames": len(list((f.parent / "data").glob("Part_*.bi4"))),
                "input_reader_error": "Line number is invalid" in text,
                "elapsed_seconds": a["elapsed_seconds"],
            }
        )
    state = {
        "status": "CHECKPOINT_PENDING_F3_ATTEMPT_REALLOCATION",
        "activity_closed": False,
        "baseline_commit": "f104e5409cec2c8dd4043f93ffc4f6c7cda96646",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "production_capability": "601-frame official native trajectory reader, explicit lifecycle/exclusion reconciliation, corrected finite-wall audit, and limited H2/H4 macro-observation reference; no T1 development tranche",
        "q0_cases_reaudited": len(q0["results"]),
        "q1_acceptance": q1["acceptance_status"],
        "f1_candidates": cases,
        "f3_attempts": failures,
        "f3_physics_status": "unknown: all six failed before time integration on empty auxiliary input",
        "f3_repair_status": "six repaired input packages passed native reader preflight; no repair solver launched",
        "remaining_dependency": "owner decision to reallocate 6 retry attempts inside original parent cap; F3 default cap remains 6",
        "qualification_attempts_used": budget["qualification_attempts_used"],
        "qualification_attempts_remaining": budget["qualification_attempts_remaining"],
        "formal_release": False,
        "development_status": "not_reached: no accepted T1 recipe/range; T2 and learning performance are not being used as blocking gates",
    }
    write("EXECUTION-STATE.json", state)
    table = "\n".join(
        f"| {r['case_id']} | {r['status']} | {r['initial_mass_kg']:.6f} | {r['final_mass_kg']:.6f} | {r['max_wall_mass_kg']:.6f} |"
        for r in cases
    )
    text = f"""# L1-R 续执行阶段性交接（2026-09-10）

**当前是阶段 checkpoint，活动未关闭。尚未得到合格 T1 开发配方或独立开发批次。** 已交付官方 Q1 的实际全帧读取、排除对账、几何审计和外部水位对照能力。本地桥接与官方整体模板候选均有实际短窗失败证据。F3 六次启动因本轮执行器的共同输入缺陷失败；修复已验证，重跑等待 F3 子额度调整，不能把它记作 F3 物理否定。

## 1. 本轮依据和边界

- 基线：`f104e5409cec2c8dd4043f93ffc4f6c7cda96646`，分支 `codex/lagrangian-fluid-exploration`。
- 已读取用户提供的续执行 ZIP 和后补 reviewer 全文，见 `source/`。ZIP 内七项 SHA256 检查通过。
- 历史 ChatGPT `read_thread` 接口不可用；没有声称读取完整历史、云端回写或 reviewer 通过。
- 用户要求是按 reviewer 规划推进、推送并交接；附件不是额外所有者签名。沿用原 L1 预算和期限。GPU 0–3、上游与 vendor、历史失败证据保留。

## 2. 已取得的能力与真实结果

### Q1：已有官方轨迹现已实际验收

`Q1-ACCEPTANCE.json`、`Q1-FINAL-GEOMETRY-FRAMES.json` 和 `Q1-OBSERVABLES.json` 是主入口。

- 复用原始 601 帧，**没有重跑相同官方 CFD**。新增本地 `campaigns/l1-resume/data/q1-native.h5`，大小 {q1['source_hdf5']['bytes']:,} bytes，SHA256 `{q1['source_hdf5']['sha256']}`。
- C++ 薄适配器调用未修改的仓库 `JBinaryData`；与独立 PartVTK 初帧逐 ID、位置、速度、密度、压力核对通过，见 `Q1-NATIVE-READER-VALIDATION.json`。压力来自原生 EOS，类型/Mk 由原生初帧按 ID 映射；缺失身份显式保留为 invalid，没有伪造后续位置。
- {q1['frames_checked']} 帧身份唯一、有效字段有限；固定边界位置未变。最终缺失 {q1['final_missing_identities']} 个身份，与 PartOut 的 {q1['native_excluded_unique_identities']} 个唯一身份完全一致，均为原生位置排除；没有身份重现。
- 质量 {q1['initial_mass_kg']:.6f} → {q1['final_mass_kg']:.6f} kg，保留率 {q1['mass_retention']:.8f}。{q1['frames_with_endpoint_wall_exceedance']} 帧超有限壁面容差；最大瞬时壁面异常质量 {q1['max_instantaneous_wall_exceedance_mass_kg']:.6f} kg。**整体粒子轨迹质量失败。**
- 采用官方自身有限水槽及障碍的 mDBC 实际界面（由源配置及实际 `hdp_Actual.vtk` 核对），没有套用 L1 小水箱。运行域来自实际 `MapRealPos(final)`。有效保存粒子域外帧为 0，与保存间隔内发生的 657 个原生位置排除不矛盾。
- H1/H2/H3/H4 水位 RMSE：{metrics['H1']['rmse']:.5f}/{metrics['H2']['rmse']:.5f}/{metrics['H3']['rmse']:.5f}/{metrics['H4']['rmse']:.5f} m。H2/H4 仅保留既有 W05 的有限宏观参照范围；H1/H3 存在显著不匹配。**没有新造事后通过阈值，也没有把有限水位用途升级成完整物理正控或 Gold。**
- P1–P8 提供原始测量与描述误差，dummy 支撑关闭；原生零值不等于支撑有效，0.01 s 输出不证明窄冲击峰精度，压力资格未通过。图见 `Q1-ELEVATION-COMPARISON.png`。

### 审计修复与旧 Q2 取证

- 实际 `finite_wall_audit.py` 已分开名义面跨越与终点容差异常。附件探针在真实模块上得到直达 `[1]`、细分 `[1,0]`，见 `REVIEWER-PROBE-ACTUAL.json`。
- 接触、回入、初始已在外侧、开口上方路径和未知运行域均有回归。未配置域返回 not_checked/null；超出保存时域的请求不再复用末帧。
- Q0 十个保留案例全部重评到 `q0-final/SUMMARY.json`，原报告不覆盖；未恢复任何旧 T1 资格。
- 旧 Q2 累计唯一超容差身份 {oldq2['unique_exceeding_identities']} 个、累计质量 {oldq2['cumulative_unique_exceeding_mass_kg']:.6f} kg；其中底壁 14、右壁 19。最大深度 {oldq2['max_depth_m']:.8f} m，发生在右壁，约 2.017 dp。最大瞬时质量仍为 {oldq2['max_instantaneous_mass_kg']:.6f} kg。
- 最早超容差身份在 0.403014 s 异常，其几何跨面区间已在 0.374014–0.375002 s。全部相关身份的持续时间下界、边角距离、最终位置、最早/最深轨迹片段见 `Q2-TRAJECTORIES.json`。这些是保存区间定位，不是精确连续事件。

### 两个本地候选和官方整体派生均已实际执行

完整差异见 `RECIPE-DIFFERENCES.md/.json`。官方源是 StepAlgorithm=2、Visco=0.01、DensityDT=3、h/dp=2；旧 Q2 是 1、0.08、2、h/dp≈1.732。

实测旧 Q2 边界节点/normal/ghost 重建底面为 z=0.005 m，而其声明底面为 0。新候选明确生成规范界面 z=0，未移动旧审计面迎合轨迹。法向保持距离语义，ghost 位移为两倍法向。间距和角点预检记录见 `GEOMETRY-AND-INITIAL-STATE.json`。

| 案例 | 质量状态 | 初始质量 kg | 最终质量 kg | 最大瞬时壁面异常 kg |
|---|---|---:|---:|---:|
{table}

C3/C4 各为 0.6 s；C4 调整半粒距格点相位，属于新初态表示，不能称作质量不变的单因素试验。官方整体模板对照为 1.5 s、no-slip，实际 Run 明确 `No Penetration=False`。三例均未通过短窗硬门，故没有扩大 F1 资格矩阵/试产。没有用 T2、F6 或模型表现封锁 T1-only 路径。

## 3. F3 失败、已完成修复与待确认边界

计划中的两个真实三维背景、三分辨率均已生成：规范水体 0.9×0.18×0.09 m；平槽及带挡板；dp=0.03/0.015/0.01 m，横向流体层数 6/12/18。最终单元中心规则在六档均匹配预声明体积质量；之前初态不一致的生成版本保留，没有当作 solver 数据。

**六次 F3 启动全部在时间积分前失败，0 个保存帧。** 原因是 GenCase 的同路径辅助文件复制警告导致加速度 CSV 被截成 0 bytes。执行器没有在第一次共同初始化错误后停止，这是本轮实现缺陷，不能归因于物理方法、GPU 紧张或外部实验缺失。

已完成：

1. 保存六个失败 attempt 和旧空文件；新建 `_INPUTFIX` 输入目录，几何/参数不变。
2. 恢复完整官方 CSV，逐文件 SHA256 一致。
3. 用原生 `JReadDatafile` 的同一读取循环检查，六份均有 167,001 行、0–8.35 s，覆盖拟运行 1.5 s；见 `F3-INPUT-REPAIR-READY.json` 和六份 `*-INPUT-PREFLIGHT.json`。
4. 启动前检查非空、哈希、原生解析和时域；执行/输入失败停止余下队列；已尝试案例禁止原地重新生成。

原计划 F3 上限为 6 次，失败也计数。现已询问所有者能否从父预算内拨出 6 次复试储备。**确认未到前，没有第七次 F3 启动。** F3 的物理质量、空间/时间资格、机制与材料结论仍未知；`F3-GATES.json` 和评分代码已备好，不能把参数卡或输入预检冒充这些结论。

## 4. 累计资源和验证

- 资格/诊断 attempt：{budget['qualification_attempts_used']}/56，余 {budget['qualification_attempts_remaining']}；六次 F3 初始化失败均已计入。GPU solver 累计约 {budget['gpu_solver_hours']:.4f}/64 GPU·h。
- 历史 CPU 计时不完整，因此保留已报告值并采用保守全活动时间上界预留，而非填 0；当前上界约 {budget['cpu_core_hours_upper_bound']:.2f}/512 core·h，**不是实测 CPU 用量**。见 `HISTORICAL-CPU-RESERVE.json`。
- 存储、磁盘余量见 `RESOURCE-PREFLIGHT.json`；原活动期限未重置，保守到期 2026-09-16 00:00 UTC。
- GPU4–7/UUID allowlist、单 solver、启动 6144 MiB及预估余量、运行 4096 MiB guard 保持；新增 UUID 连续绑定。CPU 后处理有两槽协调。没有宣称共机零性能影响。
- 最终测试结果见 `pytest-final.txt`；原生读取器检查、附件校验、真实模块探针与真实数据审计分别记录，不相互替代。
- 没有修改上游/vendor，没有强推、主线合并、正式发布、hidden-test 生成、训练或材料资格冒报。

## 5. Reviewer 优先审阅问题

1. Q1 的几何、657 个身份排除对账和逐观测范围是否表述充分；不要将整体质量失败抹去有限水位对照价值。
2. 修正后的几何跨面 locator、容差 episode 和未知运行域是否满足要求；旧/新审计差异均保留。
3. C3/C4 与官方整体派生的失败证据能否界定当前有限配方研究的范围；是否有值得另行预注册的具体假设。
4. F3 输入故障和六次浪费是否充分说明；修复后的六例是否可在所有者确认储备调剂后恢复。

这是可恢复的阶段交接，不是 `NO_GO_WITH_BRANCH_EVIDENCE` 的全路线物理否定，也不是 L1-R 活动完成或云端 reviewer 签字。
"""
    (OUT / "L1R-CONTINUATION-HANDOFF.zh-CN.md").write_text(text)


if __name__ == "__main__":
    main()
