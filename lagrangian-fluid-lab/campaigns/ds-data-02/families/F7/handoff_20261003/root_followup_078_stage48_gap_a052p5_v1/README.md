# F7 fresh078: stage48 source gap and metadata adapter repair

This package is scoped to the F7 isolated worktree and remains source-only. The source owner audit reads bounded owner JSON only and finds **47 distinct physical source IDs** across fresh064 (2), fresh065 (5), fresh070 (16), and fresh074 (24). There are no duplicate IDs in that set. The target of 48 therefore has one source-ID gap. The selected condition is `F7_OBSTACLE_QUINTIC_B08_A052P5` at **52.5 degrees** (`F7_OBSTACLE_QUINTIC_B08_A052P5` is between the registered 50.5 and 54.5 degree conditions), with the same reviewed explicit-wet geometry, DP 0.02, two finite quintic cycles over 0–8 s, neutral rest through 12 s, and 601 native frames at tout 0.02.

The owner uses the actual `ds_data02_direct_convert._physical_condition_scope(owner)` callable. The converter scope digest is `0e321453f333371dad2a0fc0713b25e6163293b5415fcf7e4dc8435d5dabff5c`. The source-plan physical payload digest is `bffda16252fb07184442f46f946bc76e98eac91107b2c1fe4d26567b9db4bf58` and remains separate. Continuum mass 320.1984 kg and native support mass 325.60001628 kg are retained as separate metadata; no rescaling is requested.

The motion file is deliberately absent. Root's registered motion worker must generate `motion_obstacle_quintic.dat` from the A052P5 owner before enabling the disabled GenCase request. The GenCase, initial native QA, full native, and typed requests are all disabled with future hashes null. They do not grant visual acceptance, Q-N, precision, or production status.

## Root383 adapter repair

The consumed fresh077 adapter was not edited. Root384 exposed two source-contract defects: templated paths were `Path` objects later used with `.format()`, and actual conversion reports carry `solver_dimension` as an object containing `solver_dimension: 3`, `run_out_dimensions: [3]`, and `xml_data2d: false`. `scripts/bind_fresh078_actual_typed.py` fixes both. It was run against Root383's actual case map and produced two completed/0 metadata bindings with disabled XMF/render requests. The actual report is in `metadata/root383-actual-adapter-validation.json`; no H5 bytes were read or hashed by the adapter.

To bind later completed fresh077 typed cases into a new external output directory, Root can run:

```text
/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python /home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_078_stage48_gap_a052p5_v1/scripts/bind_fresh078_actual_typed.py --source-package /home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_077_actual_converter_scope_root142_adapter_v1 --output-dir <external-source-only-output> --case-map <completed-case-map.json>
```

The source package remains immutable; Root owns enabling requests through the approved runner after actual receipts exist.

Files with `.dat`, `.bi4`, `.h5`, `.csv`, or scientific array payloads are not included. No solver, converter, GenCase, QA, or shared-state job was started by this package.
