# F5 Root Followup 043: Technical Review, Compact Continuous Geometry Rewrite, and Legal Fallback Delivery v1

**Schema**: `ds02.f5.root-followup-043-review.v1`  
**Family ID**: `F5`  
**Scope Directory**: `campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_043_compact_fallback_v1`  
**Date**: `2026-10-04`  
**Process Mode**: Root Followup 043 F5 single-process primary agent (Gemini 3.8 Flash High, no recursive subagents)  
**Parent Worktree**: `/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics`  
**Commit Ref Target**: `codex/ds-data-02-infra`  
**Campaign Accounting**: Charged 66.7 GPU-hours of 96.0 binding allocation, remaining reserve 29.3 GPU-hours, qualification 276/320, Homefloor 500 GiB.

---

## 1. Executive Summary and Root Rejection Synthesis

### 1.1 Root Rejection of Commit 506d37cb (Followup 042)
Commit `506d37cb` attempted to establish a prospective fallback but failed to execute Root's architectural directives:
1. **Legacy Scale Retention**:
   - Despite instructions to shrink to a compact geometry, 042 preserved the legacy 11.95 m flume with a 1.44 m width, 4.20 m fluid length, and 2,352.0 kg fluid mass.
   - It merely renamed the large-scale configuration rather than authoring a genuine compact flume.
2. **Obsolete Resolution Grid**:
   - 042 used $\Delta p \in [0.050, 0.025, 0.010]$ m instead of the requested $[0.020, 0.0125, 0.010]$ m ladder.
3. **Severe Resource Consumption Threat**:
   - The fine pair alone in 042 demanded 12.0 GPU-hours (~40% of the remaining reserve), risking premature budget exhaustion against the binding 96.0 GPU-hour ceiling.
4. **Unsupported Causal Assertions**:
   - 042 claimed that the finite wave packet "eliminates chaos and reflection" and asserted that weir overtopping would occur. Under strict campaign governance, causal claims and hydrodynamic outcomes cannot be asserted from source code alone without actual simulation evidence.

### 1.2 Followup 043 Scoped Implementation
In response to Root Followup 043 directives, this scoped release completely rewrites the physical configuration into a genuine, self-contained compact 3D flume:
- **Geometry Dimensions**: Flume width $0.30$ m ($y \in [-0.15, +0.15]$ m), fluid length $2.00$ m ($x \in [0.00, 2.00]$ m), still water depth $H = 0.40$ m ($z \in [0.00, 0.40]$ m), fluid mass $240.0$ kg, total flume length $5.00$ m ($x \in [-0.20, 4.80]$ m).
- **Continuous Bed Profile**: 7 explicit profile nodes with continuous slope $m = 0.280$ ($x \in [2.00, 3.60]$ m), horizontal crest plateau at $z = 0.448$ m ($x \in [3.60, 3.90]$ m), and downslope into a receiving basin at $z = 0.050$ m ($x \in [4.40, 4.80]$ m).
- **Two Real Hydrodynamic Mechanisms**: Sloping bed runup/return (`runup_return`) and notched weir overtopping/retention (`weir_overtopping`). Overtopping is treated as a candidate physical hypothesis without unproven dogmatic claims.
- **Observer Coordinate Correction**: All 6 Eulerian wave probes placed with baseline `point0.z` strictly equal to the true local bed elevation $z_{\text{bed}}(x)$, completely resolving sub-bed embedding defects and preventing false 1.5H step collapses.
- **Boundary Support Policy**: Reuses Root024 (`root_surface_first_boundary_preservation_024`) surface-first 52-triangle rasterization using verified `full` drawmode syntax. No invented asset SHAs, no 2mm floor gates.
- **Unequal-$r$ Resolution Ladder**: $\Delta p \in [0.020, 0.0125, 0.010]$ m ($r_{21} = 1.25$, $r_{32} = 1.6$, $r_{31} = 2.0$). Theoretical Cartesian lattice predictions separated from actual GenCase outputs.
- **Bounded Resource Footprint**: Fine pair maxwall reduced from 12.0 GPUh to 2.00 GPUh (expected ~1.80 GPUh). Total 3-DP ladder maxwall is 3.334 GPUh (expected ~2.65 GPUh), preserving 26.65 GPUh of reserve headroom.

---

## 2. Concrete Compact Physical Continuous Geometry

### 2.1 Flume and Fluid Coordinates
The flume is modeled as an authentic 3D wave channel with physical solid sidewalls, floor, and wavemaker backing:

| Parameter | Value | Unit | Coordinate Interval / Notes |
| :--- | :--- | :--- | :--- |
| **Total Flume Length** | $5.00$ | m | $x \in [-0.20, 4.80]$ m |
| **Flume Channel Width** | $0.30$ | m | $y \in [-0.15, +0.15]$ m |
| **Still Water Depth $H$** | $0.40$ | m | $z \in [0.00, 0.40]$ m |
| **Fluid Domain Length** | $2.00$ | m | $x \in [0.00, 2.00]$ m |
| **Nominal Fluid Volume** | $0.240$ | $\text{m}^3$ | $2.00 \times 0.30 \times 0.40$ |
| **Nominal Fluid Mass** | $240.0$ | kg | $\rho_0 = 1000\text{ kg/m}^3$ |
| **Left Sidewall** | $0.03$ | m thick | $y \in [-0.18, -0.15]$, $z \in [-0.15, 0.80]$ |
| **Right Sidewall** | $0.03$ | m thick | $y \in [0.15, 0.18]$, $z \in [-0.15, 0.80]$ |
| **Tank Sub-Floor** | $0.15$ | m thick | $x \in [-0.20, 4.80]$, $z \in [-0.15, 0.00]$ |
| **Wavemaker Piston** | $0.04$ | m thick | $x \in [-0.04, 0.00]$, $y \in [-0.15, 0.15]$ at rest |

### 2.2 Explicit Continuous Bed Profile Nodes
The longitudinal bed profile $z_{\text{bed}}(x)$ is defined by 7 continuous profile nodes:

```
 z [m]
 0.50 |                                 [3.60, 0.448] -- [3.90, 0.448] (Crest Plateau)
      |                                      /                  \
 0.40 | - - - - - - - - - - - - - - - - - - / - - - - - - - - - - \ - - - SWL = 0.40 m
      |                                    /                       \
 0.28 |                        [3.00, 0.280]                        \
      |                             /                                \
 0.05 |                            /                                  \-- [4.40, 0.05] -- [4.80, 0.05] (Basin)
 0.00 | [-0.20, 0.0] -- [2.00, 0.0]
      +--------------------------------------------------------------------> x [m]
       -0.20            2.00    2.60   3.00    3.43  3.60   3.90       4.40             4.80
```

1. **Node 0** `[-0.20, 0.000]`: Upstream paddle stroke clearance zone.
2. **Node 1** `[2.00, 0.000]`: End of flat generation reach; slope toe.
3. **Node 2** `[3.00, 0.280]`: Mid-slope shoaling station. Slope $m = (0.280 - 0.000)/(3.00 - 2.00) = 0.280$.
4. **Node 3** `[3.60, 0.448]`: Crest start. Slope $m = (0.448 - 0.280)/(3.60 - 3.00) = 0.280$. Total slope length $\Delta x = 1.60$ m. Shoreline at SWL $z=0.40$ m is at $x = 3.429$ m.
5. **Node 4** `[3.90, 0.448]`: Crest plateau of length $0.30$ m at elevation $z = 0.448$ m ($4.8$ cm above SWL).
6. **Node 5** `[4.40, 0.050]`: Downslope descending into downstream receiving basin.
7. **Node 6** `[4.80, 0.050]`: Receiving basin floor of length $0.40$ m at elevation $z = 0.050$ m.

### 2.3 Low Crest Notched Weir Structure (Weir Mechanism)
In the weir case, a low crest structure with a lateral notch is positioned on the slope:
- **Longitudinal Range**: $x \in [3.20, 3.35]$ m (length $\Delta x = 0.15$ m).
- **Bed Base Elevation**: $z_{\text{bed}} = (3.20 - 2.00) \times 0.280 = 0.336$ m.
- **Left Shoulder**: $y \in [-0.15, -0.04]$ m, crest elevation $z = 0.460$ m ($6.0$ cm above SWL).
- **Right Shoulder**: $y \in [0.04, 0.15]$ m, crest elevation $z = 0.460$ m ($6.0$ cm above SWL).
- **Central Notch**: $y \in [-0.04, 0.04]$ m (width $0.08$ m), sill elevation $z = 0.410$ m ($1.0$ cm above SWL).
- **Hydrodynamic Function**: A wave exceeding $1.0$ cm runup amplitude at $x=3.20$ m spills through the central notch into the upper slope and downstream basin, while waves impinging on the lateral shoulders are retained and reflected downslope.

---

## 3. Surface-First Numerical Boundary Support Policy (Root024 Heritage)

The XML generation adheres strictly to the proven boundary preservation policy established in Root024 (`root_surface_first_boundary_preservation_024`):
1. **Surface Rasterization First**:
   - The 52 triangular facets of the compact continuous bed are written directly into `<drawtriangles>` under `<setdrawmode mode="full">` with dedicated boundary marker `mk="40"`.
   - Drawing triangles first ensures that subsequent voxel rasterization gives ownership of boundary points along the physical walls and piston to the continuous surface.
