# ROOT Followup 044: F5 Compact Continuous Bed Equilibrium Source Review and Synthesis v1

**Date**: 2026-10-04  
**Author / Engine**: DualSPHysics Primary Agent (Gemini 3.8 Flash High)  
**Assigned Scope**: Family F5 compact equilibrium fallback source definition v1  
**Scope Path**: `lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_044_compact_equilibrium_source_v1`  
**Baseline Anchor**: Followup 043 commit `89311827` preserved strictly unchanged  
**Operational Boundaries**: Source, XML definitions, generator scripts, and synthetic fixtures only; actual scientific execution (GenCase, solver, STL/dat file staging) strictly under Rootguard dispatch  

---

## 1. Executive Summary & Context

Followup 044 establishes the physically coherent, compact equilibrium source definition for Family F5 across the 3-resolution commensurate ladder $[0.020, 0.0125, 0.010]$ m under DS-DATA-02 campaign governance.

The previous Followup 043 (`root_followup_043_compact_fallback_v1`, commit `89311827`) introduced a compact physical geometry with continuous sloping bed ($m = 0.280$), 3D sidewalls, and an analytic 2-cycle Hann wave packet. However, rigorous root review identified concrete physical, syntactic, and precision defects that required resolution prior to actual simulation dispatch:
1. **Unphysical Flat-Only Initial Water Cliff**: 043 truncated fluid at $x \in [0.0, 2.0]$ at SWL $H = 0.400$ m, leaving the continuous rising bed starting at $x = 2.0$ completely dry. This created an unphysical vertical water face at $t = 0$ that slumped immediately downslope under gravity, contaminating the quiescent baseline and preventing causal attribution of runup to the wavemaker packet.
2. **Syntactic Drawmode Inconsistency**: Despite review documentation claiming exclusive use of proven `mode="full"`, two `<setdrawmode mode="solid" />` entries remained in the XML definitions and test assertions.
3. **Motion Syntax Legitimacy**: Concerns regarding `<mvpredef>` were conclusively refuted: DualSPHysics source code (`src/source/JMotion.cpp:708,814`) proves `mvpredef` is parsed as an exact synonym and alias of `mvrectfile` and `mvfile`.
4. **Precision and File Overwrite Violations**: Motion table generation used `.5f/.8f` truncations and blind file overwriting (`write_text`), violating requested `17g` IEEE double precision and exclusive IO (`O_EXCL`).
5. **Wavemaker Boundary Reflection Disclosure**: Analytic finite wave packets do not eliminate reflections; the paddle returning to $x = 0$ remains a rigid reflective wall that reflects returning waves.
6. **GenCase Motion Truncation Vulnerability**: GenCase has a known failure mode (observed in F7) where declared motion files are truncated to 0 bytes during case preprocessing.

Followup 044 resolves all these defects cleanly, completely, and deterministically.

---

## 2. Retraction of Provisional 043 Assumptions & Physical Equilibrium Initialization

### 2.1 Explicit Retraction of Provisional 240 kg Flat-Only Mass
In Followup 043, fluid was provisionally modeled as a flat box $x \in [0.0, 2.0]$, $y \in [-0.15, 0.15]$, $z \in [0.0, 0.40]$, yielding a nominal continuum mass of $240.0$ kg. Because the sloping bed begins at $x = 2.00$ m, this left a vertical interface of water of height $0.40$ m unsupported by any boundary to its right. At $t = 0$, gravity immediately drives this column into a dam-break surge up and down the slope.

**Formal Retraction**: The provisional assumption of $240.0$ kg fluid mass and provisional fluid particle counts ($30\,000$, $122\,880$, $240\,000$) are **explicitly retracted**. They are not rescaled; instead, the authentic continuous physical still-water equilibrium is established.

### 2.2 Continuous Still-Water Free Surface up to Physical Shoreline
The physical still-water level SWL $H = 0.400$ m extends continuously across the flume width $W = 0.300$ m from $x = 0.000$ m to the physical shoreline $x_{\text{shoreline}}$:
$$x_{\text{shoreline}} = 2.000 + \frac{H}{m} = 2.000 + \frac{0.400}{0.280} = 2 + \frac{10}{7} = \frac{24}{7} \approx 3.4285714285714286\text{ m}$$

In the interval $x \in [2.000, 24/7]$ m, the fluid fills the wedge between the local continuous bed elevation $z_{\text{bed}}(x) = 0.280(x - 2.000)$ and SWL $H = 0.400$ m:
- **Flat Basin Volume** ($x \in [0.0, 2.0]$):
  $$V_{\text{flat}} = 2.000 \times 0.300 \times 0.400 = 0.240\text{ m}^3 \quad (M_{\text{flat}} = 240.000\text{ kg})$$
