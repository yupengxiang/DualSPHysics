# ERRATA: root_adaptive_dense_native_labels_019

**Date**: 2026-10-03  
**Status**: **SUPERSEDED — DO NOT DISPATCH**  
**Resolution**: Root completed `root-cell3-adaptive-dense-full4176-native-transport-labels-020`  

---

## Supersession Details

This request was prepared in commit `7566c599` to materialize dense transport labels.
Root independently dispatched and completed the canonical dense labels run under Attempt 020:
- **Artifact Path**: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005_DENSE_SAVE002/root-cell3-adaptive-dense-full4176-native-transport-labels-020/native-labels.h5`
- **Report Path**: `.../labels-report.json`
- **Receipt Path**: `.../execution-receipt.json`
- **Status**: Completed (returncode 0, elapsed 336.1s)
- **Validation**: All 23 closure checks passed, 4,176 frames, 108,000 identities (34,560 fluid), initial native mass 14.580000378191471 kg, 11,936 observed first passages, 0.0 kg unknown mass, 0.0 kg numerical loss.

Per Root directive:
- Existing v1 files in this directory are preserved as historical preparation records.
- No duplicate materialization of Attempt 019 labels will be dispatched.
- All downstream saved-frequency comparison requests rebind directly to the authoritative Attempt 020 artifact.
