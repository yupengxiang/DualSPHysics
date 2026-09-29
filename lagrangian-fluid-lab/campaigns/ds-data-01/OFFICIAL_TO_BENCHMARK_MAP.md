# Official examples → DS-DATA-01 benchmark families

This is the D01 candidate map. The paths and source hashes are verified against
the local `DualSPHysics_v5.4` package by
`OFFICIAL_EXAMPLES_INVENTORY.json`. “Candidate” means a selector for D02; it
does not mean that a solver run, mechanism event, or scientific acceptance has
already happened. Source dimensionality below comes from the inventory’s XML
geometry evidence. A 2D case is a calibration/contrast track, not 3D coverage.

| family | mechanism | local official seeds | local evidence/status |
|---|---|---|---|
| F1 | 溃坝、绕障、分流与再汇合 | `examples/main/01_DamBreak`; `examples/mdbc/04_Dambreak` | Both 3D source geometries; use dry/wet bed and obstacle branches as separately audited configurations. |
| F2 | 倾倒、接液、洒落与滞留 | `examples/main/05_SloshingTank`; `examples/motion`; existing verified cup assets | No complete official raw tipping mother case is claimed. This is a controlled derived family; 2D `main/05_SloshingTank` is a motion calibration only. |
| F3 | 大幅晃荡、多轴控制与分舱交换 | `examples/main/05_SloshingTank`; `examples/mdbc/03_Sloshing`; existing F3 archive | Local official seeds are 2D source geometries; preserve existing 32-case F3 assets and require a separately verified 3D branch before claiming 3D coverage. |
| F4 | 有限液团、液柱、射流碰撞 | `examples/inletoutlet/05_ShapesInlet3D`; `examples/inletoutlet/08_ImpingingJet` | The ShapesInlet3D seed is 3D; ImpingingJet is a 2D calibration/open-flow contrast. Do not treat continuous inlet mass as a closed finite-liquid case. |
| F5 | 波浪破碎、爬升、越堤与回流 | `examples/main/06_Wavemaker`; `08_WavesFlap`; `09_WavesPiston`; `10_WavesPistonAWAS`; `16_SolitaryWaves`; `17_WaveRunup` | Wavemaker and WaveRunup have 3D source geometry; the piston/flap/solitary-wave examples include 2D anchors that must remain separately labeled. |
| F6 | 刚体入水、自由漂浮与双向响应 | `examples/main/11_Floating`; `examples/main/12_FloatingWaves`; selected `examples/chrono/*` only if needed | `main/11_Floating` is 3D; `main/12_FloatingWaves` is a 2D contrast. Free-body state and force/torque semantics require D03 acceptance. |
| F7 | 活动障碍、旋转泵与搅拌输运 | `examples/main/03_MovingSquare`; `examples/main/13_Pump`; `examples/motion` | Pump is a 3D source candidate; MovingSquare is a 2D control calibration. Motion files are controls, not a completed flow case. |

## Non-core and extension tracks

- `main/02_Periodicity`, `main/15_Poiseuille`, `mdbc/01_StillWedge`, and
  selected `others/*` are calibration/interface anchors.
- `inletmesh/*`, `inletoutlet/*`, and `vresolution/*` are useful open/lifecycle
  and resolution extensions; their birth/death, `Zone+Id`, and flux semantics
  must be explicit.
- `mphase_liquidgas/*` and `mphase_nnewtonian/*` are outside the single-phase
  Newtonian core and do not block it.
- `chrono/*`, `flexstruc/*`, `moordynplus/*`, and `wavecoupling/*` are coupled
  extensions. They are not a global gate for F1–F7.
- `main/14_DEM` and other pure-mechanics material are excluded from the fluid
  core.

## D02 first canary queue

The first queue is intentionally one representative path per mechanism, with
one 3D seed where the official package provides it and a labeled 2D anchor only
where it is needed for calibration:

1. F1: `main/01_DamBreak` (3D).
2. F2: existing verified cup recipe; if unavailable for reuse, prepare the
   derived motion case but record it as non-official.
3. F3: existing 32-case F3 anchor first; separately inspect the official
   sloshing source before any 3D derivation.
4. F4: `inletoutlet/05_ShapesInlet3D` (3D) and `08_ImpingingJet` (2D contrast).
5. F5: `main/17_WaveRunup` (3D) and `main/06_Wavemaker` (3D source candidate).
6. F6: `main/11_Floating` (3D).
7. F7: `main/13_Pump` (3D).

No item in this queue is counted until it has an actual attempt receipt, a
complete source/recipe binding, native trajectory conversion, and the D03
scope-specific quality checks.
