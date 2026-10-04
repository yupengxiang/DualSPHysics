# Source Audit: Exact Generators / Sources 027–035 and Canonical 034 for Family F1

## Executive Summary

This document presents a rigorous source-level audit of the geometry generators, boundary representations, numerical constants, and execution records for Family F1 (Free-Surface Channel Flow with Asymmetric Obstacles and Dividers) across progression stages 027 through 035, up to canonical baseline 034 and checkpoint 039.

Family F1 comprises two distinct physical hydrodynamic mechanisms:
1. **Mechanism 1 (`eccentric_obstacle` / ECC)**: High-speed dambreak impact onto an eccentric prismatic solid obstacle in a rectangular flume, generating 3D asymmetric wake bypass, corner vortex shedding, and downstream wall reflection.
2. **Mechanism 2 (`asymmetric_dual_channel` / DUAL)**: Large-scale reservoir release into an asymmetrically partitioned flume, splitting the bulk surge into two unequal channels with differential velocity, surface elevation, and wave reflection.

---

## 1. Historical Failure Mode Audit: Why Old Mothers Failed

Before adopting the lower-head baseline, earlier attempts in DS-DATA-02 utilized oversized initial fluid depths:
- **Old ECC Mother**: Initial fluid height $H_0 = 0.30\ \text{m}$, continuum mass $M = 80.4\ \text{kg}$, within a tank of height $H_{\text{tank}} = 0.40\ \text{m}$.
  - *Root Cause of Failure*: With only $0.10\ \text{m}$ freeboard ($25\%$ reserve), the high-momentum dambreak surge violently climbed the front face of the obstacle at $x=0.90\ \text{m}$. The resulting runup wave overtopped the open flume sidewalls, splashing massive fluid mass out of the domain.
  - *Secondary Cause*: Boundary modeling used single-particle-layer or thin DBC walls, resulting in particle penetrations under high stagnation pressures.
- **Old DUAL Mother**: Initial fluid height $H_0 = 0.55\ \text{m}$, continuum mass $M = 616.0\ \text{kg}$, within a tank of height $H_{\text{tank}} = 0.80\ \text{m}$.
  - *Root Cause of Failure*: A fluid column of $616\ \text{kg}$ with only $0.25\ \text{m}$ freeboard slammed into the channel divider at $x=1.20\ \text{m}$. The hydraulic bore crested over the top of the divider and flume sidewalls, producing catastrophic mass loss and non-physical boundary behavior.

### The Corrective Fallback: Lower-Head and Thick DBC
Stages 027 through 032 established the lower-head thick DBC regime:
- **ECC Lower-Head**: $H_0 = 0.15\ \text{m}$, continuum mass $M = 40.2\ \text{kg}$.
  - Tank dimensions: $1.60 \times 0.67 \times 0.40\ \text{m}$.
  - Freeboard increased from $0.10\ \text{m}$ to $0.25\ \text{m}$ ($62.5\%$ reserve), completely eliminating overtopping.
  - Boundary: 4-layer thick DBC ($3 \times dp$ wall thickness), $mk=0$ for tank and $mk=1$ for obstacle.
- **DUAL Lower-Head**: $H_0 = 0.30\ \text{m}$, continuum mass $M = 300.0\ \text{kg}$.
  - Tank dimensions: $3.20 \times 1.00 \times 0.80\ \text{m}$.
  - Freeboard increased from $0.25\ \text{m}$ to $0.50\ \text{m}$ ($62.5\%$ reserve), completely containing the bore.
  - Boundary: 4-layer thick DBC ($3 \times dp$ wall thickness), $mk=0$ for tank and $mk=1$ for divider.

---

## 2. Inventory of Source Definitions and Progression (027–035)

