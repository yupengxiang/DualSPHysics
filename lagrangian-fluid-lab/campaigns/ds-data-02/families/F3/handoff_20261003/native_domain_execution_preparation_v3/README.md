# F3 Native Domain Execution Preparation (v3)

**Handoff Directory**: `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/native_domain_execution_preparation_v3`  
**Campaign**: DS-DATA-02  
**Family**: F3 (Open-Top Rectangular Tank Sloshing)  
**Authority**: Root Followup 038 under F3 isolated worktree `ds-data-02-f6`  
**Model**: Gemini 3.8 Flash High (direct execution, zero recursive delegation)  
**Governance Boundary**: Strictly prospective; all requests enforce `launch_allowed: false`, `q_n_status: not_granted` (campaign Q-N `0/336`), and `production_approval: none`. No actual scientific solver, conversion, CSV generation, or H5 reads outside Root dispatcher.

---

## 1. Overview and Root Followup 038 Objectives

Root Followup 038 establishes the **self-contained executable CPU GenCase preparation worker** and staged prospective control domain assets for the 6-case matrix:
$$\text{Amplitudes } A \in \{0.90, 0.97, 1.10\} \times \text{Lattice Spacings } dp \in \{0.006, 0.005\}\ \mathrm{m}$$

Key directives fulfilled:
1. **Self-Contained Executable Worker (`prepare_native_gencase.py`)**: Modeled on root registered `generator033` (`root_additional_commensurate_adaptive_input_033/prepare.py`) and `generator028`, executing exactly **one GenCase per dispatched request** with configurable CLI arguments or binding JSON.
2. **Byte-Exact Adoption of Transformer (`transform_forcing.py`)**: Adopts the verified stdlib transformer from commit `f630fe48` (SHA256: `c2498ff54514536ebf2a229022e5fd555d4869f61f197159ace05fb685dff934`).
3. **Strict Wrapper Guards (Zero Tolerance)**:
   - Exact start time: $t_0 = 0.0\ \mathrm{s}$ and verbatim token `"0"`.
   - Exact end time: $t_{\mathrm{final}} = 8.35\ \mathrm{s}$ and verbatim token `"8.35"`.
   - Strictly increasing time: $t_k > t_{k-1}$.
   - Exact row count: exactly 167,001 data rows (167,002 lines including header).
   - Double precision IEEE-754 `.17g` formatting (`format_coord`) without deadband clamping or small-value quantization.
   - Zero-drive formula: $\vec{a}_{\mathrm{lin}} = \vec{g} + A \cdot (\vec{a}_{\mathrm{nom}} - \vec{g})$, $\vec{\alpha} = A \cdot \vec{\alpha}_{\mathrm{nom}}$ with $\vec{g} = (0, 0, -9.81)\ \mathrm{m/s^2}$. Exact numerical identity at $A=1.0$.
   - Pinned nominal forcing CSV: SHA256 verified before and after transformation against `6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3`.
   - Exclusive non-overwrite file creation (`mode="x"`).
4. **Commensurate Spatial Ladder**:
   - Candidate: $dp = 0.006\ \mathrm{m}$ ($150 \times 30 \times 15$ fluid cells, 67,500 predicted fluid particles).
   - Reference: $dp = 0.005\ \mathrm{m}$ ($180 \times 36 \times 18$ fluid cells, 116,640 fluid particles; verified anchor Gen033/QA034: 277,272 total, 116,640 fluid, 160,632 fixed).
   - Prospective Finer: $dp = 0.0045\ \mathrm{m}$ ($200 \times 40 \times 20$ fluid cells, 160,000 predicted fluid particles; counts strictly unasserted before GenCase).
   - Pointref: commensurate cell-centre lattice $x = dp/2, y = dp/2, z = dp/2$ for all cases.
