# Fresh172 F3 final48 primary delivery

This package freezes the F3 delivery view at `ROOT_LIVE_RESUMPTION_CHECKPOINT_247`:
39 rows have an accepted visual decision and 9 rows remain registered pipeline
readiness with no visual acceptance. The membership arrays come verbatim from
Root1276, so the fixed relation is:

`Root1276 frozen first8 ⊂ Root1276 actual first24 ⊂ Root1276 registered final48`.

The accepted rows use each case's own accepted decision and its own native,
typed, XMF manifest/XML, render report/receipt, and published PNG references.
Modern nested `native`/`typed`/`xmf`/`render` evidence is resolved by role
before legacy recursive fields. Where a terminal XMF/render receipt was the
only recorded role, the builder uses that receipt's documented output root to
locate the fixed worker names `xdmf/manifest.json`, `xdmf/case.xmf`, and
`render/paraview-full-animation-report.json`; it does not search a science
tree. Contacts and keys accept both the historical string path and the newer
`{path, sha256}` form. Every reference is case-local to the published render
output root. Missing key enumeration remains disclosed; no frame-directory
inference is used.

The nine pending rows are copied from Root1287 readiness evidence only. They
retain `visual_credit=0`, the P0800 stale outer 801-frame/194427-particle
envelope where present, source-plan condition field absence, and the unknown
original pending154 typed receipt. Readiness/native/typed/XMF metadata is not
promoted to a visual decision; the two live original AY0640/AY0570 render
requests are not restarted.

`build_fresh172.py` reads/ hashes JSON metadata and stat-checks referenced
XMF/XML/PNG files. `validate_fresh172.py` enforces the frozen membership,
decision/source SHA closure, JSON metadata closure, declared published visual
digests, path containment, and string/dict PNG handling. Neither script opens
or hashes H5, BI4, IBI4, CSV, DAT, VTK, VTU, or PVTU scientific payloads, runs
a job, modifies shared state, or grants case/Q-N/Q-E/precision credit.
