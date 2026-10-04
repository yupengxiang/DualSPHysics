# F6 fresh067 full12 qualification source package

This package registers two disabled, root owned qualification requests for the
two genuine F6 Stage1 angular endpoints produced by GenCase 073:

- `F6_STAGE1_ANGULAR_RELEASE_OMEGA_S025_DP025`, with its canonical owner
  condition and generated XML/BI4 pair;
- `F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025`, with its canonical owner
  condition and generated XML/BI4 pair.

Each request is an execution-only clone of the completed mother native solver
receipt. It preserves the mother executable, `-tmax:12`, and `-tout:0.05`;
the only command substitutions are the endpoint's genuine 073 prefix and the
runner's `{attempt_root}/solver_output`. The strict runtime may inject its
leased `-gpu:0` token. No DBC, motion, forcing, time, or other solver option is
added. The expected native trajectory is 241 frames over `[0, 12]` s.

Both requests remain `launch=false` and `launch_allowed=false` even though
Root has now supplied terminal fresh QA090 evidence: its bound execution
receipt is `completed` with return code `0`, its index is
`initial-native-integrity-pass`, and both endpoint reports are `pass=true` with
no failed checks. Root must recheck those hashes immediately before enabling a
request. The historical QA086 failure is retained as provenance; it is not
rejudged here.

`workers/audit_f6_endpoint_floatinginfo_state0_v1.py` is the follow-up native
FloatingInfo state-0 corroboration worker. It reads only a bounded prefix of
the endpoint's eventual `FloatingInfo_mk60.csv`, the endpoint XML/canonical
owner metadata, and a completed solver receipt. It derives the expected
angular velocity from that endpoint's own XML and owner on every invocation;
there is no fixed mother angular velocity in the worker. It never launches a
solver or FloatingInfo, reads BI4/H5/particle arrays, or claims that GenCase
particle `V0=0` disproves angular motion.

The source package carries no Q-N, precision, visual, or production approval,
and increments the independent case count by zero. Root may submit the two
requests to the strict runner only after reviewing the QA090 gate and the
source hashes.
