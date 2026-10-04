# F3 True 3D Two-Axis Sloshing Control Preparation (v1)

**Handoff Directory**: `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_040_prospective_recipe_v1`  
**Campaign**: DS-DATA-02  
**Family**: F3 (Open-Top Rectangular Tank Sloshing)  
**Authority**: Root Followup 040 under F3 isolated worktree `ds-data-02-f6`  
**Mechanism ID**: `F3_TWOAXIS_TRANSVERSE_LINACC_V1`  
**Execution Model**: Gemini 3.8 Flash High (direct local execution, zero recursive delegation)  
**Governance Boundary**: Strictly prospective; all 9 runner requests enforce `launch_allowed: false`, `q_n_status: not_granted` (campaign Q-N remains `0/336`, remaining ~32 GPUh / 53 qualification attempts), and `production_approval: none`. No actual scientific solver execution, binary conversion, CSV generation, or H5 reads outside Root dispatcher.

---

## 1. Executive Summary & Root Followup 040 Mandate

Root Followup 040 establishes the prospective preparation package for a genuine **SECOND physical mechanism** in Family F3: **True 3D Two-Axis Sloshing Control** using bounded transverse linear acceleration $a_y(t)$ with a smooth startup/shutdown envelope in the exact plain 5-wall container.

### Core Scientific & Physical Directives:
1. **Rejection of Blind Multipliers & Fictional Frame Claims**:
   - Merely scaling the 1D pitch amplitude $A$ exercises the same planar longitudinal dynamics.
   - Previous informal proposals claimed rotating-frame Euler angle integration or asserted $\alpha(t=0) = 0$.
   - **Audit Fact**: Nominal forcing CSV (`CaseSloshingAccData.csv`, SHA256: `6f42660a...`) has $\alpha_y(t=0) = 0.312057592\ \mathrm{rad/s^2} \ne 0$.
   - **DualSPHysics GPU v5.4 Source Audit**: In [`src/source/JDsAccInput_ker.cu`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/src/source/JDsAccInput_ker.cu#L128-L130), `const bool withaccang = (accang.x!=0 || accang.y!=0 || accang.z!=0);` evaluates to `true` unconditionally from $t=0$. Therefore, GPU kernel [`cuaccin::KerAddAccInputAng`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/src/source/JDsAccInput_ker.cu#L32-L89) is ALWAYS active.
2. **Second Physical Mechanism: Bounded Transverse Linear Acceleration $a_y(t)$**:
   - Applies bounded transverse linear acceleration $a_y(t)$ directly along the Y-axis.
   - Leaves nominal pitch angular source physically consistent ($A_x = 1.0$ zero-drive formula).
   - Avoids inventing artificial roll orientation, quaternion tracking, or non-inertial frame integration claims.
   - In [`cuaccin::KerAddAccInputAng`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/src/source/JDsAccInput_ker.cu#L47), $a_y(t)$ enters directly via `acclin.y` (`accy += acclin.y`).
   - In [`JDsAccInput::ComputeVelocity`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/src/source/JDsAccInput.cpp#L255), $a_y(t)$ is integrated into `currvellin.y`, which enters the Coriolis velocity offset $(v_{\mathrm{fluid}, y} - v_{\mathrm{lin}, y})$ at line 81.
   - Fixed tank Cartesian canonical source / destination / finite plane event operator remains semantically valid in the same plain container (no baffles, no moving boundaries).
3. **Exact Numerical Identity at $A_y = 0.0$**:
   - When $A_y = 0.0\ \mathrm{m/s^2}$ and $A_x = 1.0$, $a_y(t) \equiv 0.0$, reproducing the nominal CSV with exact numerical IEEE-754 `.17g` precision.
4. **Commensurate Ladder and Known Nominal Geometry**:
   - Commensurate ladder triplet: $[0.006, 0.005, 0.0045]\ \mathrm{m}$.
   - Verified known nominal geometry particle counts:
     * $dp = 0.005\ \mathrm{m}$: **277,272** total (116,640 fluid, 160,632 fixed).
     * $dp = 0.006\ \mathrm{m}$: **179,208** total (67,500 fluid, 111,708 fixed).
     * $dp = 0.0045\ \mathrm{m}$: **356,692** total (160,000 fluid, 196,692 fixed).
   - Predictions marked pending actual runtime GenCase execution and native typed array audit by Root dispatch.
5. **Retained Consumed Negative Evidence**:
   - $dp0.010$ vs $dp0.006$ fails spatial macro (~6.28% KE).
   - $dp0.0075$ vs $dp0.005$ fails spatial macro (~5.991% KE).
   - Candidate $dp0.006$ actual seven-macro nominal-v-half full 8.35s passes 1% max ($0.00153694 \le 0.01$), BUT exhibits 2,336 same-UID paired final fate switches out of 67,500 fluid particles; no path-stable claim is made.
   - Dense full 4,176-step conversion complete 0; new canonical / save-macro underway.
   - Candidate $dp0.006$ vs ref $dp0.005$ spatial macro passes at 2.8683% $\le 5\%$; final additional $dp0.0045$ reference full 8.35s running.

---

## 2. Derivation of Physical Scales & Transverse Control Formula

### Plain Container Parameters
- Length (pitch sloshing axis $X$): $L = 0.90\ \mathrm{m}$
- Width (transverse sloshing axis $Y$): $W = 0.18\ \mathrm{m}$
- Total Height (vertical axis $Z$): $H_{\mathrm{tank}} = 0.51\ \mathrm{m}$
- Water Depth: $h = 0.09\ \mathrm{m}$
- Density: $\rho_0 = 1000\ \mathrm{kg/m^3}$
- Continuum Fluid Mass: $M = 0.90 \times 0.18 \times 0.09 \times 1000 = 14.58\ \mathrm{kg}$
- Baseline Gravity: $\vec{g} = (0, 0, -9.81)\ \mathrm{m/s^2}$

### Transverse Sloshing Eigenmode
From linear potential wave theory for finite water depth $h$:
$$\omega^2 = g k \tanh(k h)$$
For the fundamental transverse mode across width $W = 0.18\ \mathrm{m}$:
- Wavenumber: $k_{y,1} = \frac{\pi}{W} = \frac{\pi}{0.18} \approx 17.4533\ \mathrm{rad/m}$
- Depth product: $k_{y,1} h = 17.4533 \times 0.09 = 1.5708 \approx \frac{\pi}{2}$
- $\tanh(k_{y,1} h) \approx \tanh(1.5708) \approx 0.91715$
- Circular frequency: $\omega_{y,1} = \sqrt{9.81 \times 17.4533 \times 0.91715} \approx 12.5312\ \mathrm{rad/s}$
- Cyclic frequency: $f_{y,1} = \frac{\omega_{y,1}}{2\pi} \approx 1.9944\ \mathrm{Hz}$
- Wave period: $T_{y,1} = \frac{1}{f_{y,1}} \approx 0.5014\ \mathrm{s}$

### Control Formulation
$$\vec{a}(t) = \vec{a}_{\mathrm{long}}(t) + a_y(t) \hat{j}$$
where the longitudinal component follows the established zero-drive formula ($A_x = 1.0$):
$$\begin{aligned}
a_x(t) &= A_x \cdot a_{x,\mathrm{nom}}(t) \\
a_z(t) &= g_z + A_x \cdot (a_{z,\mathrm{nom}}(t) - g_z) \\
\vec{\alpha}(t) &= A_x \cdot \vec{\alpha}_{\mathrm{nom}}(t)
\end{aligned}$$
and the transverse linear acceleration is:
$$a_y(t) = A_y \cdot E(t) \cdot \sin(\omega_y \cdot t + \phi_y)$$
with $\omega_y = 12.5312\ \mathrm{rad/s}$, $\phi_y = 0.0\ \mathrm{rad}$, and smooth Hann/cosine ramp envelope $E(t)$:
$$E(t) = \begin{cases}
0, & t \le 0 \\
\frac{1}{2}\left[1 - \cos\left(\frac{\pi t}{\tau_{\mathrm{ramp}}}\right)\right], & 0 < t < \tau_{\mathrm{ramp}} \\
1, & \tau_{\mathrm{ramp}} \le t \le t_{\mathrm{final}} - \tau_{\mathrm{ramp}} \\
\frac{1}{2}\left[1 - \cos\left(\frac{\pi (t_{\mathrm{final}} - t)}{\tau_{\mathrm{ramp}}}\right)\right], & t_{\mathrm{final}} - \tau_{\mathrm{ramp}} < t < t_{\mathrm{final}} \\
0, & t \ge t_{\mathrm{final}}
\end{cases}$$
where $\tau_{\mathrm{ramp}} = 0.50\ \mathrm{s} \approx 1.0 \times T_{y,1}$ and $t_{\mathrm{final}} = 8.35\ \mathrm{s}$.

### Bounded Amplitude Levels
- **AY_0P25** ($A_y = 0.25\ \mathrm{m/s^2}$, $\sim 0.025 g$): Transverse Endpoint Low ($Y_{\mathrm{amp}} \approx 1.59\ \mathrm{mm}$).
- **AY_0P50** ($A_y = 0.50\ \mathrm{m/s^2}$, $\sim 0.051 g$): Transverse Nominal Control ($Y_{\mathrm{amp}} \approx 3.18\ \mathrm{mm}$).
- **AY_0P75** ($A_y = 0.75\ \mathrm{m/s^2}$, $\sim 0.076 g$): Transverse Endpoint High ($Y_{\mathrm{amp}} \approx 4.78\ \mathrm{mm}$).
- **AY_0P00** ($A_y = 0.00\ \mathrm{m/s^2}$): Zero Transverse Drive (Exact Numerical Identity with nominal forcing).

---

## 3. DualSPHysics GPU v5.4 Kernel Branch Source Audit

Audit performed on local repository sources:

| Source File | Line(s) | Audited Code / Kernel Logic | Physical Significance |
| :--- | :---: | :--- | :--- |
| [`src/source/JDsAccInput_ker.cu`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/src/source/JDsAccInput_ker.cu#L128) | 128 | `const bool withaccang=(accang.x!=0 \|\| accang.y!=0 \|\| accang.z!=0);` | Determines whether angular or purely linear kernel is invoked. |
| [`src/source/JDsAccInput_ker.cu`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/src/source/JDsAccInput_ker.cu#L129-L130) | 129-130 | `if(withaccang) KerAddAccInputAng <<<...>>> (...); else KerAddAccInputLin <<<...>>> (...);` | Because nominal $\alpha_y(t=0) = 0.312057592 \ne 0$, `KerAddAccInputAng` is ALWAYS executed. |
| [`src/source/JDsAccInput_ker.cu`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/src/source/JDsAccInput_ker.cu#L46-L51) | 46-51 | `accx+=acclin.x; accy+=acclin.y; accz+=acclin.z;` | $a_y(t)$ enters particle acceleration directly via `acclin.y` without frame transformation. |
| [`src/source/JDsAccInput_ker.cu`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/src/source/JDsAccInput_ker.cu#L80-L84) | 80-84 | `accx+=((2.0*velang.y)*velz)-((2.0*velang.z)*(vely-vellin.y));` | Coriolis acceleration accounts for relative transverse fluid velocity $(v_y - v_{\mathrm{lin},y})$. |
| [`src/source/JDsAccInput.cpp`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/src/source/JDsAccInput.cpp#L254-L256) | 254-256 | `currvellin.y=vellin0.y+(acclin.y*dt);` | Integrates linear acceleration into linear velocity table. |
| [`src/source/JDsAccInput.cpp`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/src/source/JDsAccInput.cpp#L349) | 349 | `const bool withaccang=(v.accang.x!=0 \|\| v.accang.y!=0 \|\| v.accang.z!=0);` | Host CPU logic mirrors GPU kernel branch condition. |

---

## 4. Staged Cases Matrix (3 x 3 Commensurate Ladder)

All 9 requests enforce `launch_allowed: false`, `kind: "cpu"`, `cpu_task_kind: "gencase"`, `independent_case_count_increment: 0`, and `production_approval: "none"`.

| Case ID | Spacing ($dp$) | Transverse $A_y$ | Role | Known Particles | Binding File | Request File |
| :--- | :---: | :---: | :--- | :---: | :--- | :--- |
| `F3_CELL3_LONG_DP006_AY0P25_ADAPTIVE_CFL05_COEF005` | 0.006 m | 0.25 m/s² | Candidate Endpoint Low | 179,208 | `bindings/binding_dp006_ay0p25.json` | `requests/gencase_cpu_dp006_ay0p25_request.json` |
| `F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005` | 0.006 m | 0.50 m/s² | Candidate Nominal Control | 179,208 | `bindings/binding_dp006_ay0p50.json` | `requests/gencase_cpu_dp006_ay0p50_request.json` |
| `F3_CELL3_LONG_DP006_AY0P75_ADAPTIVE_CFL05_COEF005` | 0.006 m | 0.75 m/s² | Candidate Endpoint High | 179,208 | `bindings/binding_dp006_ay0p75.json` | `requests/gencase_cpu_dp006_ay0p75_request.json` |
| `F3_CELL3_LONG_DP005_AY0P25_ADAPTIVE_CFL05_COEF005` | 0.005 m | 0.25 m/s² | Reference Endpoint Low | 277,272 | `bindings/binding_dp005_ay0p25.json` | `requests/gencase_cpu_dp005_ay0p25_request.json` |
| `F3_CELL3_LONG_DP005_AY0P50_ADAPTIVE_CFL05_COEF005` | 0.005 m | 0.50 m/s² | Reference Nominal Control | 277,272 | `bindings/binding_dp005_ay0p50.json` | `requests/gencase_cpu_dp005_ay0p50_request.json` |
| `F3_CELL3_LONG_DP005_AY0P75_ADAPTIVE_CFL05_COEF005` | 0.005 m | 0.75 m/s² | Reference Endpoint High | 277,272 | `bindings/binding_dp005_ay0p75.json` | `requests/gencase_cpu_dp005_ay0p75_request.json` |
| `F3_CELL3_LONG_DP0045_AY0P25_ADAPTIVE_CFL05_COEF005` | 0.0045 m | 0.25 m/s² | Finer Ref Endpoint Low | 356,692 | `bindings/binding_dp0045_ay0p25.json` | `requests/gencase_cpu_dp0045_ay0p25_request.json` |
| `F3_CELL3_LONG_DP0045_AY0P50_ADAPTIVE_CFL05_COEF005` | 0.0045 m | 0.50 m/s² | Finer Ref Nominal Control | 356,692 | `bindings/binding_dp0045_ay0p50.json` | `requests/gencase_cpu_dp0045_ay0p50_request.json` |
| `F3_CELL3_LONG_DP0045_AY0P75_ADAPTIVE_CFL05_COEF005` | 0.0045 m | 0.75 m/s² | Finer Ref Endpoint High | 356,692 | `bindings/binding_dp0045_ay0p75.json` | `requests/gencase_cpu_dp0045_ay0p75_request.json` |

---

## 5. Verification & Root Entrypoint

Root can verify the staged package using the executable entrypoint:

```bash
python3 lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_040_prospective_recipe_v1/run_twoaxis_sloshing_audit.py
```

The script executes 6 primary audit categories covering 16 synthetic unit tests:
1. DualSPHysics GPU v5.4 force branch source code audit.
2. Pinned nominal source CSV SHA verification (`6f42660a...`) and verification of $\alpha_y(t=0) \ne 0$.
3. Transformer (`transform_twoaxis_forcing.py`) and GenCase worker (`prepare_twoaxis_gencase.py`) SHA checks.
4. All 12 XML definitions validation (commensurate cell-centre grid pointref $= dp/2$, CFL 0.05, open 5-wall, globalgravity 0).
5. All 9 bindings and 9 runner requests validation (`launch_allowed: false`, single-case dispatch).
6. 16 focused synthetic unit tests (`test_twoaxis_sloshing_preparation.py`).

Output is written to [`audit-report.json`](./audit-report.json).
