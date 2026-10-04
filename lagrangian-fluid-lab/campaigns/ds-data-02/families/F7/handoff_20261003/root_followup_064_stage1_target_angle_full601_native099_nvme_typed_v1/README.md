# F7 fresh064: actual native099 full-window NVMe typed conversion

This source handoff binds the two already completed endpoint runs to two disabled
CPU NVMe conversion requests:

- F7_OBSTACLE_QUINTIC_B08_A030: source condition hash
  d23a491656bd152dd8dd0216abcd41b6df8a1f9e4478f9c9fd2f11b79f1f38e4,
  canonical physical_binding.v1 hash
  2c863c5a0c553d38ec7182a6f7ddb38a52bafa070e574bc121b100bb91fac050.
- F7_OBSTACLE_QUINTIC_B08_A065: source condition hash
  7694c57f286b25b288fd7813a0abbaa2eac82751a1540c623e3f3268d7eb8600,
  canonical physical_binding.v1 hash
  5812777b33c44b326fdc9ff13f84fb9f3d52a8e6a4cc168b402e2b7eb86e7fb0.

The owners reproduce source062's concrete source geometry: tank
[-0.6,-0.4,0] + [1.2,0.8,0.6], all-filled paddle
[-0.07,-0.24,0.05] + [0.06,0.48,0.48], four explicit wet slabs, and pivot
[-0.04,0,0.05] to [-0.04,0,1.05]. The two amplitudes are the only endpoint
variation. The owners retain the full native recipe (dp=0.02, 601 frames,
12 s, 0.02 s save interval, 12,001 motion rows, fixed 27,495, moving Type 1
1,984, fluid Type 3 40,700).

Actual evidence already bound:

- genuine GenCase085 completed with the endpoint XML/BI4 hashes from fresh063;
- QA096 completed and passed both endpoints, including typed blocks, positive
  weights/densities, zero initial velocity, 3-D, and pairwise initial
  no-overlap;
- native solver099 completed both 12 s runs with 601 native frames;
- native fluid mass is 325.60001628 kg, while the continuum comparison is
  320.1984 kg; neither is rescaled;
- analytic target C2 is retained as source description; native sampled motion
  is piecewise linear and is not claimed C2.

physical_condition_sha256 in each owner/request is the source062 endpoint
hash. The converter will compute a separate hash from the explicit
physical_binding.v1. The helper records both values and never treats them as
equal. This distinction is required because the source hash includes recipe
fields such as dp, TimeMax, and TimeOut.

All work here is source-only. No solver, converter, PartVTK, BI4 decoder, H5
dataset, or native array was run or opened while preparing fresh064. The two
conversion requests remain launch_allowed=false.

Root static review:

    python3 scripts/bind_completed_conversion.py --endpoint F7_OBSTACLE_QUINTIC_B08_A030 --mode static
    python3 scripts/bind_completed_conversion.py --endpoint F7_OBSTACLE_QUINTIC_B08_A065 --mode static

After Root enables and completes the corresponding disabled request, bind only
the conversion metadata and H5 byte hash:

    python3 scripts/bind_completed_conversion.py \
      --endpoint F7_OBSTACLE_QUINTIC_B08_A030 --mode bind \
      --conversion-report /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/F7_OBSTACLE_QUINTIC_B08_A030/root-stage1-f7-a030-full601-native-typed-nvme-064/conversion-report.json \
      --trajectory-h5 /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/F7_OBSTACLE_QUINTIC_B08_A030/root-stage1-f7-a030-full601-native-typed-nvme-064/trajectory.h5 \
      --output /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/F7_OBSTACLE_QUINTIC_B08_A030/root-stage1-f7-a030-full601-native-typed-nvme-064/typed-binding.json

Use the same command with A065 and its corresponding DATA paths. The helper
reads JSON metadata and hashes the H5 bytes; it does not open H5 datasets.
Conversion remains evidence only: no Q-N, visual acceptance, or production
approval is granted.
