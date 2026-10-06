# fresh115 F3 Root884 native successor handoff

fresh115 is a disabled, F3-scoped successor template based on the immutable
Root884 request set. The Root884 source snapshot contained four completed
native receipts with return code 0 and nine remaining candidate requests. The
first candidate in that order, `F3_STAGE1_DP006_P1200_AY0320`, was consumed by
Root948 while this handoff was being audited. The live re-audit records its
reservation, launcher, and solver child and excludes it from the new template.
The request in this package is therefore the next still-unstarted case,
`F3_STAGE1_DP006_P1200_AY0360`.

The successor preserves the source physical binding, exact command, 8.35 s
window, 0.01 s output interval, 836 saved frames, genuine 3-D GenCase and
initial-QA provenance, and producer-attested input digest values. The source
package did not open, copy, or rehash BI4, CSV, DAT, VTK, H5, or other
scientific payloads. Future solver receipts, output roots, H5, visual receipts,
and credit remain null/zero. The original Root884 requests are untouched.

The future Home reservation is explicit: the native estimate is 10 GiB plus
2 GiB headroom (12 GiB total), while the Home free floor remains 500 GiB. The
old 16 GiB metadata headroom is not carried into the successor.

The original Root884 controller is now absent with no children or exact
Root884 reservation. Root948 is an active successor lineage and is preserved;
fresh115 does not kill, retire, or duplicate it. Root947 subsequently froze
and retired the old Root884 metadata while retaining its request and receipt
bytes; fresh115 therefore treats Root884 as historical provenance, never as a
live controller. The audit lists both the source-time four-plus-nine frontier
and the current one-active/eight-unstarted frontier.

`metadata/root943-h5-boundary-correction.json` fixes the fresh114 wording:
Root943 was a registered ParaView child allowed to read immutable source H5
through XMF. The source/orchestrator did not read or hash H5. Root943 was a
frame-0 diagnostic only and did not grant full-case visual credit.

Validation:

```text
python3 scripts/validate_fresh115.py
```