5. **Physical Plain Container**: Open 5-wall geometry ($0.9 \times 0.18 \times 0.51\ \mathrm{m}$, water depth $0.09\ \mathrm{m}$, continuum mass $14.58\ \mathrm{kg}$, `globalgravity = 0` full-body $g$ CSV). Frozen event config without baffle. Second mechanism deferred unreviewed pending real current time/path evidence.
6. **Observed Sourcepair Bounds**: Fixed primary macro/time/saved budgets: spatial 0.05 (5%), temporal 0.01 (1%), saved frequency 0.01 (1%). Retained negative evidence: $dp0.010$ vs $dp0.006$ fails (~6.28% KE), $dp0.0075$ vs $dp0.005$ fails (~5.991%). These failures are retained; $dp0.006$ vs $dp0.005$ passes (2.8683% $\le 5\%$) and remains a prospective candidate.

---

## 2. Directory Contents

```
native_domain_execution_preparation_v3/
├── README.md                                      # Comprehensive specification and audit report
├── prepare_native_gencase.py                      # Self-contained CPU GenCase worker with strict wrapper guards
├── transform_forcing.py                           # Byte-exact stdlib transformer from f630fe48 (c2498ff5...)
├── source_audit_and_comparison.json               # Selected functions, compared source SHA, generator basis
├── binding_manifest.json                          # Complete ladder, budgets, physical domain, and cases matrix
├── run_domain_execution_preparation_audit.py      # Executable Root-ready entrypoint script
├── test_native_domain_execution_preparation_v3.py # 14 focused synthetic unit test fixtures
├── audit-report.json                              # Verification report emitted by Root entrypoint
├── definitions/                                   # 9 XML case definitions (CFL 0.05, cell-centre grid)
│   ├── F3_CELL3_plain_0p006_Def.xml
│   ├── F3_CELL3_plain_0p005_Def.xml
│   ├── F3_CELL3_plain_0p0045_Def.xml              # Prospective finer ladder extension (200x40x20)
│   ├── F3_CELL3_LONG_DP006_A0P90_ADAPTIVE_CFL05_COEF005_Def.xml
│   ├── F3_CELL3_LONG_DP006_A0P97_ADAPTIVE_CFL05_COEF005_Def.xml
│   ├── F3_CELL3_LONG_DP006_A1P10_ADAPTIVE_CFL05_COEF005_Def.xml
│   ├── F3_CELL3_LONG_DP005_A0P90_ADAPTIVE_CFL05_COEF005_Def.xml
│   ├── F3_CELL3_LONG_DP005_A0P97_ADAPTIVE_CFL05_COEF005_Def.xml
│   └── F3_CELL3_LONG_DP005_A1P10_ADAPTIVE_CFL05_COEF005_Def.xml
├── bindings/                                      # Single-case binding JSON definitions
│   ├── binding_dp006_a0p90.json
│   ├── binding_dp006_a0p97.json
│   ├── binding_dp006_a1p10.json
│   ├── binding_dp005_a0p90.json
│   ├── binding_dp005_a0p97.json
│   └── binding_dp005_a1p10.json
└── requests/                                      # 6 Runner requests (schema ds02.runner-request.v2)
    ├── gencase_cpu_dp006_a0p90_request.json       # launch_allowed: false
    ├── gencase_cpu_dp006_a0p97_request.json       # launch_allowed: false
    ├── gencase_cpu_dp006_a1p10_request.json       # launch_allowed: false
    ├── gencase_cpu_dp005_a0p90_request.json       # launch_allowed: false
    ├── gencase_cpu_dp005_a0p97_request.json       # launch_allowed: false
    └── gencase_cpu_dp005_a1p10_request.json       # launch_allowed: false
```

---

## 3. Staged Cases Matrix

All 6 requests enforce `launch_allowed: false`, `kind: "cpu"`, `cpu_task_kind: "gencase"`, `independent_case_count_increment: 0`, and `production_approval: "none"`.

