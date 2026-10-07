# Fresh226 F2 final48 actual primary delivery

This source-only package is the immutable successor to fresh224. It copies the 47
fresh224 primary rows and fills the fresh224 pending slot with the completed Root1436 product for
`F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX053_RY014_FILL080_ROT090` (original 1063).
The result is 48 accepted actual primary products with zero pending boundary.
Fresh224 and all consumed source bytes remain unchanged.

The appended row is bound to actual full401 own-QI1430, the actual XMF manifest/XML
and receipts, the actual render/publish receipts, and the Root1436 accepted visual
decision. Its native physical scope is `03e792f100771b0c5bb1e686dfccad3f29e8d4b5b7dcc2847a6cebaa6f30563e`;
the typed/XMF legacy producer scope is
`2a5f6038420f2c22cb53d5bcf4718ff9af01a52422d40ed47c00e9acf835ec00`.
They remain distinct. The native source-plan physical field is present with the
native canonical value; native condition-plan and both XMF source-plan fields are
absent in the actual metadata and remain absent. The actual XMF is available at the
`XMF_XML.path` in the appended product row and is also repeated in the adoption
metadata.

The row retains 418104 particles, 401 frames, 3D, actual time window
`0.0..4.000051746876743`, and the producer-attested two-fluid omission record:
IDs 403829 and 410867, first missing at frame 158, cumulative 387 omissions,
with location/state/cause unknown. No synthetic identity repair is introduced.
The inherited 421566 particle-axis baseline, P03 typed135/no-return-code versus
XMF197 correction, old render-request462 correction, and all other old absent or
unknown roles remain preserved in the fresh224/base provenance sidecars. They are
not normalized into the new 418104 row.

Published contact/personal-key metadata and canonical navigation metadata remain
separate roles. The package adds no simulation, conversion, render, Q-N, Q-E, or
case credit and never reads or hashes H5/BI4/CSV/DAT/VTK/PNG content. Producer
metadata references and XML/XMF/JSON metadata are checked by the read-only
validator.

Run:

```text
python3 scripts/validate_fresh226.py
```
