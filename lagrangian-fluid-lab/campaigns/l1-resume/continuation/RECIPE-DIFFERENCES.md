# Q1/Q2 数值配方逐项对照

来源与完整 XML/Run 字段、摘要见 RECIPE-DIFFERENCES.json。unknown 表示 Run 未报告，不能从源值假装已确认运行值。

| 字段 | 类别 | Q1 源 | Q1 实际 Run | Q2 源 | Q2 实际 Run |
|---|---|---|---|---|---|
| StepAlgorithm | discretization | 2 | "Symplectic" | 1 | "Verlet" |
| Kernel | discretization | 2 | "Wendland" | 2 | "Wendland" |
| ViscoTreatment | stabilization | 1 | "Artificial" | 1 | "Artificial" |
| Visco | stabilization | 0.01 | 0.01 | 0.08 | 0.08 |
| ViscoBoundFactor | stabilization | 1 | 1 | 1 | 1 |
| DensityDT | stabilization | 3 | "Fourtakas et al 2019 (full)" | 2 | "Fourtakas et al 2019 (inner)" |
| DensityDTvalue | stabilization | 0.1 | 0.1 | 0.1 | 0.1 |
| Boundary | discretization | 2 | "mDBC" | 2 | "mDBC" |
| SlipMode | discretization | 1 | "DBC vel=0" | 1 | "DBC vel=0" |
| NoPenetration | discretization | 0 | False | 0 | False |
| Shifting | stabilization | 0 | "None" | 0 | "None" |
| DtMin | discretization | 0 | 2.192792678133564e-05 | 0 | 1.935891645194918e-05 |
| DtFixed | discretization | 0 | unknown | 0 | unknown |
| TimeMax | observation | 6 | 6 | 0.6 | 0.6 |
| TimeOut | observation | 0.01 | 0.01 | 0.001 | 0.001 |
| SavePosDouble | observation | 0 | False | 2 | True |
| RhopOutMin | runtime | 700 | 700 | 700 | 700 |
| RhopOutMax | runtime | 1300 | 1300 | 1300 | 1300 |
| hdp | discretization | {'value': '2', 'comment': 'Alternative option to calculate the smoothing length (h=hdp*dp)'} | 0.020000  (CoefficientH=1.1547; H/Dp=2) | absent | 0.017321  (CoefficientH=1; H/Dp=1.73205) |
| coefh | discretization | absent | 0.020000  (CoefficientH=1.1547; H/Dp=2) | {'value': '1.0'} | 0.017321  (CoefficientH=1; H/Dp=1.73205) |
| cflnumber | discretization | {'value': '0.2', 'comment': 'Coefficient to multiply dt'} | 0.2 | {'value': '0.05'} | 0.05 |
| coefsound | stabilization | {'value': '20', 'comment': 'Coefficient to multiply speedsystem'} | 45.60394616971211 | {'value': '20'} | 44.73522172181558 |
| rhopgradient | physical | {'value': '2', 'comment': 'Initial density gradient 1:Rhop0, 2:Water column, 3:Max. water height (default=2)'} | unknown | {'value': '2'} | unknown |

数值域属 runtime，采用 MapRealPos(final)，完整界限见各验收 JSON。规范几何、初始质量、COM、格点相位属 physical/discretization，实测见 GEOMETRY-AND-INITIAL-STATE.json。normal/ghost 保留距离语义。

Q2C3/C4 同时引入官方数值策略与明确的规范界面生成修订，属于系统级候选。Q2C4 另改格点相位，初始质量 58.905 kg，不能作为质量不变的单因素试验。
