# fresh171: F6 final48 particle + rigid joined delivery

This F3-owned source package is a read-only metadata catalog for the F6 final48
roster. It joins the authoritative cp242 F6 rows to Root1305's full-time
FloatingInfo delivery by `physical_case_id`, and preserves Root1313's fixed
`frozen8 ⊂ actual24 ⊂ registered48` membership and first24 sidecars.
Root1320's independent native field-role closure is retained as a metadata
source: it supplies the actual completed native receipt for each non-baseline
F6 physical case, including the pending visual case, while the historical
baseline's true native-field absence remains null.

There are **47 accepted visual decisions and one pending visual case**. The
pending case is
`F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025`. Its Root951 render
request/controller observation and Root709 own manifest are retained as live or
incomplete metadata. It has no accepted decision, primary render refs, PNG
credit, or visual acceptance claim. Its Root1305 rigid-motion row is complete
and is kept independently of the pending visual state.

For each accepted case, `F6-FINAL48-PARTICLE-RIGID-47ACCEPTED-ONE-PENDING.json`
keeps the accepted decision ref, own XMF manifest/XML, render report/receipt,
native and typed metadata refs, explicit PNG refs where the immutable decision
or report names them, and the decision's scope roles. When a historical
immutable decision contains only visual counts and no named key-frame paths,
the catalog records that absence instead of deriving paths from a frame
folder. Native condition, actual converter scope, source plan, SourceDef,
legacy typed scope, and accepted-top hashes remain separate roles.

The Root1305 rigid row is copied verbatim for every physical ID. It retains
241-frame/finite/Part/time metadata for the 47 new exports and the historical
baseline's `Part=false/null` boundary. The baseline is not treated as a new
export certificate. Numeric precision, Q-N, Q-E, and case credit remain zero;
this package does not add a case or modify any index, receipt, source, ledger,
controller, or scientific output.

The builder and validator read/hash JSON metadata only. Referenced XMF/XML,
PNG, CSV, H5, BI4, DAT, and VTK files are never opened or hashed; non-JSON
references are checked with filesystem stat only. No job, solver, conversion,
render, or shared-state operation is performed.

Run the source-only validator:

```text
python3 lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_171_f3_assigned_f6_final48_particle_rigid_47accepted_one_pending_delivery_v1/validate_fresh171.py
```

`build_fresh171.py` is retained as the reproducible metadata builder. Do not
rerun it against a moving checkpoint without producing a new package: the
catalog is intentionally frozen to cp242, Root1313, Root1305, and Root1320.
