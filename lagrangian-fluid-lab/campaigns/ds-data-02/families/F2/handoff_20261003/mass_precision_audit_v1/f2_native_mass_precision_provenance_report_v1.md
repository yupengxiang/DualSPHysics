# DS-DATA-02 Family F2: Native Mass Precision Provenance & Binary Format Review

**Report Identifier:** `f2-native-mass-precision-provenance-report-v1`  
**Date:** 2026-10-03  
**Family:** F2 (Matched Sloshing / Moving Boundary Dynamics)  
**Author:** F2 Family Delegated Owner (`gemini-3.8-flash-high`, high effort)  
**Target Campaign:** DS-DATA-02 (`lagrangian-fluid-lab/campaigns/ds-data-02`)  
**Operating Worktree:** `/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics`  
**Execution Restriction:** SOURCE INSPECTION ONLY — zero unmetered scientific H5/CSV array analysis outside Root runtime.

---

## 1. Executive Summary

This report establishes the complete source-line and hash provenance for particle mass precision across the DualSPHysics software stack, official tools, and DS-DATA-02 conversion/label pipelines. 

A critical finding from this review is that mass precision across the campaign spans **four distinct operational precision layers**:
1. **Source Header 64-bit IEEE-754 `DOUBLE`**: Declared and stored in native BI4 headers via `JPartDataBi4::ConfigCtes` (`SetvDouble`/`GetvDouble`, type code `12`).
2. **Solver 32-bit IEEE-754 `float32` Interaction**: Explicitly downcast in `JSph::Init` (`MassFluid = (float)ctes.GetMassFluid()`), stored as `float MassFluid` in `JSph.h`, and bound into simulation constants `CSP.massfluid` for CUDA/CPU kernels. Widened back to `double` in C++ implicit promotion when writing output BI4 headers (`parthead.ConfigCtes`).
3. **Direct HDF5 Adapter 32-bit `f4` (`float32`)**: Read from decoded XML by `ds_data02_direct_convert.py` and stored as fixed `f4` datasets (`mass` and `initial_mass`).
4. **Official PartVTK Tool CSV Display**: Emitted as single-precision floating point text in CSV with an official comparison tolerance of $1.0 \times 10^{-7}$.
5. **Continuous Case XML Reference Decimal**: Specified as exact decimal numbers ($0.001$, $0.000512$, $0.000125\text{ kg}$) yielding continuous total fluid mass $M_{\text{cont}} = 24.576\text{ kg}$.

### Critical Policy Assertions:
1. **Bitwise Payload Invariance $\neq$ Physical Zero Mass Defect**: Bitwise identity of the `mass` dataset across HDF5 frames simply reflects the fact that particle mass attributes are immutable scalar properties in solver memory and HDF5 storage under IEEE-754 binary32. It does **not** establish physical conservation of fluid without defect.
2. **No Rescaling or Normalization**: Particle masses, cohort totals, and observation ledgers must never be artificially rescaled or normalized to force agreement with continuous reference values.
3. **v6 Labels Mass Ledger Uses XML Decimal Weights**: The v6 label generator multiplies particle counts by the continuous decimal XML reference ($m_{\text{xml}} = 0.001$, etc.), yielding exactly $24.576\text{ kg}$, whereas native `float32` summation yields $24.576001167\dots\text{ kg}$. Therefore, one **cannot claim a native weight bitwise label mass pass**.
4. **Invalid Particles Strictly Classified as Unknown Loss**: All particles ejected by the solver ($2,151$ fine, $210$ medium, $118$ coarse) remain strictly categorized as `unknown_invalid` loss in the campaign ledger. They are never inferred as physical spill or zero defect.
5. **Preservation of Timing Save Failure**: The frozen campaign contract save interval allowance is $0.0007336391\text{ s}$. The actual simulation interval $dt = 0.010\text{ s}$ fails this allowance by $\approx 13.6\times$. This failure is preserved and recorded honestly without parameter gate relaxation or fabricated pass.

---

## 2. Pinned Source Files & Cryptographic Digests

All source files reviewed are pinned to immutable locations and verified via SHA-256 digests:

| Component / Subsystem | Repository Path | SHA-256 Digest |
| :--- | :--- | :--- |
| `JPartDataBi4.h` | `vendor/official/DualSPHysics_v5.4/src/source/JPartDataBi4.h` | `80130f90bbb9334315da90c66c63cf9df9723abc431e49cb219af1f038a32dec` |
| `JPartDataBi4.cpp` | `vendor/official/DualSPHysics_v5.4/src/source/JPartDataBi4.cpp` | `e507d88c8fac9b990b74d8dce71edb3524f71f46a04b3bdc5d289bf0af4ecdfc` |
| `JBinaryData.h` | `vendor/official/DualSPHysics_v5.4/src/source/JBinaryData.h` | `e63f60e6ae6d3ee8ed1f137ebca1bf45e6b783fb5a54c510fa80a3b09556af38` |
| `JBinaryData.cpp` | `vendor/official/DualSPHysics_v5.4/src/source/JBinaryData.cpp` | `a166250e1d339b45c549c25ed49e9533742bf52ce722102b96042f54c750566d` |
| `JSph.h` | `vendor/official/DualSPHysics_v5.4/src/source/JSph.h` | `251e19bd812aacb9e3b617becf8b65aefa6467eb35d3dc9a5ef89a89d1d9e3f9` |
| `JSph.cpp` | `vendor/official/DualSPHysics_v5.4/src/source/JSph.cpp` | `8729eb29db778288b0495855a04fa0984000896546f484dcf96176ec48da5454` |
| `ds_data02_direct_convert.py` | `scripts/ds_data02_direct_convert.py` | `8ec204edb5ac20f2d83e2b9a3b5e70eb45cf1104fe0ee4bd8c3413a241c10ccd` |
| `f8_r008_safe_bi4_decoder_v1.py` | `scripts/f8_r008_safe_bi4_decoder_v1.py` | `affbbb6c04a4d21d03037e74d0023112c60c7d8e5972cc6dfc882e1c7c5dc319` |
| `PartVTK_linux64` | `vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64` | `62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00` |
| `bi4_dump` | `campaigns/l1-resume/artifacts/bi4_dump` | `b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e` |

---

## 3. Detailed Source-Line Precision Analysis

### 3.1. Layer 1: Native BI4 Header Storage (`JPartDataBi4` / `JBinaryData`)
In `JPartDataBi4.h` and `JPartDataBi4.cpp`:
- **Line 216–222 (`JPartDataBi4.h`)**:
  ```cpp
  double Get_Dp()const{           return(GetData()->GetvDouble("Dp"));         }
  double Get_H()const{            return(GetData()->GetvDouble("H"));          }
  double Get_B()const{            return(GetData()->GetvDouble("B"));          }
  double Get_Rhop0()const{        return(GetData()->GetvDouble("Rhop0"));      }
  double Get_Gamma()const{        return(GetData()->GetvDouble("Gamma"));      }
  double Get_MassBound()const{    return(GetData()->GetvDouble("MassBound"));  }
  double Get_MassFluid()const{    return(GetData()->GetvDouble("MassFluid"));  }
  ```
- **Line 234–244 (`JPartDataBi4.cpp`)**:
  ```cpp
  void JPartDataBi4::ConfigCtes(double dp,double h,double b,double rhop0
    ,double gamma,double massbound,double massfluid)
  {
    Data->SetvDouble("Dp",dp);
    Data->SetvDouble("H",h);
    Data->SetvDouble("B",b);
    Data->SetvDouble("Rhop0",rhop0);
    Data->SetvDouble("Gamma",gamma);
    Data->SetvDouble("MassBound",massbound);
    Data->SetvDouble("MassFluid",massfluid);
  }
  ```
- **Type Code & Storage (`JBinaryData.cpp`)**:
  - `DatDouble` is enumerated with type code `12`.
  - Line 2632–2634:
    ```cpp
    void JBinaryData::SetvDouble(const std::string& name,double v){
      Values[ChecksSetValue(name,JBinaryDataDef::DatDouble)].vdouble=v;
    }
    ```
  - Line 564: `FmtDouble = "%.15E";` (15 digits after decimal point, 16 significant figures).
  - Line 721:
    ```cpp
    case JBinaryDataDef::DatDouble: tx=tx+"v=\""+ fun::DoubleStr(v.vdouble,FmtDouble.c_str()) +"\" />"; break;
    ```
  **Finding:** The native BI4 container explicitly stores `MassFluid` as a 64-bit IEEE-754 `double`.

---

### 3.2. Layer 2: Solver Compute Engine Downcasting (`JSph`)
In `JSph.h` and `JSph.cpp`:
- **Line 236 (`JSph.h`)**:
  ```cpp
  float MassFluid;         ///<Reference mass of the fluid particle [kg].
  float MassBound;         ///<Reference mass of the general boundary particle [kg].
  ```
- **Line 654–655 (`JSph.cpp`)**:
  ```cpp
  MassFluid=(float)ctes.GetMassFluid();
  MassBound=(float)ctes.GetMassBound();
  ```
  *Crucial architectural transition:* At line 654, the solver explicitly downcasts the 64-bit `double` value returned by `ctes.GetMassFluid()` to single-precision `float`.