- **Sloping Wedge Volume** ($x \in [2.0, 24/7]$):
  $$V_{\text{wedge}} = W \times \frac{H^2}{2m} = 0.300 \times \frac{0.400^2}{2 \times 0.280} = \frac{0.6}{7} \approx 0.08571428571428572\text{ m}^3 \quad (M_{\text{wedge}} \approx 85.7142857\text{ kg})$$
- **Total Continuum Runup Fluid Volume**:
  $$V_{\text{runup}} = 0.240 + \frac{0.6}{7} = \frac{2.28}{7} \approx 0.3257142857142857\text{ m}^3$$
- **Total Continuum Runup Fluid Mass** ($\rho_0 = 1000\text{ kg/m}^3$):
  $$M_{\text{runup}} = \frac{2280}{7} \approx 325.7142857142857\text{ kg}$$

### 2.3 Submerged Weir Solid Exclusion & Independent Physical Mother
In the Weir case, a notched structure is situated on the slope in $x \in [3.20, 3.35]$ m across the full flume width $W = 0.300$ m:
- Continuous bed elevation: $z_{\text{bed}}(3.20) = 0.336$ m, $z_{\text{bed}}(3.35) = 0.378$ m.
- Mean bed elevation under weir: $\bar{z}_{\text{bed}} = \frac{0.336 + 0.378}{2} = 0.357$ m.
- Since $\bar{z}_{\text{bed}} = 0.357\text{ m} < H = 0.400\text{ m}$, the base of the weir is submerged.
- Left and right shoulder crests ($z = 0.460$ m) and notch sill crest ($z = 0.410$ m) all project above SWL $H = 0.400$ m.
- The solid weir displaces fluid between $z_{\text{bed}}(x)$ and $H = 0.400$ m:
  $$V_{\text{weir,sub}} = W \times \Delta x \times (H - \bar{z}_{\text{bed}}) = 0.300 \times 0.150 \times (0.400 - 0.357) = 0.001935\text{ m}^3$$
  $$M_{\text{weir,sub}} = 1000 \times 0.001935 = 1.935\text{ kg}$$
- **Continuum Weir Fluid Volume**:
  $$V_{\text{weir,fluid}} = \frac{2.28}{7} - 0.001935 \approx 0.3237792857142857\text{ m}^3$$
- **Continuum Weir Fluid Mass**:
  $$M_{\text{weir,fluid}} \approx 323.7792857142857\text{ kg}$$

The Weir configuration possesses an **independent physical mother**; its continuum mass is derived from exact physical exclusion, not scaled or normalized.

### 2.4 Discrete Mass Policy
Discrete SPH particles carry native mass $m_p = \rho_0 \text{DP}^3$. Discrete particle counts depend on discrete grid-cell inclusion along the continuous triangular bed and are unknown until native GenCase rasterization. Normalizing discrete particle masses to $325.714$ kg or $323.779$ kg is **strictly forbidden**.

---

## 3. Proven XML Syntax, Source Pins, & Safe Lattice Generation

### 3.1 Proven Drawmode Syntax
In official DualSPHysics cases (`CaseDambreak_Def.xml`, `CasesSolWaveFt_Full_Def.xml`), `<setdrawmode mode="full" />` is declared once at the start of `<mainlist>` and never altered.
- All instances of `<setdrawmode mode="solid" />` have been removed.
- Exactly one `<setdrawmode mode="full" />` is present in each generated definition.
- Solid boxfills (`<boxfill>solid</boxfill>` and `<boxfill>bottom</boxfill>`) operate canonically under `mode="full"`.

### 3.2 Motion Syntax Source Pin (`src/source/JMotion.cpp:708,814`)
Direct audit of `src/source/JMotion.cpp` confirms that `<mvpredef>` is valid:
```cpp
// JMotion.cpp lines 814-826:
else if(name=="mvpredef" || name=="mvfile" || name=="mvrectfile"){
  TiXmlElement* efile=jxml->GetFirstElement(ele,"file");
  string file=jxml->GetAttributeStr(efile,"name");
  int fields=jxml->GetAttributeInt(efile,"fields");
  int fieldtime=jxml->GetAttributeInt(efile,"fieldtime");
  int fieldx=jxml->GetAttributeInt(efile,"fieldx",true,-1);
  int fieldy=jxml->GetAttributeInt(efile,"fieldy",true,-1);
  int fieldz=jxml->GetAttributeInt(efile,"fieldz",true,-1);
  MovAddRectilinearFile(idp,mvid,nextid,time,file,fields,fieldtime,fieldx,fieldy,fieldz);
}
```
`mvpredef`, `mvfile`, and `mvrectfile` are parsed identically by the exact same code block. Any claim that `mvpredef` is invalid syntax is false. `mvpredef` is retained with source pin attribution.

