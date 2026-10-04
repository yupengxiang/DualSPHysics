# F3 Two-Axis Sloshing Native Transport & Domain Preparation (Followup 046)

**Handoff Directory**: `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_046_twoaxis_native_transport_and_domain_v1`  
**Campaign**: DS-DATA-02  
**Family**: F3 (Open-Top Rectangular Tank Sloshing)  
**Authority**: Root Followup 046 under F3 isolated worktree `ds-data-02-f6`  
**Mechanism ID**: `F3_TWOAXIS_TRANSVERSE_LINACC_V1`  
**Execution Model**: Gemini 3.8 Flash High (direct local execution, zero recursive delegation)  
**Governance & Claim Boundary**: Pure prospective source-only implementation and proposal. All 5 runner requests enforce `launch_allowed: false`, `q_n_status: not_assessed` (campaign Q-N remains `0/336`, remaining ~32 GPUh / 53 qualification attempts), and `production_approval: none`. Root alone executes scientific operations through strict dispatcher.

---

## 1. Executive Summary & Evidence State

Root Followup 046 delivers the source-only implementation of binding-driven canonical native label generation and same-UID paired transport comparison workers for the **SECOND physical mechanism** in Family F3: **True 3D Two-Axis Sloshing Control** ($A_y = 0.50\ \mathrm{m/s^2}$, $\omega_y = 12.5312\ \mathrm{rad/s}$, $\tau_{\mathrm{ramp}} = 0.50\ \mathrm{s}$, $t_{\mathrm{final}} = 8.35\ \mathrm{s}$).

### Completed Evidence Milestones (Root Dispatch):
1. **Three-Discretization Ladder Execution (Root 060 & 067)**:
   - All 3 native GPU simulations (`dp006`, `dp005`, `dp0045`) completed with returncode 0 under `root_actual_twoaxis_full_native_060`.
   - All 3 typed conversions completed with returncode 0 and official PartVTK validation under `root_actual_twoaxis_full_typed_067`.
2. **Actual 3DP Spatial Macro Verification (Root 071)**:
   - Full 8.35s spatial macro audit across all 7 observables and all 3 pairs (`coarse_v_medium`, `coarse_v_fine`, `medium_v_fine`) **PASSED the 5% budget**:
     $$\max_{\text{all 7, all pairs}} \Delta \le 0.040173865820097604 \le 0.05$$
3. **Time and Frequency Sensitivities (Root 065 & 070)**:
   - Halfstep (`CFL=0.025, CoefDtMin=0.0025`, 836 frames) native solver completed 0; typed conversion completed 0 under `root_actual_twoaxis_independent_time_save_typed_070`.
   - Dense save (`tout=0.002s`, 4,176 frames) native solver completed 0; typed conversion currently running in Root background.
   - Root independent halfstep frozen macro (Root 073) pending.

---

## 2. Canonical Digest & Physical Condition Erratum Governance

Per Root 072 erratum (`root_actual_twoaxis_canonical_digest_erratum_072`), the actual canonical physical condition body hash is:
$$\text{SHA256}_{\text{canonical\_condition}} = \texttt{49e319c0a874733707a028e916362e74e2301d6681e34bc6b717581dbd7edaeb}$$
- **Declared Top-Level Erratum Marker Preserved**: The declared top-level digest marker $\texttt{49d16330fd5267668670f166a20191bfb00c5223ad5528439630c7e62dd4c6a0}$ is explicitly preserved to maintain provenance continuity without conflating it with the canonical body digest.
- **Strict Prohibition of Hash Transfer**: Nominal single-axis controls hashes ($\texttt{59abc8c5...}$ and $\texttt{86562c5a...}$) are strictly forbidden from transferring to two-axis cases. All bindings enforce the canonical two-axis physical body hash.

---

## 3. Binding-Driven Reusable Workers

