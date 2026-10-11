# F1 三维水深开发数据：内部诊断版本 v1

本卡对应内部诊断版本 `ds-data-02-upstream-first-f1-depth-development`。H050、H052、H058、H060 均已完成完整数据包、独立路径重放和实际字段篡改验收，交付完成 4/4。完整证据见 `M4_RELEASE_FINAL_V1.json`，正式读取索引见 `M4_INTERNAL_DATASET_V1.json`。历史检查点及失败产物保留。

## 条件与范围

全部条件源自 DualSPHysics v5.4 官方三维 mDBC 溃坝案例，初始水深分别为 0.50、0.52、0.58、0.60 m，粒子间距 0.01 m，求解时间 6 s，名义保存间隔 0.025 s。水深是物理变化；保存间隔相对于母例的 0.01 s 是单独的数值输出差异。母例水深 0.55 m，保持 reference-only。

| 条件 | 初始流体节点 | 固定边界节点 | 当前完整产品验收 |
| --- | ---: | ---: | --- |
| H050 | 591,822 | 363,597 | 已完成 |
| H052 | 615,978 | 363,597 | 已完成 |
| H058 | 688,446 | 363,597 | 已完成 |
| H060 | 712,602 | 363,597 | 已完成 |

同一物理条件的保存窗口、重复运行或分辨率变化不增加条件数量。四个子例具有共同上游母例谱系，全部归入 development；validation 为空。没有独立留出或泛化评估信用。

## 数据字段与来源

数据保留所有初始数值节点和所有 241 帧，包含固定边界，采用 `(Zone,Idp)` 初始身份轴及逐帧 `valid`。节点缺失时保留身份槽位；相应数值使用 NaN 并标记无效，不能插值成仍然存在的粒子。

| 字段 | 单位 | 来源与含义 |
| --- | --- | --- |
| time | s | 原始 BI4 TimeStep；保留真实保存时刻，不重定时 |
| position / velocity | m / m·s⁻¹ | 原始 BI4 全空间数值状态 |
| density | kg·m⁻³ | 原始 BI4 密度 |
| mass | kg | BI4 MassFluid/MassBound 按节点类型还原，并与官方 PartVTK 检查 |
| pressure | Pa | 由原始密度和每帧 B/Rhop0/Gamma 计算的 EOS 压力；不是实验压力真值 |
| particle_id / particle_zone | 无量纲 | 数值 Idp 与 BI4 Piece；共同形成身份键 |
| type / mk | 无量纲 | 原始数值类型、生成输入块标记 |
| initial_type / initial_mk / initial_mass | 对应单位 | 完整初始身份轴上的类型、块和质量 |

实际末帧时刻可能略晚于名义 6 s，原始时间不作修剪或拟合。H050、H052、H058、H060 末帧依次为 6.000021271086452、6.000016628849316、6.000044150477992、6.000015461415244 s。观测曲线比较使用已声明的共同时间窗，不能把这种保存时刻差异解释成新的物理条件。

几何和控制由真实生成 XML、工况 manifest 与语义差异共同绑定。几何包括官方中央障碍物及初始水体；控制保留求解器、边界、输出间隔、物理常数和数值配方。父元数据、子工况所有者元数据及实际 XML 的哈希分别保存，原始母例元数据不被就地修订。

## 数值输运标签

标签将帧零和末帧按同一数值身份键连接，保存源/目的有效掩码、位置、位移和标签。有效端点分别为 `valid_source`、`valid_destination`；缺失端点保持 `unknown` 或 `censored`。原生 PartOut 数值排除原因与排除时刻单独保留。H050 的 766 个、H052 的 679 个、H058 的 672 个、H060 的 726 个末帧缺失节点分别与原生 position 排除记录一致。

这些标签用于数值来源—去向诊断，不宣称连续材料轨迹，也不把数值排除推断成流体的物理消失、出流或最终归宿。边界节点可以有效存在；分析流体时须使用实际 type/mk 和 valid 掩码。

## 读取与验收

每个独立搬迁包包含 `normalized.h5`、几何/控制侧车、interface、reader manifest、无模型 evaluator，以及 `runtime/m4_portable_adapter.py` 和 `runtime/l2_reader.py`。实际搬迁路径以完成的 actual-validation receipt 为准，不能从准备请求推测。

在包含 numpy、h5py 的 Python 环境中执行包内校验器：

