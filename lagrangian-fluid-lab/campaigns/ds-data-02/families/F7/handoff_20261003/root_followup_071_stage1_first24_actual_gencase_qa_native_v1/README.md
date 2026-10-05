# F7 fresh071: first24 actual GenCase -> native QA handoff

This package binds the sixteen new F7 first24 target-angle cases A031, A032, A033, A034, A036, A037, A038, A039, A041, A042, A043, A044, A046, A047, A048, and A049 to the actual Root303 GenCase outputs.

Root303 evidence is complete for all sixteen cases: each actual receipt is `completed` with return code 0, three-dimensional GenCase, total 70179, fluid 40700; the bounded XML/report contract is fixed 27495, moving 1984, floating 0, fluid 40700, `dp=.02`, `TimeMax=12`, and `TimeOut=.02`. The corrected Root003 layout is flat under each attempt: `prepared/CASE.xml`, `prepared/CASE.bi4`, `prepared/CASE_Def.xml`, `prepared/motion_obstacle_quintic.dat`, and `prepared/prepared-input-report.json`. The earlier fresh070 nested `prepared/CASE/` paths remain historical evidence and are not used here.

`metadata/actual-native-qa-binding.json` and `requests/native-initial-qa/F7_FIRST24_NATIVE_INITIAL_QA-071.disabled-request.json` are the aggregate CPU PartVTK handoff. The worker is the sixteen-case adaptation of the reviewed F7 PartVTK initial-state checks, with the XML block contract corrected for Root003's actual XML shape. Root must enable it through the strict runner after review. It is the only source of initial UID/type/Mk/finite/positive mass/density/3D/no-overlap evidence; no source-side GenCase count is promoted to native QA.

The sixteen `requests/qualification/*.json` entries are disabled `kind=qualification` full12/native601 requests for the Root146 strict qualification entry. They retain the exact F7 recipe: DP .02, 12 seconds, .02 output, 601 frames, 12001 motion rows, four source wet slabs, two finite quintic cycles from 0 to 8 seconds, neutral rest 8 to 12 seconds, and piecewise-linear native motion. Native fluid mass 325.60001628 kg and continuum envelope mass 320.1984 kg remain separate, without rescaling. No request claims Q-N, precision, visual, or production acceptance.

Source preparation only hashes bounded JSON/XML/Def metadata and runtime/source code. BI4, CSV, H5, and motion payload bytes are not read or hashed here. They appear only in `future_input_files` with null hashes. Future native QA reports/receipts, solver outputs, XMF, and render outputs also remain null.

Run the static check from this package with:

```text
python3 scripts/preflight_fresh071.py
```

Expected output is `status: pass`, 16 cases, 17 disabled requests, and `arrays_read: false`.
