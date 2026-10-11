# M3 upstream seven-family mother map (metadata only)

This crosswalk maps the current seven-family catalog to local DualSPHysics v5.4 definition/script candidates. It records source availability, configured controls and postprocessing outputs; it grants **zero equivalence or scientific qualification credit**.

## Boundary and provenance

- Official package: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4` (DualSPHysics5             v5.4.355            08-04-2025).
- Current catalog: `/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m3/scope_catalog.json`; `336` rows, `7` families, `335` saved-mask rows, `78` field-scan rows, `117` native joins.
- The 335/78/117 values are aggregate metadata counts. They do not make a case or family scientifically passed; all catalog QI/QN/QE remain UNKNOWN.
- The builder parsed selected XML and launch scripts only. CSV/DAT/ODS/XLSX/ZIP/VTK/STL and solver outputs are path/size pointers and were not opened.

## Family rollup

| Family | Current catalog contract | Best official match | Reference status | Main gap |
|---|---|---|---|---|
| F1 | eccentric lower-head / gravity release around a finite obstacle | STRONG_3D_CONFIGURATION_CANDIDATE | present | Do not transfer the official mother’s identity or any external-reference result to all 48 current F1 rows. |
| F2 | prescribed rotating offset cup with receiver/aperture transport | NO_EXACT_OFFICIAL_CANDIDATE | none found | The current F2 first-arrival, residence_mass_time and flux contract has no official metadata candidate with the required geometry and observable. |
| F3 | two-axis prescribed acceleration and sloshing response | NO_GENUINE_3D_OFFICIAL_SLOSHING_MOTHER | present | Four current F3 solver rows remain launch-only/incomplete in source closure; this mapping does not repair lifecycle evidence. |
| F4 | finite drop impact into a finite pool | NO_EXACT_OFFICIAL_DROP_INTO_POOL_CANDIDATE | present | No official exact candidate or exact reference chain was found for the current finite-drop impact family. |
| F5 | compact runup with prescribed forcing and recovery window | 2D_CALIBRATION_PLUS_PARTIAL_3D_RUNUP | present | Current F5 catalog has 48 source-bound development rows with QI/QN/QE UNKNOWN; official gauge presence does not qualify them. |
| F6 | free six-degree-of-freedom rigid release with fluid coupling | STRONG_3D_FLOATING_CONTROL_WITH_OBSERVATION_GAPS | present | Current F6 native join count is an identity/cause audit count, not pose/SE(3) or physical qualification. |
| F7 | finite wet-base tank with prescribed quintic moving obstacle | PARTIAL_3D_MOVING_PUMP_ONLY | present | Current F7 has 24 GenCase schema-unknown rows and five launch/incomplete rows; official candidate metadata does not close those lifecycle gaps. |

## F1: eccentric lower-head / gravity release around a finite obstacle

**Mapping.** The root-owned derivative design names UF_F1_MDBC_DAMBREAK3D; the official mDBC definition below is the matching 3D mother configuration. The existing F1 catalog mechanism and fill-depth variants still require explicit geometry/initial-state binding.

**Current observer contract.** mass [kg], COM [m], velocity [m/s], time [s].

| Candidate | Definition / dimension | Controls and configured observations | Available script outputs | References and hard gaps |
|---|---|---|---|---|
| `UF_F1_MDBC_DAMBREAK3D` (STRONG_3D_CONFIGURATION_CANDIDATE) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml`; 3D, dp=0.01 m | `elevation.txt`, `pressure.txt`; Definition: 3D gravity release, dp=0.01 m, tank plus central obstacle, mDBC Boundary=2, SlipMode=1, NoPenetration=0., Definition: TimeMax=6 s and TimeOut=0.01 s. | MeasureTool elevation histories from elevation.txt (with -elevation:0.5).; MeasureTool pressure histories from pressure.txt (press, k-correction and VTK/CSV products).; PartVTK fluid velocity/rhop/pressure and PartVTKOut excluded-fluid records. | `SPHERIC_Test2.zip` (Exists, but coordinate, initial-state, boundary and time-origin matching remain unproved.); `EXP_X-DamTipPosition_Koshizula&Oka1996.txt` (Reference is for the main/01 definition, not a demonstrated match to the mDBC obstacle mother.). Gaps: The official package directory has no same-directory experimental reference bound to this mDBC XML; elevation.txt and pressure.txt are point lists, not reference observations.; Current F1 catalog names eccentric lower-head / fill-depth variants; a family label does not prove this exact tank, obstacle, fill and sensor binding.; Mass, COM, obstacle fate and open-top return are not direct official gauge quantities; they need a declared postprocessor and acceptance contract. |