```sh
python <搬迁包绝对路径>/runtime/m4_portable_adapter.py validate --bundle-root <搬迁包绝对路径>
```

真实验收使用 bubblewrap 屏蔽原始工况的求解器、生成输入、审计、转换及原始包路径，并从 `/srv/runtime` 读取搬迁包内代码，重新检查所有字段、标签和 evaluator。Python 环境是明确的运行依赖，数据包不包含整个解释器环境。

另对独立私有副本修改 endpoint Zone 身份或有效目的位置，再重新绑定 HDF5、interface、reader manifest 和 bundle manifest 的哈希。生产校验器必须因身份语义或位移一致性拒绝它们；校验后移除私有副本，核对原始包未变。

H050 的首轮搬迁副本位于准备阶段目录，这是请求占位符展开造成的路径问题。真实隔离重放有效，5,354,865,799 字节已一次性补入共享累计账本，原始收据保留。后续队列在正式授权请求前重绑定目标路径，使新副本落在计费的最终验收目录内。

## 用途资格

已完成工况可用于内部读取、数值身份与有效性诊断、几何/控制检查、来源—去向标签检查及模型无关工程评估。M3 中 H050/H060 已有实际 H1–H4 与 P1–P8 母例比较，差异及排除记录保留。

本版本没有 Q-N、Q-E、数值收敛、实验真值、物理归宿或留出泛化声明。本轮未执行模型训练、学习推理或隐藏模型测试，也未公开发布。四条件版本已通过全部实际数据包、重放、重新计算哈希的两种负例及源数据未变验收，共八项实际篡改检测；最终共享账本审计已结算全部实际任务。

## 正式搬迁包

每包均保留自身 reader、evaluator 和 runtime；本索引与数据卡放在本地控制工作区，大文件在 NAS。

| 条件 | 搬迁包绝对路径 | normalized.h5 字节数 |
| --- | --- | ---: |
| H050 | `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1/UF_F1_MDBC_DP010_H050/m4-relocation-preparation-001/m4-actual-validation/relocated/UF_F1_MDBC_DP010_H050` | 5,354,766,153 |
| H052 | `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1/UF_F1_MDBC_DP010_H052/m4-actual-validation-001/m4-actual-validation/relocated/UF_F1_MDBC_DP010_H052` | 5,546,390,732 |
| H058 | `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1/UF_F1_MDBC_DP010_H058/m4-actual-validation-001/m4-actual-validation/relocated/UF_F1_MDBC_DP010_H058` | 6,129,473,917 |
| H060 | `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1/UF_F1_MDBC_DP010_H060/m4-actual-validation-001/m4-actual-validation/relocated/UF_F1_MDBC_DP010_H060` | 6,321,165,817 |

## 按帧读取

以下示例使用索引中的正式搬迁包。reader 首次读取会验证完整 HDF5 哈希，随后在同一个 manifest 对象中复用验证记录。

```python
import json
from pathlib import Path
import sys

index = json.loads(Path('/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/M4_INTERNAL_DATASET_V1.json').read_text())
condition = index["conditions"][0]
bundle = Path(condition["bundle"]["root"])
sys.path.insert(0, str(bundle / "runtime"))
import l2_reader

manifest = l2_reader.load_manifest(bundle / "reader-manifest.json")
frame = l2_reader.read_frame(manifest, condition["case_id"], 0,
    fields=("position", "velocity", "density", "mass", "pressure", "type", "mk", "valid"))
print(frame["time"], frame["position"].shape, frame["valid"].sum())
```

F1 当前参考包为 `F1_REFERENCE_PACK_V4.json`，F5 为 `F5_REFERENCE_PACK_V2.json`；原始清单和旧版本保留。F5 的 ODS 比较只覆盖 [2,15] s，300 个请求样本没有完整参考支持；[2,30] s 分析波参考比较的负结果也保留。M1 的交接完成不代表这些科学限制已消失。

资源证据见 `m4-cost-audit/checkpoints/M4-resource-audit-final-v1.json`。H060 第一轮转换超出磁盘预约而失败，其 13,100,411,143 字节和实际 CPU 已保留并计费；新转换器只保留一帧解码 scratch 后完成 direct002。CPU 总账包含母例完整帧审计的 3600 核秒保守上限结算，不把它冒称为实测耗时。