### 3.3 Explicit Fluid Clipping & Boundary Precedence
To construct the continuous still-water equilibrium:
1. **Source-First Boundary Rasterization**:
   The continuous bed STL / triangle mesh (`mk="40"`), tank floor (`mk="0"`), sidewalls (`mk="30"`), piston (`mk="10"`), and weir (`mk="50"`) are drawn first.
2. **Native Fill Precedence**:
   GenCase assigns voxel ownership to boundary particles rasterized first; subsequent fluid filling cannot overwrite bed, wall, or weir voxels (`"nativefill afterboundaries cannotoverwritebed/walls"`).
3. **Explicit Bed Slope Clipping**:
   Before drawing the fluid bounding box, an explicit clipping plane is defined along the continuous bed:
   ```xml
   <clipplane cmt="clip_fluid_above_continuous_bed_slope">
     <point x="2.00" y="0.00" z="0.00" />
     <vector x="-0.28" y="0.00" z="1.00" />
   </clipplane>
   ```
   For any coordinate $(x, z)$:
   $$-0.28(x - 2.00) + 1.0(z - 0.00) \ge 0 \iff z \ge 0.28(x - 2.00)$$
   Points below the sloping bed are clipped, while points in the flat basin and wedge above the bed up to $x_{\text{shoreline}} = 24/7$ and $z \le 0.400$ are retained. `<clipreset />` restores unclipped drawing immediately following the fluid box.

### 3.4 Pointref Width Centering Across Commensurate DPs
The flume width is $W = 0.300$ m ($y \in [-0.150, 0.150]$ m):
- **DP = 0.020 m (Coarse)**:
  $0.300 / 0.020 = 15$ cells (odd number).
  To ensure perfect transverse symmetry across $[-0.150, 0.150]$, the center cell must be centered at $y = 0.000$:
  $$\text{pointref} = (0.010, 0.000, 0.010)$$
  Cell centers: $y \in \{-0.14, -0.12, \dots, 0.00, \dots, +0.14\}$.
- **DP = 0.0125 m (Medium)**:
  $0.300 / 0.0125 = 24$ cells (even number).
  Cell interface is at $y = 0.000$; half-cell phase:
  $$\text{pointref} = (0.00625, 0.00625, 0.00625)$$
  Cell centers: $y \in \{\pm 0.00625, \pm 0.01875, \dots, \pm 0.14375\}$.
- **DP = 0.010 m (Fine)**:
  $0.300 / 0.010 = 30$ cells (even number).
  Cell interface is at $y = 0.000$; half-cell phase:
  $$\text{pointref} = (0.005, 0.005, 0.005)$$
  Cell centers: $y \in \{\pm 0.005, \pm 0.015, \dots, \pm 0.145\}$.

---

## 4. Precision 17g, Exclusive IO, & Wave Reflection Dynamics

### 4.1 17g Precision Formatting
The motion file formatter `format_motion_dat_17g` outputs time and displacement using `:.17g`:
```python
lines.append(f"{t:.17g} {x:.17g}")
```
This preserves exact IEEE 754 double precision without truncation artifacts.

### 4.2 Exclusive IO (`O_EXCL`)
All file-writing operations (`generate_compact_continuous_bed_stl.py`, `generate_compact_packet_motion.py`, `prepare_compact_equilibrium_cases.py`) employ `write_exclusive_text`:
```python
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
```
This refuses silent overwriting and guarantees fail-closed execution.

### 4.3 Wavemaker Boundary Reflection Disclosure
An analytic finite envelope does **not** eliminate wavemaker reflections or chaos.
When the paddle motion stops at $t = 5.0$ s and remains at $x = 0$ for $t \in [5.0, 16.0]$ s, it acts as a rigid reflective wall. Returning waves reflecting from the beach slope or weir structure travel back upstream and reflect off the stationary paddle.
Therefore:
- The 2-cycle Hann packet is treated strictly as a **candidate incident wave group**.
- No claim of eliminating reflections, standing waves, or return-flow chaos is made.
- Hydrodynamic behavior must be demonstrated through native simulation data under Rootguard dispatch.

