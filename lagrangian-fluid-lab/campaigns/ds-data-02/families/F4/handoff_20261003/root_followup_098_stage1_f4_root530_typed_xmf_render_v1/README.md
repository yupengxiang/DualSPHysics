# F4 fresh098: Root530 frame-0 to typed/XMF/render handoff

This source package binds the 24 Root530 official PartVTK frame-0 JSON
reports to the already Root-owned Root533 typed-conversion requests.  The
builder records the current Root533 receipt state and prepares one disabled
XMF request plus one disabled Root023 full-state render request per physical
case.

Root533 remains the owner of typed conversion.  fresh098 does not duplicate,
restart, or settle that conversion.  A typed receipt with return code 0 is
only an execution observation; XMF remains gated on an independently checked
conversion report with all 1201 frames, 3-D particle shape, and the expected
83233-particle identity lifecycle.  Rendering remains gated on that XMF
result.  Future H5, XMF, manifest, and render hashes are therefore null in
this source package.

The Root530 reports are JSON evidence produced by the Root-owned official
PartVTK worker.  They record raw Mk/Type and velocity observations, including
the generated-XML mapping Mkfluid 0 to native Mk 1 (pool) and Mkfluid 1 to
native Mk 2 (drop).  This builder reads only the JSON report and receipt; it
does not read or hash the PartVTK CSV or native BI4 payload.

`actual_converter_physical_scope.physical_condition_sha256` from each Root533
request is kept separate from the source-owner and source-plan condition
hashes.  The Root533 enriched owner metadata is referenced as the converter
owner.  The legacy scope remains a provenance label and grants no canonical
cross-resolution or Q-N claim.

Run the source builder from the F4 worktree when Root533 receipt metadata
changes:

```sh
python3 lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_098_stage1_f4_root530_typed_xmf_render_v1/build_fresh098.py
```

The local contract test checks 24 cases, disabled launch state, static input
closure, physical-scope separation, N3 vector metadata, and null future
product hashes.  It does not launch a worker and does not inspect scientific
payloads.
