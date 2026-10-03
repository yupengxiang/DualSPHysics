# ERRATA & SUPERSEDED STATUS: root_saved_frequency_comparison_020

**Date**: 2026-10-03  
**Author**: Delegated F3 Family Agent (under Root)  
**Status**: **SUPERSEDED — DO NOT DISPATCH**  
**Successor**: `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_saved_frequency_comparison_022/`  
**Reference**: Root source review (`gemini_root_followups_024/root-source-review.json` and `f3-task.txt`)

---

## 1. Summary of Scientific & Methodological Errata in v1

The saved-frequency comparison v1 preparation (`ds_data02_f3_saved_frequency_compare_v1.py` and `root_saved_frequency_comparison_020/PLAN.md`, commit `7566c599`) contained several erroneous claims and methodological issues identified in Root's independent source review:

1. **Unsupported Identical Trajectory / Pure-Isolation Claim**:
   - v1 asserted that because total interval step count is identical (383,190 steps), the comparison "isolates the pure effect of temporal save resolution (save-bracket quantization)" and reflects an "identical physical simulation".
   - **Correction**: Baseline native RunPARTs has row 0 Steps = 1 and active steps = 383,189; dense native RunPARTs has row 0 Steps = 0 and active steps = 383,190 (both summing to 383,190). Sharing the identical initial condition, geometry, driving motion, and physical controls does **NOT** prove bitwise equal subsequent trajectories under differing output cadences. The comparison measures saved-frequency sensitivity under an unchanged recipe, which encompasses both save-bracket resolution refinement and potential downstream numerical trajectory differences.
2. **Canonical Chord Estimates Are Not True Crossing Times**:
   - v1 treated chord estimates as crossing times.
   - **Correction**: Piecewise-linear chord estimates between discrete saved frames are approximations; they are not true continuous crossing times, nor can they resolve hidden inter-frame recrossings.
3. **Nearest-Saved-Frame Comparisons Are Asynchronous Observations**:
   - v1 directly compared categorical destination time series between nearest frames without reporting temporal offsets or qualifying interpolation semantics.
   - **Correction**: Discrete nearest-frame comparisons have non-zero time offsets $\Delta t = t_{\text{dense}}[j] - t_{\text{nom}}[k]$. Discrete categorical destination states lack valid continuous interpolation semantics across asynchronous sampling instants. Offsets must be reported explicitly and analysis restricted to the common physical window.
4. **Cadence Refinement Factor**:
   - v1 computed cadence refinement factor as `len(time_dense) / len(time_nom) = 4176 / 836 \approx 4.9952`.
   - **Correction**: Cadence factor is defined strictly by the ratio of save intervals: $0.01\text{ s} / 0.002\text{ s} = 5.0$, distinct from the frame count ratio.
5. **Censored Event Quantiles**:
   - v1 returned empty dicts `{}` or omitted keys for unreached quantiles.
   - **Correction**: Empty or unreached censored quantiles must evaluate to `None` (JSON `null`).
6. **Hardcoded Provenance & Fallback Risks**:
   - v1 had potential fallbacks (`masses_nom = ... if ... else np.full(...)`) and hardcoded `total_solver_steps = 383190`.
   - **Correction**: Missing ledgers or missing mass datasets must raise immediate strict errors; timestep audit evidence is bound dynamically from actual timestep reports.
7. **Superseded Dense Labels Binding (Attempt 019)**:
   - v1 anticipated binding `root-cell3-adaptive-baseline-dense-native-transport-labels-019`.
   - **Correction**: Root already executed and completed `root-cell3-adaptive-dense-full4176-native-transport-labels-020` (returncode 0, all 23 closure checks PASS, native mass 14.580000378191471 kg, 11,936 observed, unknown/loss 0). No duplicate 019 labels job should be materialized.

---

## 2. Preservation Status

Per DS-DATA-02 activity boundaries and Root governance:
- All original v1 bytes (`ds_data02_f3_saved_frequency_compare_v1.py`, `root_saved_frequency_comparison_020/PLAN.md`, `binding.json`, and `request.json`) are preserved byte-for-byte as historical records of owner preparation.
- All corrected logic, specifications, bindings, and requests are published in FRESH v2 (`ds_data02_f3_saved_frequency_compare_v2.py` and `root_saved_frequency_comparison_022/`).
