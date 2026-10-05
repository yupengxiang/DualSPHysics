# F7 fresh079: family-48 audit and actual-XMF render closure

This is a source and bounded-metadata handoff for F7.  It does two things:

1. It audits the physical registry. The 47 distinct rows in fresh064,
   fresh065, fresh070, and fresh074 do not by themselves represent the whole
   family. The fresh062 mother accepted by checkpoint 074 has the separate
   physical identity `F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1`.
   Unioning that mother with the 47 source rows gives 48 unique physical
   identities. `F7_OBSTACLE_QUINTIC_B08_A052P5` from consumed fresh078 remains
   a separate prospective disabled candidate; it is not counted and does not
   trigger a mother rerun.
2. It closes the metadata contract from the actual Root411 XMF requests to
   disabled Root023 render requests. Root412 supplied 24 XMF receipts with
   `completed/0`; the generated disabled render requests are under
   `actual-bound-xmf-render/requests/render/`.

The Root411 correction is part of the binding: every producer scope is the
actual `ds_data02_direct_convert._physical_condition_scope(owner)` result from
fresh077, while each fresh074 source-plan hash remains a separate provenance
field. The old fresh078/Root410 scope is retained only as historical evidence
and is not an input to these render requests.

The XMF metadata preflight checks the temporal manifest schema, 601 saved
frames, 70179 native particles, 3-D field metadata, and every XDMF frame's
vector dimensions as `70179 3` and scalar dimensions as `70179`. This catches
the previous particle-axis loss before Root023 is enabled. Root023 uses its
automatic native all-frame bounds and writes to a fresh `{attempt_root}/render`
directory. Future render receipt, contact-page, and report hashes remain
null, and all requests remain disabled for Root review.

The adapter is [bind_fresh079_actual_xmf_render.py](scripts/bind_fresh079_actual_xmf_render.py).
It only reads JSON/XML/source metadata. It treats the producer H5 digest as an
attestation from `conversion-report.json` and never opens or hashes H5, BI4,
CSV, DAT, or scientific arrays. To rebuild the disabled render staging after
a future Root411-compatible XMF run, write outside this immutable package:

```text
python3 scripts/bind_fresh079_actual_xmf_render.py \
  --root411-dir <Root411 request directory> \
  --data-root /home/jade/Projects/DualSPHysics-data/ds-data-02 \
  --output-dir <external staging directory>
```

The package records no visual acceptance, Q-N, precision, production, or new
case-count claim beyond the registry audit above. No solver, converter, XMF,
ParaView, or shared-state operation was started by this handoff.
