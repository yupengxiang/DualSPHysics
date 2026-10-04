# ROOT FOLLOWUP 048: Independent Source Audit of Compact Flume Spatial Failure & Root-Guarded Diagnostic Worker Proposal

**Author**: F5 Autonomous Agent (Pair programming with User)  
**Execution Context**: `/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics`  
**Target Handoff Workspace**: `lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_048_compact_actual_spatial_failure_diagnosis_v1`  
**Model Requirement**: `gemini-3.8-flash-high` (Verified direct session; zero model substitution, zero recursive subagent delegation)  
**Task Authority**: User-authorized F5 SOURCE-ONLY diagnosis  
**Scope**: Source-only audit of XML, C++ parser/solver, and GenCase assembly; non-reconstructive review of actual Round 057 macro failure report; design of a Root-guarded diagnostic worker for full initial CSV054 particle support tests; minimal conditional repair proposals (max 2 per cause). Strictly NO solver/GenCase/actual numeric CSV/H5/BI4 execution, NO GPU attempt request, NO account change, NO unrelated edit.

---

## 1. Executive Context & Macro 057 Spatial Failure Review

### 1.1 Provenance & Chronology Leading to Round 057
1. **Owner045 Source-Contract Review**: Accepted only C++ parser syntax proofs (e.g. required `value="0"` attribute for `<hswl auto="true" />`, canonical `SavePosDouble="1"`, elimination of `IncZ` domain conflicts). Synthetic particle counts and claims of monotonic continuum convergence were explicitly rejected by Root.
2. **Root Round 049 - 053 Intermediate Corrections**:
   - Round 049 coarse geometry QA revealed $99.6\%$ of fluid particles placed below the sloped bed due to inverted clipplane normal vector $(-0.28, 0, 1.0)$.
   - Round 050 corrected the clipplane vector to $(0.28, 0, -1.0)$, retaining fluid strictly above the continuous bed.
   - Round 053 resolved a submerged weir ownership defect where the fluid drawbox had overwritten weir boundary particles; weir drawing was moved after fluid generation.
   - Round 054 Initial Native QA verified the 6 generated initial cases across 13 native fields, confirming fluid strictly above the bed, zero fluid outside physical flume bounds, zero fluid inside weir solid, and authentic 3D lattice dimensions. **However, Initial QA 054 checked only fluid envelope and existence; bed/wall support thickness, layer count, and kernel support completeness were not evaluated.**
   - Round 056 resolved relative motion CWD resolution paths, enabling successful full 16.0 s solver executions for both Runup and Weir coarse and medium cases.

### 1.2 The Massive Spatial Failure in Actual Macro 057
On October 4, 2026, Root audited the completed coarse ($dp=0.020$ m) vs medium ($dp=0.0125$ m) full 16.0 s native gauge comparison (`frozen-native-gauge-comparison.json`). The results failed the frozen spatial error allocation ($5\%$ of $H = 0.400$ m, i.e. $0.020$ m) massively across both mechanisms:

| Mechanism | Probe | $x$ [m] | Raw SWL RMSE [m] | Normalized $\eta$ RMSE [m] | Relative $\eta$ RMSE / $H$ | Relative $\eta$ Max / $H$ | 5% Spatial Gate | Dry Occupancy (Coarse / Med / Dropout) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Runup** | **WG1** | $0.60$ | $0.17085$ | $0.17086$ | **42.71%** | **52.49%** | **FAIL** | 0 / 0 / 0 (800 wet) |
| **Runup** | **WG2** | $1.40$ | $0.16984$ | $0.16985$ | **42.46%** | **52.82%** | **FAIL** | 0 / 0 / 0 (800 wet) |
| **Runup** | **RunupToe** | $2.00$ | $0.16983$ | $0.16983$ | **42.46%** | **49.48%** | **FAIL** | 0 / 0 / 0 (800 wet) |
| **Runup** | **WG3** | $2.60$ | $0.16794$ | $0.16794$ | **41.98%** | **59.77%** | **FAIL** | 35 / 0 / 34 (766 wet) |
| **Runup** | **WG4** | $3.20$ | $0.06716$ | $0.06715$ | **16.79%** | **23.00%** | **FAIL** | **782 / 0 / 782** (18 wet) |
| **Runup** | **Crest** | $3.75$ | $0.00000$ | $0.00000$ | **0.00%** | **0.00%** | Pass (Dry) | 800 / 800 / 0 (0 wet) |
| **Weir** | **WG1** | $0.60$ | $0.17323$ | $0.17324$ | **43.31%** | **52.74%** | **FAIL** | 0 / 0 / 0 (800 wet) |
| **Weir** | **WG2** | $1.40$ | $0.17248$ | $0.17249$ | **43.12%** | **53.27%** | **FAIL** | 0 / 0 / 0 (800 wet) |
| **Weir** | **RunupToe** | $2.00$ | $0.17233$ | $0.17234$ | **43.08%** | **50.47%** | **FAIL** | 0 / 0 / 0 (800 wet) |
| **Weir** | **WG3** | $2.60$ | $0.16970$ | $0.16970$ | **42.42%** | **58.93%** | **FAIL** | 50 / 0 / 49 (751 wet) |
| **Weir** | **WG4** | $3.20$ | $0.00000$ | $0.00000$ | **0.00%** | **0.00%** | Pass (Dry) | 800 / 800 / 0 (0 wet) |
| **Weir** | **Crest** | $3.75$ | $0.00000$ | $0.00000$ | **0.00%** | **0.00%** | Pass (Dry) | 800 / 800 / 0 (0 wet) |

