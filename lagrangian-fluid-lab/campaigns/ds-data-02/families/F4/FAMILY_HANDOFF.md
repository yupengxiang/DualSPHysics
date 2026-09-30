# F4 handoff

The two finite 3D mechanisms are materialized from the read-only official mothers and are ready for shared CPU GenCase. The source mothers are actual `Data2D=false` cases with finite fluid counts and five finite tank faces. New core definitions use a balanced centre-lattice initialization with native `rho*dp^3` mass and no mass rescaling. The frozen complete event window is 1.20 s and the reference output cadence is 0.001 s; 0.0005 s output and CFL=0.1 are independent controls. Run both JSON requests through the shared runner, then bind their real receipts to qualification requests. This handoff makes no Q-N or product claim.

## CPU receipts

Both coarse parent GenCase requests completed through the shared runner with actual 3D output: drop 2469 total/928 fluid, oblique 1733 total/192 fluid. Receipt and input hashes are in `gencase_receipts.json`; the two GPU qualification requests are ready but have not been started here.
