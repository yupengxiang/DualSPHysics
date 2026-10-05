# F2 P03 recovery-aware XMF and Root023 handoff

This source-only package derives two disabled, root-owned CPU requests from the
existing P03 typed artifact. recovery_aware_export_xmf.py validates the
immutable running/null conversion receipt, the completed opaque artifact audit,
the JSON conversion report, and canonical owner hashes before any HDF5 read.
Its metadata-only mode does not open or hash HDF5. A root execution of the
normal mode is the only operation that reads the original H5 and emits a full
401-frame XDMF product.

The original typed conversion remains status=running, returncode=null, tool
status 143. The independent P03 artifact audit is attempt 197, completed/0,
with arrays_decoded=false, PartVTK all_passed=true, 401 verified frames,
418104 verified particles, and the producer H5 digest
98b1e1696e3d16cb343e0f77f11d0525c61d34c5550094e5d6d0f6e96e5b7e31. No
conversion completion is inferred from that audit.

Root023 is bound to all saved frames, native velocity N3, and the established
Root023 renderer. It has no diagnostic frame subset. The preview request stays
disabled until the upstream XMF manifest and XMF SHA are actual and added to
its strict input hash map. Neither request grants visual acceptance, Q-N, or a
new physical case.

The recorded checkpoint labels P03's actual audit Root197; Root202 in that
checkpoint is the unrelated F3 AY0270 audit. This package preserves that
distinction.
