# F5 A061 fresh066: typed065 XMF and short bed audit binding

This isolated F5 handoff binds completed Root products: GenCase075 "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061/root-stage1-f5-explicit-bed-repair-a-genuine-gencase-075/execution-receipt.json", native short solver093 "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061/root-stage1-f5-explicit-bed-repair-a-short-event-native-093/execution-receipt.json", initial QA083 "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061/root-stage1-f5-explicit-bed-repair-a-native-qa-083/initial-qa/a061-native-initial-qa.json", and typed NVME065 "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061/root-stage1-f5-explicit-bed-repair-a-short-event-native-typed-nvme-065/execution-receipt.json" plus its conversion report and H5.

Receipt roles are explicit: typed_receipt is typed065 and native_receipt is native093. GenCase075 is gencase_receipt. This fixes the old template role mix-up. The typed065 canonical hash is "d4a165e67b16f4f4871aa8a37eaf7cef6c08796cbf644cf2c9e101af9f84fbb7", while the source-plan hash is "268d4ea37228fb63ef493a6e535740bb765d165d874f97804443d5e11eb3497c"; the difference is disclosed and does not authorize source or precision changes.

The binder reads JSON metadata and hashes immutable files. It does not decode BI4/H5 arrays or start jobs. Generate the disabled XMF request with:

    scripts/bind_completed_products.py --mode xmf --output-dir /home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_066_stage1_a061_short_event_native093_nvme_typed_bed_audit_v2

After Root has an actual XMF output and manifest, bind the disabled bed request with:

    scripts/bind_completed_products.py --mode bed --output-dir /home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_066_stage1_a061_short_event_native093_nvme_typed_bed_audit_v2 --force

The bed worker audits all 51 saved frames only inside the exact profile x domain and y [-0.15, 0.15] m, reports below-1DP and below-2DP counts, fractions, depth, samples, and unexplained UID/nonfinite observations. It compares stored native timestamps and does not assume equal spacing. The 0..1 s result is right-censored diagnostic evidence and cannot certify full16 s or increment case count.