### A. `twoaxis_labels_worker.py`
Generates canonical labels from actual completed typed HDF5 sources through Root guard validation:
- **Frozen Canonical Helper**: Binds `f3_legacy_plain_full_transport_config.v1.json` ($\texttt{69c3a478...}$).
- **23 Event Closure Categories**: Independently evaluates all 23 closure criteria (`complete`, `unique_identity`, `exact_source_identity`, `finite_positive_initial_cohort`, `native_initial_mass`, `finite_increasing_time`, `source_labels_cover_initial_fluid`, `final_matches_last_destination`, `source_final_mass_closed`, `censor_codes`, `finite_observed_brackets`, `positive_observed_brackets`, `estimates_within_brackets`, `unobserved_brackets_nan`, `finite_nonnegative_residence`, `finite_nonnegative_unresolved`, `disjoint_residence_within_window`, `finite_monotone_directional_flux`, `net_flux_difference`, `label_shapes`, `destination_codes`, `fluid_cohort_identity`, `every_frame_unknown_loss_invalid_ledger`).
- **13 Mandatory Payload Datasets**: Verifies that all 13 particle datasets (`time`, `particle_id`, `particle_zone`, `source_label`, `destination_time_series`, `final_category`, `failure_reason`, `first_passage_interval`, `first_passage_chord_time`, `first_passage_censor`, `residence_time_s`, `unresolved_interval_time_s`, `initial_fluid_mass_kg`) and 6 summary datasets are preserved in `native-labels.h5`.
- **HDF5 Immutability**: Enforces stat and hash comparison before and after execution; never edits the source `trajectory.h5`.

### B. `twoaxis_paired_transport_worker.py`
Compares actual same-UID Lagrangian transport between paired runs:
- **Exact Native UID Alignment**: Confirms strict equality of `particle_id`, `particle_zone`, `initial_fluid_mass_kg`, and `source_label` (67,500 fluid identities for DP006).
- **Fate Switches Retention**: Computes `actual_fate_switches` and `native_fate_switch_mass_kg`. Never discards fate switches.
- **First-Passage Event Decomposition**: Tracks joint passages, nominal-only passages, and sensitivity-only passages (`half_only_first_passages` or `dense_only_first_passages`).
- **Bracket Overlap vs Disjoint Tracking**: Evaluates `literal_native_bracket_overlap_count` and `literal_native_bracket_disjoint_count` based on true saved-frame intervals without post-hoc thresholding.
- **Binary Native Weights**: Uses unchanged GenCase/BI4 `MassFluid` values for all weighted calculations.
- **Scientific Gate Boundary**: Enforces `q_n: "not_granted"` and `production_approval: "none"`. No retrospective CDF gate or arbitrary per-UID timing filter. Consumed negative evidence retained (dp0.0075 1,388 switches, dp0.006 2,336 switches).

---

## 4. SAME-Mother Second-Mechanism Transverse Amplitude Bracket & Interior Points

### Plain Container Parameters:
- Length: $L = 0.90\ \mathrm{m}$, Width: $W = 0.18\ \mathrm{m}$, Height: $H = 0.51\ \mathrm{m}$
- Water Depth: $h = 0.09\ \mathrm{m}$, Density: $\rho_0 = 1000\ \mathrm{kg/m^3}$, Mass: $M = 14.58\ \mathrm{kg}$
- Commensurate Ladder: $dp \in \{0.006, 0.005, 0.0045\}\ \mathrm{m}$

### Proposed Amplitude Bracket & Interior Points:
$$\vec{a}(t) = \vec{a}_{\mathrm{long}}(t) + A_y \cdot E(t) \cdot \sin(\omega_y \cdot t) \hat{j}$$
where $\omega_y = 12.531236478398654\ \mathrm{rad/s}$ and $\tau_{\mathrm{ramp}} = 0.50\ \mathrm{s}$.

| Amplitude Point | $A_y\ (\mathrm{m/s^2})$ | Nominal $Y_{\mathrm{amp}}\ (\mathrm{mm})$ | Role & Execution Status |
|---|---|---|---|
| **AY0P25** | $0.25$ | $1.59$ | Lower Endpoint Bracket Bound |
| **AY0P375** | $0.375$ | $2.39$ | Proposed Intermediate Interior Point |
| **AY0P50** | $0.50$ | $3.18$ | Nominal Center Interior Point (Executed: Native 060, Typed 067, 3DP Macro 071 PASS) |
| **AY0P625** | $0.625$ | $3.98$ | Proposed Intermediate Interior Point |
| **AY0P75** | $0.75$ | $4.78$ | Upper Endpoint Bracket Bound |
| **AY0P00** | $0.00$ | $0.00$ | Zero-Drive Reference (Exact Numerical Identity with nominal pitch) |

