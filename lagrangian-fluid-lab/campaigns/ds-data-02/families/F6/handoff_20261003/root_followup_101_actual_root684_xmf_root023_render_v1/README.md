# F6 fresh101: Root684 registered XMF -> Root023 full241 render adapter

This is a source-only F6 renderer handoff. It binds each case to its own Root684
registered XMF request and binding, while keeping the Root684 receipt, `case.xmf`, and
manifest as future inputs with null hashes. It contains only the Root023 renderer source
and metadata; it contains and reads no BI4, H5, CSV, DAT, or scientific array payload.

All 24 render requests and bindings are disabled. The render contract declares 24 CPU
cores and a 14400-second wall limit while keeping OMP/BLAS/VTK/LP environment thread
limits at 2 and `MESA_GLTHREAD=false`. Root023 scans native valid positions over all 241
saved frames and does not use a fixed camera or domain bounds. Physical producer scope,
Root606 classified scope, fresh088 canonical scope, and source-plan scope remain separate.

## Root enable order

1. Run `python3 workers/validate_fresh101_source.py` from this package directory.
2. Wait for each same-case Root684 XMF receipt, `case.xmf`, and manifest; preserve their
   actual metadata hashes when an enabled Root-owned clone is made.
3. After that case is eligible and the global render drain permits, Root may enable its
   paired Root023 request. Use the actual Root684 manifest path and a new empty
   `{attempt_root}/render` child.

The package grants no visual, Q-N, precision, or production credit. All render outputs,
receipts, frames, GIF, ParaView state, and report SHA256 values remain null here.