**Family-level gaps.**

- Do not transfer the official mother’s identity or any external-reference result to all 48 current F1 rows.
- Current catalog QI/QN/QE and split_safe remain UNKNOWN/false.

## F2: prescribed rotating offset cup with receiver/aperture transport

**Mapping.** No official XML metadata was found that combines a rotating offset cup, a receiver or aperture, and a transport/residence measurement. Pump and moving-square examples are nearest controls only and receive no family equivalence credit.

**Current observer contract.** mass [kg], first_arrival_time [s], residence_mass_time [kg*s], flux [kg/s].

| Candidate | Definition / dimension | Controls and configured observations | Available script outputs | References and hard gaps |
|---|---|---|---|---|
| `OFFICIAL_PUMP_ROTATING_BOUNDARY_PARTIAL` (PARTIAL_3D_ROTATING_BOUNDARY_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/13_Pump/CasePump_Def.xml`; 3D, dp=0.004 m | `pump_fixed.vtk`, `pump_moving.vtk`; Definition: 3D finite tank and moving pump meshes; mvrotace with 500 degrees/s^2, initial 90 degrees/s, axis points; TimeMax=6 s, TimeOut=0.02 s, PartsOutMax=0.9. | BoundaryVTK moving-pump and fixed-pump geometry histories.; PartVTK fluid and PartVTKOut excluded-fluid records.; IsoSurface products with velocity and density fields. | none found. Gaps: No cup, receiver volume, finite aperture crossing or gross/net flux observable is declared.; No same-directory experimental/analytic reference file was found for this pump candidate. |
| `OFFICIAL_MOVING_SQUARE_PARTIAL` (PARTIAL_2D_MOVING_BOUNDARY_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/03_MovingSquare/CaseMovingSquare_Def.xml`; 2D, dp=0.02 m | none; Definition: 2D moving square, gravity zero, mvrect velocity 2.8 m/s, TimeMax=2.5 s and TimeOut=0.01 s. | PartVTK fluid velocity/density/pressure/vorticity and moving-square boundary histories.; PartVTKOut excluded-fluid records. | none found. Gaps: No rotating offset cup, receiver/aperture, residence integral, flux sign convention or reference data. |

**Family-level gaps.**

- The current F2 first-arrival, residence_mass_time and flux contract has no official metadata candidate with the required geometry and observable.
- Keep the historical alias F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090 and F2H10V2_OFFSET_V1 manifest gap UNKNOWN as recorded by the catalog.

## F3: two-axis prescribed acceleration and sloshing response

**Mapping.** Official SloshingAcc is the exact control style for prescribed acceleration and has pressure/force postprocessing. Its definition bounds are 2D. A metadata sweep of all parseable official Sloshing/Slosh definitions found no 3D full-sloshing mother. CaseForces is recorded as a compact 3D acceleration fallback only; it is not a sloshing or externally referenced F3 candidate.

**Current observer contract.** COM/front [m], velocity [m/s], kinetic_energy [J], time [s].

| Candidate | Definition / dimension | Controls and configured observations | Available script outputs | References and hard gaps |
|---|---|---|---|---|
| `OFFICIAL_SLOSHING_ACC` (STRONG_2D_CONTROL_CANDIDATE_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingAcc_Def.xml`; 2D, dp=0.002 m | `CaseSloshingAccData.csv`, `CaseSloshingAcc_PointsPressure_Correct.txt`, `CaseSloshingAcc_PointsPressure_Incorrect.txt`, `FromMotionToAcc.txt`; Definition: 2D sloshing tank, dp=0.002 m, gravity -9.81 m/s^2, accinputs for mkfluid=0, acceleration centre (0.45,0,0), globalgravity=0, and external acceleration data file., Definition: TimeMax=8.35 s and TimeOut=0.01 s. | MeasureTool pressure and k-correction at correct and incorrect point sets.; ComputeForces tank force and moment CSV about a declared axis.; PartVTK all particles and PartVTKOut excluded-fluid records. | `EXP_Pressure_SPHERIC_Benchmark#10.txt` (Exists; coordinate, time-window and pressure convention still require explicit acceptance binding.); `CaseSloshing_Pressure_Probes.pdf` (Exists; documentation is not a numerical acceptance result by itself.). Gaps: The acceleration CSV was not opened; exact axis ordering, trajectory and window matching are unresolved by this metadata map.; Current family COM/front, velocity and kinetic-energy contract is not a direct official output contract; postprocessing remains required. |
| `OFFICIAL_SLOSHING_MOTION` (PARTIAL_2D_ROTATIONAL_CONTROL_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingMotion_Def.xml`; 2D, dp=0.002 m | `CaseSloshingMotionData.dat`; Definition: 2D tank with mvrotfile around the y-axis and the same 8.35 s / 0.01 s output schedule. | Moving pressure point positions, pressure/k-correction, tank force and moment, particle and excluded-fluid products. | `EXP_Pressure_SPHERIC_Benchmark#10.txt` (Same reference as SloshingAcc; motion-input equivalence is not implied.). Gaps: Rotation-file semantics and current two-axis family controls are not proven equivalent from filenames or family labels. |
| `OFFICIAL_EXTERNAL_FORCES_3D_COSTED_FALLBACK` (NON_EQUIVALENT_3D_ACCELERATION_CONTROL_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/04_ExternalForces/CaseForces_Def.xml`; 3D, dp=0.02 m | `CaseForcesData_0.csv`, `CaseForcesData_1.csv`; Definition: genuine 3D bounds, dp=0.02 m, two fluid IDs in finite boxes and a central sphere; separate acceleration inputs for mkfluid=0/1 with global gravity enabled., Definition: TimeMax=5 s and TimeOut=0.02 s; no sloshing pressure reference is declared. | PartVTK fluid mk/velocity/type/density/pressure and PartVTKOut excluded-fluid records. Planning only: about 24,879 fluid particles, 251 frames, and 0.2–0.6 GiB native before VTK. | none found. Gaps: This is a 3D force/acceleration test, not a tank sloshing benchmark; it has no external primary observable/reference file.; It cannot supply F3 sloshing COM/front, pressure or kinetic-energy acceptance without a new declared observer and reference. |

**Family-level gaps.**

- Four current F3 solver rows remain launch-only/incomplete in source closure; this mapping does not repair lifecycle evidence.
- No genuine 3D official full-sloshing mother with an external primary reference was found. The compact 3D CaseForces fallback is explicitly non-equivalent and reference-free.
- No 3D qualification credit is transferred from the 2D official examples or the non-equivalent CaseForces fallback.

## F4: finite drop impact into a finite pool

**Mapping.** The package contains a 3D Chrono dam-break with a floating cube and a 2D falling wedge, but no exact finite drop into a finite pool with the current impact/rebound contract.

**Current observer contract.** mass [kg], COM/front [m], impact_time [s], velocity [m/s].

| Candidate | Definition / dimension | Controls and configured observations | Available script outputs | References and hard gaps |
|---|---|---|---|---|
| `OFFICIAL_DAMBREAK_ONE_CUBE_CHRONO` (PARTIAL_3D_FLOATING_COLLISION_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/chrono/07_DamBreakCubes/DamBreak1Cube_Def.xml`; 3D, dp=0.0125 m | `Floating_Materials.xml`; Definition: 3D finite dam-break tank with floating cube, massbody=2.7, Chrono RigidAlgorithm=3, savedata=0.01 s, TimeMax=2 s and TimeOut=0.01 s. | PartVTK fluid/cube and PartVTKOut excluded-fluid products.; BoundaryVTK cube/tank motion, FloatingInfo motion data and IsoSurface products. | `EXP_COMP_CUBE1.xlsx` (Exists; cube/dam-break comparison is not a finite-drop impact reference.); `EXP_COMP_CUBE3.xlsx` (Exists; cube/dam-break comparison is not a finite-drop impact reference.). Gaps: Initial cube placement and dam-break forcing do not establish a released finite drop, finite pool impact time, or rebound censoring.; Current mass-weighted front/COM and impact_time require a typed observer contract beyond the listed postprocessors. |
| `OFFICIAL_FALLING_WEDGE_2D` (PARTIAL_2D_DROP_LIKE_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/vresolution/04_FallingWedge2D/CaseFallingWedge2DVRes_Def.xml`; 2D, dp=0.002 m | none; Definition: 2D floating wedge, massbody=241, initial linear velocity z=-6.15 m/s, gravity -9.81 m/s^2, Boundary=2, TimeMax=0.025 s and TimeOut=0.00005 s. | PartVTK bound/fluid velocity, density and pressure products. | none found. Gaps: No finite-pool drop reference, impact/rebound event file or external acceptance data is present in this example directory.; 2D wedge and variable-resolution controls cannot establish the current finite-drop family. |
| `OFFICIAL_FLOATING_SPHERE_VAL2D` (PARTIAL_2D_FLOATING_REFERENCE_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/11_Floating/CaseFloatingSphereVal2D_Def.xml`; 2D, dp=0.025 m | none; Definition: 2D floating sphere validation geometry with relativeweight=1.20, FtPause=1 s, TimeMax=6 s and TimeOut=0.02 s. | PartVTK fluid/floating and PartVTKOut products, FloatingInfo and surface slices. | `EXP_FloatingSphereVal2D_Displacement_Fekken2004.txt` (Exists; floating-sphere displacement does not establish drop-impact equivalence.); `EXP_FloatingSphereVal2D_Velocity_Fekken2004.txt` (Exists; floating-sphere velocity does not establish drop-impact equivalence.); `EXP_FloatingSphereVal2D.ods` (Exists; workbook was not opened by this map.). Gaps: 2D buoyant sphere validation has no finite drop/pool impact event and no current F4 source-cohort binding. |

**Family-level gaps.**

- No official exact candidate or exact reference chain was found for the current finite-drop impact family.
- Current catalog has 21 F4 GenCase receipt-schema-unknown rows; upstream examples do not close that lifecycle gap.

## F5: compact runup with prescribed forcing and recovery window

**Mapping.** CasePistonBeach_REG is the planned 2D calibration mother. CaseWaveRunup is the official 3D runup candidate with gauges and an external reference. The two are separate candidates; the 2D result cannot be counted as 3D coverage.

**Current observer contract.** front/runup [m], mass [kg], velocity [m/s], time [s].

| Candidate | Definition / dimension | Controls and configured observations | Available script outputs | References and hard gaps |
|---|---|---|---|---|
| `UF_F5_PISTON_BEACH_REG_2D` (STRONG_2D_CALIBRATION_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/09_WavesPiston/CasePistonBeach_REG_Def.xml`; 2D, dp=0.02 m | `elevation.txt`, `velocity.txt`, `CasePiston_SPHvsTheory.ods`; Definition: 2D regular piston beach, dp=0.02 m, wave height 0.15 m, period 2 s, depth 0.66 m, TimeMax=30 s and TimeOut=0.05 s., Definition: piston savemotion at xpos=6.0 and zpos=-0.26; wave gauge files are consumed by the launch script. | MeasureTool elevation and velocity histories, PartVTK fluid/piston, PartVTKOut, tracer and surface products. | `CasePiston_SPHvsTheory.ods` (Exists; workbook content and acceptance window were not opened by this map.). Gaps: Definition bounds are 2D; this candidate is calibration only and cannot satisfy the M1/M4 3D count.; Current F5 recovery/tail and mass-distribution observers are not all direct official gauge outputs. |
| `OFFICIAL_WAVE_RUNUP_3D` (PARTIAL_3D_RUNUP_CANDIDATE) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/17_WaveRunup/CaseWaveRunup_Def.xml`; 3D, dp=0.008 m | `Slope.stl`, `Blocks_3D_scaled.stl`, `Mov_piston.dat`, `wg1234.txt`; Definition: 3D slope/blocks runup, prescribed piston file, seven named swl gauges, dp=0.008 m, TimeMax=20 s and TimeOut=0.02 s. | MeasureTool wg1234 gauge histories, PartVTK fluid/piston, PartVTKOut, boundary motion and surface products. | `EXP_CaseWaveRunup_CIEMito.txt` (Exists; gauge coordinates, runup definition and time window require explicit binding.). Gaps: The official 3D geometry and piston are not the planned 2D PistonBeach input; no result or acceptance is borrowed across them.; Current compact-runup recovery/tail and mass observers need an explicit typed postprocessor and reference contract. |

**Family-level gaps.**

- Current F5 catalog has 48 source-bound development rows with QI/QN/QE UNKNOWN; official gauge presence does not qualify them.

## F6: free six-degree-of-freedom rigid release with fluid coupling

**Mapping.** CaseFloating_Def is the simplest official 3D free-floating control with mass and particle/motion postprocessors. Chrono OWSC3D adds 3D rigid coupling but is wave-driven; the 2D sphere case has reference files. None proves the current six-DOF release contract or external 3D acceptance.

**Current observer contract.** pose [m, quaternion], linear_velocity [m/s], angular_velocity [rad/s], fluid mass [kg].

| Candidate | Definition / dimension | Controls and configured observations | Available script outputs | References and hard gaps |
|---|---|---|---|---|
| `OFFICIAL_FLOATING_3D` (STRONG_3D_FLOATING_CONTROL_WITH_OBSERVATION_GAPS) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/11_Floating/CaseFloating_Def.xml`; 3D, dp=0.1 m | none; Definition: 3D floating body mkbound=50, massbody=10000, gravity -9.81 m/s^2, moving piston control, RigidAlgorithm=1, TimeMax=10 s and TimeOut=0.1 s. | PartVTK fluid/floating/moving-piston products and PartVTKOut.; BoundaryVTK floating/piston motion and fixed box; FloatingInfo motion data; IsoSurface. | none found. Gaps: No external 3D pose, linear/angular velocity or fluid-mass reference file is present in this example directory.; FloatingInfo script selects onlymk:60 while the definition declares mkbound=50; mark binding must be checked before claiming telemetry.; Quaternion/SE(3), angular velocity and fluid-mass observer semantics are not established by output file names alone. |
| `OFFICIAL_OWSC3D_CHRONO` (PARTIAL_3D_WAVE_DRIVEN_CHRONO_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/chrono/05_OWSC/CaseOWSC3D_Def.xml`; 3D, dp=0.05 m | `CaseOWSC3D_tank.stl`, `CaseOWSC3D_flap.stl`, `Floating_Materials.xml`; Definition: 3D floating flap with Chrono RigidAlgorithm=3, center/inertia, wave piston and TimeMax=10 s / TimeOut=0.02 s. | PartVTK fluid/wavemaker/flap and PartVTKOut, BoundaryVTK, FloatingInfo flap motion, ComputeForces tank moment and IsoSurface. | none found. Gaps: Wave-driven Chrono flap is not a free rigid release; no current F6 release/initial-state mapping or external reference is declared.; FloatingInfo selects onlymk:15 while XML floating mkbound=5; telemetry mark binding needs verification. |
| `OFFICIAL_FLOATING_SPHERE_VAL2D` (PARTIAL_2D_REFERENCE_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/11_Floating/CaseFloatingSphereVal2D_Def.xml`; 2D, dp=0.025 m | none; Definition: 2D floating sphere, relativeweight=1.20, FtPause=1 s, TimeMax=6 s and TimeOut=0.02 s. | PartVTK fluid/floating, PartVTKOut, FloatingInfo and surface slices. | `EXP_FloatingSphereVal2D_Displacement_Fekken2004.txt` (Exists; 2D displacement reference only.); `EXP_FloatingSphereVal2D_Velocity_Fekken2004.txt` (Exists; 2D velocity reference only.); `EXP_FloatingSphereVal2D.ods` (Exists; workbook was not opened by this map.). Gaps: 2D sphere output/reference cannot establish 3D six-DOF equivalence.; FloatingInfo selects onlymk:61 while XML floating mkbound=51; telemetry mark binding needs verification. |

**Family-level gaps.**

- Current F6 native join count is an identity/cause audit count, not pose/SE(3) or physical qualification.
- No official candidate supplies the complete current pose, linear/angular velocity and fluid-mass contract with 3D reference data.

## F7: finite wet-base tank with prescribed quintic moving obstacle

**Mapping.** CasePump_Def is the official 3D moving-boundary candidate named by the plan. Its rotation and fluid products do not provide the current quintic, wet-base, left/right flux and residence contract.

**Current observer contract.** mass [kg], front [m], flux [kg/s], time [s].

| Candidate | Definition / dimension | Controls and configured observations | Available script outputs | References and hard gaps |
|---|---|---|---|---|
| `OFFICIAL_PUMP_3D` (PARTIAL_3D_MOVING_PUMP_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/13_Pump/CasePump_Def.xml`; 3D, dp=0.004 m | `pump_fixed.vtk`, `pump_moving.vtk`; Definition: 3D finite tank, rotating pump, gravity -9.81 m/s^2, mvrotace control, TimeMax=6 s, TimeOut=0.02 s, PartsOutMax=0.9. | BoundaryVTK pump motion and fixed geometry.; PartVTK fluid and PartVTKOut excluded-fluid products.; IsoSurface products with velocity and density. | none found. Gaps: No prescribed quintic trajectory, wet-base partition, left/right mass split, flux/residence gauge or same-directory reference data.; Current F7 observer contract therefore needs a new typed postprocessor and an explicit reference source before qualification. |
| `OFFICIAL_FLEXIBLE_OBSTACLE_2D` (PARTIAL_2D_FLEXIBLE_GATE_ONLY) | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/chrono/13_FlexibleObstacle/CaseFlexibleObstacle_Def.xml`; 2D, dp=0.001 m | `GateMotion.txt`; Definition: 2D mDBC flexible gate, motion file GateMotion.txt, Chrono floating beam, TimeMax=1 s and TimeOut=0.01 s. | PartVTK fixed/fluid/beam products, BoundaryVTK gate, FloatingInfo and excluded/geometry products. | `ModelComparison.ods` (Exists; 2D flexible-gate comparison is not a quintic pump reference.). Gaps: Flexible 2D gate and external motion file do not establish the 3D pump, quintic trajectory, wet-base or flux semantics. |

**Family-level gaps.**

- Current F7 has 24 GenCase schema-unknown rows and five launch/incomplete rows; official candidate metadata does not close those lifecycle gaps.
- No equivalence is credited from the shared words moving obstacle or pump.

## Cross-family rules

- An official definition, script and reference file prove source availability only; they do not prove that any current 48-case family row has the same geometry, initial state, boundary, motion, time window or sensor semantics.
- Reference-data existence is recorded separately from reference-data binding. No ODS/XLSX/ZIP/CSV/DAT scientific or control payload was opened by this builder.
- The current catalog's 335 masks, 78 scans and 117 joins remain aggregate metadata provenance; no per-case passed state, QI, QN or QE is inferred.
- Resolution, recovery, window transfer and prospective split safety remain UNKNOWN for all families.

The JSON retains absolute source paths, metadata hashes where read, existence/byte metadata for referenced assets, XML control summaries and the current catalog's family/source-closure evidence.