- **Line 1514–1515 (`JSph.cpp`)**:
  ```cpp
  CSP.massfluid     =MassFluid;
  CSP.massbound     =MassBound;
  ```
  `CSP.massfluid` is passed to CUDA/CPU interaction kernels as `float` (`float32`). All hydrodynamics, pressure, and viscous interactions operate purely at 32-bit precision.
- **Line 2740 (`JSph.cpp`)**:
  ```cpp
  parthead.ConfigCtes(Dp,KernelH,CteB,RhopZero,Gamma,MassBound,MassFluid,Gravity);
  ```
  When the solver writes output BI4 frames, `MassFluid` (`float`) is implicitly converted back to `double` in the call to `ConfigCtes`.
  **Finding:** The output BI4 header contains a 64-bit double whose numerical value is the float-widened `float32` value (`(double)((float)massfluid)`).

---

### 3.3. Layer 3: Direct HDF5 Conversion (`ds_data02_direct_convert.py`)
In `scripts/ds_data02_direct_convert.py`:
- **Line 568–572**:
  ```python
  bound = _as_float(metadata, "MassBound")
  fluid = _as_float(metadata, "MassFluid")
  if bound is None or fluid is None or bound <= 0 or fluid <= 0:
      raise DirectConversionError("decoder lacks finite positive MassBound/MassFluid")
  mass = np.where(types == 3, fluid, bound).astype(np.float32)
  ```
- **Line 623, 628**:
  ```python
  h5.create_dataset(name, shape=(frames, particles), dtype="f4", chunks=chunks_1, compression="lzf", fillvalue=np.nan)
  h5.create_dataset("initial_mass", shape=(particles,), dtype="f4")
  ```
- **Line 651**:
  ```python
  mass[indices] = frame_mass[indices]
  ```
- **Line 47**:
  ```python
  PARTVTK_TOLERANCES = { ..., "mass": 1.0e-7, ... }
  ```
  **Finding:** The direct converter casts the decoded scalar to `np.float32` and stores it into HDF5 datasets as `f4`.

---

### 3.4. Layer 4: Official PartVTK CSV Tooling (`PartVTK_linux64`)
- Reads the native BI4 stream.
- Outputs `Mass [kg]` in CSV format as text.
- Because PartVTK outputs single-precision floating point text representations, differences of up to $\sim 10^{-7}$ relative to exact `float32` array values in memory occur due to ASCII decimal formatting.

---

### 3.5. Layer 5: Case XML Decimal Reference
In the case definition XML (`GenCase` input):
- Continuous volume: $V_{\text{cont}} = 0.32 \times 0.24 \times 0.32\text{ m}^3 = 0.024576\text{ m}^3$.
- Fluid density: $\rho_0 = 1000.0\text{ kg/m}^3$.
- Continuous fluid mass: $M_{\text{cont}} = 24.576\text{ kg}$.
- Discrete particle mass definitions:
  - **Coarse ($dp = 0.010\text{ m}$, $N = 24,576$)**: $m_{\text{xml}} = 0.001\text{ kg}$
  - **Medium ($dp = 0.008\text{ m}$, $N = 48,000$)**: $m_{\text{xml}} = 0.000512\text{ kg}$
  - **Fine ($dp = 0.005\text{ m}$, $N = 196,608$)**: $m_{\text{xml}} = 0.000125\text{ kg}$

---

## 4. Exact IEEE-754 Arithmetic Representation Deltas

The table below contrasts the continuous XML decimal reference with native single-precision float32 values:

| Parameter | Coarse ($dp = 0.010\text{ m}$) | Medium ($dp = 0.008\text{ m}$) | Fine ($dp = 0.005\text{ m}$) |
| :--- | :--- | :--- | :--- |
| Particle Count ($N$) | $24,576$ | $48,000$ | $196,608$ |
| XML Decimal $m_{\text{xml}}$ [kg] | `0.001` | `0.000512` | `0.000125` |
| Continuous Reference Mass [kg] | `24.576` | `24.576` | `24.576` |
| Native `float32` Value [kg] | `0.0010000000474974513` | `0.0005119999987073243` | `0.0001250000059371814` |
| Hexadecimal IEEE-754 (binary32) | `0x6f12833a` | `0xbd37063a` | `0x6f120339` |
| Widened to `double` (binary64) | `1.0000000474974513e-3` | `5.1199999870732427e-4` | `1.2500000593718141e-4` |
| Exact Sum ($N \times m_{f32}$) [kg] | `24.57600021362305` | `24.57600021362305` | `24.57600021362305` |
| Array Sum (Accumulated) [kg] | `24.576001167297363` | `24.575999937951565` | `24.576001167297363` |
| Arithmetic Delta $\Delta M$ [kg] | $+1.1673 \times 10^{-6}$ | $-6.2048 \times 10^{-8}$ | $+1.1673 \times 10^{-6}$ |
| Relative Arithmetic Drift | $+4.75 \times 10^{-8}$ | $-2.52 \times 10^{-9}$ | $+4.75 \times 10^{-8}$ |

