# F5 fresh110: six independent amplitude/time forcing conditions

This pack keeps the C082S1 analytic closed bed, finite tank, source Mk40 to native Mk50 mapping, and three-dimensional source definition. It adds six distinct forcing owners from the Cartesian product amplitude {0.8, 1.0, 1.2} x time scale {0.9, 1.1}. A transformed table ends at 14.4 s or 17.6 s; every full native template runs 0..24 s at .02 s (1201 states) so it includes the complete transformed forcing and a post-forcing runup tail.

All requests are source-only and disabled. The motion worker is registered for future Root CPU execution; it reads the base DAT only at execution time. GenCase, initial placement/Mk50 QA, 1 s/51-state native qualification, dynamic bed audits, and 24 s full native templates require fresh producer receipts. Counts remain null until each candidate's own GenCase report.

The historical C082S1 counts and fresh109 A080/A120 short-bed evidence are provenance only. They are not copied as new-candidate expectations. Root314's exact-DP 1e-6 negative and the earlier A/B severe penetration failures remain preserved. Existing A080/A120 Root511 visual review is still WAIT; no fresh110 full run is approved by this package.

| Candidate | amplitude | time scale | transformed table end | full window | canonical condition SHA | owner source SHA |
|---|---:|---:|---:|---:|---|---|
| `M080_T090` | 0.8 | 0.9 | 14.4 s | 0..24 s / 1201 | `8a172e9a34d968f4eb3b3cd3e5705073e6dcf33f0beb413eed72091fde1ae6da` | `632f2de89b6f1c56c9842d2cf79d5fe56acbf724ae90074fb7c096a8aa55231a` |
| `M080_T110` | 0.8 | 1.1 | 17.6 s | 0..24 s / 1201 | `1ee99ae940b82315c1bc79d533ce4d64dbada30fd3d1ace6d3bbd2df087d4b21` | `9e682f69bdce5c947384eb78ac511db20345e6d5d819de33f675f0f7c6aa633a` |
| `M100_T090` | 1 | 0.9 | 14.4 s | 0..24 s / 1201 | `b6489a524ebfb61e67238638e1cb7a72fd41a9ea338e8229dc9a371a0a20d17f` | `6da47b19fbd45517a62197f77df5f47de68633ad768a2e9c208a61bb56df650c` |
| `M100_T110` | 1 | 1.1 | 17.6 s | 0..24 s / 1201 | `6ff361b3562125fa044abce45f46a516ed978c3258d2fe88801ae80726fb98c4` | `55ba8be2295b89d2e01369d8671ba7e123b4c4cea1f06352bb733b0e7679622c` |
| `M120_T090` | 1.2 | 0.9 | 14.4 s | 0..24 s / 1201 | `c1686dfa5dbad41ce6e1b5090e6036a5d8b7b3d0b21603bd3f056cca374f5cd5` | `5e25e8141d80726c20ea2421c86a2250ca96c657e16a28d246d6868eeca37f24` |
| `M120_T110` | 1.2 | 1.1 | 17.6 s | 0..24 s / 1201 | `a1db404ed28f64a63d9ec4f69aca7741cc906eb909de995ee867ececf151a76c` | `c5ed53a2304ef3bd4510307cea18fdc8c626f13f1d56d18c7314aa7927b75e1d` |

Root next entries are the `requests/*-motion-transform-request.json` files, followed by each matching GenCase and initial QA request only after the actual transform receipt is bound. The short native/bed and full native/bed requests stay disabled until Root review and Root230 live UUID/lease protection are supplied.

Source preparation did not read or hash DAT, BI4, H5, CSV, VTK, or solver payloads and did not start a job or modify shared state.
