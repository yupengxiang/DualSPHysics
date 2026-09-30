# Direct BI4 conversion (DS-DATA-02 infrastructure)

`scripts/ds_data02_direct_convert.py` is an independent streaming adapter for
DualSPHysics `Part_XXXX.bi4` output.  It invokes the existing upstream
`bi4_dump` binary once per frame, establishes a fixed initial `(Zone, Idp)`
axis, and writes one HDF5 frame at a time.  It keeps position, velocity,
density, EOS pressure, mass, valid, type, and mk; invalid identities receive
NaN physical values and remain on the same typed axis.  Type mapping comes from
the generated `execution/particles` ranges, while `Zone` comes from the BI4
`Piece` field.  The converter therefore does not infer moving or floating
mass from position, and it rejects open birth, adaptive, periodic, and
multi-piece streams.

The converter records SI units, the actual 2D/3D banner from `Run.out`, the
coordinate-frame declaration, raw-tree hashes before and after the read, and
separate physical-condition and numerical-parameter hashes.  It reports the
resource usage of the converter and its decoder children.  The raw BI4 tree is
read-only; the runner request contains representative input hashes and the
converter hashes the complete source tree itself.

For a real artifact, the shared CPU runner request
`infra/requests/f1-bi4-direct-conversion-fine-v1.json` runs official PartVTK
on frame 0, the middle frame, and the final frame.  It compares every emitted
identity, type, mk, position, velocity, density, mass, and pressure field, and
then performs a chunked comparison with the existing F1 reference HDF5.  The
attempt output belongs under the external DS-DATA-02 data root; no trajectory
is committed to this worktree.

This adapter produces conversion evidence only.  Its report explicitly leaves
Q-N and production eligibility unevaluated; lifecycle, geometry/control
completeness, and scientific acceptance remain the responsibility of the
campaign auditors.

The actual F1 fine run is summarized in
`infra/f1-direct-bi4-fine-v3-evidence.json`.  Attempt v3 completed through the
shared CPU runner in 26.57 wall seconds (28.70 CPU seconds) and wrote its HDF5
and report under the external DS-DATA-02 data root.  The evidence keeps the
strict exactness result separate from the numeric tolerance result: the legacy
CSV HDF5 has tiny position/velocity/density serialization differences, while
identity/time/valid/type/mk are exact and every numeric field is within the
recorded tolerance.
