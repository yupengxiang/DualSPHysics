# Recipe card: W2-A mDBC + explicit normals（受控失败）

状态：`diagnostic_failed_or_unknown`；不可作为 T1、development、training 或 release 配方。该卡只记录一次边界表示假设检验。

## 控制设计

固定 h11=`0.506 m`、fine、`dp=0.010 m`、CFL=`0.05`、时间轴、流体几何和其他数值常数；仅改变边界表示：

- `Boundary=2`（mDBC），`SlipMode=1`；日志确认 `Boundary="mDBC"`。
- `GeometryForNormals` 生成 bottom/left/right/front/back 五个闭合面；open top 不生成法向，也未注册为 absorber。
- `normals active=true`，`geometryfile=[CaseName]_hdp_Actual.vtk`，`distanceh=2.0`，`svshapes=true`。

输入和生成物：

- `cases/L1_W2_A_BOUNDARY_MDBC_h11_fine_dp0p01_cfl005/L1_W2_A_BOUNDARY_MDBC_h11_fine_dp0p01_cfl005_Def.xml`
- `artifacts/W2-A-boundary-mdbc/L1_W2_A_BOUNDARY_MDBC_h11_fine_dp0p01_cfl005/generated/L1_W2_A_BOUNDARY_MDBC_h11_fine_dp0p01_cfl005.xml`
- `artifacts/W2-A-boundary-mdbc/L1_W2_A_BOUNDARY_MDBC_h11_fine_dp0p01_cfl005/generated/L1_W2_A_BOUNDARY_MDBC_h11_fine_dp0p01_cfl005_hdp_Actual.vtk`

## 结果

solver 返回 code 0、保存 1501 帧，但完整审计失败：60,060 个初始身份中 49,769 个被 native `position` 排除，最终只保留 10,291 个（保留率 `0.1713453213`）；首个闭壁越界在 `t=0.130014 s`，1371 帧越界，最大闭壁外质量 `18.3140009 kg`。因此该假设不扩展。

完整机器证据：`l1-w2-boundary-control.json`、`audits/L1_W2_A_BOUNDARY_MDBC_h11_fine_dp0p01_cfl005.json`、W2 attempt 目录中的 `Run.out`、`RunPARTs.csv` 和 `CfgInit_Normals*.vtk`。
