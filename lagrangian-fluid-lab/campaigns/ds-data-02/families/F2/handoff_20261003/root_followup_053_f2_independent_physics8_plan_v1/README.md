# F2 independent physics batch8 plan

This is a source-only prospective plan for eight distinct F2 physical tuples.
It deliberately stops before XML or motion materialization.  The plan does
not launch GenCase, DualSPHysics, conversion, H5/BI4/CSV readers, or a
ParaView render, and it cannot add cases to the campaign count by itself.

Each row uses exactly one true 3-D `dp=0.01 m` view over the complete 4 s
event window with 0.01 s saved output.  The three resolution aliases from the
historical F2 split are excluded from counting.  The rows vary the existing
bounded mother mechanisms (`center_catch` and `offset_spill`), receiver
endpoints, cup interior (`open_rim` or `short_spout`), smooth rotation duration
(`0.65` or `1.2 s`), and fluid fill (`0.8` or `1.0`).  The initial cup tilt
values (`-4`, `0`, `+4` degrees about a candidate world-X axis) are explicitly
prospective: a root geometry preflight must prove non-overlap and finite
boundary coverage before any row is materialized.

The source templates and hashes are the existing F2 nominal medium definition
and native motion files.  They establish lineage only; they are not copied or
modified here.  Native unknown/excluded identities remain unknown, and no
spill or loss meaning is inferred.  Every row is marked
`planned_not_materialized`, `launch_allowed=false`, and
`numerical_precision_status=not accepted`.

Generate a reviewable JSON plan in a new location with:

```text
python3 batch8_plan.py --output /absolute/path/to/new/batch8-plan.json
```

That command writes a plan document only.  Root binds actual source bytes,
geometry preflight evidence, and visual approvals before any future launcher
request is constructed.
