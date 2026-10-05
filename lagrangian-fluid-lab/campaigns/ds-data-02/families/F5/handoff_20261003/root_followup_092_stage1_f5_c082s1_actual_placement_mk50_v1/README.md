# F5 fresh092 C082S1 stage-one placement and Mk50 audit

This is a source-only handoff for the already generated C082S1 producer. It
does not change the solid-fluid source introduced by fresh090/fresh091. The
actual GenCase producer is
`root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293`, with
`194427` total particles: `158559` fixed, `4210` moving, `0` floating and
`31658` fluid in 3-D. Its receipt, prepared report and XML remain immutable
inputs. The BI4 SHA `ca47865795da43a42f8b58d9b15118a2c71ab4c7ba19bbb22a15ef2dd208e198`
is copied from the producer prepared report; this source handoff does not open
or rehash BI4.

Root314 generated the official particle CSV and the scalar helper reports. The
helper provenance supplies the CSV SHA
`a1165d9d1d6645f22774eb57c6be0a236b1fbba90f46577cc2ab3fa51d2abfb8`. The
helper reports actual fluid `31658`, 15 transverse y levels, zero fluid below
the continuous bed and zero fluid outside the source bounds. Root314 itself
failed at the original exact-DP-lattice residual check (`1e-6` cell units).
That failure is retained as `numerical_precision`; it is not relabelled as a
pass and it is not used to block the basic stage-one placement proof.

`workers/placement_mk50_audit.py` is a Root-run CPU audit over that already
produced CSV. It independently checks the actual producer count and 3-D XML,
finite rows, integral Zone/Idp/Type/Mk, UID uniqueness, type counts, positive
mass/density, zero initial velocity, spatial no-overlap, exact source box and
bed separation, exact 15 y levels, and Type-0/native-Mk50 support in six bed
segments. It reports central `abs(y)<=0.01` surface-half-DP counts per segment.
It computes max and quantile DP-lattice residuals as a diagnostic only; the
worker never labels that numerical precision check passed and never grants a
solver or Q-N qualification.

`requests/placement-mk50-audit-request.json` is disabled and binds audit315
to the Root314 receipt and helper JSON provenance. The request uses the
documented CPU `audit` task kind, an explicit storage guard, closed static
input hashes, and no live resource-ledger input. The downstream 1 s/51-state
native request is also disabled. It names the official BASE solver, unchanged
motion asset and exact `.02 s`/51-frame recipe, but requires Root review of
the stage-one placement/Mk50 result before any launch. Full 16 s/full801,
typed conversion, XMF and dynamic bed audit remain disabled.

The canonical physical hash
`e691d030eda575b9cfabe62f295c9bdc142e5a04cb4357c9fe2790aaec549dbf` and
source-definition hash
`5bad3ec9f9a71aa87da8272003c357f4523d4ffa164d3f06e5d25fee1a4fbfa6` remain
separate identities. Historical A061/B071 dynamic failures and C082R1
void-fill/precision evidence are preserved. No independent case is added.
