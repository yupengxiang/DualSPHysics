# fresh170: F6 actual-first24 particle/XMF + rigid-motion joined delivery

This F3-owned package joins the fixed F6 `actual_first24_physical_case_ids`
from Root1276 with the same physical IDs in the Root1305 F6 full48
FloatingInfo delivery. The join key is `physical_case_id`, and row order is
the authoritative order in Root1276's F6 delivery file. No directory name,
case alias, lexical ordering, or inferred condition is used.

Each row copies Root1276's own primary particle/XMF/render/visual-decision
references and Root1305's own rigid-motion report, execution-receipt, native
condition, official FloatingInfo CSV producer attestation, 241-row Part/time
coverage, required unit-bearing field list, and scope-role metadata. Referenced
XMF, PNG, CSV, H5, BI4, DAT, and VTK files are not packaged, opened, or hashed
by this source review; producer-declared hashes remain attestations.

The package records the historical baseline separately. Its old alias is kept,
and `legacy_Part_column_validation_field_present=false` with
`legacy_Part_unique_count=null` remains explicit. That historical row is not
converted into a fresh 47-export Part certificate.

Membership is preserved as `frozen8 ⊂ actual24 ⊂ registered48`. The package
adds no case, visual, Q-N, Q-E, or numerical-precision credit and does not
modify Root1276, Root1305, shared indexes, or ledgers.

Run the source-only validator:

```text
python3 lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_170_f3_assigned_f6_actual24_particle_rigid_joined_delivery_v1/validate_fresh170.py
```
