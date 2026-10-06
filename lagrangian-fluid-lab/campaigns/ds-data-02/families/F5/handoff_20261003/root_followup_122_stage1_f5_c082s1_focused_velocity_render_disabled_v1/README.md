# F5 fresh122: focused Root023 velocity display (disabled)

This source-only package registers a focused display view for the actual Root598
A080/A120 XMF products. It keeps Root023 render.py unchanged at SHA
5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66. The local
worker patches only the ParaView fluid representation to color native Type-3
points by velocity magnitude on a fixed 0.0--0.6 m/s display scale, and passes
a local water/shoreline camera window. The source reader, native type/Mk fields,
actual XMF/H5 time values, all 801 frames, and the 194427 particle axis remain
unchanged.

The camera window is a view setting. It does not clip the source reader or
remove particles from the PVSM graph. Focus frames are 0, 97, 153, 219, 400,
718 and 800; the disabled requests ask Root023 to render all 801 saved states
and contact sheets, with those frames called out in metadata.

H5 is an external producer payload. This package records only its producer
attestation from the Root598 manifest and never opens or rehashes H5. It also
does not read DAT, BI4, CSV or VTK. The requests are CPU/audit, disabled, and
derived-view-only. Root must wait for the current render cap to drain and
review the focused output; this does not grant visual mechanism acceptance,
Q-N, or case credit.
