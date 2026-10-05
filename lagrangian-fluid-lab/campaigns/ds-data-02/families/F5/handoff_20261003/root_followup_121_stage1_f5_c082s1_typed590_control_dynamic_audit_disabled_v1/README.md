# F5 fresh121: typed590 control/state diagnostic adapter (disabled)

This is an independent source-only adapter for the actual A080/A120
full16s/801 typed products. Fresh120 remains immutable. The adapter fixes the
consumed request closure: both requests point to this package's binding, XML,
and the unchanged producer worker whose actual SHA256 is
d8ecb69288afeb4e5041a5c2b1e7527bdcfe9d59b86b34cd1f900a446846107f.
The previous bb726a... worker value is retained only as a negative stale-hash
case in the validator; it is not an executable input.

The package contains source code and metadata only. H5 and DAT paths remain
external producer outputs. Their hashes are copied from the typed590
conversion report and motion-transform report; the validator verifies those
attestations without opening or rehashing either payload.

When Root explicitly enables a request, the unchanged worker reads each
producer-attested typed590 H5 and transformed motion table and reports all 801
states plus focus frames 0, 97, 153, 219, 400, 718 and 800. It measures moving
center/control residuals, fluid state summaries, identity/finite checks and
the native Mk50 footprint proxy. It does not alter data, resample, change
penetration thresholds, grant precision/Q-N, accept visual runup, or create
case credit.

Both requests remain disabled, execution_allowed=false, and
fullnative_gate=WAIT. Root visual mechanism review is still required; the
fresh120 historical precision negative and all earlier penetration evidence are
preserved.
