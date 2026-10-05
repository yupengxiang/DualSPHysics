# F5 B071 fresh076: short native qualification and full-saved diagnostics

This is a source-only handoff for `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071`. It binds the actual GenCase 163, Root175 initial QA, and Root185 frame-zero coverage metadata. No solver, converter, PartVTK, HDF5, CSV, BI4, or renderer was run while preparing this package.

Root185 is the corrected marker audit. The source Def uses `mkbound=40`; the actual generated XML maps that source marker to native `Mk=50` (19,720 fixed rows). Native `Mk=40` is the 102,944-row sidewall/mixed cohort and is not a bed filter. Root185 found native `Type=0, Mk=50` central half-DP support `[10, 13, 18, 15, 20, 20]` across the six profile segments, global support 11,724, and zero initial fluid rows below the profile. This supports a manually reviewed short native qualification request. The support is patchy, so it does not certify a uniform dense bed or dynamic stability.

The disabled short request is a real 0..1 s, `-tmax:1.0`, `-tout:0.02` native run. Its working directory is the actual GenCase prepared directory so the relative motion asset resolves. It requires all 51 saved states for later typed conversion, XMF publication, framewise bed penetration diagnostics, and full-saved rendering. Every downstream request remains disabled and future receipt/product hashes are null until Root binds actual outputs.

The framewise audit reports, for every saved state, Type-3 fluid rows in the exact profile x domain and `y ∈ [-0.15, 0.15]`, `<1DP`/`<2DP` counts, fractions, maximum depth, nonfinite rows, and missing/unexpected initial UIDs. Penetration bins are diagnostic observations; no threshold is relaxed or treated as automatic acceptance. The short event is right-censored and adds zero independent cases. Full801/full16 remain disabled.

Candidate A's real severe short-event failure and Root183's wrong-native-marker result remain historical negative evidence and are not overwritten or reused as the B gate.

## Actual immutable metadata

- GenCase receipt: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-genuine-gencase-163/execution-receipt.json` (`52ce589ee3cb51136daf7188c0cedbc5a43999e28ee13557942d646d115c56dd`)
- Generated XML: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-genuine-gencase-163/prepared/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071.xml` (`9abb26c6a364618f588038410c748606ec481aaf61ea2f9a9cd235143ca8af90`)
- Root175 QA provenance: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-initial-qa-output-root-binding-repair-175/initial-qa/b071-initial-qa-provenance.json` (`ff00983f227e745616d2a1d28f81a2c3a038e27a9ace7c1baca85d7c212cc555`)
- Root185 coverage report: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-native-bed-marker-mapping-repair-185/initial-bed-coverage/b071-direct-native-initial-fixed-bed-coverage.json` (`d6f99d4830accac0b97315d4707cc7009434e8fc6084b1af0c59dc08731c575d`)
- Root185 execution receipt: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-native-bed-marker-mapping-repair-185/execution-receipt.json` (`74cfb6c7e690c8572c0387e2e5c343d9a3a61018b5efc4224d3cf729b1fad818`)

Run the source-only verifier with `python3 scripts/verify_fresh076.py`. It validates actual small JSON/XML receipt identity and AST/contracts without opening CSV, H5, BI4, or starting a job.