2. **Proven Valid Drawmode Syntax**:
   - `<setdrawmode mode="full">` is used for surface triangles and `<drawfilestl file="assets/f5_compact_continuous_bed_profile.stl">`.
   - `<setdrawmode mode="solid">` is restored for box fills (floor, walls, piston, weir).
   - Unverified custom solid setdrawmode syntax is avoided.
3. **No Invented Asset SHAs or 2mm Floor Gates**:
   - No hardcoded synthetic hash is asserted for the compact bed STL. The SHA256 digest is computed dynamically by the preparation worker upon Rootguard generation.
   - Fluid bounding boxes match integer grid cell boundaries exactly with no arbitrary $2$ mm floor offsets.

---

## 4. Observer True Local Bed Elevation Layout

The Eulerian wave probes are positioned across 6 key physical zones with baseline elevations `point0.z` matching the exact local continuous bed elevation:

| Gauge Name | $x$ [m] | $y$ [m] | $z_{\text{bed}}(x)$ [m] | `point0.z` [m] | `point2.z` [m] | Zone Description |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **WG1** | $0.60$ | $0.0$ | $0.000$ | $0.000$ | $0.700$ | Upstream flat basin propagation |
| **WG2** | $1.40$ | $0.0$ | $0.000$ | $0.000$ | $0.700$ | Shoaling approach before slope toe |
| **RunupToe** | $2.00$ | $0.0$ | $0.000$ | $0.000$ | $0.700$ | Exact slope toe transition |
| **WG3** | $2.60$ | $0.0$ | $0.168$ | $0.168$ | $0.700$ | Lower slope shoaling / breaking |
| **WG4** | $3.20$ | $0.0$ | $0.336$ | $0.336$ | $0.700$ | Upper slope / weir approach |
| **Crest** | $3.75$ | $0.0$ | $0.448$ | $0.448$ | $0.700$ | Horizontal crest plateau |

**Resolution of Observer Defect**:
- In legacy 024/042 cases, probes on the slope had `point0.z = -0.020` m, placing the baseline up to $55$ cm below solid rock. When fluid drained below the surface detection threshold, DualSPHysics `JDsGaugeItem` collapsed to `point0.z`, creating a catastrophic $1.5H$ artificial negative step jump.
- In this compact specification, when water recedes on the slope or crest, the gauge collapses to `point0.z = z_bed`, reporting a relative water depth $\eta - z_{\text{bed}} \equiv 0.000$ m, completely eliminating artificial observer errors.

---

## 5. Commensurate Unequal-$r$ Resolution Ladder

The prospective cases form an unequal-$r$ spatial convergence ladder:

$$\Delta p \in [0.020, 0.0125, 0.010]\text{ m} \quad \implies \quad r_{21} = 1.25, \; r_{32} = 1.60, \; r_{31} = 2.00$$

Direct unequal-$r$ comparison is employed without Richardson extrapolation assumptions:

| Resolution Key | $\Delta p$ [m] | Name | Grid Size ($N_x \times N_y \times N_z$) | Theoretical Fluid Lattice Particles | Nominal Root Fluid Index | Predicted Total Particles | Maxwall [s] | Maxwall [GPUh] |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **dp020** | $0.0200$ | Coarse | $100 \times 15 \times 20$ | $30,000$ | $60,000$ | $\approx 50,000$ | $600$ | $0.167$ |
| **dp0125** | $0.0125$ | Medium | $160 \times 24 \times 32$ | $122,880$ | $122,880$ | $\approx 178,000$ | $1800$ | $0.500$ |
| **dp010** | $0.0100$ | Fine | $200 \times 30 \times 40$ | $240,000$ | $240,000$ | $\approx 325,000$ | $3600$ | $1.000$ |

*Governance Note on Particles: Theoretical fluid lattice particle counts represent analytical volume discretizations ($2.00 \times 0.30 \times 0.40\text{ m}^3 / \Delta p^3$). Nominal root fluid index reflects the Root specification reference numbers. Actual simulation particle counts are determined solely upon GenCase execution and are not claimed as pre-existing facts.*

---

## 6. Finite Single-Wave Packet Control

The wavemaker paddle displacement $x(t)$ is driven by `control_compact_packet.dat` over the full $16.0$ s event window:
- **Sampling Frequency**: $40$ Hz ($\Delta t = 0.025$ s, 641 discrete time points).
- **Pulse Duration**: $T_{\text{pulse}} = 5.0$ s.
- **Wavemaker Stroke**: Peak excursion $S_{\text{max}} = 0.0243$ m ($2.43$ cm), strictly within flume limits ($\le 0.030$ m).
- **Quiescent Return Window**: For $t \in [5.0, 16.0]$ s, $x(t) \equiv 0.00000000$ m (residual $< 10^{-12}$ m). The paddle acts as a rigid stationary end wall during return flow.
- **Assertion Boundary**: The single packet isolates incident propagation from paddle reflection, but does NOT assert unproven elimination of wave turbulence or chaos.

