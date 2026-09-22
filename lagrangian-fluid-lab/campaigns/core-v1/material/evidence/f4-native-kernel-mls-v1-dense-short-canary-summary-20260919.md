# F4 native-kernel MLS short canary

This is an independent CPU diagnostic for `f4_native_kernel_mls_v1`.  It is
not a T1/T2 result and does not modify the prior F3/F4 material outputs or
their gates.

- Backend code: `scripts/f4_native_kernel_mls.py`
- Code SHA-256: `bb3db37dbbef74ddc6b7baa158f513f3da250b67a49eb60836475060ad561181`
- Native source: `runtime/attempts/f4-resting-pool-native-dense-002-canary-s0p3-center-q0p5/20260919T185855-d91665790347/product/trajectory.h5`
- Source SHA-256: `eaa423cd1e6cdb2e0bd89fcd9b0332fd0e9524e10be0c907926d4155b3ce46b9`
- Result SHA-256: `2e77f66007cf74de8959020b0efbf3c93ab80709c4ea4a77406e7f94bb90565e`
- Execution receipt SHA-256: `1622e436f3ca89170790eafa03132ea4e9e5c28d39c68097c9c4e740a3f0c90f`

The source is the real F4 native `.002 s` dense output.  Frames 0 through 150
were processed sequentially on CPU; only frames 0, 80, 81, 82 and 150 were
saved.  Query positions started from an independent 8x8x8 drop-box grid and
advanced with explicit Euler using the velocity reconstructed from the current
frame.  An unknown query holds its position for the next step.  The provider
read only position, velocity, mass, density, valid, `type==3`, and time.  It
did not read a future velocity or density, and no source label or native
particle id was used.

The current numerical support checks remained reliable for all 512 queries in
the five saved frames.  This is expected because this backend deliberately
reports the reconstruction residual separately rather than inheriting the old
F3 reconstruction-error gate.  The residual p95 was `0.01108 m/s` at frame
80 (`t=.160015 s`), `0.16387 m/s` at frame 81 (`t=.162004 s`), `0.47428 m/s`
at frame 82 (`t=.164008 s`), and `0.05840 m/s` at frame 150
(`t=.300003 s`).  Thus the canary has no qualification claim even though the
numerical support mask is complete.

The versioned current-support diagnostic uses a graph radius of `1.5*dp =
0.01125 m` and never partitions by initial source identity.  At frame 81 it
found one geometric support component for every query, but a two-branch
velocity fit had p95 separation `0.25576 m/s` and within-branch RMS
`0.09953 m/s`.  At frame 82 the corresponding values were `1.11327` and
`0.47950 m/s`.  At frame 150, 4.8828125% of queries had more than one current
geometric component (maximum three components), with p95 branch separation
`0.19868 m/s`.  This supports the hypothesis that cross-interface velocity
mixing can begin before a disconnected component is visible; it is evidence,
not a change to the backend gate.

The run used 103.16 CPU seconds, 0.92 system seconds, 87.91 wall seconds and
137 MiB maximum RSS.  GPU, ledger and slot use were all false.
