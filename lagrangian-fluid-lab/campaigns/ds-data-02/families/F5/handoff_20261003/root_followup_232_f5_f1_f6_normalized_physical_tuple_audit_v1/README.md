# fresh232 F1/F6 normalized physical tuple audit

This is a source-only, metadata-only audit for the 96 current F1/F6 primary cases in the Root1451 delivery index: 48 F1 and 48 F6. It reads JSON receipts, request objects, owner/source-plan JSON, the authoritative delivery index, and the one actual F6 baseline GenCase source-definition XML named by that native request. It does not open or hash BI4, H5, CSV, DAT, VTK, XMF, PNG, solver output, or any science array, and it launches no task.

The report has one `normalized_physical_tuple` per case. The tuple deliberately excludes case IDs, paths, hashes, DP, and time-window fields. F1 rows contain the ECC/DUAL geometry, fluid depth, materialized drawbox height when a source plan declares it, and initial fluid `v_x`. F1 Root283/090 source-plan rows use their source-plan height/velocity and inherit only the same-family parent geometry from an actual JSON physical binding; the shared fallback binding is not allowed to overwrite those mutations. F6 rows contain declared physical rigid mass, initial angular velocity, initial yaw, and the rectangular tank/fluid/rigid/paddle geometry.

The baseline F6 request is intentionally thin: its native request has declared rigid mass semantics but no native angular-velocity or orientation fields. The report preserves those absence flags and cites the owner metadata separately; the actual baseline GenCase XML supplies the native mass, angular vector, and native floating-body drawbox (`point=[2,0.8,0.9]`, `size=[0.775,0.775,0.375]`). XML has no yaw field, so the normalized yaw remains the owner declaration and is explicitly marked as absent from the source definition; no rotation is inferred from that absence. It does not manufacture native request condition fields. The declared physical mass is 128 kg and remains distinct from the 256 kg support mass.

Native pin verification requires each receipt to say `status=completed`, `returncode=0`, and to contain equal `input_hashes_at_launch` and `input_hashes_after_run` dictionaries. The report verifies this for all 96 rows without copying hash values. The current result is 96 rows, 96 native pins, zero missing/ambiguous rows, and zero duplicate normalized tuple groups.

Root1453's lifecycle evidence remains separate from this tuple audit: `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_all336_actual_full_lifecycle_omission_counts_relative_to_initial_fluid_unknown_causes_preserved_1454/all336-full-lifecycle-relative-fluid-omission-proof.json` (commit `64fc6b261`). It reports small unknown-cause fluid omissions across all 48 F6 cases (maximum 7/327680 = 0.00213623%); this package makes no zero-loss, Q-N/Q-E, strict-containment, or numerical-precision claim.

Validate the frozen report with:

```sh
python3 /home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_232_f5_f1_f6_normalized_physical_tuple_audit_v1/audit_physical_tuples.py \
  --validate /home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_232_f5_f1_f6_normalized_physical_tuple_audit_v1/physical-tuples-report.json
```

Configured profile: GPT-5.6 Luna, max reasoning, no recursive delegation. Case credit, Q-N, and Q-E remain zero.