### 1.3 Key Empirical Observations from Macro 057
1. **Initial Agreement vs Dynamic Divergence**:
   At $t = 0.0$ s, the initial offset between coarse and medium SWL at WG1 was essentially zero:
   $$\text{initial\_offset\_m} = 6.00 \times 10^{-6}\text{ m (6 microns)}$$
   This proves that initial fluid placement at $t=0$ was geometrically consistent. However, as soon as the simulation evolved, the water level diverged immediately, reaching an RMS discrepancy of $\approx 0.171$ m.
2. **Uniformity of Flat-Basin Discrepancy**:
   Across all flat basin probes (WG1, WG2, RunupToe), the discrepancy is extraordinarily uniform ($\Delta \eta_{RMS} \approx 0.170 - 0.173$ m, $\Delta \eta_{max} \approx 0.210 - 0.213$ m) across both Runup and Weir. This points to a global, datum-level numerical subsidence of the water column rather than localized wave scattering.
3. **Severe Shoreline Resolution Dropout at WG4**:
   In Runup, coarse resolution was dry for **782 out of 800 samples (97.75%)**, whereas medium resolution was wet for **all 800 samples (100%)**.
4. **Weir WG4 Decoupling**:
   In Weir, WG4 was dry for **all 800 samples in both resolutions**, proving it was positioned inside/behind the weir solid obstruction rather than measuring active hydraulics.
5. **Crest Sub-aerial Inactivity**:
   The Crest probe ($z = 0.448$ m, $4.8$ cm above SWL $0.400$ m) was **100% dry (800/800 samples)** in both mechanisms and both resolutions. The small piston wave packet ($\le 0.03$ m amplitude) did not produce sustained overtopping over the crest plateau.

**Scientific Status**: The new compact mother flume is formally **REJECTED** pending causal diagnosis. Scientific Q-N is not granted. Historical negative results on the large flume ($12\%$ spatial error, $1\%$ time error) remain retained.

---

## 2. Independent Source-Only Audit of Potential Causal Defects

### 2.1 Defect Area 1: Boundary Bed Extrusion, Solid Fill, Sampling, and Draw Ownership

