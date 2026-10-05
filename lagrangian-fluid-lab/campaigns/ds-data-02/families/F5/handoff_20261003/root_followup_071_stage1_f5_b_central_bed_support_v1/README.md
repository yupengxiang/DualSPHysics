# F5 fresh071: central bed support candidate B (source-only)

This handoff is the second and final currently justified geometry/fill repair candidate: A061/A075 is the first candidate and failed the real Root131 short event; B is the one bounded follow-up. fresh071 gives B a new execution identity but keeps the B069 source bytes unchanged (`e912c12cc6cf9d3e754cba69a307f47588e717a8a4717f1ed190c63443cc3e72`). It does not modify consumed fresh069/fresh070 files, run GenCase, inspect BI4/H5/CSV arrays, convert, solve, render, or authorize full801.

## Evidence and diagnosis

Root148 is a completed actual frame-zero audit of A061. It reports 214,385 total particles, 40,710 fluid, 167,855 fixed, and 159,065 `mk=40` fixed rows. The six profile x segments have `surface_half_dp_mid_y_count = [0, 0, 0, 0, 0, 0]`; each observed y-level set is `[-.22,-.20,-.18,-.16,-.14,-.12,-.10,.12,.14,.16,.18,.20,.22]`. Thus the explicit A mesh/rasterization produced outer y bands and no fixed support in the central `abs(y)<=.01 m` surface band. The `mk=40` cohort includes walls, so its count is not a bed-only proof. Initial fluid below-profile/nonfinite counts were zero.

A075's source has 52 explicit triangles whose vertices use only y = ±0.15 m and has no `drawfilestl`; its generated command list has no erase-like command. `setmkfluid` and the clipplane occur before the fluid drawbox and after all fixed geometry. The official XML template and examples document `setdrawmode`, `drawfilestl autofill`, `clipreset`, and `shapeout reset`; the available package contains no GenCase geometry implementation source and no `erase`/`eraseall` selector in the XML contract or official examples. Therefore there is no evidence that the later fluid clip or `shapeout reset` deleted A's fixed center. B tests a missing volume/rasterization contract by drawing the retained closed STL in `full` mode with `autofill=true`, after the explicit surface and physical boxes, then proceeds to fluid setup. This is an evidence-based hypothesis, not a success claim.

## B071 source contract

- source definition: `candidate_source/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B_Def.xml`, SHA256 `e912c12cc6cf9d3e754cba69a307f47588e717a8a4717f1ed190c63443cc3e72`
- canonical physical recipe: SHA256 `d791355fcb5d8562a45ecdbee1772b1039f2fe8e6534760734509b51511c5d3f` (kept separate from source-plan hash)
- retained STL: `9a64a266c64d0eeee0194efc102263ba89e61538acf94095733f73827fd7f87c`; motion: `51e197f0831915a73534c619704658b06812c9d52c38c470ab4cbb8d59f5614a`
- unchanged DP 0.02 m, bed y ±0.15 m, profile nodes, clipplane, fluid box, motion, 3-D runtime recipe, and no penetration threshold changes
- no underlay, no bulk batch, no solver request, and `independent_case_count_increment = 0`

The future B GenCase total is intentionally unknown until a fresh receipt. Requests require reporting the actual total and generated XML `np`; they do not assume A's 214,385 or the prior rejected 214,515. The unchanged fluid box is expected to yield 40,710 fluid rows, but QA must verify that against the genuine B receipt.

## Root execution order

1. Review `gencase-request.json` and enable only a fresh Root-owned genuine GenCase attempt. Its source and both asset hashes are fixed in `gencase-binding.json`.
2. Run `scripts/bind_gencase_qa.py` against that fresh receipt and generated XML to create an actual QA manifest in the DATA attempt. Then manually enable `initial-qa-request.json` using the bound manifest. QA checks typed rows and actual total; it is not a bed-completeness or dynamic gate.
3. After Root has a fresh typed B product and XDMF, run `scripts/bind_initial_coverage.py` with the actual JSON/XML/XDMF paths. It hashes small metadata only and cross-checks the H5 digest declarations from conversion report/manifest/receipt without rehashing or decoding H5.
4. Manually enable `initial-fixed-bed-distribution-audit-request.json`. Review every frame-zero segment's 0.5/1/2 DP surface counts, central y support, UID/finite/overlap and fluid separation. This is diagnostic only. Even a structural pass cannot approve a dynamic event; the existing A full801 gate remains rejected until Root performs a separate evidence-based review.

All three request files remain `launch_allowed: false`; only Root may enable them through the strict dispatcher. `tests/test_fresh071_source_package.py` is static/synthetic only.
