# F2 fresh165 physical membership audit

This F6 handoff freezes the authoritative F2 physical membership relation
`first8 ⊂ first24 ⊂ final48` at Root checkpoint 186. It uses the explicit
first8 and first24 source manifests, the actual registered 24-condition
first48 source-generation report, and the Root1205 full336 role-aware index.
It does not select cases by lexical order, retries, resolution aliases, or
render availability. `physical_case_id` and `case_id` remain separate.

The declared sets are 8, 24, and 48 unique physical IDs. The first8 source
manifest explicitly adds five lattice conditions to the existing mother/P01/P03
bindings. The first24 manifest explicitly subsumes eight and adds sixteen
domain conditions. The actual first48 source-generation report declares 24
new source conditions and the generation config says the existing 24 are
preserved. Its actual source-generation completion count is zero and it grants
no qualification, visual acceptance, or case credit.

Each row contains three separate roles: source-declared condition, checkpoint
accepted decision/top hash, and the native-request scope snapshot. The audit
never asserts those hashes are equal. Native counts and scientific downstream
outputs are not filled. Motion/DAT and H5/BI4/CSV/VTK payload paths and hashes
are deliberately omitted.

A metadata-only render census found one completed/published F2 case outside
checkpoint 186: RX058/ROT105, already personally reviewed in fresh164 and
therefore not re-reviewed here. No new unreviewed completed/published render
was found.

Run:

```text
python3 scripts/validate_fresh165.py
```

This package grants no global case credit and does not start or register any
job.
