# F2 fresh103 native-path and XMF adapter

Fresh103 rebinds the 16 real fresh102 prepared GenCase reports to disabled
initial-QA, native401, XMF and Root023 render requests.  Every prepared
report is bound to its actual JSON/XML/receipt path and dynamic counts
(372840 fixed + 24150 moving + 0 floating + 21114 fluid = 418104 total).
The upstream producer sidecar supplies the 3-D dimension; fresh103 never
patches the raw execution receipt.

The disabled QA adapter keeps the raw receipt immutable and creates an
attempt-local semantic receipt only when Root enables the CPU worker.  That
semantic field is derived from the fresh102 prepared-evidence sidecar and is
reported separately from the raw execution receipt.  The wrapper then invokes
the existing PartVTK initial-QA worker; no source preparation reads BI4,
DAT, H5, CSV, VTK or XMF.  Existing fresh102 QA outputs are retained as
historical negative/pending evidence and never treated as passes.

All downstream requests preserve the 401-frame, 4.0 s, 0.01 s, 3-D native
recipe.  XMF vectors use dynamic `{actual_particles} 3` dimensions and
scalars use `{actual_particles}`; the 418104 prepared count is upstream
evidence, not a typed trajectory count.  Source-plan, prospective
legacy-owner, actual-converter and canonical physical scopes remain separate.
The logical guard digest is `a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a`; the current strict-dispatch file is bound separately at
`81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec`.

No request is executable.  Native, typed, H5, XMF and render receipts and
hashes are null.  This package adds zero cases, grants no qualification or
production status, does not modify fresh100-102, and does not write global
registry or ledger state.
