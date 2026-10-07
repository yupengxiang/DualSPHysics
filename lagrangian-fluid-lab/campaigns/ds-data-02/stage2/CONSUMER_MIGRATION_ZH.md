# Stage 2 消费者收口记录

这份记录只描述消费者迁移边界，不改变 Stage 1 产物。旧脚本仍作为历史证据保留；第二阶段读取、观测标签和划分必须从 `CURRENT336.json` 的物理案例行开始。

## 旧依赖审计

| 历史消费者 | 已发现的依赖 | 迁移风险 |
| --- | --- | --- |
| `scripts/ds_data02_f1_stage8_labels.py` | `full-typed-native-conversion-*/trajectory.h5` 排序后取最后一个；固定 `ecc/dual` 案例列表 | 目录中新转换或残留目录可以改变来源，案例范围不会跟随336例目录 |
| `scripts/ds_data02_f2_stage8_labels.py` | 通过 `glob` 发现轨迹；固定 `CENTER_P01..P04` 与 `OFFSET_P01..P04` | 旧八例不是当前336例的可迁移索引 |
| `scripts/ds_data02_f3_stage8_labels.py` | 固定八例；按 `sorted(glob(...))[-1]` 选轨迹 | 同一物理案例的恢复/重转换可能被静默替换 |
| `scripts/ds_data02_f3_stage8_audit.py` | 固定八例；按目录排序寻找资格运行；成功收据不匹配时回退任意 `solver/Run.out` | 任意日志不能证明当前 HDF5、recipe 或 attempt 的身份 |
| `scripts/ds_data02_f5_stage8_labels.py` | 固定 Stage 8 列表和最新转换目录；生产定义用 glob | 旧生产集合与 CURRENT 的物理案例边界脱钩 |
| `scripts/ds_data02_f6_stage8_labels.py` | 固定案例列表和最新转换目录 | 不能表达当前刚体字段/生命周期未知状态 |
| `scripts/ds_data02_f7_stage8_labels.py` | 固定泵/障碍案例列表；按 glob 取最新轨迹 | 不能绑定运动面、控制和真实 CURRENT 行 |

以上脚本中的 glob、固定案例和任意 `Run.out` 只标为历史风险，不回溯污染已消费字节。可运行的机器审计是 `audit_legacy_consumers()`；它只报告发现，不执行旧脚本。

## 新接口

`scripts/ds_data02_stage2_consumers.py` 提供：

- `load_current_catalog()` / `Current336Catalog.case()`：要求 `ds02.stage2.current336.v1`、唯一 `physical_case_id`、336行、源目录哈希和 producer HDF5 哈希；支持显式最长前缀路径映射，绝不搜索目录。
- `CurrentCase.inspect()`：逐选中的 CURRENT 行核对轨迹字节/mtime、manifest/XMF 小文件哈希、HDF5 schema、字段形状/dtype/chunks、单位、坐标系、`(Zone,Idp)` 静态身份轴和真实时间窗。
- `CurrentCase.inspect()` 保留 `physical_case_id`、`manifest_physical_case_id` 与 `accepted_alias_evidence` 分列；4 个 F1 accepted alias 的 canonical inventory scope 和 actual converter scope 只作为两套证据保存，scope equality 永远为 `NOT_ASSERTED`。manifest 身份还要与对应 manifest payload 的 `physical_case_id`、family 和 schema 对齐。
- `read_case_window()`：只读取绑定案例的指定帧/粒子窗口，返回完整绑定信息；没有任意 `Run.out` fallback。
- `materialize_labels()`：生成新的 `ds02.stage2.observation-labels.v2` sidecar。初始流体质量分母是所有 `initial_type==3` 的正质量，包含初态无效身份；`valid=0`、`valid=1` 但 NaN/非正质量分别保留为 missing/invalid_state；身份复活、出生和自适应质量直接转为 unknown/失败，不补零轨迹。
- 移动面事件使用保存时刻的显式平面位姿和相对法向速度 `(u-u_surface)·n`。v2 只接受带明确法向、速度、孔径坐标系的轴对齐平移面；无法解释的旋转面不会静默按静态 AABB 处理。
- `prepare_sentinel_observation_plan()`：仅绑定14个哨点到 CURRENT，状态为 `NOT_MATERIALIZED`、QI/QN/QE=`UNKNOWN`，不批量宣称精确资格。
- `build_prospective_split()`：按已知 source/control/geometry lineage group 分配 development train/validation/test；同一谱系不得跨角色。336例均标 `stage1_seen=true`、`hidden_test=false`，不制造 hidden test 叙事。

真实 guard probe `scripts/ds_data02_stage2_current_probe.py` 仅读 4 个 accepted alias 加 F2/F3 各一例的 header、首帧和首身份。F2/F3 当前 manifest 均声明 `ds02.stage1.paraview-temporal-product.v1`，但 temporal contract/window 等内容不同，接口按 manifest payload 自身绑定，不把一个 family 的 schema 内容套到另一个 family。probe 不生成标签；执行收据位于共享数据根的 `families/infra/STAGE2_CURRENT_PROBE/current-probe-001/`，状态不代表任何 QN/QE 或精确资格。

`*_v2.py` 保留 v1 收据对应的源码快照，并修复三类边界：同一 alias 判定要求 manifest ID 明确不同且存在 provenance/evidence，普通 manifest ID 相等的 canonical 行可通过；`cumulative_crossing_count` 先在每个粒子 chunk 形成时间历史后再跨 chunk 相加；label chunk 按时间长度自适应，工作数组估算上限为 256 MiB，且拒绝浮点 chunk 截断。v2 对 active、valid 身份的非有限 velocity 直接返回 unknown/error，避免把带 NaN 的 event speed 写成 observed。

v2 的 prospective split 只使用 manifest/CURRENT 中的 physical-condition/common-lineage evidence 做连通分量，忽略 generated XML 与 numerical parameter hash。缺证据时整族闭合到 `PROVISIONAL_FAMILY_CLOSURE`，结果标 `split_safety=PROVISIONAL`，不宣称 split-safe；制造反例覆盖同一 physical condition 但 XML/数值 hash 不同仍同组。

每个标签的 `q_i_status=UNKNOWN`、`q_n_status=NOT_ASSESSED`、`q_e_status=NOT_ASSESSED` 是接口默认值；标签数值存在不等于数值资格成立。