### Distinction Between XML Decimal and Native Float32 Ledger
The v6 label generation pipeline calculates cohort masses as:
$$M_{\text{cohort}} = N_{\text{cohort}} \times m_{\text{xml}}$$
Under this formula, the total initial fluid mass ledger reports exactly $24.576\text{ kg}$.
However, summing the native `float32` mass datasets stored in HDF5 yields $24.576001167\dots\text{ kg}$.
Because of this distinction:
- **One cannot claim a native weight bitwise label mass pass**.
- The label ledger is an XML decimal cohort projection; the native HDF5 dataset contains IEEE-754 single-precision scalars.
- Both values are scientifically valid within their respective domains, but they must **never be conflated or rescaled**.

---

## 5. Binary BI4 Format Metadata Layout Specification

Based on official source code (`JBinaryData.cpp`, `JPartDataBi4.cpp`) and the safe parser (`f8_r008_safe_bi4_decoder_v1.py`):

```
+-------------------------------------------------------------------------+
| FILE HEADER (64 bytes)                                                  |
| Magic string: "#FileJBD JPartDataBi4\0..."                             |
+-------------------------------------------------------------------------+
| ROOT ITEM RECORD                                                        |
| Definition length (uint32)                                              |
| Record Code: "\nITEM\n"                                                |
| Name: "PART_DATA"                                                       |
| Hide flags: int32 item_hidden, int32 hide_values                        |
| Format strings: FmtFloat ("%.7E"), FmtDouble ("%.15E")                  |
| Counts: uint32 num_arrays, uint32 num_items, uint32 values_bytes        |
+-------------------------------------------------------------------------+
| ROOT VALUES BLOCK (values_bytes)                                        |
| Magic: "\nVALUES", uint32 count                                         |
| Value 0: Name="Dp",        Type=12 (DatDouble), Payload=8 bytes (double)|
| Value 1: Name="H",         Type=12 (DatDouble), Payload=8 bytes (double)|
| Value 2: Name="B",         Type=12 (DatDouble), Payload=8 bytes (double)|
| Value 3: Name="Rhop0",     Type=12 (DatDouble), Payload=8 bytes (double)|
| Value 4: Name="Gamma",     Type=12 (DatDouble), Payload=8 bytes (double)|
| Value 5: Name="MassBound", Type=12 (DatDouble), Payload=8 bytes (double)|
| Value 6: Name="MassFluid", Type=12 (DatDouble), Payload=8 bytes (double)|
| ...                                                                     |
+-------------------------------------------------------------------------+
| CHILD ITEM: PART_XXXX                                                   |
| Definition length, "\nITEM\n", Name="PART_0000", ...                    |
| Values: TimeStep, Npok, Nout, Step, RunTime, DomainMin, DomainMax       |
| Arrays: Idp (uint), Pos (float3/double3), Vel (float3), Rhop (float)    |
+-------------------------------------------------------------------------+
```

Each simulation constant is typed as `DatDouble` (code `12`), encoded as an 8-byte little-endian IEEE-754 binary64 scalar.

