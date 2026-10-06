# F5 fresh124: native typed590 initial_mk keyframe scatter audit (disabled)

This package registers a CPU-only, read-only audit for the actual Root598
typed590 H5 products. The worker selects the original saved frames
0, 97, 153, 219, 400, 718 and 800, reports each frame's actual H5 time, UID/type/valid/finite checks and the producer `initial_mk` field and particle counts, then writes three scatter PNGs
per frame: full-domain x-z, local shoreline x-z and local shoreline y-z.

Plots use original native rows only. Fluid Type 3 points are colored by native
velocity magnitude in m/s on a fixed display scale of 0.0--0.6; fixed and
moving points are gray. The optional frame-0 overlay is the original frame-0
fluid position set. The local window is a display selection and does not edit,
smooth, interpolate, resample or reconstruct arrays. It cannot certify a free
surface, transport, wave mechanism or visual acceptance.

The source package does not open or hash H5, DAT, CSV, BI4 or VTK. H5 SHA values
are copied from the Root598 conversion producer attestation. Both requests
remain disabled under the Root142 CPU/audit path with cpu_threads=2 and
single-thread environment overrides. Fullnative, Q-N and case credit remain
WAIT/false.

The worker reads the producer H5 `initial_mk` one-dimensional field on the fixed `particle_id` axis (shape 194427, dtype int16). Mk50 is the native bed marker and source mkbound is 40. It intersects that fixed marker mask with each frame’s current valid/type rows; it makes no time-varying Mk claim. It reports the exact saved frame index plus H5 time. This is a scatter diagnostic only; it does not infer a free surface or certify wave/runup mechanism.

The Root598 manifest metadata is part of the binding: `initial_mk` is shape `[194427]` and there is no `mk` time-array field.
