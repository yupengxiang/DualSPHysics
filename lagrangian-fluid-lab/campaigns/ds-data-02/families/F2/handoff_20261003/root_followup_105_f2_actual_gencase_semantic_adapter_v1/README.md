# F2 fresh105: semantic GenCase and CSV layout adapter

Fresh104 correctly parsed all Root397 scientific predicates for four existing
PartVTK reports, but its report contract required `;` and exactly one separate
units row. Root397 showed comma output with units embedded in the header. The
fresh105 parser accepts either official delimiter and either inline units or
zero/one standalone units row; all finite, UID, type/Mk, mass, density, count,
and 3-D checks remain required.

The package also supplies a Root-owned metadata audit that joins each immutable
Root353/354 receipt with its prepared-input report and fresh102 sidecar. It
emits a separate semantic receipt with the runtime-required 3-D and particle
count fields. The raw receipt is never rewritten. The 16 QA, 16 semantic-audit,
and 16 native requests are disabled; native requests defer their GenCase input
to the future semantic receipt and remain gated on an actual QA pass and a live
Root230 UUID lease.

`build_fresh105.py` and the structural validator read/hash only JSON, XML and
source metadata. Producer-recorded CSV/BI4/DAT/H5 digests are carried as
provenance and are not recomputed. `tests/test_fresh105_csv_layouts.py` covers
comma plus inline units and semicolon plus a standalone units row using only
synthetic text fixtures.
