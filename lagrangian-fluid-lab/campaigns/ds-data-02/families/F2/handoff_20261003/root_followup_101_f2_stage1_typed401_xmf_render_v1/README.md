# F2 fresh101 typed401 XMF and Root023 render adapter

This source-only package provides one disabled XMF request and one disabled
Root023 full-animation render request for each of the 16 fresh100 physical
conditions.  It reuses the validated legacy-aware XMF exporter and Root023
renderer shape from Root306/309, while keeping each fresh100 source-plan hash,
prospective `legacy-owner-scope.v0` hash, future actual converter scope, and
future trajectory H5 digest separate.

The XMF worker is enabled only after Root has independently completed the
matching GenCase, native 401-frame run, initial QA, and typed conversion.  It
reads the actual conversion report to obtain the particle count and emits
dynamic N3 XDMF dimensions (`N 3` vectors and `N` scalars); it does not use a
source-side guessed count.  The Root023 worker then scans every saved native
frame for bounds and keeps the full native geometry.  No fixed camera or
domain bounds are supplied.

Fresh101 preparation read and hashed only JSON/XML/Python/text metadata.  It
did not read or hash motion `.dat`, BI4/CSV/HDF5/XMF scientific payloads and
did not execute GenCase, solver, converter, decoder, PartVTK, ParaView, or
modify the shared ledger/registry.  All future receipts, XMF/render outputs,
trajectory hashes, and actual converter scope hashes remain null.  This is a
derived downstream view for existing conditions and adds zero independent
cases or qualification/production approval.

Every disabled request carries the verified strict-dispatch guard digest and
hash-closed inputs for runtime_v2, strict_dispatch, the Root142/Root230 home
floor policy, the resource approval, and the relevant renderer/converter
contracts.  The source package does not rely on a later validator to fill
those guard inputs.