### Strict Scientific Boundary Declarations:
1. **Existing Single-Axis Domain**: Accepted none ($A_x \in [0.97, 1.10]$ tested); 1D longitudinal scaling does not produce true 3D lateral sloshing transport diversity.
2. **No Assertion of Endpoints Convergence**: Proposing the bracket $[0.25, 0.75]\ \mathrm{m/s^2}$ and interior points does NOT assume or assert monotonic or uniform convergence across amplitude endpoints. Wave breaking and free surface non-monotonicity are genuine physical phenomena.
3. **No Non-Native Tracers**: Native SPH fluid particles ($mkfluid=0$, type=3) provide complete spatial, residence, and first-passage observables; artificial massless numerical tracer injection is unneeded.
4. **Governance**: All numeric compute remains Root-only. Actual arrays and numeric outputs pending Root review and execution.

---

## 5. Prior Canonical Code Filenames Enumerated

The following F3-scope canonical files were audited and bound:
1. `lagrangian-fluid-lab/scripts/ds_data02_native_labels.py`
2. `lagrangian-fluid-lab/scripts/ds_data02_verified_native_labels_v1.py`
3. `lagrangian-fluid-lab/scripts/ds_data02_f3_nvme_input_audit_v1.py`
4. `lagrangian-fluid-lab/scripts/ds_data02_f3_genuine_adaptive_transport_compare_v1.py`
5. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/legacy_plain_8/f3_legacy_plain_full_transport_config.v1.json`
6. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_candidate_dp006_actual_canonical_labels_045/baseline-binding.json`
7. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_candidate_dp006_actual_canonical_labels_045/baseline-request.json`
8. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_candidate_dp006_actual_canonical_labels_045/half-binding.json`
9. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_candidate_dp006_actual_canonical_labels_045/half-request.json`
10. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_candidate_dp006_actual_paired_transport_050/binding.json`
11. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_candidate_dp006_actual_paired_transport_050/request.json`
12. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_candidate_dp006_actual_paired_transport_050/run.py`
13. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_candidate_dp006_actual_dense_labels_051/binding.json`
14. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_candidate_dp006_actual_dense_labels_051/request.json`
15. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_candidate_dp006_actual_dense_paired_transport_055/binding.json`
16. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_candidate_dp006_actual_dense_paired_transport_055/request.json`
17. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_candidate_dp006_actual_dense_paired_transport_055/run.py`
18. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_actual_adaptive_spatial_full_native_025/coarse-request.json`
19. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_actual_adaptive_spatial_full_native_025/medium-request.json`
20. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_actual_twoaxis_full_native_060/dp006/physical-binding.json`
21. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_actual_twoaxis_full_typed_067/dp006/owner.json`
22. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_actual_twoaxis_independent_time_save_typed_070/halfstep/owner.json`
23. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_twoaxis_actual_three_dp_spatial_macro_071/binding.json`
24. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_twoaxis_actual_three_dp_spatial_macro_071/audit.py`
25. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_actual_twoaxis_canonical_digest_erratum_072/canonical-digest-erratum.json`
26. `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_actual_twoaxis_independent_halfstep_frozen_macro_073/binding.json`

---

## 6. Verification and Audit Results

1. **Unit Tests (`test_twoaxis_transport_and_domain.py`)**:
   - 12 comprehensive unit tests: **PASS (12/12, 0 errors, 0 failures)**.
2. **Audit Report (`run_twoaxis_sloshing_audit.py` -> `audit-report.json`)**:
   - All 5 bindings audited and conformant.
   - All 5 runner requests verified with `launch_allowed: false` and exact file hashes.
   - 18 XML definitions and amplitude bracket specification validated.
   - Preflight worker dry-run checks passed.
   - Overall audit status: **`all_checks_passed: true`**.
