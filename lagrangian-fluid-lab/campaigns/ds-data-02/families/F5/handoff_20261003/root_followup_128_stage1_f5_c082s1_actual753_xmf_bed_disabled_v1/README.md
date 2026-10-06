# F5 fresh128: Root753 typed -> N3 XMF -> full801 Mk50 bed audit (disabled)

This source-only package binds the two actual Root753 typed producers for `M085_T080` and `M115_T100`. Root754 reports `finished=2`, `completed0=2`, and terminal controller return code zero. Each producer is independently checked from its own JSON receipt, Root753 request, conversion report, and owner metadata closure.

The actual typed producer contract is 801 saved frames, 194427 particles, 3-D, with fixed=158559, moving=4210, fluid=31658, floating=0. The conversion reports attest `PartVTK all_passed=true`; their H5 output paths and SHA256 values are copied as producer attestations only. This package never opens or hashes H5, BI4, CSV, DAT, VTK, or solver arrays.

The physical identities remain separate. Fresh125 canonical hashes are M085 `58d38ff69b4ab543255e31a4dd8179b6a8dfb87d020e2e850407335b80fcf5f6` and M115 `a6fa3f7d0e41c9b1eb83ba3387c911c180bb6eec2fa9af4ee4987b4dd10d27ce`. Source-plan/DefXML hashes are `8894cee1e30e302d5c531f88a5c1690fd871b1891babf4726c15211162e09fbe` and `36b426c00ac044579105e46935e2f79b4c126674e9b537bde32ae6e9642474ed`. The actual converter legacy H5 scopes are M085 `399532868fb90f2c182f6179637e57c7dde73f85777e2b14e0fcbc57e4cc5a28` and M115 `8c8f663de21bdf49a711a88499ad89d073850bfcbbc6a3b64a36899023986526`. The earlier fresh125 forecast `3cd1ceab16be11428bbc1011a1b4e297c384d8c7926432c222c254064744ccd0` is retained as forecast provenance and is not asserted equal to either actual report scope; no cross-resolution equivalence or mass rescale is claimed.

The XMF requests use Root142 `kind=cpu`, `cpu_task_kind=audit`, CPU2, Home-floor inventory policy, and the shared NVMe cap of two. They are disabled and contain no launch permission. The bed workers reuse the successful full801 footprint algorithm, preserve the exact bed profile `x=-0.2..4.8`, `y=-0.22..0.22`, Mk40 source-to-native Mk50 mapping, full initial fluid UID denominator, and 1DP/2DP diagnostic thresholds 0.02/0.04 m. Because Root753 did not publish a saved-state JSON sidecar, the fresh128 bed worker checks only the exact `Part_0000.bi4` through `Part_0800.bi4` directory-entry sequence at execution time; it never opens or hashes those BI4 bytes.

All future XMF, bed-audit, and receipts hashes are null. Root must bind the actual XMF manifest and receipt before enabling the bed request. Typed success alone does not approve the full event, Q-N, visual acceptance, or case credit. The remaining ten candidates and all four T120 candidates remain closed; T120 forcing is not certified by the 16 s/801-frame window. The historical A/B penetration failures and Root314 exact-DP 1e-6 numerical-precision negative (5e-6 observed) remain unchanged.

Root operation after review:

```text
python3 scripts/validate_fresh128.py
# Root derives an enabled per-tag XMF request from requests/*-full801-xmf-request.json.
# After XMF completed/0, Root binds its real manifest/receipt into the bed binding,
# then derives and registers requests/*-full801-bed-audit-request.json.
```

The package creates no independent case increment and contains no science payload.