| Step / Attempt ID | Case ID | Resolution / $dp$ | Particle Count (Fluid / Total) | Returncode | Status |
|:---|:---|:---:|:---:|:---:|:---|
| `root-fallback-ecc-coarse-actual-gencase-027` | `F1_FALLBACK_ECC_COARSE` | $0.01\ \text{m}$ | $40,200$ / $141,636$ | 0 | Completed |
| `root-fallback-ecc-medium-actual-gencase-027` | `F1_FALLBACK_ECC_MEDIUM` | $0.005\ \text{m}$ | $321,600$ / $711,252$ | 0 | Completed |
| `root-fallback-ecc-fine-actual-gencase-output-text-fix-028` | `F1_FALLBACK_ECC_FINE` | $0.00333333\ \text{m}$ | $1,085,400$ / $1,950,372$ | 0 | Completed |
| `root-fallback-dual-coarse-actual-gencase-027` | `F1_FALLBACK_DUAL_COARSE` | $0.02\ \text{m}$ | $37,500$ / $125,316$ | 0 | Completed |
| `root-fallback-dual-medium-actual-gencase-027` | `F1_FALLBACK_DUAL_MEDIUM` | $0.01\ \text{m}$ | $300,000$ / $649,416$ | 0 | Completed |
| `root-fallback-dual-fine-actual-gencase-027` | `F1_FALLBACK_DUAL_FINE` | $0.005\ \text{m}$ | $2,400,000$ / $3,768,828$ | 0 | Completed |
| `root-fallback-ecc-coarse-full161-native-032` | `F1_FALLBACK_ECC_COARSE` | $0.01\ \text{m}$ | $161$ frames, $t_{\max}=1.6\ \text{s}$ | 0 | Completed |
| `root-fallback-ecc-medium-full161-native-032` | `F1_FALLBACK_ECC_MEDIUM` | $0.005\ \text{m}$ | $161$ frames, $t_{\max}=1.6\ \text{s}$ | 0 | Completed |
| `root-fallback-ecc-fine-full161-native-033` | `F1_FALLBACK_ECC_FINE` | $0.00333333\ \text{m}$ | $161$ frames, $t_{\max}=1.6\ \text{s}$ | 0 | Completed |
| `root-fallback-dual-coarse-full401-native-032` | `F1_FALLBACK_DUAL_COARSE` | $0.02\ \text{m}$ | $401$ frames, $t_{\max}=4.0\ \text{s}$ | 0 | Completed |
| `root-fallback-dual-medium-full401-native-032` | `F1_FALLBACK_DUAL_MEDIUM` | $0.01\ \text{m}$ | $401$ frames, $t_{\max}=4.0\ \text{s}$ | 0 | Completed |
| `root-fallback-dual-fine-full401-native-storage-fix-035` | `F1_FALLBACK_DUAL_FINE` | $0.005\ \text{m}$ | $401$ frames, $t_{\max}=4.0\ \text{s}$ | 0 | Completed |
| `root-fallback-ecc-coarse-full161-typed-034` | `F1_FALLBACK_ECC_COARSE` | $0.01\ \text{m}$ | $161$ frames $\to$ `trajectory.h5` | 0 | Completed |
| `root-fallback-ecc-medium-full161-typed-034` | `F1_FALLBACK_ECC_MEDIUM` | $0.005\ \text{m}$ | $161$ frames $\to$ `trajectory.h5` | 0 | Completed |
| Dual typed & ECC fine typed (034 / 036 queued) | DUAL / ECC Fine | $0.02, 0.01, 0.005, 0.0033$ | Queued conversion requests | — | Queued |

---

## 3. Canonical Physical Bindings and Hashes (Root 034)

The authoritative canonical bindings defined in `root_actual_fallback_canonical_bindings_and_typed_034`:
- **ECC Lower-Head Mother (`F1_ECC_THICK_DBC_LOWER_HEAD_V1`)**:
  - `physical_condition_sha256`: `687c069f836dd81b3c4c85ea6f977f9f2775debea01d3657b81356801ced71d3`
  - Window: $[0, 1.6]\ \text{s}$, $161$ frames ($tout=0.01\ \text{s}$).
  - Geometry: Flume $1.60 \times 0.67 \times 0.40\ \text{m}$; Obstacle at $[0.90, 0.24, 0.00]$, size $[0.12, 0.12, 0.45]\ \text{m}$; Fluid reservoir at $[0, 0, 0]$, size $[0.40, 0.67, 0.15]\ \text{m}$.
- **DUAL Lower-Head Mother (`F1_DUAL_THICK_DBC_LOWER_HEAD_V1`)**:
  - `physical_condition_sha256`: `feb710be76c89fb67074b1bbbf6c9c22869652ce5760c4d7e4721187b4d580bf`
  - Window: $[0, 4.0]\ \text{s}$, $401$ frames ($tout=0.01\ \text{s}$).
  - Geometry: Flume $3.20 \times 1.00 \times 0.80\ \text{m}$; Divider at $[1.20, 0.34, 0.00]$, size $[0.80, 0.06, 0.70]\ \text{m}$; Fluid reservoir at $[2.20, 0, 0]$, size $[1.00, 1.00, 0.30]\ \text{m}$.

---

## 4. Scientific Separation of Gates

In accordance with the user-edited Active Goal:
1. **Q-I (Integrity)**: Verified via initial QA (particle count matching, grid non-overlap, valid boundary encapsulation, finite coordinates) and trajectory integrity ($13$ typed datasets, valid flags, monotonic timestamps).
2. **Visual Review**: Full-animation ParaView dynamic review checking for physical plausibility (no explosive scattering, no severe wall penetrations, continuous surface profile).
3. **Q-N (Numerical Precision)**: Spatial convergence, save/cadence sensitivity, and cross-DP particle matching. **Explicitly NOT ACCEPTED for Stage 1; prior negative precision results are preserved and disclosed, but do not block Stage 1 visual dataset progress.**
4. **Q-E (External Validation)**: Experimental comparison; not a Stage 1 prerequisite.
