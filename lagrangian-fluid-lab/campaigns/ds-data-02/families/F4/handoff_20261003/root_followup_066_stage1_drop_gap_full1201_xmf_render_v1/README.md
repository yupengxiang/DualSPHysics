# F4 full 1201-frame XMF and ParaView handoff (fresh066)

This source-only handoff covers the two already completed Root103 typed conversions:

- F4_DROP_ENDPOINT_GAP0p18000_DP010 -> canonical physical owner F4_DROP_B08_gap0p18000_xoff0p00000_yoff0p00000_uz0p50000 (773e18...e15de56)
- F4_DROP_ENDPOINT_GAP0p26000_DP010 -> canonical physical owner F4_DROP_B08_gap0p26000_xoff0p00000_yoff0p00000_uz0p50000 (b625ef...a75412)

Both native Root077 receipts and Root103 conversion receipts are bound as completed with return code 0. Each conversion report records 1201 frames and 83233 particles, with 59072 fluid particles and official PartVTK checks passing at frames 0, 600, and 1200. The opaque HDF5 hashes are recorded; this package does not open HDF5, BI4, CSV, or numerical arrays.

Unchanged Root105 export_xmf.py is requested for each actual trajectory.h5. It must publish all 1201 saved states and preserve the actual HDF5 time values in XDMF using .17g. The XMF requests are disabled until Root enables them. The paired ParaView requests remain disabled until their XMF manifest and case.xmf complete with status/return code completed/0.

The F4 renderer is a source derivation of Root023, the proxy-lifetime-safe native renderer already used for complete F4 animations. Its Root023 camera_for_bounds receives endpoint XML known bounds: the physical tank [0, 1.2] x [0, 0.4] x [0, 0.6] contains the complete pool/drop event, while the definition envelope is retained as provenance. It derives two full orthographic views (isometric and transverse-side/drop-pool) from those bounds. Native fluid, boundary, moving, and floating point proxies remain visible; display-only Clip/Outline branches never mutate the source reader, which remains unclipped in the PVSM. The renderer records computed camera parameters and bounds in paraview-full-animation-report.json.

Each full render must write 1201 frame PNGs, 51 contact pages keyed by contact-page-keys.json (24 frames per page, final page frame 1200), a GIF, a PVSM state, and the full report. Text is F4-only and actual-time labels use .17g; no rounded time labels are accepted. Visual review, numerical precision, Q-N, and production approval remain pending Root review. Neither endpoint increments the independent-case count.

Root execution order is: enable the paired XMF request, bind its completed receipt/manifest hashes, then enable the matching full ParaView request. No shared registry, ledger, solver, conversion, or render job is launched by this source package.