---

## 7. Bounded GPU Budget and Headroom Analysis

```
Campaign Allocated Budget: 96.0 GPU-hours
[===================================================-----------------------]
Charged: 66.7 GPUh                                   Remaining Reserve: 29.3 GPUh
                                                     |
                                                     +- Proposed 3-DP Ladder: ~2.65 GPUh
                                                     +- Preserved Headroom:   ~26.65 GPUh
```

| Execution Scope | Maxwall per Run | Total Maxwall (Pair) | Expected Runtime (Pair) | Impact on 29.3 GPUh Reserve |
| :--- | :--- | :--- | :--- | :--- |
| **Coarse Pair (Runup + Weir)** | $600$ s ($0.167$ h) | $0.334$ GPUh | $\approx 0.16$ GPUh | $0.5\%$ |
| **Medium Pair (Runup + Weir)** | $1800$ s ($0.500$ h) | $1.000$ GPUh | $\approx 0.70$ GPUh | $2.4\%$ |
| **Fine Pair (Runup + Weir)** | $3600$ s ($1.000$ h) | $2.000$ GPUh | $\approx 1.80$ GPUh | $6.1\%$ |
| **Total 3-DP Ladder (6 cases)** | — | **$3.334$ GPUh** | **$\approx 2.66$ GPUh** | **$9.1\%$** |

**Comparison with Rejected 042**:
- In 042, the fine pair alone demanded $12.0$ GPU-hours (~$41\%$ of the remaining budget).
- The compact rewrite reduces fine pair execution by **$6.7\times$** to $\le 2.00$ GPUh maxwall, leaving over $26.65$ GPUh ($>90\%$) of campaign reserve intact for downstream evaluation.

---

## 8. Deliverables Inventory in `root_followup_043_compact_fallback_v1`

1. **`generate_compact_continuous_bed_stl.py`**:
   - Pure-function geometry and watertight 52-triangle mesh generator for the compact continuous bed.
   - Provides exact $z_{\text{bed}}(x)$ interpolation and CLI entry point for Rootguard asset generation.
2. **`generate_compact_packet_motion.py`**:
   - Pure-function finite single-wave packet motion generator with smooth Hann tapering and 11.0 s quiescent tail.
3. **`prepare_compact_fallback_cases.py`**:
   - Case preparation worker synthesizing all 6 DualSPHysics XML definitions and `prepared_cases_manifest.json`.
4. **`compact_fallback_specification.json`**:
   - Formal machine-readable ds02 specification for compact physical dimensions, bed nodes, weir structure, and observers.
5. **`definitions/runup/`**:
   - `F5_REF_RUNUP_DP020_COMPACT_043.xml`
   - `F5_REF_RUNUP_DP0125_COMPACT_043.xml`
   - `F5_REF_RUNUP_DP010_COMPACT_043.xml`
6. **`definitions/weir/`**:
   - `F5_REF_WEIR_DP020_COMPACT_043.xml`
   - `F5_REF_WEIR_DP0125_COMPACT_043.xml`
   - `F5_REF_WEIR_DP010_COMPACT_043.xml`
7. **`requests/`**:
   - `F5_COMPACT_FALLBACK_PREPARATION_REQUEST.json`: Bounded CPU asset preparation (`launch_allowed: false`).
   - `F5_COMPACT_FALLBACK_GENCASE_3DP_REQUEST.json`: Bounded CPU GenCase execution (`launch_allowed: false`).
   - `F5_COMPACT_FALLBACK_SOLVER_3DP_REQUEST.json`: GPU solver execution for 6 cases (~2.65 GPUh expected, `launch_allowed: false`).
8. **`test_compact_fallback_v1.py`**:
   - 9 synthetic unit tests validating profile geometry, watertight mesh topology, observer alignment, motion characteristics, XML syntax, and request governance (100% pass).
9. **`manifest.json`**:
   - Cryptographic catalog of all deliverables with byte sizes and SHA256 digests.

---

## 9. Next Executable Tasks for Root

1. **Request Review**: Root reviews `requests/F5_COMPACT_FALLBACK_PREPARATION_REQUEST.json` and `requests/F5_COMPACT_FALLBACK_GENCASE_3DP_REQUEST.json`.
2. **Rootguard Asset Dispatch**: When authorized, Root launches the CPU preparation task to write `assets/f5_compact_continuous_bed_profile.stl` and `control_compact_packet.dat`.
3. **GenCase Dispatch**: Root dispatches GenCase across the 6 compact definitions to obtain true boundary and fluid particle statistics.
4. **GPU Lease Scheduling**: Following successful preflight, Root schedules the 3-DP ladder solver request (~2.65 GPUh) within the shared DS-DATA-02 runner lease.