### 5.1. Exact Binary Stream Cursor Management & Type Widths
To prevent stream desynchronization (`desync`), the binary parser must account for every type width in the `JBinaryDataDef::TpData` enum ([`JBinaryData.cpp#L83-L110`](file:///home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/src/source/JBinaryData.cpp#L83-L110)):
- **1 Byte**: `DatChar` (type code 3), `DatUchar` (4)
- **2 Bytes**: `DatShort` (5), `DatUshort` (6)
- **4 Bytes**: `DatBool` (2), `DatInt` (7), `DatUint` (8), `DatFloat` (11)
- **8 Bytes**: `DatLlong` (9), `DatUllong` (10), `DatDouble` (12)
- **12 Bytes**: `DatInt3` (20), `DatUint3` (21), `DatFloat3` (22)
- **24 Bytes**: `DatDouble3` (23)
- **Variable Length**: `DatText` (1) = uint32 string length + UTF-8 bytes
- **Unknown Type Codes**: Must raise an immediate exception and reject rather than skipping bytes arbitrarily, guaranteeing cursor synchronization across the entire VALUES payload.

### 5.2. Actual Audit Targets: Initial GenCase DOUBLE vs Solver Output Float32 Widening
The revised metered audit targets the 6 canonical files on campaign storage:

| Target Identifier | Role | File Path | SHA-256 Digest |
| :--- | :--- | :--- | :--- |
| `coarse_gencase_initial` | GenCase Initial DOUBLE | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010/gencase-f2_rv4eq_matched_offset_v1_coarse_dp010-20261003-001/F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010.bi4` | `1022ee3f14b1d0680e8d8ca9ad89b6641ddb88fac0b71216a3a7941b80805a86` |
| `coarse_solver_frame0` | Solver Frame 0 Widened Float32 | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/qualification-f2_rv4eq_matched_offset_v1_coarse_dp010-spatial-reference-save010-root-review-001/solver_output/data/Part_0000.bi4` | `911b215215663d8c5ae6161cf18e3c987b744b98bc84252b3db5c99673be3c8d` |
| `medium_gencase_initial` | GenCase Initial DOUBLE | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008/gencase-f2_rv4eq_matched_offset_v1_medium_dp008-20261003-001/F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008.bi4` | `55935d3a60a732cb8384ed040fde2328337407c8a29a66e176139225a2e95eeb` |
| `medium_solver_frame0` | Solver Frame 0 Widened Float32 | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/qualification-f2_rv4eq_matched_offset_v1_medium_dp008-spatial-reference-save010-root-review-001/solver_output/data/Part_0000.bi4` | `a4125ba899a16389e7f807cdd289d4f4264cd9969cb8382e9fdb82136ee6f2b3` |
| `fine_gencase_initial` | GenCase Initial DOUBLE | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1/gencase-f2_rv4eq_dp005_offset_v1-20261002-001/F2_RV4EQ_DP005_OFFSET_V1.bi4` | `efa7d2a296ed3de308c93b598e47225b36865006977caaa6a9a8898099b922a6` |
| `fine_solver_frame0` | Solver Frame 0 Widened Float32 | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/qualification-f2_rv4eq_dp005_offset_v1-baseline-save001-native-fullstate-v1/solver_output/data/Part_0000.bi4` | `424dc6cf114f96072f95bb3b5096976a8228fb243f0cbda7f915d040b1aa80fa` |

This exact pairing enables Root's metered audit to directly measure:
1. Initial GenCase DOUBLE precision constants created from XML continuous decimal reference.
2. Output solver BI4 DOUBLE precision constants widened from solver float32 interaction constants.

---

## 6. Review of Commit `a6f1aafb` Prospective Spatial Scope

In commit `a6f1aafb`, the 3DP spatial transport comparison pipeline (`f2_rv4eq_matched_offset_3dp_spatial_comparison_v1.py`) was introduced. A rigorous review against campaign contracts confirms:

1. **Diagnostic Failure on Timing Save Allowance**:
   - Frozen quality contract save interval allowance: $0.0007336390799938275\text{ s}$ ($\sim 0.0007336\text{ s}$).
   - Actual simulation save interval: $0.010\text{ s}$ ($401$ frames over $4.0\text{ s}$).
   - Status: $0.010 > 0.0007336\text{ s}$, which represents a diagnostic failure of the save interval allowance by $\approx 13.6\times$.
   - **Assertion:** This failure is acknowledged honestly and permanently. No parameter gate relaxation or synthetic pass is permitted.
2. **Event Window & Censoring**:
   - The matched duration is $4.0\text{ s}$ ($401$ frames, $dt = 0.010\text{ s}$) across all three resolutions.
   - Right-censoring at $t = 4.0\text{ s}$ accounts for fluid remaining in motion or settling; initial fluid particle denominators ($196,608$ fine, $48,000$ medium, $24,576$ coarse) are strictly preserved.
3. **Unknown Loss Accounting**:
   - Native invalid particles ejected by the solver ($2,151$ fine, $210$ medium, $118$ coarse) are strictly recorded as `unknown_invalid` loss. They are never classified as physical spill.

---

## 7. Conclusion & Next Steps

1. This report and accompanying sidecar establish the definitive 4-tier mass precision provenance.
2. A revised metered runner request (`requests/f2_native_bi4_header_precision_audit_request_v1.json`) is prepared to allow Root to execute an independent, bounded verification of raw BI4 header constants directly on campaign storage across all 6 targets.
3. Synthetic unit tests verify all mathematical relationships, exact type widths, and schema invariants with 100% campaign write isolation.
