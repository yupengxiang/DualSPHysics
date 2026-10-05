# F5 fresh117: sixteen additions completing the first 24-condition source batch

This pack keeps the C082S1 analytic closed bed, finite tank, source Mk40 to native Mk50 mapping, and three-dimensional source definition. It adds sixteen distinct forcing owners from amplitude {0.85, 0.95, 1.05, 1.15} crossed with time scale {0.80, 0.90, 1.00, 1.20}. The set is disjoint from A080/A120 and fresh110's six M/T conditions. The slowest transformed table ends at 19.2 s; each full native template runs 0..26 s at .02 s (1301 states), leaving a 6.8 s post-forcing runup tail.

All requests are source-only and disabled. The motion worker is registered for future Root CPU execution; it reads the base DAT only at execution time. GenCase, initial placement/Mk50 QA, 1 s/51-state native qualification, dynamic bed audits, and 26 s full native templates require fresh producer receipts. Counts remain null until each candidate's own GenCase report.

The historical C082S1 counts and fresh109 A080/A120 short-bed evidence are provenance only. They are not copied as new-candidate expectations. Root314's exact-DP 1e-6 negative and the earlier A/B severe penetration failures remain preserved. Existing A080/A120 full native typed results still await complete all801 bed and root visual review; no fresh117 full run is approved by this package.

| Candidate | amplitude | time scale | transformed table end | full window | canonical condition SHA | owner source SHA |
|---|---:|---:|---:|---:|---|---|
| `M085_T080` | 0.85 | 0.8 | 12.8 s | 0..26 s / 1301 | `58d38ff69b4ab543255e31a4dd8179b6a8dfb87d020e2e850407335b80fcf5f6` | `fb31642a81fa1972e429d36235f2b4b44a4de2480589b1a1a66f925966b99ac1` |
| `M085_T090` | 0.85 | 0.9 | 14.4 s | 0..26 s / 1301 | `cd77b07c6918a47a1bcbff5e1f066c36a34b0ca01d5f276e75d96a2d3dc89259` | `e3bb4bb803340f73207b3003b8eb60a655c2c6c891156c3f757e96a90fbd1014` |
| `M085_T100` | 0.85 | 1 | 16 s | 0..26 s / 1301 | `0521b11e6a5eab05ca3c8e41058cc55971f6c1dd599650b6947daaaa77837965` | `35863c71412814a921d6e650cb0a677732e0aea34639219812e7e4d0ddec1771` |
| `M085_T120` | 0.85 | 1.2 | 19.2 s | 0..26 s / 1301 | `3326104b747a55329be40ee508d5ed44b2158561808abbd552fc7385665f44d6` | `b4b7771ed6e690b1503ed384d68f7d2e58bd958a2b0600b40163d7f9d24f08b0` |
| `M095_T080` | 0.95 | 0.8 | 12.8 s | 0..26 s / 1301 | `9b51cce0a2f5940a8e6fdf2d284e407dd57f918fad42172eccfd498cbac1eaee` | `688be59177c55884437f31312fa77c7b2673f12b8b46c4557e350548adcdd677` |
| `M095_T090` | 0.95 | 0.9 | 14.4 s | 0..26 s / 1301 | `88e4d21325c19591188a5ebea6041ff0e26ccd18ccc09860bdfea7271cadc167` | `e74d82a415d8ac344eaeb49dc1466228bbcd1989bb325e0a4d2ab93f4435ce0b` |
| `M095_T100` | 0.95 | 1 | 16 s | 0..26 s / 1301 | `81b91a91bcce2365496f0892d0e5d2a5362da917be1ed49b6dd2c1536e8c0ebf` | `e4d315e5d8e5f44ac22fec0122c2560962e43d6603c9ed1e916e90f70f98541a` |
| `M095_T120` | 0.95 | 1.2 | 19.2 s | 0..26 s / 1301 | `6e1976c1c640171636c970c05eb1da4374c53dc391ad37d21b892141609ee26c` | `e0921c4c03c47d918145fc5e695354233076fc51ec1174d10f7470bfe9a2a796` |
| `M105_T080` | 1.05 | 0.8 | 12.8 s | 0..26 s / 1301 | `8f8c96ac8ec4b36ffe893782830637e45c728e8c509211b6299f3986b83feb73` | `4c00ae83feef13912d954dc46f63e5affa82d4c5afb3bba2b1ae6b9e2b253fe6` |
| `M105_T090` | 1.05 | 0.9 | 14.4 s | 0..26 s / 1301 | `723086161aec499a8977dfb457b9cd0a5b380bc6c78c44cf6fcd9f5639d9df80` | `a86ab4ce033f61c255aa7cf0bf8ade87a4f05b101df44801651a3c4ce304fb06` |
| `M105_T100` | 1.05 | 1 | 16 s | 0..26 s / 1301 | `00b37ae025988a4eff9e2394f4be3863112630e8374131619c65365c66b5caff` | `91712b70a48aae7aefea1718e3ca98f1ca22f03d167d304061b020db72d4f9b3` |
| `M105_T120` | 1.05 | 1.2 | 19.2 s | 0..26 s / 1301 | `e0f91a6263b8d4d07c7dd2234154dda15bbbdaffa4dcfb6f7ee4f1349d4b8c32` | `4b808bff6a43e86ac7a8076b8e438406e9a52dd0d42694071efb28fc0bcd45fc` |
| `M115_T080` | 1.15 | 0.8 | 12.8 s | 0..26 s / 1301 | `88b7675cc646f6be00dd6af97c9cfdbd4e0610816bb14e516e5f450b74fc3895` | `34be7f1b5ff64dac5f8865d9b82ec994db1af925a89c903a886d618fd49aa29d` |
| `M115_T090` | 1.15 | 0.9 | 14.4 s | 0..26 s / 1301 | `5d7ea375d3f0582d32133134548ef709a9554d20bab43dc8f4e011594d37eec1` | `120dbac20e43ff746111a31729839974893d20288d5e306601deeb05aef8364e` |
| `M115_T100` | 1.15 | 1 | 16 s | 0..26 s / 1301 | `a6fa3f7d0e41c9b1eb83ba3387c911c180bb6eec2fa9af4ee4987b4dd10d27ce` | `b59373f869c28a033a202127dc14d2722bf64a0b29f1e09b7f2e4f823ff9460a` |
| `M115_T120` | 1.15 | 1.2 | 19.2 s | 0..26 s / 1301 | `df3f72798bcb423f97553c6c2ae749f6a56f4b60ab9537afdf0a04973095967a` | `000710bba66c285f19b43bb390b3627164bda5c3e47f73dd5e61220cd5d9e920` |

Root next entries are the `requests/*-motion-transform-request.json` files, followed by each matching GenCase and initial QA request only after the actual transform receipt is bound. The short native/bed and full native/bed requests stay disabled until Root review and Root230 live UUID/lease protection are supplied.

Source preparation did not read or hash DAT, BI4, H5, CSV, VTK, or solver payloads and did not start a job or modify shared state.