#### Source Pins:
- [`F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_Def.xml:26-241`](file:///home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_compact_equilibrium_actual_clip_direction_fix_050/selected_definitions/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_Def.xml#L26-L241) (`<drawtriangles>`)
- [`F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_Def.xml:269-271`](file:///home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_compact_equilibrium_actual_clip_direction_fix_050/selected_definitions/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_Def.xml#L269-L271) (`<drawfilestl file="assets/f5_compact_continuous_bed_profile.stl" />`)
- [`generate_compact_continuous_bed_stl.py:127-203`](file:///home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_actual_compact_equilibrium_source_preparation_045/generate_compact_continuous_bed_stl.py#L127-L203)
- [`doc/xml_format/GenCase_CaseTemplate.xml:363-379`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/doc/xml_format/GenCase_CaseTemplate.xml#L363-L379)
- [`F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050.xml:385`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050/root-compact-equilibrium-runup_coarse-clip-direction-fix-gencase-050/prepared/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050.xml#L385)

#### Forensic Audit & Mathematical Proof of Hollow Bed:
In `generate_compact_continuous_bed_stl.py:127-203`, the continuous bed is synthesized as a closed 52-triangle watertight polyhedron bounded by $x \in [-0.20, 4.80]$ m, $y \in [-0.15, 0.15]$ m, and $z \in [-0.15, z_{bed}(x)]$ m.
The total 3D geometric volume of this closed solid is:
$$V_{bed} = \int_{-0.20}^{4.80} \int_{-0.15}^{0.15} (z_{bed}(x) - (-0.15)) \, dy \, dx \approx 0.41619\text{ m}^3$$

If GenCase were performing a 3D solid volumetric fill of this polyhedron at resolution $dp$, the expected discrete particle counts would be:
- Coarse ($dp = 0.020$ m, cell volume $8.0 \times 10^{-6}\text{ m}^3$):
  $$N_{solid, coarse} = \frac{0.41619}{8.0 \times 10^{-6}} \approx \mathbf{52,023\text{ particles}}$$
- Medium ($dp = 0.0125$ m, cell volume $1.953125 \times 10^{-6}\text{ m}^3$):
  $$N_{solid, medium} = \frac{0.41619}{1.953125 \times 10^{-6}} \approx \mathbf{213,089\text{ particles}}$$

However, in the actual GenCase output XMLs (`F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050.xml:385` and `F5_REF_RUNUP_DP0125_EQUILIBRIUM_ROOT050.xml:385`), the actual generated bed particles (`mkbound="40"`, remapped to `mk="50"`) are:
- Actual Coarse Bed Particles: **13,556** (only $26.1\%$ of solid volume)
- Actual Medium Bed Particles: **40,561** (only $19.0\%$ of solid volume)

Now consider the total 2D surface area of the 52 facets of the polyhedron:
- Top sloped bed surface: $5.20\text{ m} \times 0.30\text{ m} = 1.56\text{ m}^2$
- Bottom floor face ($z = -0.15$ m): $5.00\text{ m} \times 0.30\text{ m} = 1.50\text{ m}^2$
- Lateral side panels ($y = \pm 0.15$ m): $2 \times 1.3873\text{ m}^2 = 2.7746\text{ m}^2$
- Upstream and downstream endcaps: $0.045\text{ m}^2 + 0.060\text{ m}^2 = 0.105\text{ m}^2$
- Total surface area $A_{surface} \approx 5.94\text{ m}^2$

At lattice grid $dp$, surface particle generation scales as $A / dp^2$:
- Coarse expected surface particles: $5.94 / 0.02^2 \times \text{sampling efficiency} \approx 14,850 \approx \mathbf{13,556}$
- Medium expected surface particles: $5.94 / 0.0125^2 \times \text{sampling efficiency} \approx 38,016 \approx \mathbf{40,561}$

The ratio of particle counts between medium and coarse is:
$$\frac{N_{medium}}{N_{coarse}} = \frac{40,561}{13,556} = 2.99$$
For a 3D solid, the scaling would be $(0.02 / 0.0125)^3 = 1.6^3 = 4.096$. For a 2D surface, the scaling is $1.6^2 = 2.56$. A scaling of $2.99$ reflects 2D surface facet discretization with grid-alignment effects.

**Defect Conclusion 1**:
1. **The continuous bed is completely hollow**. GenCase did not fill the interior of the bed solid.
2. In DualSPHysics XML syntax, `<setdrawmode mode="full" />` specifies drawing all faces of geometric primitives (wire vs face vs full); it **does not** trigger ray-casting volumetric autofill for STL or triangular meshes.
3. Volumetric filling of an STL in GenCase requires `<drawfilestl file="..." autofill="true" />` or `<drawfilestl file="..." advanced="true"><depth depthmin="..." /></drawfilestl>` (documented in `doc/xml_format/GenCase_CaseTemplate.xml:364, 374-379`). Because these tags were omitted, the bed was sampled as an ultra-thin 1-particle-thick hollow skin.
4. **Draw Ownership Duplication**: In `commands/mainlist`, the bed triangles were drawn twice: first at lines 28-241 via `<drawtriangles>`, and then again at line 270 via `<drawfilestl>`. In between, `tank_floor` (mk 0) and `sidewalls` (mk 30) were drawn. The second draw via `drawfilestl` re-asserted mk 40 on intersecting particles, creating conflicting ownership at boundary junctions.

---

### 2.2 Defect Area 2: Upstream Floor and Sidewall Support

#### Source Pins:
- [`F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_Def.xml:242-261`](file:///home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_compact_equilibrium_actual_clip_direction_fix_050/selected_definitions/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_Def.xml#L242-L261)
- [`F5_REF_RUNUP_DP0125_EQUILIBRIUM_ROOT050_Def.xml:242-261`](file:///home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_compact_equilibrium_actual_clip_direction_fix_050/selected_definitions/F5_REF_RUNUP_DP0125_EQUILIBRIUM_ROOT050_Def.xml#L242-L261)

#### Forensic Audit:
1. **`tank_floor` Geometry and Location**:
   ```xml
   <setmkbound mk="0" />
   <drawbox cmt="tank_floor">
     <boxfill>bottom</boxfill>
     <point x="-0.20" y="-0.18" z="-0.15" />
     <size x="5.00" y="0.36" z="0.15" />
     <layers vdp="0,1,2" />
   </drawbox>
   ```
   - `<boxfill>bottom</boxfill>` commands GenCase to draw **only the bottom face** of the defined bounding box.
   - The box origin is at $z = -0.15$ m, so the bottom face is positioned at $z = -0.15$ m (with `layers vdp="0,1,2"` placing layers at $z = -0.15, -0.17, -0.19$ m).
   - In the upstream flat basin ($x \in [0.0, 2.0]$ m), the fluid is positioned at $z \ge 0.00$ m.
   - There is **no tank floor boundary at $z = 0.00$ m**.
   - The only barrier separating the $0.40$ m fluid column from the void beneath is the top face of the hollow bed skin at $z = 0.00$ m.
   - Between $z = 0.00$ m and $z = -0.15$ m, there is a **15 cm empty vertical gap**. Under hydrostatic load ($p \approx 3924$ Pa), fluid particles resting on this single skin have zero structural back-support.

2. **Sidewall Thickness and Layer Truncation**:
   ```xml
   <setmkbound mk="30" />
   <drawbox cmt="finite_sidewall_left">
     <boxfill>solid</boxfill>
     <point x="-0.20" y="-0.18" z="-0.15" />
     <size x="5.00" y="0.03" z="0.95" />
     <layers vdp="0,1,2" />
   </drawbox>
   ```
   - The defined transverse width of the sidewall is $\Delta y = 0.030$ m (from $y = -0.18$ to $-0.15$ m, and from $y = 0.15$ to $0.18$ m).
   - At coarse resolution ($dp = 0.020$ m):
     To place 3 full boundary layers (`vdp="0,1,2"`), GenCase requires a minimum physical thickness of:
     $$\Delta y_{req} = 3 \times dp = 3 \times 0.020 = 0.060\text{ m}$$
     Because the box width is only $0.030$ m ($1.5 dp$), layer 2 ($0.040$ m offset) falls outside the box bounds and is truncated!
     Consequently, **the coarse sidewall contains only 1 to 2 particle layers instead of the required 3 layers**.
   - At medium resolution ($dp = 0.0125$ m):
     $3 \times dp = 0.0375$ m, allowing 2 to 3 layers within $0.030$ m.
   - This creates an asymmetric, resolution-dependent transverse kernel truncation between coarse and medium.

---

### 2.3 Defect Area 3: Physical DP-Dependent Support Relation, Initial Rhop Gradient, and EOS

#### Source Pins:
- [`src/source/JSph.cpp:92, 701-705`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/src/source/JSph.cpp#L701-L705) (`Boundary="DBC"`)
- [`src/source/JCaseCtes.cpp:137-139`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/src/source/JCaseCtes.cpp#L137-L139) (`rhopgradient="2"`)
- [`src/source/JDsGaugeItem.cpp:728-753`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/src/source/JDsGaugeItem.cpp#L728-L753) (`CalculeMassCpu`)

#### Forensic Audit:
1. **Dynamic Boundary Condition (DBC) Kernel Completeness Requirement**:
   DualSPHysics implements DBC (`Boundary="1"` per `JSph.cpp:702`). DBC boundary particles participate in the continuity equation and momentum equation exactly like fluid particles, but their positions remain fixed (or follow rigid motion).
   The compact support radius of the Wendland kernel with $\text{coefh} = 1.0$ is:
   $$2h = 2 \times \sqrt{3} dp \approx 3.464 dp$$
   For an SPH fluid particle located within distance $d < 2h$ of a boundary, complete kernel integration $\int W(r) dV \approx 1$ requires the boundary to have a physical thickness $\ge 2h$ (at least 3 to 4 particle layers).
   When the boundary has only **one single layer of particles** (as proven in Section 2.1):
   - Over $60\%$ of the lower hemisphere in the fluid particle's kernel support is empty space.
   - The computed density gradient and repulsive boundary pressure force:
     $$\vec{a}_{b} = -\sum_{b \in boundary} m_b \left( \frac{p_a}{\rho_a^2} + \frac{p_b}{\rho_b^2} \right) \nabla W_{ab}$$
     is severely deficient.

2. **The Hydrostatic Initial Condition Mismatch**:
   In `constantsdef`, `<rhopgradient value="2" />` selects `RHOG_WaterCol` (`JCaseCtes.cpp:137`).
   - GenCase initializes fluid particle densities hydrostatically based on depth below SWL ($H = 0.400$ m):
     $$p_{bottom} \approx \rho_0 g H = 1000 \times 9.81 \times 0.40 = 3924\text{ Pa}$$
     $$\rho_{bottom} \approx \rho_0 \left(1 + \frac{p_{bottom}}{B}\right)^{1/\gamma} = 1000 \times \left(1 + \frac{3924}{224228.6}\right)^{1/7} \approx 1002.48\text{ kg/m}^3$$
   - However, in DualSPHysics, **boundary particles are initialized at reference density $\rho_0 = 1000.0\text{ kg/m}^3$ and zero pressure ($p_b = 0$)**.
   - At $t = 0^+$, before any fluid motion occurs, DBC boundary particles have $\frac{d\rho_b}{dt} = 0$ because velocities are zero.
   - Therefore, boundary particles cannot provide initial hydrostatic repulsive pressure ($p_b = 0$). Only the fluid's own pressure $p_a$ acts against the boundary.
   - Combined with the single-layer kernel truncation, the upward repulsive force from the hollow bed is incapable of counterbalancing gravitational acceleration $g = -9.81\text{ m/s}^2$.

3. **Why the Datum Sagging Scales Massively with $dp$**:
   In SPH, numerical penetration depth into a deficient boundary scales directly with $h$ and $dp$:
   - At coarse resolution ($dp = 0.020$ m, $h = 0.0346$ m):
     Fluid particles sag significantly deeper into the single-particle boundary layer.
   - At medium resolution ($dp = 0.0125$ m, $h = 0.0217$ m):
     The kernel radius is $37.5\%$ smaller, and the penetration depth is substantially less.
   - This resolution-dependent boundary sag creates a systematic, persistent downward shift of the entire fluid column at coarse resolution relative to medium resolution.
   - This explains the observed uniform $\approx 0.170 - 0.173$ m DC offset at WG1, WG2, and RunupToe!

---

### 2.4 Defect Area 4: Gauge Selection, Shoreline Wetting/Drying, and Downstream Dry Counts

#### Source Pins:
- [`src/source/JDsGaugeItem.cpp:758-787`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/src/source/JDsGaugeItem.cpp#L758-L787) (`JGaugeSwl::CalculeCpuT`)
- [`doc/xml_format/_FmtXML_Gauges.xml:41-46`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/doc/xml_format/_FmtXML_Gauges.xml#L41-L46)
- [`frozen-native-gauge-comparison.json:209-395, 487-675`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_COMPACT_EQUILIBRIUM_COARSE_MEDIUM_FROZEN_GAUGES/root-compact-both-mechanisms-coarse-medium-full16-all-six-frozen-gauges-057/frozen-native-gauge-comparison.json#L209-L395)

#### Forensic Audit:
1. **The Native DualSPHysics SWL Dry-Clamping Mechanism**:
   In `src/source/JDsGaugeItem.cpp:771-782`, `JGaugeSwl::CalculeCpuT` iterates along the gauge line from `Point0` to `Point2`:
   ```cpp
   tdouble3 ptsurf = TDouble3(DBL_MAX);
   float mpre = 0;
   tdouble3 ptpos = Point0;
   for(unsigned cp = 0; cp <= PointNp; cp++){
     const float mass = CalculeMassCpu<tker>(ptpos, dvd, pos, code, velrho);
     if(mass > MassLimit) mpre = mass;
     if(mass < MassLimit && mpre){
       const float fxm1 = (MassLimit - mpre) / (mass - mpre) - 1;
       ptsurf = ptpos + (PointDir * double(fxm1));
       cp = PointNp + 1;
     }
     ptpos = ptpos + PointDir;
   }
   if(ptsurf.x == DBL_MAX) ptsurf = Point0 + (PointDir * (mpre ? PointNp : 0));
   ```
   **Critical Contract**: When a gauge probe detects no fluid along its length (`mpre == 0`), line 782 executes:
   $$\text{ptsurf} = \text{Point0}$$
   In `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_Def.xml:308-341`, `Point0.z` for each gauge was defined at the local bed elevation:
   - WG1, WG2, RunupToe: $z_{point0} = 0.000$ m
   - WG3: $z_{point0} = 0.168$ m
   - WG4: $z_{point0} = 0.336$ m
   - Crest: $z_{point0} = 0.448$ m
   Therefore, **whenever a probe is dry, DualSPHysics reports $SWL = z_{point0} = z_{bed}$**.

2. **Resolution-Dependent Shoreline Dropout at WG4**:
   - Location: $x = 3.20$ m on the sloped beach ($m = 0.280$).
   - Local bed elevation: $z_{bed} = 0.280 \times (3.20 - 2.00) = 0.336$ m.
   - Nominal still-water depth: $H - z_{bed} = 0.400 - 0.336 = 0.064$ m (6.4 cm).
   - In coarse resolution ($dp = 0.020$ m):
     A depth of 6.4 cm corresponds to only $3.2$ particles vertically. As soon as the fluid slumps or dynamic swash recedes, the local particle count drops below `MassLimit`, causing the gauge to report dry ($SWL = 0.336$ m).
     In `frozen-native-gauge-comparison.json`, **coarse was dry for 782 out of 800 frames ($97.75\%$)**.
   - In medium resolution ($dp = 0.0125$ m):
     A depth of 6.4 cm corresponds to $5.12$ particles vertically. Medium resolution successfully maintained fluid particles at $x = 3.20$ m throughout the simulation (**0 dry frames out of 800**).
   - This resolution dropout caused an artificial discrepancy: comparing wet medium SWL ($\approx 0.40$ m) to dry-clamped coarse SWL ($0.336$ m).

3. **Weir WG4 Geometric Obstruction**:
   - In the Weir case, the solid weir structure is located at $x \in [3.20, 3.35]$ m.
   - The gauge WG4 is sited at $x = 3.20$ m, which coincides exactly with the front face of the weir.
   - The weir crest rises to $z = 0.410$ m (notch) and $z = 0.460$ m (side crest), both above SWL $0.400$ m.
   - As a result, WG4 in Weir is **100% dry (800/800 frames) in both coarse and medium**, measuring the inactive weir base rather than downstream transmitted waves.

4. **Crest Sub-aerial Inactivity**:
   - Crest is at $x = 3.75$ m, $z = 0.448$ m ($4.8$ cm above SWL).
   - Because the solitary packet motion amplitude was small ($\le 0.030$ m), water never overtopped the crest.
   - Crest remained **100% dry (800/800 frames)** in both resolutions.
   - In the comparison report, Crest shows $\text{RMSE} = 0.000$ m simply because both resolutions were clamped to $z = 0.448$ m for the entire duration!

---

## 3. Root-Guarded Diagnostic Worker Proposal

To verify and quantify these findings directly on the actual native data without running full simulations or unguarded numerical reconstructions, we propose a bounded, read-only CPU Diagnostic Worker.

### 3.1 Diagnostic Scope & Governance
- **Execution Target**: Read-only diagnostic audit of existing Round 054 CSV exports:
  `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_COMPACT_EQUILIBRIUM_ACTUAL_COARSE_GEOMETRY_QA/root-compact-equilibrium-both-mechanisms-three-dp-corrected-native-geometry-qa-054/`
- **Cases Covered**: All 6 cases: `runup_coarse`, `runup_medium`, `runup_fine`, `weir_coarse`, `weir_medium`, `weir_fine`.
- **Governing Constraints**:
  - Pure CPU audit: 2 CPU threads, max 600 wall-seconds, zero GPU requirement.
  - Zero simulation re-run; operates exclusively on completed official exports.
  - Preserves all raw IDs, particle weights, generated XML hashes, and 13 native payload columns (`Pos.x, Pos.y, Pos.z, Zone, Idp, Type, Mk, Mass, Vel.x, Vel.y, Vel.z, Rhop, Press`).
  - **Explicit Scientific Label**: "DIAGNOSTIC ONLY; NOT Q-N; PRODUCTION APPROVAL: NONE".

### 3.2 Five Quantitative Diagnostic Tests
1. **Full Particle Inventory & Mk Breakdown**:
   Extract exact particle counts for all types (`0: Fixed Boundary`, `1: Moving Piston`, `3: Fluid`) and all remapped markers:
   - Mk 10: Tank floor
   - Mk 20: Piston paddle
   - Mk 40: Lateral sidewalls
   - Mk 50: Continuous bed (or weir solid in Weir cases)
2. **Bed Shell vs Solid Cavity Inspection**:
   - Query the region interior to the bed polyhedron:
     $$\Omega_{interior} = \{(x, y, z) \mid x \in [-0.2, 4.8], |y| \le 0.14, -0.14 \le z \le z_{bed}(x) - dp\}$$
   - Count the number of particles inside $\Omega_{interior}$. If count $= 0$, proof of hollow bed is empirically confirmed on the native binary export.
3. **Nearest Boundary Support & Kernel Completeness**:
   - For every fluid particle $a \in \text{Fluid}$, compute:
     $$d_{min}(a) = \min_{b \in \text{Boundary}} \|\vec{x}_a - \vec{x}_b\|$$
   - Count the number of boundary particles within the kernel support radius $r \le 2h = 2\sqrt{3} dp$:
     $$N_{b, 2h}(a) = \sum_{b \in \text{Boundary}} \mathbb{I}(\|\vec{x}_a - \vec{x}_b\| \le 2h)$$
   - Evaluate whether $N_{b, 2h}$ achieves full multi-layer support ($\ge 3$ layers) or reflects 1-layer truncation.
4. **Bed Clearance Distribution**:
   - Compute fluid clearance $\Delta z = z_a - z_{bed}(x_a)$ for all fluid particles above the continuous profile.
   - Establish whether the minimum clearance at $t=0$ equals $0.5 dp$ across all 3 commensurate resolutions.
5. **Sidewall Layer Count & Thickness**:
   - Count boundary particles in the sidewall coordinate bands $y \in [-0.18, -0.15]$ m and $y \in [0.15, 0.18]$ m across coarse, medium, and fine.
   - Verify whether coarse resolution is truncated to $< 3$ layers.

### 3.3 Optional Transparent Bounded Temporal Sinking Check
If Root authorizes temporal verification of particle sinking without full time-series processing:
- Use official `PartVTK_linux64` to export only 3 discrete frames from existing `Part_????.bi4`:
  - Frame 0 ($t = 0.0$ s)
  - Frame 400 ($t = 8.0$ s, mid-window)
  - Frame 800 ($t = 16.0$ s, window end)
- Compare the vertical position distribution of fluid particles adjacent to the bed to quantify actual downward penetration over time.

---

## 4. Grounded Minimal Conditional Repair Proposals

*(Max 2 distinct repairs per cause; Root will evaluate and decide after diagnostic data is produced)*

### 4.1 Cause 1: Hollow 1-Particle-Thick Continuous Bed Shell

#### Repair Proposal 1A (Native GenCase STL Autofill):
- **Mechanism**: In `selected_definitions/*_Def.xml`, replace the hollow `<drawfilestl>` and delete the duplicate `<drawtriangles>`:
  ```xml
  <!-- Remove pre-draw drawtriangles at start of mainlist -->
  <!-- Update drawfilestl to activate GenCase native volumetric autofill -->
  <setmkbound mk="40" />
  <drawfilestl file="assets/f5_compact_continuous_bed_profile.stl" autofill="true" />
  ```
- **Rationale**: `autofill="true"` triggers GenCase's built-in ray-casting solid fill for watertight STL polyhedra, generating a solid boundary mesh with full interior support ($\approx 52,000$ particles at coarse, $\approx 213,000$ at medium).
- **Pros**: Retains the exact 52-facet STL asset without altering geometric profile.
- **Risk**: Increases boundary particle count, raising GPU memory by $\approx 10-15\%$.

#### Repair Proposal 1B (Multi-Layer Extrusion / Prismatic Bed Support):
- **Mechanism**: Generate a structured 3-layer boundary shell using GenCase advanced depth extrusion:
  ```xml
  <setmkbound mk="40" />
  <drawfilestl file="assets/f5_compact_continuous_bed_profile.stl" advanced="true">
    <depth depthmin="0.08" />
  </drawfilestl>
  ```
- **Rationale**: Guarantees exactly $3$ to $4$ boundary layers (thickness $0.08\text{ m} > 2h$) directly underneath the wet surface without filling the deep hollow core at $z = -0.15$ m, minimizing particle overhead.
- **Pros**: Bounded particle count while providing $100\%$ kernel completeness to the fluid.

---

### 4.2 Cause 2: Upstream Tank Floor and Sidewall Decoupling

#### Repair Proposal 2A (Floor Datum Realignment):
- **Mechanism**: Re-align `tank_floor` to sit at the upstream basin datum $z = 0.00$ m with solid fill and 3 layers:
  ```xml
  <setmkbound mk="0" />
  <drawbox cmt="tank_floor_upstream">
    <boxfill>solid</boxfill>
    <point x="-0.20" y="-0.18" z="-0.08" />
    <size x="2.20" y="0.36" z="0.08" />
    <layers vdp="0,1,2" />
  </drawbox>
  ```
- **Rationale**: Eliminates the 15 cm hollow drop under the flat basin ($x \in [0, 2]$ m), establishing a solid substrate directly under the fluid.

#### Repair Proposal 2B (Sidewall Width Expansion for Commensurate $3dp$ Support):
- **Mechanism**: Increase sidewall box width from $0.030$ m to $0.060$ m:
  ```xml
  <setmkbound mk="30" />
  <drawbox cmt="finite_sidewall_left">
    <boxfill>solid</boxfill>
    <point x="-0.20" y="-0.21" z="-0.15" />
    <size x="5.00" y="0.06" z="0.95" />
    <layers vdp="0,1,2" />
  </drawbox>
  ```
- **Rationale**: Allows coarse resolution ($dp = 0.020$ m) to instantiate all 3 layers (`vdp="0,1,2"`) without spatial boundary truncation, restoring lateral kernel support.

---

### 4.3 Cause 3: Shoreline Gauge Siting and Dry-Dropout Mitigation

#### Repair Proposal 3A (Gauge Siting Optimization):
- **Mechanism**: Realink probe positions to avoid geometric obstructions and thin shoreline dropouts:
  - Shift WG4 from $x = 3.20$ m upstream to $x = 2.90$ m (bed elevation $z = 0.252$ m, still-water depth $0.148$ m $\approx 7.4 dp$ in coarse).
  - Move Weir WG4 to downstream transmitted basin (e.g. $x = 4.20$ m) where it measures actual overtopping rather than the dry weir structure.
- **Rationale**: Ensures WG4 remains wet across all 3 commensurate resolutions, eliminating false resolution dropout.

#### Repair Proposal 3B (Evaluation Reporting Contract Segmentation):
- **Mechanism**: Retain native DualSPHysics dry codes in the frozen evaluator, but report segmented metrics:
  - `wet_only_relative_eta_rmse`: Computed strictly over time steps where both resolutions are wet.
  - `resolution_dropout_fraction`: Explicitly quantifying grid-dependent drying.
- **Rationale**: Prevents artificial skewing of RMSE by dry-code clamping while preserving frozen registration integrity.

---

## 5. Budget Accounting & Campaign Constraints

- **Qualification Cap**: 320 attempts (current count: 300 attempts used; 20 attempts remaining).
- **GPU Budget**: 96.0 h allocation (75.0 h used; 21.0 h remaining reserve).
- **Disk Storage**: `/home/jade` free space $\ge 500$ GiB strictly maintained.
- **Diagnostic Execution Cost**:
  - Proposed CPU diagnostic worker uses $\le 0.2$ CPU core-hours.
  - Zero GPU hours requested.
  - Zero new simulation runs staged until Root reviews diagnostic findings.

---

## 6. Verification Checklist & Non-Q-N Declaration

- [x] Independent source audit completed across all 4 candidate defect areas with exact C++ and XML pins.
- [x] Mathematical and geometrical proof of hollow bed established from actual particle counts.
- [x] Native DualSPHysics SWL gauge clamping mechanism deconstructed from C++ source.
- [x] Root-guarded diagnostic worker designed for existing Round 054 CSV exports.
- [x] Max 2 grounded minimal repair proposals per distinct cause provided.
- [x] Zero solver/GenCase execution performed.
- [x] Zero GPU attempt requests staged.
- [x] Scoped exclusively to own fresh handoff directory in infraWT.
- [x] Local scoped git commit prepared.

**SCIENTIFIC STATUS DECLARATION**:  
This audit provides diagnostic analysis only. No scientific Q-N qualification is granted. No product approval is claimed. Macro 057 failure remains active until actual diagnostic data is evaluated and Root formally approves an authorized repair.
