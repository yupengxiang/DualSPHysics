# F7 fresh063 actual native initial QA handoff

This handoff binds the two actual GenCase 085 endpoint outputs to a new strict
initial-state worker.  It is source-only: no solver, conversion, rendering,
BI4/H5/CSV array read, or production launch was performed while preparing this
directory.

The bound GenCase evidence is:

- `F7_OBSTACLE_QUINTIC_B08_A030`: completed return code 0, 70,179 total, 40,700 fluid, 3-D; generated XML SHA256 `9fbc65975a11ae6078231a212a0e282d657c7468a8a6f7e6403e02496e6ed487` and BI4 SHA256 `b31f590f78f25bc011a406d7d6e0827e674a64a47e52467af560a3e7457d425d`.
- `F7_OBSTACLE_QUINTIC_B08_A065`: completed return code 0, 70,179 total, 40,700 fluid, 3-D; generated XML SHA256 `e92f2422b2416ce32ad36350bf19aa129e9fdf6c474ef92009e39dee13acb81f` and BI4 SHA256 `f905a45f615304877f2a753471639bf812021d1741df7fcd4b5dc536b258864a`.

Both generated XML files declare the same mother partition: 27,495 fixed
particles (`Type=0`, `Mk=10`), 1,984 moving particles (`Type=1`, `Mk=12`),
and 40,700 fluid particles (`Type=3`, `Mk=2`).  The source Definition has the
moving `mk=2` all-filled obstacle, four explicit solid wet slabs under
`setmkfluid mk=1`, and the 12-second forcing pivots.  These are source and
typed-partition checks; they do not certify solver dynamics or visual
acceptance.

The 074 motion-preparation receipt is completed.  Its two tables contain 12,001
rows each at 0.001 s sampling.  The native reader is recorded as
`piecewise_linear_absolute_angle_increment`; the analytic target is C2, while
the native sampled table is not claimed to be C2.  The registered native fluid
mass is 325.60001628000003 kg and the separate continuum-envelope mass is
320.1984 kg.  The worker reports both and never rescales the native weights.

Files:

- `binding.json` — fresh 063 source, endpoint, forcing, hash, and QA contract.
- `workers/run_f7_target_angle_native_initial_qa.py` — Root-run strict worker.
- `requests/f7_target_angle_native_initial_qa_request.json` — disabled CPU QA request.
- `requests/f7_a030_full12_native_qualification_request.json` — disabled A030 full 12 s request.
- `requests/f7_a065_full12_native_qualification_request.json` — disabled A065 full 12 s request.

The two qualification commands are exactly the native mother recipe:
`DualSPHysics5.4_linux64 <actual-085-prefix> {attempt_root}/solver_output
-tmax:12 -tout:0.02`.  Each request uses the corresponding actual 085
`prepared` directory as `cwd`, because `motion_obstacle_quintic.dat` is a
relative forcing asset there.  Root must first run and review the fresh initial
QA, bind its real report/receipt paths and hashes, and explicitly enable a
qualification request.  All requests in this source handoff remain
`launch_allowed=false`.