| Case ID | Grid Spacing ($dp$) | Amplitude ($A$) | Role | Expected Fluid | Binding File | Request File |
| :--- | :---: | :---: | :--- | :---: | :--- | :--- |
| `F3_CELL3_LONG_DP006_A0P90_ADAPTIVE_CFL05_COEF005` | 0.006 m | 0.90 | Endpoint Low | 67,500 | `bindings/binding_dp006_a0p90.json` | `requests/gencase_cpu_dp006_a0p90_request.json` |
| `F3_CELL3_LONG_DP006_A0P97_ADAPTIVE_CFL05_COEF005` | 0.006 m | 0.97 | Internal Probe | 67,500 | `bindings/binding_dp006_a0p97.json` | `requests/gencase_cpu_dp006_a0p97_request.json` |
| `F3_CELL3_LONG_DP006_A1P10_ADAPTIVE_CFL05_COEF005` | 0.006 m | 1.10 | Endpoint High | 67,500 | `bindings/binding_dp006_a1p10.json` | `requests/gencase_cpu_dp006_a1p10_request.json` |
| `F3_CELL3_LONG_DP005_A0P90_ADAPTIVE_CFL05_COEF005` | 0.005 m | 0.90 | Endpoint Low | 116,640 | `bindings/binding_dp005_a0p90.json` | `requests/gencase_cpu_dp005_a0p90_request.json` |
| `F3_CELL3_LONG_DP005_A0P97_ADAPTIVE_CFL05_COEF005` | 0.005 m | 0.97 | Internal Probe | 116,640 | `bindings/binding_dp005_a0p97.json` | `requests/gencase_cpu_dp005_a0p97_request.json` |
| `F3_CELL3_LONG_DP005_A1P10_ADAPTIVE_CFL05_COEF005` | 0.005 m | 1.10 | Endpoint High | 116,640 | `bindings/binding_dp005_a1p10.json` | `requests/gencase_cpu_dp005_a1p10_request.json` |

---

## 4. Compared Source Audit & Selected Functions

Refer to [`source_audit_and_comparison.json`](./source_audit_and_comparison.json) for formal digest records.

- **Adopted Transformer Source**: `adaptive_control_domain_prospective_v2/transform_forcing.py` (commit `f630fe48`).
- **Compared Source SHA256**: `c2498ff54514536ebf2a229022e5fd555d4869f61f197159ace05fb685dff934`.
- **Generator Basis**: Root registered `generator033` / `generator028` (`root_additional_commensurate_adaptive_input_033/prepare.py`, SHA256: `f9ab1bdf9287312fdce14e1f964f3c3d41569854d49b2c8e2768103c44aad319`).
- **Pinned Source CSV**: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005/root-cell3-nominal-cfl-decoupled-floor-input-005/prepared/CaseSloshingAccData.csv` (SHA256: `6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3`).

### Selected Functions
1. `compute_sha256`: Chunked binary SHA256 calculation.
2. `format_coord`: Double precision `.17g` IEEE-754 coordinate formatting (no clamps, no quantization, finite guard).
3. `transform_row`: Token-preserving zero-drive formula evaluation with verbatim time string.
4. `transform_forcing_stream_with_guards`: Stream processor enforcing strictly increasing time, exact endpoint bounds, 167,001 data rows, and non-finite rejection.
5. `transform_and_validate_forcing_file`: File processor with before/after source hash verification and exclusive file creation (`mode="x"`).

---

## 5. Verification and Root-Ready Entrypoint

Root can audit and verify this package using the Root-ready entrypoint:

```bash
python3 lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/native_domain_execution_preparation_v3/run_domain_execution_preparation_audit.py
```

The script executes 11 comprehensive automated checks:
- Transformer byte-exact digest verification against `f630fe48` (`c2498ff5...`).
- Pinned nominal forcing CSV SHA verification (`6f42660a...`).
- Worker existence and SHA reporting (`prepare_native_gencase.py`).
- 9 XML definitions validation (commensurate cell-centre lattice, CFL 0.05, open 5-wall, `globalgravity = 0`).
- 6 case bindings and runner requests schema validation (`launch_allowed: false`, single GenCase per request).
- 14 focused synthetic unit tests execution via `test_native_domain_execution_preparation_v3.py`.
- Emits structured report to [`audit-report.json`](./audit-report.json) and exits 0 upon success.