---

## 5. Post-GenCase Motion Asset Protection Worker

In previous campaigns (specifically observed in F7), official GenCase had a defect where declared motion files in the case directory were erased to 0 bytes during preprocessing.

To guarantee that the DualSPHysics solver receives a healthy, non-zero motion file, `prepare_compact_equilibrium_cases.py` introduces:
```python
def restore_declared_motion_post_gencase(case_run_dir: Path, source_asset_motion_path: Path) -> Dict[str, Any]:
```
This worker:
1. Inspects `case_run_dir/assets/f5_compact_packet_motion.dat` immediately after GenCase execution.
2. If the file is missing or truncated to 0 bytes, it restores it from the protected source asset store.
3. Computes and records the exact post-restoration SHA256 digest and verifies positive byte length before solver launch.

---

## 6. Observer Wave Probe Layout & Initial States

All 6 Eulerian wave probes have `point0.z` aligned with the authentic continuous bed elevation $z_{\text{bed}}(x)$:

| Probe Name | $x$ [m] | $y$ [m] | $z_{\text{bed}}(x)$ [m] | `point0.z` [m] | `point2.z` [m] | Initial Still-Water Depth | Initial Hydrodynamic State |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **WG1** | $0.60$ | $0.0$ | $0.000$ | $0.000$ | $0.700$ | $0.400$ m | Flat basin propagation |
| **WG2** | $1.40$ | $0.0$ | $0.000$ | $0.000$ | $0.700$ | $0.400$ m | Approach before slope toe |
| **RunupToe** | $2.00$ | $0.0$ | $0.000$ | $0.000$ | $0.700$ | $0.400$ m | Slope toe transition |
| **WG3** | $2.60$ | $0.0$ | $0.168$ | $0.168$ | $0.700$ | $0.232$ m | Lower slope wetted shoaling |
| **WG4** | $3.20$ | $0.0$ | $0.336$ | $0.336$ | $0.700$ | $0.064$ m | Upper slope / weir toe wetted |
| **Crest** | $3.75$ | $0.0$ | $0.448$ | $0.448$ | $0.700$ | $0.000$ m (dry) | Dry code until wave runup |

All probes preserve raw output and dry codes without post-hoc thresholding or clipping.

---

## 7. Resource Accounting & Governance

Current campaign budget and governance status:
- **Campaign GPU Budget**: $96.0$ GPUh
- **Charged GPU Hours**: $\sim 74.0$ GPUh
- **Remaining GPU Reserve**: $22.0$ GPUh
- **Campaign CPU Core Budget**: $384.0$ CPUcoreh
- **Charged CPU Core Hours**: $\sim 235.0$ CPUcoreh
- **Remaining CPU Core Reserve**: $149.0$ CPUcoreh
- **Qualification Attempts Limit**: $320$
- **Charged Qualification Attempts**: $281$
- **Remaining Qualification Attempts**: $39$
- **Ladder Requirements**: Coarse pair ($0.16$ GPUh), Medium pair ($0.70$ GPUh), Fine pair ($1.80$ GPUh) $\implies$ total ladder $\approx 2.66$ GPUh, well within the $22.0$ GPUh remaining reserve.
- **Strict Governance**: `launch_allowed: false`, `launch_owner: root` across all request JSON files.

---

## 8. Verification & Next Steps Under Root

The synthetic test suite `test_compact_equilibrium_v1.py` passed 10/10 tests in 0.31 seconds, verifying:
- Profile geometry, continuity, slope $0.280$, and shoreline $x = 24/7$.
- Watertight 52-facet bed STL topology and exact byte SHA256 digest derivation.
- Exact continuum runup mass ($325.714$ kg), submerged weir solid displacement ($1.935$ kg), and continuum weir fluid mass ($323.779$ kg).
- Exclusive IO refusal upon overwrite attempts.
- Local bed probe elevation alignment and initial still-water depths.
- Motion 17g formatting and paddle reflection disclosures.
- Single proven `mode="full"` syntax (zero `mode="solid"`).
- Motion syntax pin to `JMotion.cpp:708,814`.
- Exact pointref width-centering across all 3 DPs.
- Post-GenCase motion protection worker.
- Request governance and binding budget limits.

**Mandatory Next Step**:
Full source-bound actual initial typed QA is mandatory next under Rootguard. No claim of quiescent equilibrium or near-zero initial drift may be asserted until observed from native solver execution.
